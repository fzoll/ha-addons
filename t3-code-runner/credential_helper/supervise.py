"""Container PID1: T3 is primary; failed/timed-out publication never stops it."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

from publish_once import SAFE_ERRORS


def terminate_group(child, grace=2):
    if child is None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=grace)
        # The parent may have exited while a CLI grandchild still owns the group.
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS may report EPERM for a group whose last member just exited.
        # A still-running owned child is always reaped directly as fallback.
        if child.poll() is None:
            child.kill()
            child.wait()


def reap_orphans(server, helper):
    # As container PID1, reap adopted descendants after timed-out helper groups.
    # Preserve exit statuses for the two Popen children if they exit in this race.
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return
        for child in (server, helper):
            if child is not None and child.pid == pid:
                child.returncode = os.waitstatus_to_exitcode(status)


def emit(state, reason=None):
    message = {'component': 'credential-publish', 'state': state}
    if isinstance(reason, str) and reason in SAFE_ERRORS | {'credential_guard_failed', 'configuration_or_io_error'}:
        message['reason'] = reason
    print(json.dumps(message), flush=True)


def supervise(server_command, helper_command=None, interval=300, helper_timeout=90, shutdown_timeout=60):
    server = subprocess.Popen(server_command, start_new_session=True)
    helper = None; helper_started = 0; next_run = time.monotonic(); stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    previous = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        while server.poll() is None and not stopping:
            reap_orphans(server, helper)
            if server.returncode is not None:
                break
            now = time.monotonic()
            if helper is not None and helper.poll() is not None:
                # Never echo arbitrary subprocess output (including malformed future helpers).
                terminate_group(helper)
                raw = helper.stdout.read(4096)
                helper.stdout.close()
                reason = None
                try:
                    value = json.loads(raw)
                    reason = value.get('reason')
                    state = value.get('state')
                    if helper.returncode != 0 or state not in ('healthy', 'published', 'unconfigured'):
                        state = 'attempt_failed'
                except Exception:
                    state = 'invalid_helper_output'
                emit(state, reason)
                helper = None; next_run = now + interval
            if helper is not None and now - helper_started >= helper_timeout:
                terminate_group(helper); helper.stdout.close(); helper = None; next_run = now + interval
                emit('attempt_timed_out')
            if helper_command and helper is None and now >= next_run:
                try:
                    helper = subprocess.Popen(helper_command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
                    helper_started = now
                except OSError:
                    emit('start_failed'); next_run = now + interval
            time.sleep(0.1)
        terminate_group(helper)
        if helper is not None and helper.stdout is not None:
            helper.stdout.close()
        if server.poll() is None:
            # Let T3 itself manage provider children; don't signal their whole group on graceful stop.
            server.terminate()
            try:
                server.wait(timeout=shutdown_timeout)
            except subprocess.TimeoutExpired:
                terminate_group(server)
        if stopping:
            return 0
        return server.returncode if server.returncode >= 0 else 128 - server.returncode
    finally:
        terminate_group(helper)
        if helper is not None and helper.stdout is not None:
            helper.stdout.close()
        if server.poll() is None:
            terminate_group(server)
        for signum, handler in previous.items(): signal.signal(signum, handler)


def main():
    p = argparse.ArgumentParser()
    for name in ('state-dir', 'node-bin', 'cli', 'base-dir', 'node-id'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--helper-enabled', action='store_true')
    a = p.parse_args()
    helper = None
    if a.helper_enabled:
        helper = [sys.executable, os.path.join(os.path.dirname(__file__), 'publish_once.py')]
        for name in ('state_dir', 'node_bin', 'cli', 'base_dir', 'node_id', 'port'):
            helper += ['--'+name.replace('_', '-'), str(getattr(a, name))]
    return supervise([a.node_bin, a.cli, 'serve', '--port', str(a.port), '--host', '0.0.0.0', '--base-dir', a.base_dir], helper)


if __name__ == '__main__': sys.exit(main())
