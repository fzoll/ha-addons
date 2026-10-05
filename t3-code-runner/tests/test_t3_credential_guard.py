import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'credential_helper'))
from t3_credential_guard import GuardError, rotate


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'rpi.token'
        self.path.write_text('old')
        self.now = 1800000000
        self.config = {'baseUrl': 'http://127.0.0.1:3773', 'tokenPath': str(self.path), 'environmentId': 'expected'}
        self.mints = 0
        self.old_expiry = self.now + 3600
        self.fail_new = False
        self.new_scopes = ['orchestration:read', 'orchestration:operate']

    def mint(self, config):
        self.mints += 1
        return 'pairing-secret'

    def http(self, base, route, token=None, form=None):
        if route.endswith('/environment'):
            return {'environmentId': 'expected'}
        if route == '/oauth/token':
            self.assertEqual(form['subject_token'], 'pairing-secret')
            return {'access_token': 'new-secret'}
        if token == 'new-secret' and self.fail_new:
            raise GuardError('transport_or_response_error')
        if token == 'old' and self.old_expiry is None:
            raise GuardError('http_401')
        seconds = self.old_expiry if token == 'old' else self.now + 30 * 86400
        return {'authenticated': True, 'scopes': self.new_scopes,
                'expiresAt': dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()}

    def run_guard(self, apply=True):
        return rotate(self.config, apply=apply, http=self.http, mint=self.mint, now=self.now)

    def test_check_does_not_issue_or_replace(self):
        self.assertEqual(self.run_guard(False)['state'], 'rotation_due')
        self.assertEqual(self.mints, 0)
        self.assertEqual(self.path.read_text(), 'old')

    def test_healthy_skips_rotation(self):
        self.old_expiry = self.now + 20 * 86400
        self.assertEqual(self.run_guard()['state'], 'healthy')
        self.assertEqual(self.mints, 0)

    def test_rotation_is_private_and_idempotent(self):
        result = self.run_guard()
        self.assertEqual(result['state'], 'rotated')
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(self.path.read_text().strip(), 'new-secret')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.with_name('rpi.token.previous').read_text().strip(), 'old')
        self.assertEqual(self.run_guard()['state'], 'healthy')
        self.assertEqual(self.mints, 1)

    def test_revoked_token_recovers_via_local_issuer(self):
        self.old_expiry = None
        self.assertEqual(self.run_guard()['state'], 'rotated')

    def test_candidate_survives_validation_outage_without_reissuance(self):
        self.fail_new = True
        with self.assertRaises(GuardError):
            self.run_guard()
        self.assertEqual(self.path.read_text(), 'old')
        self.fail_new = False
        self.assertEqual(self.run_guard()['state'], 'rotated')
        self.assertEqual(self.mints, 1)

    def test_environment_mismatch_never_mints(self):
        self.config['environmentId'] = 'wrong'
        with self.assertRaisesRegex(GuardError, 'environment_mismatch'):
            self.run_guard()
        self.assertEqual(self.mints, 0)

    def test_admin_scope_is_rejected(self):
        self.new_scopes.append('access:write')
        with self.assertRaisesRegex(GuardError, 'unexpected_scopes'):
            self.run_guard()
        self.assertEqual(self.path.read_text(), 'old')

    def test_remote_plaintext_target_is_rejected(self):
        self.config['baseUrl'] = 'http://192.168.68.61:3773'
        with self.assertRaisesRegex(GuardError, 'local_loopback_url_required'):
            self.run_guard()
        self.assertEqual(self.mints, 0)

    def test_revoked_candidate_does_not_block_recovery(self):
        self.path.with_name('rpi.token.candidate').write_text('old')
        self.old_expiry = None
        self.assertEqual(self.run_guard()['state'], 'rotated')
        self.assertEqual(self.mints, 1)


if __name__ == '__main__':
    unittest.main()
