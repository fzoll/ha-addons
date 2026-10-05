#!/usr/bin/env python3
"""Local T3 credential rotation and independent publication to the central store.

Secrets never leave process memory, private 0600 files, or a pipe to the pinned
receiver. They are never placed in argv, logs, prompts, or agent transcripts."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


class GuardError(Exception):
    pass


def atomic_write(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request(base, path, token=None, form=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(base + path, headers=headers, data=data)
    try:
        # Local control must never send credentials through environment proxies
        # or follow a redirect to a different host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=10) as response:
            return json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        raise GuardError('http_' + str(error.code)) from None
    except Exception:
        raise GuardError('transport_or_response_error') from None


def issue(config):
    command = config['cli'] + ['auth', 'pairing', 'create', '--base-dir', config['home'],
                               '--ttl', '5m', '--label', 'cc-runner-guard', '--json']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)['credential']
    except Exception:
        # CalledProcessError includes stdout/stderr; do not propagate either.
        raise GuardError('local_pairing_failed') from None


def clean_base(url_string, loopback_only):
    """Validate an API base. Loopback control forbids non-local hosts and TLS-less
    remotes; receiver node verification allows a config-pinned host over https/http."""
    url = urllib.parse.urlparse(url_string)
    scheme_ok = url.scheme == 'http' if loopback_only else url.scheme in ('http', 'https')
    loop_ok = (not loopback_only) or url.hostname in ('127.0.0.1', '::1', 'localhost')
    if not scheme_ok or not loop_ok or url.username or url.password \
            or url.path not in ('', '/') or url.query or url.fragment:
        raise GuardError('local_loopback_url_required' if loopback_only else 'invalid_node_api_base')
    return url_string.rstrip('/')


def token_base_path(config):
    path = Path(config['tokenPath']).expanduser()
    if not path.is_absolute() or not config.get('environmentId'):
        raise GuardError('invalid_configuration')
    if not path.parent.is_dir() or path.is_symlink():
        raise GuardError('unsafe_token_path')
    return path


def generation(credential):
    """Stable, non-reversible identifier for a credential, safe to log and to
    compare across sender and receiver without revealing the secret."""
    return hashlib.sha256(credential.encode()).hexdigest()


def acquire_candidate(config, base, path, now, http, mint):
    """Return a validated access token, reusing a persisted candidate when one
    survives validation so a lost acknowledgement never forces fresh minting.
    Mints at most one new credential and persists it privately before returning."""
    candidate_path = path.with_name(path.name + '.candidate')
    candidate = candidate_path.read_text().strip() if candidate_path.exists() else None
    if candidate:
        try:
            session = http(base, '/api/auth/session', candidate)
            validate_session(session, now)
            if expiry(session) - now <= config.get('renewBeforeSeconds', 604800):
                # An interrupted publication can leave a valid but aging candidate.
                # Replace it atomically only after a new exchange succeeds; do not
                # strand recovery until its actual expiration or touch current.
                candidate = None
        except GuardError as error:
            if str(error) not in ('http_401', 'expired_session', 'invalid_session'):
                raise
            candidate_path.unlink()
            candidate = None
    if not candidate:
        credential = mint(config)
        response = http(base, '/oauth/token', form={
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
            'subject_token': credential,
            'subject_token_type': 'urn:t3:params:oauth:token-type:environment-bootstrap',
            'requested_token_type': 'urn:ietf:params:oauth:token-type:access_token',
        })
        candidate = response.get('access_token')
        if not isinstance(candidate, str) or not candidate:
            raise GuardError('invalid_exchange_response')
        atomic_write(candidate_path, candidate + '\n')
    verified = http(base, '/api/auth/session', candidate)
    validate_session(verified, now)
    if expiry(verified) - now <= config.get('renewBeforeSeconds', 604800):
        raise GuardError('candidate_lifetime_too_short')
    return candidate, candidate_path, verified


def expiry(session):
    try:
        parsed = dt.datetime.fromisoformat(session['expiresAt'].replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except Exception:
        raise GuardError('invalid_expiry') from None


def validate_session(session, now):
    scopes = session.get('scopes', [])
    required = {'orchestration:read', 'orchestration:operate'}
    allowed = required | {'terminal:operate', 'review:write', 'relay:read'}
    if session.get('authenticated') is not True or not isinstance(scopes, list):
        raise GuardError('invalid_session')
    if not required.issubset(scopes) or not set(scopes).issubset(allowed):
        raise GuardError('unexpected_scopes')
    if expiry(session) <= now:
        raise GuardError('expired_session')


def rotate(config, apply=False, force=False, http=request, mint=issue, now=None):
    now = dt.datetime.now(dt.timezone.utc).timestamp() if now is None else now
    base = clean_base(config['baseUrl'], loopback_only=True)
    path = token_base_path(config)
    lockpath = path.with_name(path.name + '.guard.lock')
    lockfd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lockfd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GuardError('rotation_in_progress') from None
        environment = http(base, '/.well-known/t3/environment')
        if environment.get('environmentId') != config['environmentId']:
            raise GuardError('environment_mismatch')
        previous = path.read_text().strip() if path.exists() else None
        session = None
        if previous:
            try:
                session = http(base, '/api/auth/session', previous)
                validate_session(session, now)
            except GuardError as error:
                if str(error) not in ('http_401', 'http_403', 'expired_session', 'invalid_session'):
                    raise
                session = None
        due = not session or expiry(session) - now <= config.get('renewBeforeSeconds', 604800)
        if not force and not due:
            return {'state': 'healthy', 'expiresAt': session['expiresAt']}
        if not apply:
            return {'state': 'rotation_due', 'expiresAt': session['expiresAt'] if session else None}
        candidate, candidate_path, verified = acquire_candidate(config, base, path, now, http, mint)
        # Retain one private rollback credential, not an unbounded history.
        if previous:
            atomic_write(path.with_name(path.name + '.previous'), previous + '\n')
        atomic_write(path, candidate + '\n')
        candidate_path.unlink()
        # No blanket revocation: other clients and live sessions are unrelated.
        return {'state': 'rotated', 'expiresAt': verified['expiresAt']}


def read_record(record_path):
    """A published-generation receipt: the acknowledged generation and its expiry.
    Contains no secret, so a lost acknowledgement is recoverable without reminting."""
    if not record_path.exists():
        return None
    try:
        record = json.loads(record_path.read_text())
    except Exception:
        return None
    if not isinstance(record, dict) or not isinstance(record.get('generation'), str):
        return None
    return record


def live_session(http, base, credential, now):
    """Return a freshly validated session for a credential, or None when the node API
    reports it revoked/expired/invalid. Transient transport errors propagate so a
    network outage is never mistaken for a revocation (the caller preserves current)."""
    try:
        session = http(base, '/api/auth/session', credential)
        validate_session(session, now)
        return session
    except GuardError as error:
        if str(error) in ('http_401', 'http_403', 'expired_session', 'invalid_session'):
            return None
        raise


def reconcile(transport, credential, expected_generation, target):
    """Re-hand a retained credential to the pinned receiver over the restricted
    transport and confirm the secret-free ack still pins our generation and target.
    Idempotent on the receiver: an unchanged store re-acknowledges, a
    deleted/rolled-back store re-installs the same credential without any new mint."""
    ack = transport(credential)
    if not isinstance(ack, dict) or ack.get('generation') != expected_generation:
        raise GuardError('publication_not_acknowledged')
    if ack.get('node') != target['node'] or ack.get('environmentId') != target['environmentId']:
        raise GuardError('publication_target_mismatch')
    return ack


def ssh_transport(config):
    """Narrow transport: run the exact argv in config (an ssh invocation whose remote
    end is pinned to the receiver via an authorized_keys forced command) and feed the
    credential on stdin only. The secret is never in argv, so it cannot leak via the
    process table or shell history; the receiver replies with a secret-free ack."""
    argv = config['publish']['transport']
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv) or not argv:
        raise GuardError('invalid_transport_configuration')

    def send(credential):
        try:
            result = subprocess.run(argv, input=credential + '\n', capture_output=True,
                                    text=True, timeout=config['publish'].get('timeoutSeconds', 30))
        except Exception:
            raise GuardError('publication_transport_failed') from None
        if result.returncode != 0:
            # Never surface remote stderr: it may echo the pipe or internal paths.
            raise GuardError('publication_transport_failed')
        try:
            return json.loads(result.stdout)
        except Exception:
            raise GuardError('publication_bad_ack') from None

    return send


def publish(config, apply=False, force=False, http=request, mint=issue, transport=None, now=None):
    """Sender side (Mac/HA): mint+validate a candidate locally, then hand it to the
    pinned receiver over a restricted transport. A healthy result is never granted
    from a cached receipt alone: the retained credential's live session is re-validated
    and (in apply mode) the receiver is reconciled over the transport, so a revoked
    credential or a deleted/rolled-back receiver store is detected and corrected. The
    published credential is retained privately so a revoke/rollback is re-published
    without re-minting; a lost acknowledgement reuses the persisted candidate instead."""
    now = dt.datetime.now(dt.timezone.utc).timestamp() if now is None else now
    base = clean_base(config['baseUrl'], loopback_only=True)
    path = token_base_path(config)
    target = config['publish']
    if not target.get('node') or not target.get('environmentId'):
        raise GuardError('invalid_publish_target')
    transport = ssh_transport(config) if transport is None else transport
    record_path = path.with_name(path.name + '.published')
    secret_path = path.with_name(path.name + '.published-secret')
    renew_before = config.get('renewBeforeSeconds', 604800)
    lockpath = path.with_name(path.name + '.publish.lock')
    lockfd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lockfd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GuardError('publication_in_progress') from None
        environment = http(base, '/.well-known/t3/environment')
        if environment.get('environmentId') != config['environmentId']:
            raise GuardError('environment_mismatch')
        record = read_record(record_path)
        retained = secret_path.read_text().strip() if secret_path.exists() else None
        # Healthy requires a remembered generation, its private credential, a live
        # local session for that credential and adequate remaining lifetime. The
        # cached expiry is never trusted on its own.
        if record and retained and not force and generation(retained) == record.get('generation'):
            session = live_session(http, base, retained, now)
            if session and expiry(session) - now > renew_before:
                if not apply:
                    return {'state': 'healthy', 'expiresAt': session['expiresAt']}
                # Reconcile the receiver over the restricted transport. A network
                # failure here raises and leaves every local file untouched, so the
                # current credential is preserved; a deleted/rolled-back receiver
                # store is re-installed with the same retained credential, no mint.
                ack = reconcile(transport, retained, record['generation'], target)
                atomic_write(record_path, json.dumps({
                    'generation': record['generation'], 'expiresAt': session['expiresAt'],
                    'acknowledgedState': ack.get('state')}) + '\n')
                return {'state': 'healthy', 'expiresAt': session['expiresAt']}
        if not apply:
            return {'state': 'publish_due', 'expiresAt': record['expiresAt'] if record else None}
        candidate, candidate_path, verified = acquire_candidate(config, base, path, now, http, mint)
        gen = generation(candidate)
        ack = transport(candidate)
        if not isinstance(ack, dict) or ack.get('generation') != gen:
            # No acknowledgement: keep the candidate for the next run, mint nothing new.
            raise GuardError('publication_not_acknowledged')
        if ack.get('node') != target['node'] or ack.get('environmentId') != target['environmentId']:
            raise GuardError('publication_target_mismatch')
        # Retain the published credential privately so a later revoke/rollback can be
        # re-published without minting, then record the secret-free receipt.
        atomic_write(secret_path, candidate + '\n')
        atomic_write(record_path, json.dumps({'generation': gen, 'expiresAt': verified['expiresAt'],
                                              'acknowledgedState': ack.get('state')}) + '\n')
        candidate_path.unlink()
        return {'state': 'published', 'expiresAt': verified['expiresAt']}


def receive(config, credential, http=request, now=None):
    """Receiver side (central RPi store, run under an authorized_keys forced command).
    Pins the node, environment and target path from local config, independently
    verifies the incoming candidate against the node API, and only then atomically
    installs it with private permissions. Idempotent: an already-current credential
    is re-acknowledged without rewriting. The current credential is preserved on any
    verification failure. The returned ack carries only a generation hash, never the
    secret. The full verify/check/backup/replace/ack critical section runs under an
    exclusive OS lock, so concurrent receivers cannot race the current/previous update."""
    now = dt.datetime.now(dt.timezone.utc).timestamp() if now is None else now
    credential = (credential or '').strip()
    if not credential or len(credential) > 8192 or any(c.isspace() for c in credential):
        raise GuardError('invalid_candidate')
    if not config.get('node') or not config.get('environmentId'):
        raise GuardError('invalid_receiver_configuration')
    path = Path(config['tokenPath'])
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise GuardError('unsafe_token_path')
    lockpath = path.with_name(path.name + '.receive.lock')
    lockfd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lockfd, 'w') as lock:
        # Blocking, not LOCK_NB: a second publication serializes behind the first
        # rather than racing it. The sender's transport timeout bounds any wait.
        fcntl.flock(lock, fcntl.LOCK_EX)
        base = clean_base(config['nodeApiBase'], loopback_only=False)
        environment = http(base, '/.well-known/t3/environment')
        if environment.get('environmentId') != config['environmentId']:
            raise GuardError('environment_mismatch')
        session = http(base, '/api/auth/session', credential)
        validate_session(session, now)
        if expiry(session) - now <= config.get('minLifetimeSeconds', 604800):
            raise GuardError('candidate_lifetime_too_short')
        gen = generation(credential)
        ack = {'node': config['node'], 'environmentId': config['environmentId'],
               'generation': gen, 'expiresAt': session['expiresAt']}
        if path.exists() and path.read_text().strip() == credential:
            ack['state'] = 'already_current'
            return ack
        if path.exists():
            atomic_write(path.with_name(path.name + '.previous'), path.read_text().strip() + '\n')
        atomic_write(path, credential + '\n')
        ack['state'] = 'published'
        return ack


def run_local(handler, args):
    try:
        config = json.loads(Path(args.config).read_text())
        print(json.dumps(handler(config, args.apply, args.force)))
    except GuardError as error:
        print(json.dumps({'state': 'error', 'reason': str(error)}))
        return 1
    except Exception:
        print(json.dumps({'state': 'error', 'reason': 'local_io_or_configuration_error'}))
        return 1
    return 0


def run_receive(args):
    try:
        config = json.loads(Path(args.config).read_text())
        # Credential arrives on stdin only, never argv; cap the read defensively.
        print(json.dumps(receive(config, sys.stdin.read(8193))))
    except GuardError as error:
        print(json.dumps({'state': 'error', 'reason': str(error)}))
        return 1
    except Exception:
        print(json.dumps({'state': 'error', 'reason': 'receiver_io_or_configuration_error'}))
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('rotate', 'publish', 'receive'):
        command, rest = argv[0], argv[1:]
    else:
        # Legacy invocation (systemd timer): no subcommand means rotate.
        command, rest = 'rotate', argv
    parser = argparse.ArgumentParser(description=__doc__, prog='t3_credential_guard ' + command)
    parser.add_argument('--config', required=True)
    if command != 'receive':
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--force', action='store_true')
    args = parser.parse_args(rest)
    if command == 'receive':
        return run_receive(args)
    handler = publish if command == 'publish' else rotate
    return run_local(handler, args)


if __name__ == '__main__':
    raise SystemExit(main())
