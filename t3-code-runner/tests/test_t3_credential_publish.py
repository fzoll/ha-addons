"""Failure-injection tests for independent publication (Mac/HA -> central RPi store).

All credentials are fake. The transport is a local in-process fake that wires the
sender's pipe straight into the receiver, so the lost-acknowledgement, unreachable,
scope/environment, preservation, repeat and redaction paths are exercised without
SSH, live nodes, or real tokens.
"""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'credential_helper'))
from t3_credential_guard import GuardError, generation, publish, receive


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1800000000
        # Sender-side private store (candidate + published receipt live here).
        self.sender = Path(self.tmp.name) / 'mac.token'
        # Receiver-side central store target (what cc_runner reads on the RPi).
        self.central = Path(self.tmp.name) / 'central' / 'mac.token'
        self.central.parent.mkdir()
        self.mints = 0
        self.scopes = ['orchestration:read', 'orchestration:operate']
        self.env_id = 'mac-env'
        self.drop_ack = False          # receiver stores, sender never hears back
        self.unreachable = False       # transport cannot reach the receiver at all
        self.revoked = set()           # tokens the node API now rejects (401)
        self.exchanged = 'minted-token-1'
        self.config = {
            'baseUrl': 'http://127.0.0.1:3773',
            'tokenPath': str(self.sender),
            'environmentId': self.env_id,
            'publish': {'node': 'mac', 'environmentId': self.env_id, 'transport': ['true']},
        }
        self.receiver_config = {
            'node': 'mac',
            'environmentId': self.env_id,
            'tokenPath': str(self.central),
            'nodeApiBase': 'http://100.111.149.53:3773',
        }

    # --- fakes -----------------------------------------------------------------
    def mint(self, config):
        self.mints += 1
        return 'pairing-secret'

    def http(self, base, route, token=None, form=None):
        if route.endswith('/environment'):
            return {'environmentId': self.env_id}
        if route == '/oauth/token':
            self.assertEqual(form['subject_token'], 'pairing-secret')
            return {'access_token': self.exchanged}
        # /api/auth/session — a revoked credential is rejected even with future expiry.
        if token in self.revoked:
            raise GuardError('http_401')
        return {'authenticated': True, 'scopes': self.scopes,
                'expiresAt': iso(self.now + 30 * 86400)}

    def transport(self):
        """Local fake wire: sender pipe -> receiver. Optionally drops the ack after
        the receiver has already committed, or fails before reaching it."""
        def send(credential):
            if self.unreachable:
                raise GuardError('publication_transport_failed')
            ack = receive(self.receiver_config, credential, http=self.http, now=self.now)
            if self.drop_ack:
                raise GuardError('publication_transport_failed')
            return ack
        return send

    def run_publish(self, apply=True, force=False):
        return publish(self.config, apply=apply, force=force, http=self.http,
                       mint=self.mint, transport=self.transport(), now=self.now)

    # --- sender ----------------------------------------------------------------
    def test_check_does_not_mint_or_send(self):
        result = self.run_publish(apply=False)
        self.assertEqual(result['state'], 'publish_due')
        self.assertEqual(self.mints, 0)
        self.assertFalse(self.central.exists())

    def test_publish_installs_remotely_and_is_redacted(self):
        result = self.run_publish()
        self.assertEqual(result['state'], 'published')
        self.assertNotIn(self.exchanged, json.dumps(result))
        self.assertEqual(self.central.read_text().strip(), self.exchanged)
        self.assertEqual(self.central.stat().st_mode & 0o777, 0o600)
        # Receipt remembers the acknowledged generation, holds no secret.
        receipt = json.loads(self.sender.with_name('mac.token.published').read_text())
        self.assertEqual(receipt['generation'], generation(self.exchanged))
        self.assertNotIn(self.exchanged, json.dumps(receipt))
        # A healthy published generation is not re-minted or re-sent.
        self.assertEqual(self.run_publish()['state'], 'healthy')
        self.assertEqual(self.mints, 1)

    def test_lost_ack_reuses_candidate_without_reminting(self):
        self.drop_ack = True
        with self.assertRaisesRegex(GuardError, 'publication_transport_failed'):
            self.run_publish()
        # Receiver committed, sender kept the candidate, wrote no receipt.
        self.assertEqual(self.central.read_text().strip(), self.exchanged)
        self.assertTrue(self.sender.with_name('mac.token.candidate').exists())
        self.assertFalse(self.sender.with_name('mac.token.published').exists())
        # Retry: idempotent re-ack, reused candidate, nothing minted twice.
        self.drop_ack = False
        self.assertEqual(self.run_publish()['state'], 'published')
        self.assertEqual(self.mints, 1)

    def test_unreachable_receiver_preserves_and_reuses(self):
        self.unreachable = True
        with self.assertRaisesRegex(GuardError, 'publication_transport_failed'):
            self.run_publish()
        self.assertFalse(self.central.exists())
        self.assertTrue(self.sender.with_name('mac.token.candidate').exists())
        self.unreachable = False
        self.assertEqual(self.run_publish()['state'], 'published')
        self.assertEqual(self.mints, 1)

    def test_aging_candidate_after_lost_ack_is_reissued_once(self):
        self.drop_ack = True
        with self.assertRaisesRegex(GuardError, 'publication_transport_failed'):
            self.run_publish()
        # Receiver already uses this credential, but sender retained the candidate.
        self.drop_ack = False
        original_http = self.http

        def aging_http(base, route, token=None, form=None):
            response = original_http(base, route, token, form)
            if route == '/api/auth/session' and token == 'minted-token-1':
                response['expiresAt'] = iso(self.now + 86400)
            return response

        self.http = aging_http
        self.exchanged = 'minted-token-2'
        self.assertEqual(self.run_publish()['state'], 'published')
        self.assertEqual(self.mints, 2)
        self.assertEqual(self.central.read_text().strip(), 'minted-token-2')
        self.assertEqual(self.central.with_name('mac.token.previous').read_text().strip(),
                         'minted-token-1')
        self.assertEqual(self.run_publish()['state'], 'healthy')
        self.assertEqual(self.mints, 2)

    def test_failed_aging_candidate_exchange_preserves_candidate_and_current(self):
        self.drop_ack = True
        with self.assertRaises(GuardError):
            self.run_publish()
        original_http = self.http

        def failed_exchange(base, route, token=None, form=None):
            if route == '/oauth/token':
                raise GuardError('transport_or_response_error')
            response = original_http(base, route, token, form)
            if route == '/api/auth/session':
                response['expiresAt'] = iso(self.now + 86400)
            return response

        self.http = failed_exchange
        with self.assertRaisesRegex(GuardError, 'transport_or_response_error'):
            self.run_publish()
        self.assertEqual(self.mints, 2)
        self.assertEqual(self.sender.with_name('mac.token.candidate').read_text().strip(),
                         'minted-token-1')
        self.assertEqual(self.central.read_text().strip(), 'minted-token-1')

    def test_new_short_lived_candidate_fails_without_reissue_loop(self):
        self.central.write_text('working-current\n')
        original_http = self.http

        def short_lived_http(base, route, token=None, form=None):
            response = original_http(base, route, token, form)
            if route == '/api/auth/session':
                response['expiresAt'] = iso(self.now + 86400)
            return response

        self.http = short_lived_http
        with self.assertRaisesRegex(GuardError, 'candidate_lifetime_too_short'):
            self.run_publish()
        self.assertEqual(self.mints, 1)
        self.assertEqual(self.central.read_text().strip(), 'working-current')
        self.assertTrue(self.sender.with_name('mac.token.candidate').exists())

    def test_sender_environment_mismatch_never_mints(self):
        self.config['environmentId'] = 'wrong'
        with self.assertRaisesRegex(GuardError, 'environment_mismatch'):
            self.run_publish()
        self.assertEqual(self.mints, 0)
        self.assertFalse(self.central.exists())

    def test_target_mismatch_is_rejected(self):
        self.config['publish']['node'] = 'ha'
        with self.assertRaisesRegex(GuardError, 'publication_target_mismatch'):
            self.run_publish()
        # Receiver pins node=mac, so it never produced a matching ack; no receipt.
        self.assertFalse(self.sender.with_name('mac.token.published').exists())

    def test_published_credential_retained_privately(self):
        self.run_publish()
        secret = self.sender.with_name('mac.token.published-secret')
        self.assertEqual(secret.read_text().strip(), self.exchanged)
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        # The receipt still carries no secret, only the generation hash.
        self.assertNotIn(self.exchanged, self.sender.with_name('mac.token.published').read_text())

    def test_revoke_after_ack_reissues_without_trusting_cache(self):
        self.run_publish()
        self.assertEqual(self.central.read_text().strip(), 'minted-token-1')
        # Central credential revoked server-side though its cached expiry is far off.
        self.revoked.add('minted-token-1')
        self.exchanged = 'minted-token-2'
        result = self.run_publish()
        self.assertEqual(result['state'], 'published')
        self.assertEqual(self.mints, 2)
        self.assertEqual(self.central.read_text().strip(), 'minted-token-2')
        self.assertEqual(self.central.with_name('mac.token.previous').read_text().strip(),
                         'minted-token-1')

    def test_central_missing_reconciled_without_reminting(self):
        self.run_publish()
        self.central.unlink()                       # receiver store deleted out-of-band
        result = self.run_publish()
        self.assertEqual(result['state'], 'healthy')
        self.assertEqual(self.central.read_text().strip(), 'minted-token-1')
        self.assertEqual(self.mints, 1)             # re-published, never re-minted

    def test_central_rollback_reconciled_without_reminting(self):
        self.run_publish()
        self.central.write_text('stale-rollback\n')  # receiver rolled back out-of-band
        result = self.run_publish()
        self.assertEqual(result['state'], 'healthy')
        self.assertEqual(self.central.read_text().strip(), 'minted-token-1')
        self.assertEqual(self.central.with_name('mac.token.previous').read_text().strip(),
                         'stale-rollback')
        self.assertEqual(self.mints, 1)

    def test_healthy_reconcile_network_failure_preserves_current(self):
        self.run_publish()
        self.unreachable = True                     # transport unreachable on next run
        with self.assertRaisesRegex(GuardError, 'publication_transport_failed'):
            self.run_publish()
        # Current credential and receipt untouched; nothing re-minted.
        self.assertEqual(self.central.read_text().strip(), 'minted-token-1')
        self.assertEqual(self.sender.with_name('mac.token.published-secret').read_text().strip(),
                         'minted-token-1')
        self.assertEqual(self.mints, 1)

    def test_concurrent_receivers_serialize(self):
        import threading
        import time
        entered = threading.Event()

        def slow_http(base, route, token=None, form=None):
            if route.endswith('/session') and token == 'tok-a':
                entered.set()
                time.sleep(0.3)         # hold the receiver lock mid critical section
            return self.http(base, route, token, form)

        results = {}

        def worker(name, tok, fn):
            try:
                results[name] = receive(self.receiver_config, tok, http=fn, now=self.now)
            except Exception as error:                      # noqa: BLE001 - record for assert
                results[name] = error

        first = threading.Thread(target=worker, args=('a', 'tok-a', slow_http))
        first.start()
        self.assertTrue(entered.wait(2))                    # 'a' holds the lock
        second = threading.Thread(target=worker, args=('b', 'tok-b', self.http))
        second.start()
        first.join(5)
        second.join(5)
        # Serialized: 'a' committed first, then 'b' backed it up and became current.
        self.assertEqual(results['a']['state'], 'published')
        self.assertEqual(results['b']['state'], 'published')
        self.assertEqual(self.central.read_text().strip(), 'tok-b')
        self.assertEqual(self.central.with_name('mac.token.previous').read_text().strip(), 'tok-a')

    def test_remote_plaintext_sender_base_rejected(self):
        self.config['baseUrl'] = 'http://100.111.149.53:3773'
        with self.assertRaisesRegex(GuardError, 'local_loopback_url_required'):
            self.run_publish()
        self.assertEqual(self.mints, 0)

    # --- receiver --------------------------------------------------------------
    def test_receiver_rejects_unexpected_scope_and_preserves_current(self):
        self.central.write_text('existing-token\n')
        self.scopes = ['orchestration:read', 'orchestration:operate', 'access:write']
        with self.assertRaisesRegex(GuardError, 'unexpected_scopes'):
            receive(self.receiver_config, 'candidate-x', http=self.http, now=self.now)
        self.assertEqual(self.central.read_text().strip(), 'existing-token')

    def test_receiver_rejects_environment_mismatch_and_preserves_current(self):
        self.central.write_text('existing-token\n')
        self.receiver_config['environmentId'] = 'other-env'
        with self.assertRaisesRegex(GuardError, 'environment_mismatch'):
            receive(self.receiver_config, 'candidate-x', http=self.http, now=self.now)
        self.assertEqual(self.central.read_text().strip(), 'existing-token')

    def test_receiver_idempotent_repeat_keeps_backup_once(self):
        first = receive(self.receiver_config, 'tok-a', http=self.http, now=self.now)
        self.assertEqual(first['state'], 'published')
        self.assertNotIn('tok-a', json.dumps(first))
        again = receive(self.receiver_config, 'tok-a', http=self.http, now=self.now)
        self.assertEqual(again['state'], 'already_current')
        self.assertEqual(again['generation'], first['generation'])
        # No .previous written for a no-op repeat.
        self.assertFalse(self.central.with_name('mac.token.previous').exists())

    def test_receiver_rotation_keeps_private_previous(self):
        receive(self.receiver_config, 'tok-a', http=self.http, now=self.now)
        receive(self.receiver_config, 'tok-b', http=self.http, now=self.now)
        self.assertEqual(self.central.read_text().strip(), 'tok-b')
        previous = self.central.with_name('mac.token.previous')
        self.assertEqual(previous.read_text().strip(), 'tok-a')
        self.assertEqual(previous.stat().st_mode & 0o777, 0o600)

    def test_receiver_rejects_credential_with_whitespace(self):
        with self.assertRaisesRegex(GuardError, 'invalid_candidate'):
            receive(self.receiver_config, 'two words', http=self.http, now=self.now)

    def test_receiver_rejects_non_loopback_without_pinned_base(self):
        self.receiver_config['nodeApiBase'] = 'http://evil@host:3773'
        with self.assertRaisesRegex(GuardError, 'invalid_node_api_base'):
            receive(self.receiver_config, 'tok-a', http=self.http, now=self.now)


if __name__ == '__main__':
    unittest.main()
