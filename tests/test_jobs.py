import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from backend.jobs import Jobs
from backend.server import make_handler


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def engine(self, agent=None, timeout=2):
        return Jobs(self.tmp.name, self.tmp.name, agent, timeout)

    def wait(self, jobs, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = jobs.get(job)
            if row['status'] not in ('queued', 'running'):
                return row
            time.sleep(0.01)
        self.fail('Job did not finish')

    def test_diagnostics_persistence(self):
        jobs = self.engine()
        job = jobs.submit('diagnostics', '')['id']
        self.assertEqual(self.wait(jobs, job)['status'], 'completed')
        self.assertIn('Python:', ''.join(e['text'] for e in jobs.events(job)))
        restarted = self.engine()
        self.assertEqual(restarted.get(job)['exit_code'], 0)
        self.assertEqual(restarted.events(job)[0]['kind'], 'ack')

    def test_prompt_is_single_literal_argument(self):
        jobs = self.engine([sys.executable, '-u', '-c', 'import sys; print(sys.argv[1])', '{prompt}'])
        prompt = 'a; $(echo unsafe) "quoted"'
        job = jobs.submit('agent', prompt)['id']
        self.assertEqual(self.wait(jobs, job)['status'], 'completed')
        self.assertIn(prompt, ''.join(e['text'] for e in jobs.events(job)))

    def test_failure_and_missing_executable(self):
        for argv in ([sys.executable, '-c', 'raise SystemExit(7)', '{prompt}'],
                     ['/nonexistent/terminal-agent', '{prompt}']):
            jobs = self.engine(argv)
            job = jobs.submit('agent', 'test')['id']
            self.assertEqual(self.wait(jobs, job)['status'], 'failed')

    def test_timeout(self):
        jobs = self.engine([sys.executable, '-c', 'import time; time.sleep(10)', '{prompt}'], timeout=0.1)
        job = jobs.submit('agent', 'test')['id']
        self.assertEqual(self.wait(jobs, job)['status'], 'timed_out')

    def test_restart_interrupted_and_validation(self):
        jobs = self.engine()
        with jobs.connect() as db:
            db.execute("INSERT INTO jobs(id,status) VALUES('unfinished','running')")
        self.assertEqual(self.engine().get('unfinished')['status'], 'interrupted')
        with self.assertRaises(ValueError):
            jobs.submit('agent', 'not configured')
        with self.assertRaises(ValueError):
            self.engine(['missing-placeholder'])

    def test_http_and_event_resume(self):
        jobs = self.engine()
        token = 'test-token-at-least-24-characters'
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(jobs, token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'

        def request(path, payload=None, headers=None):
            h = {'Authorization': 'Bearer ' + token}
            h.update(headers or {})
            data = json.dumps(payload).encode() if payload is not None else None
            return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h), timeout=5)

        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(base + '/jobs', timeout=5)
        self.assertEqual(unauthorized.exception.code, 401)
        unauthorized.exception.close()
        with request('/jobs', {'template': 'diagnostics'}) as response:
            self.assertEqual(response.status, 202)
            job = json.load(response)['id']
        self.wait(jobs, job)
        first = jobs.events(job)[0]['id']
        with request(f'/jobs/{job}/events', headers={'Last-Event-ID': str(first)}) as response:
            stream = response.read().decode()
        self.assertNotIn('event: ack', stream)
        self.assertIn('event: output', stream)
        self.assertIn('completed', stream)
        with request('/jobs') as response:
            self.assertEqual(json.load(response)[0]['id'], job)


if __name__ == '__main__':
    unittest.main()
