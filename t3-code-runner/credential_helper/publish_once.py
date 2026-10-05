"""One bounded publication attempt using the image's running CLI and private volume."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

from t3_credential_guard import GuardError, publish

SAFE_ERRORS = {
    'environment_mismatch', 'local_pairing_failed', 'publication_transport_failed',
    'publication_bad_ack', 'publication_ack_mismatch', 'transport_or_response_error',
    'invalid_session', 'expired_session', 'missing_orchestration_scopes',
    'candidate_lifetime_too_short', 'http_401', 'http_403', 'http_404', 'http_503',
    'already_running', 'unsafe_token_path', 'unsafe_config', 'invalid_config',
}


def private_file(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or stat.S_IMODE(s.st_mode) & 0o077:
        raise GuardError('unsafe_config')
    return path


def configuration(state_dir, node_bin, cli, base_dir, node_id, port):
    state = Path(state_dir)
    # Explicit paths come from the SAME launch script that starts T3; never options.json CLI overrides.
    if not all(Path(p).is_absolute() for p in (state_dir, node_bin, cli, base_dir)):
        raise GuardError('invalid_config')
    if state.is_symlink():
        raise GuardError('unsafe_config')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    config = state / 'receiver.json'
    if not config.exists():
        return None
    c = json.loads(private_file(config).read_text())
    if set(c) != {'environmentId', 'receiverHost', 'receiverUser', 'receiverPort'}:
        raise GuardError('invalid_config')
    if not isinstance(c['environmentId'], str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', c['environmentId']):
        raise GuardError('invalid_config')
    if not isinstance(c['receiverHost'], str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}', c['receiverHost']):
        raise GuardError('invalid_config')
    if not isinstance(c['receiverUser'], str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', c['receiverUser']):
        raise GuardError('invalid_config')
    if type(c['receiverPort']) is not int or not 1 <= c['receiverPort'] <= 65535:
        raise GuardError('invalid_config')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', node_id) or not 1 <= port <= 65535:
        raise GuardError('invalid_config')
    key = private_file(state / 'id_ed25519')
    hosts = private_file(state / 'known_hosts')
    return {'baseUrl': 'http://127.0.0.1:'+str(port), 'environmentId': c['environmentId'],
            'tokenPath': str(state / (node_id+'.token')), 'home': base_dir,
            'cli': [node_bin, cli], 'renewBeforeSeconds': 604800,
            'publish': {'node': node_id, 'environmentId': c['environmentId'], 'timeoutSeconds': 30,
                'transport': ['/usr/bin/ssh', '-T', '-F', '/dev/null', '-o', 'BatchMode=yes',
                    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                    '-o', 'ConnectTimeout=10', '-o', 'UserKnownHostsFile='+str(hosts),
                    '-i', str(key), '-p', str(c['receiverPort']), '-l', c['receiverUser'], c['receiverHost']]}}


def run(args, publisher=publish):
    try:
        c = configuration(args.state_dir, args.node_bin, args.cli, args.base_dir, args.node_id, args.port)
        if c is None:
            return {'component': 'credential-publish', 'state': 'unconfigured'}, 0
        result = publisher(c, apply=True)
        if result.get('state') not in ('healthy', 'published'):
            raise GuardError('invalid_session')
        return {'component': 'credential-publish', 'state': result['state']}, 0
    except GuardError as error:
        reason = str(error) if str(error) in SAFE_ERRORS else 'credential_guard_failed'
    except Exception:
        reason = 'configuration_or_io_error'
    return {'component': 'credential-publish', 'state': 'error', 'reason': reason}, 1


def main():
    p = argparse.ArgumentParser()
    for name in ('state-dir', 'node-bin', 'cli', 'base-dir', 'node-id'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--port', type=int, required=True)
    result, status = run(p.parse_args())
    print(json.dumps(result), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main())
