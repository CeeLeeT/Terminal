import os
import signal
import stat
import codecs
from contextlib import contextmanager
import sqlite3
import subprocess
import sys
import threading
import uuid
from pathlib import Path


class Jobs:
    def __init__(self, directory, workdir, agent=None, timeout=120):
        if os.name != 'posix':
            raise RuntimeError('Secure storage and process cleanup currently require POSIX')
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid():
            raise ValueError('Data directory must be owned by the server user and not be a symlink')
        directory.chmod(0o700)
        self.database = str(directory / 'terminal.sqlite3')
        fd = os.open(self.database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('Database must be an owned regular file without hard links')
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.workdir = str(Path(workdir).resolve())
        self.agent, self.timeout = agent, timeout
        self.slots = threading.BoundedSemaphore(2)
        self._lock = threading.RLock()
        self._closing = False
        self._processes = {}
        self._threads = set()
        if timeout <= 0:
            raise ValueError('Timeout must be positive')
        if agent is not None and (not isinstance(agent, list) or not agent
                or any(not isinstance(x, str) or not x for x in agent)
                or agent.count('{prompt}') != 1):
            raise ValueError('Agent argv requires exactly one {prompt} argument')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, template TEXT, prompt TEXT, status TEXT,
                    exit_code INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, kind TEXT, text TEXT);
                CREATE INDEX IF NOT EXISTS events_job_id ON events(job,id);
            ''')
            for row in db.execute("SELECT id FROM jobs WHERE status IN ('queued','running')").fetchall():
                db.execute("UPDATE jobs SET status='interrupted' WHERE id=?", row)
                db.execute('INSERT INTO events(job,kind,text) VALUES(?,?,?)', (row[0], 'status', 'interrupted'))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def templates(self):
        return ['diagnostics'] + (['agent'] if self.agent else [])

    def get(self, job):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            return dict(row) if row else None

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC, rowid DESC LIMIT 100')]

    def events(self, job, after=0):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM events WHERE job=? AND id>? ORDER BY id', (job, after))]

    def event(self, job, kind, text):
        with self.connect() as db:
            db.execute('INSERT INTO events(job,kind,text) VALUES(?,?,?)', (job, kind, text))

    def status(self, job, status, code=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,exit_code=? WHERE id=?', (status, code, job))
            db.execute('INSERT INTO events(job,kind,text) VALUES(?,?,?)', (job, 'status', status))

    def submit(self, template, prompt):
        if template not in self.templates() or not isinstance(prompt, str) or len(prompt) > 16000:
            raise ValueError('Unknown template or invalid prompt')
        if template == 'agent' and not prompt.strip():
            raise ValueError('Agent prompt must not be empty')
        if not self.slots.acquire(blocking=False):
            raise RuntimeError('Two jobs are already active')
        job = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('INSERT INTO jobs(id,template,prompt,status) VALUES(?,?,?,?)',
                           (job, template, prompt, 'queued'))
                db.execute('INSERT INTO events(job,kind,text) VALUES(?,?,?)', (job, 'ack', 'Auftrag erhalten.'))
            with self._lock:
                if self._closing:
                    self.status(job, 'interrupted')
                    raise RuntimeError('Job engine is stopping')
                thread = threading.Thread(target=self.run, args=(job, template, prompt))
                self._threads.add(thread)
                thread.start()
        except Exception:
            self.slots.release()
            raise
        return {'id': job, 'status': 'queued', 'message': 'Auftrag erhalten.'}

    @staticmethod
    def kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self):
        # Serialize shutdown with Popen so no process can escape registration.
        with self._lock:
            self._closing = True
            for process in self._processes.values():
                self.kill(process)
            threads = list(self._threads)
        for thread in threads:
            thread.join()

    def run(self, job, template, prompt):
        process = timer = None
        expired = threading.Event()
        limited = False
        try:
            self.status(job, 'running')
            argv = ([sys.executable, '-u', '-c',
                     'import platform; print("Python:",platform.python_version()); print("System:",platform.system())']
                    if template == 'diagnostics' else [prompt if x == '{prompt}' else x for x in self.agent])
            with self._lock:
                if self._closing:
                    self.status(job, 'interrupted')
                    return
                environment = os.environ.copy()
                environment.pop('TERMINAL_API_TOKEN', None)
                process = subprocess.Popen(argv, cwd=self.workdir, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           env=environment, start_new_session=True)
                self._processes[job] = process

            def kill():
                self.kill(process)

            def timeout():
                expired.set()
                kill()

            timer = threading.Timer(self.timeout, timeout)
            timer.start()
            count = 0
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while chunk := process.stdout.read1(4096):
                count += len(chunk)
                if count > 1024 * 1024:
                    limited = True
                    kill()
                    self.event(job, 'error', 'Output limit exceeded (1 MiB).')
                    break
                text = decoder.decode(chunk)
                if text:
                    self.event(job, 'output', text)
            tail = decoder.decode(b'', final=True)
            if tail:
                self.event(job, 'output', tail)
            code = process.wait()
            timer.cancel()
            status = ('interrupted' if self._closing else
                      'timed_out' if expired.is_set() else ('failed' if limited or code else 'completed'))
            self.status(job, status, code)
        except Exception as exc:
            if process and process.poll() is None:
                self.kill(process)
                process.wait()
            self.event(job, 'error', str(exc))
            self.status(job, 'failed')
        finally:
            if process:
                self.kill(process)
            if timer:
                timer.cancel()
            if process and process.stdout:
                process.stdout.close()
            self.slots.release()
            with self._lock:
                self._processes.pop(job, None)
                self._threads.discard(threading.current_thread())
