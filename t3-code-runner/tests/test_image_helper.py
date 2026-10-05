import ast
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest

HELPERS = Path(__file__).resolve().parents[1] / 'credential_helper'
sys.path.insert(0, str(HELPERS))
import publish_once as p
from supervise import emit


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.state.mkdir(mode=0o700)
        self.args = types.SimpleNamespace(state_dir=str(self.state), node_bin='/opt/node',
            cli='/data/t3/apps/server/dist/bin.mjs', base_dir='/share/t3', node_id='ha', port=3773)

    def provision(self):
        for name, content in [('receiver.json', json.dumps({'environmentId': 'env-123',
                'receiverHost': '192.168.68.61', 'receiverUser': 'fzowl', 'receiverPort': 22})),
                ('id_ed25519', 'TEST-KEY'), ('known_hosts', 'TEST-HOST')]:
            path = self.state / name
            path.write_text(content)
            path.chmod(0o600)

    def test_unconfigured_does_not_invoke_publisher(self):
        result, code = p.run(self.args, lambda *a, **k: self.fail('must not mint'))
        self.assertEqual((result['state'], code), ('unconfigured', 0))

    def test_exact_launch_cli_base_and_pinned_transport(self):
        self.provision()
        captured = []
        result, code = p.run(self.args, lambda config, **kw: captured.append((config, kw)) or {'state': 'healthy'})
        self.assertEqual(code, 0)
        config, kw = captured[0]
        self.assertEqual(config['cli'], ['/opt/node', self.args.cli])
        self.assertEqual(config['home'], '/share/t3')
        self.assertEqual(kw, {'apply': True})
        self.assertIn('StrictHostKeyChecking=yes', config['publish']['transport'])
        self.assertNotIn('TEST-KEY', json.dumps(config))

    def test_unsafe_files_fail_before_mint(self):
        self.provision()
        for name in ('receiver.json', 'id_ed25519', 'known_hosts'):
            with self.subTest(name=name):
                path = self.state / name
                path.chmod(0o644)
                result, code = p.run(self.args, lambda *a, **k: self.fail('must not mint'))
                self.assertEqual((result['reason'], code), ('unsafe_config', 1))
                path.chmod(0o600)
        key = self.state / 'id_ed25519'
        key.unlink()
        key.symlink_to(self.state / 'known_hosts')
        self.assertEqual(p.run(self.args)[0]['reason'], 'unsafe_config')

    def test_config_cannot_override_cli_or_inject_ssh_option(self):
        self.provision()
        path = self.state / 'receiver.json'
        original = json.loads(path.read_text())
        for changes in ({'cli': ['evil']}, {'receiverHost': '-oProxyCommand=evil'}, {'receiverPort': True}):
            path.write_text(json.dumps(original | changes))
            result, code = p.run(self.args, lambda *a, **k: self.fail('must not mint'))
            self.assertEqual((result['reason'], code), ('invalid_config', 1))

    def test_supervisor_filters_untrusted_reason(self):
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            emit('attempt_failed', {'bad': 'SECRET_SENTINEL'})
            emit('attempt_failed', 'SECRET_SENTINEL')
            emit('attempt_failed', 'publication_transport_failed')
        self.assertNotIn('SECRET_SENTINEL', capture.getvalue())
        self.assertIn('publication_transport_failed', capture.getvalue())

    def test_actual_guard_codes_survive_wrapper_and_supervisor(self):
        self.provision()
        # Keep the whitelist aligned with the vendored guard's bounded literals.
        tree = ast.parse((HELPERS / 't3_credential_guard.py').read_text())
        codes = {node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'GuardError' and node.args
            and isinstance(node.args[0], ast.Constant)}
        codes.update(('local_loopback_url_required', 'invalid_node_api_base', 'http_401'))
        for code in sorted(codes):
            with self.subTest(code=code):
                def fail(*a, **k): raise p.GuardError(code)
                result, status = p.run(self.args, fail)
                self.assertEqual((result['reason'], status), (code, 1))
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    emit('attempt_failed', result['reason'])
                self.assertEqual(json.loads(capture.getvalue())['reason'], code)

    def test_raw_exceptions_and_results_never_appear(self):
        self.provision()
        for error in (p.GuardError('SECRET_SENTINEL'), RuntimeError('SECRET_SENTINEL')):
            def fail(*a, **k): raise error
            result, code = p.run(self.args, fail)
            self.assertEqual(code, 1)
            self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
        result, code = p.run(self.args, lambda *a, **k: {'state': 'SECRET_SENTINEL'})
        self.assertNotIn('SECRET_SENTINEL', json.dumps(result))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition(): return
            time.sleep(.03)
        self.fail('condition timed out')

    def launch(self, helper_code, server_code=None):
        marker = self.root / 'stopped'
        if server_code is None:
            server_code = ('import signal,time,pathlib,sys; '
                f'signal.signal(signal.SIGTERM,lambda *a: (pathlib.Path({str(marker)!r}).write_text("yes"),sys.exit(0))); '
                'time.sleep(30)')
        code = f'import sys; sys.path.insert(0,{str(HELPERS)!r}); from supervise import supervise; sys.exit(supervise({[sys.executable,"-c",server_code]!r}, {[sys.executable,"-c",helper_code]!r}, interval=.1, helper_timeout=.3, shutdown_timeout=1))'
        child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        return child, marker

    def test_failed_helper_retries_primary_survives_and_no_secret_logs(self):
        attempts = self.root / 'attempts'
        helper = f'import pathlib,sys; p=pathlib.Path({str(attempts)!r}); p.open("a").write("x"); print("SECRET_SENTINEL"); print("SECRET_SENTINEL",file=sys.stderr); sys.exit(1)'
        child, marker = self.launch(helper)
        self.wait_for(lambda: attempts.exists() and len(attempts.read_text()) >= 2)
        self.assertIsNone(child.poll())
        child.terminate()
        out, err = child.communicate(timeout=4)
        self.assertEqual(child.returncode, 0)
        self.assertTrue(marker.exists())
        self.assertNotIn('SECRET_SENTINEL', out + err)
        self.assertIn('invalid_helper_output', out)

    def test_hung_helper_times_out_without_stopping_primary(self):
        started = self.root / 'started'
        helper = f'import pathlib,time; pathlib.Path({str(started)!r}).open("a").write("x"); time.sleep(30)'
        child, marker = self.launch(helper)
        self.wait_for(lambda: started.exists() and len(started.read_text()) >= 2)
        self.assertIsNone(child.poll())
        child.terminate()
        out, err = child.communicate(timeout=4)
        self.assertIn('attempt_timed_out', out)
        self.assertTrue(marker.exists())

    def test_primary_failure_propagates(self):
        child, _ = self.launch('import time; time.sleep(30)', 'import time,sys; time.sleep(.2); sys.exit(7)')
        out, err = child.communicate(timeout=4)
        self.assertEqual(child.returncode, 7)


class CadenceTests(unittest.TestCase):
    def test_default_and_explicit_interval(self):
        from supervise import configured_interval
        self.assertEqual(configured_interval({}), 30)
        self.assertEqual(configured_interval({'T3_CREDENTIAL_INTERVAL_SECONDS': '60'}), 60)
        self.assertEqual(configured_interval({'T3_CREDENTIAL_INTERVAL_SECONDS': '300'}), 300)

    def test_bad_helper_interval_cannot_prevent_primary_start(self):
        from supervise import configured_interval
        for value in ['nan', 'inf', '0', '-1', '301', '1.5', '']:
            self.assertEqual(configured_interval({'T3_CREDENTIAL_INTERVAL_SECONDS': value}), 30)


if __name__ == '__main__': unittest.main()
