import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

from backend.jobs import Jobs
from backend.server import LimitedHTTPServer, make_handler


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Condition did not become true')


def running(pid):
    # Killed grandchildren can remain zombies briefly until the OS reaps them.
    proc = Path(f'/proc/{pid}/stat')
    if sys.platform.startswith('linux') and proc.exists():
        return proc.read_text().split(') ', 1)[1][0] != 'Z'
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@unittest.skipUnless(os.name == 'posix', 'POSIX security guarantees')
class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_local_credentials_and_custom_databases_ignored(self):
        paths = ['.env.local', '.env.production', 'custom/history.sqlite3',
                 'custom/history.sqlite3-journal', 'custom/history.sqlite3-wal',
                 'custom/history.sqlite3-shm', 'custom/backup.db', '.env.example']
        result = subprocess.run(['git', 'check-ignore', '--no-index', *paths],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(result.stdout.splitlines()), set(paths[:-1]))

    def test_private_storage_and_existing_permissions(self):
        data = self.root / 'data'
        old = os.umask(0o022)
        try:
            jobs = Jobs(data, self.root)
        finally:
            os.umask(old)
        self.addCleanup(jobs.close)
        self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(jobs.database).stat().st_mode), 0o600)
        data.chmod(0o755)
        Path(jobs.database).chmod(0o644)
        restarted = Jobs(data, self.root)
        self.addCleanup(restarted.close)
        self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(jobs.database).stat().st_mode), 0o600)
        with restarted.connect() as db:
            db.execute("INSERT INTO jobs(id,status) VALUES('probe','queued')")
            journal = Path(jobs.database + '-journal')
            self.assertTrue(journal.exists())
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)

    def test_symlinks_and_hardlinks_rejected(self):
        target = self.root / 'target'
        target.mkdir()
        link = self.root / 'link'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            Jobs(link, self.root)
        database = target / 'terminal.sqlite3'
        outside = self.root / 'outside'
        outside.write_text('untouched')
        database.symlink_to(outside)
        with self.assertRaises(OSError):
            Jobs(target, self.root)
        database.unlink()
        os.link(outside, database)
        with self.assertRaises(ValueError):
            Jobs(target, self.root)
        self.assertEqual(outside.read_text(), 'untouched')

    def test_api_token_not_inherited(self):
        jobs = Jobs(self.root / 'data', self.root,
                    [sys.executable, '-c', 'import os; print("TERMINAL_API_TOKEN" in os.environ)', '{prompt}'])
        self.addCleanup(jobs.close)
        old = os.environ.get('TERMINAL_API_TOKEN')
        os.environ['TERMINAL_API_TOKEN'] = 'dummy-security-test-token'
        try:
            job = jobs.submit('agent', 'probe')['id']
            wait_until(lambda: jobs.get(job)['status'] == 'completed')
        finally:
            if old is None:
                os.environ.pop('TERMINAL_API_TOKEN', None)
            else:
                os.environ['TERMINAL_API_TOKEN'] = old
        output = ''.join(e['text'] for e in jobs.events(job) if e['kind'] == 'output')
        self.assertEqual(output.strip(), 'False')

    def test_shutdown_kills_process_group(self):
        marker = self.root / 'pids'
        program = ('import os,subprocess,sys,time; from pathlib import Path; '
                   'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                   f'Path({str(marker)!r}).write_text(str(os.getpid())+","+str(child.pid)); time.sleep(30)')
        jobs = Jobs(self.root / 'data', self.root, [sys.executable, '-c', program, '{prompt}'])
        self.addCleanup(jobs.close)
        job = jobs.submit('agent', 'probe')['id']
        wait_until(marker.exists)
        pids = [int(x) for x in marker.read_text().split(',')]
        jobs.close()
        for pid in pids:
            wait_until(lambda pid=pid: not running(pid))
        self.assertEqual(jobs.get(job)['status'], 'interrupted')
        with self.assertRaises(RuntimeError):
            jobs.submit('agent', 'after shutdown')

    def test_sigterm_entrypoint_cleans_children(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        marker = self.root / 'pid'
        program = f'import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)'
        environment = os.environ.copy()
        environment.update(TERMINAL_API_TOKEN='dummy-security-test-token',
                           TERMINAL_DATA_DIR=str(self.root / 'data'),
                           TERMINAL_AGENT_ARGV=json.dumps([sys.executable, '-c', program, '{prompt}']))
        launcher = ('from backend import server; original=server.LimitedHTTPServer; '
                    f'server.LimitedHTTPServer=lambda address,handler: original(("127.0.0.1",{port}),handler); server.main()')
        parent = subprocess.Popen([sys.executable, '-c', launcher], env=environment,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        pid = None
        try:
            def ready():
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        return True
                except OSError:
                    return False
            wait_until(ready)
            request = urllib.request.Request(f'http://127.0.0.1:{port}/jobs',
                data=json.dumps({'template': 'agent', 'prompt': 'probe'}).encode(),
                headers={'Authorization': 'Bearer dummy-security-test-token'})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
            wait_until(marker.exists)
            pid = int(marker.read_text())
            parent.send_signal(signal.SIGTERM)
            self.assertEqual(parent.wait(timeout=3), 0)
            wait_until(lambda: not running(pid))
            self.assertEqual(parent.stderr.read(), b'')
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            parent.stderr.close()
            if pid and running(pid):
                os.killpg(pid, signal.SIGKILL)

    def server(self, **limits):
        jobs = Jobs(self.root / 'data', self.root)
        server = LimitedHTTPServer(('127.0.0.1', 0), make_handler(jobs, 'dummy-token'), **limits)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        def cleanup():
            server.shutdown()
            jobs.close()
            server.server_close()
            thread.join()
        self.addCleanup(cleanup)
        return server

    def test_connection_cap_before_authentication(self):
        server = self.server(max_connections=1)
        first = socket.create_connection(server.server_address, timeout=1)
        self.addCleanup(first.close)
        wait_until(lambda: len(server._connections) == 1)
        with socket.create_connection(server.server_address, timeout=1) as extra:
            self.assertEqual(extra.recv(1), b'')
        first.close()
        wait_until(lambda: len(server._connections) == 0)
        with socket.create_connection(server.server_address, timeout=1) as recovered:
            recovered.sendall(b'GET /templates HTTP/1.0\r\nAuthorization: Bearer dummy-token\r\n\r\n')
            self.assertIn(b'200 OK', recovered.recv(1024))

    def test_slow_headers_hit_absolute_deadline(self):
        server = self.server(request_deadline=.15)
        with socket.create_connection(server.server_address, timeout=1) as connection:
            connection.sendall(b'GET /templates HTTP/1.0\r\nX-Test: ')
            time.sleep(.08)
            connection.sendall(b'x')
            time.sleep(.12)
            self.assertEqual(connection.recv(1), b'')
        wait_until(lambda: len(server._connections) == 0)

    def test_stream_deadline_and_resume(self):
        server = self.server(stream_deadline=.15)
        jobs = Jobs(self.root / 'stream-data', self.root,
                    [sys.executable, '-c', 'import time; time.sleep(.4)', '{prompt}'])
        self.addCleanup(jobs.close)
        # Use a distinct handler/storage without changing the server's resource limits.
        server.RequestHandlerClass = make_handler(jobs, 'dummy-token')
        job = jobs.submit('agent', 'probe')['id']
        with socket.create_connection(server.server_address, timeout=1) as connection:
            connection.sendall(f'GET /jobs/{job}/events HTTP/1.0\r\nAuthorization: Bearer dummy-token\r\n\r\n'.encode())
            stream = b''
            while chunk := connection.recv(4096):
                stream += chunk
        self.assertIn(b'event: ack', stream)
        self.assertNotIn(b'completed', stream)
        wait_until(lambda: jobs.get(job)['status'] == 'completed')
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/jobs/{job}/events',
                                        headers={'Authorization': 'Bearer dummy-token', 'Last-Event-ID': '1'})
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertIn(b'completed', response.read())


if __name__ == '__main__':
    unittest.main()
