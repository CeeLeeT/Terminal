import hmac
import json
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .jobs import Jobs


class LimitedHTTPServer(ThreadingHTTPServer):
    """Bound accepted connections before creating threads, including unauthenticated ones."""
    request_queue_size = 16

    def __init__(self, address, handler, max_connections=16, request_deadline=10,
                 stream_deadline=150):
        self.request_deadline = request_deadline
        self.stream_deadline = stream_deadline
        self._slots = threading.BoundedSemaphore(max_connections)
        self._connections = set()
        self._connection_lock = threading.Lock()
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._connection_lock:
            self._connections.add(request)
        try:
            super().process_request(request, client_address)
        except Exception:
            self.release_connection(request)
            raise

    def release_connection(self, request):
        with self._connection_lock:
            self._connections.discard(request)
        self._slots.release()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.release_connection(request)

    def server_close(self):
        with self._connection_lock:
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


def make_handler(jobs, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(getattr(self.server, 'request_deadline', 10))
            self.set_deadline(getattr(self.server, 'request_deadline', 10))

        def set_deadline(self, seconds):
            if hasattr(self, '_deadline'):
                self._deadline.cancel()
            self._deadline = threading.Timer(seconds, self.expire_connection)
            self._deadline.daemon = True
            self._deadline.start()

        def expire_connection(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            try:
                super().finish()
            finally:
                self._deadline.cancel()

        def handle(self):
            try:
                super().handle()
            except OSError:
                # Deadlines and disconnects are expected; do not log request details.
                pass

        def log_message(self, *args):
            pass

        def reply(self, code, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            supplied = self.headers.get('Authorization', '').encode('utf-8')
            if hmac.compare_digest(supplied, ('Bearer ' + token).encode('utf-8')):
                return True
            self.reply(401, {'error': 'Authorization required'})
            return False

        def do_POST(self):
            if not self.authorized():
                return
            if urlsplit(self.path).path != '/jobs':
                return self.reply(404, {'error': 'Not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    raise ValueError('Invalid body size')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('Expected JSON object')
                self.reply(202, jobs.submit(payload.get('template'), payload.get('prompt', '')))
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except RuntimeError as exc:
                self.reply(429, {'error': str(exc)})

        def do_GET(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            if path == '/templates':
                return self.reply(200, jobs.templates())
            if path == '/jobs':
                return self.reply(200, jobs.list())
            parts = path.strip('/').split('/')
            if len(parts) not in (2, 3) or parts[0] != 'jobs':
                return self.reply(404, {'error': 'Not found'})
            job = jobs.get(parts[1])
            if job is None:
                return self.reply(404, {'error': 'Unknown job'})
            if len(parts) == 2:
                return self.reply(200, job)
            if parts[2] != 'events':
                return self.reply(404, {'error': 'Not found'})
            try:
                after = int(self.headers.get('Last-Event-ID', '0'))
                if after < 0:
                    raise ValueError()
            except ValueError:
                return self.reply(400, {'error': 'Invalid Last-Event-ID'})
            self.set_deadline(getattr(self.server, 'stream_deadline', 150))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                while True:
                    active = jobs.get(parts[1])['status'] in ('queued', 'running')
                    for event in jobs.events(parts[1], after):
                        data = json.dumps({'text': event['text']}, ensure_ascii=False)
                        self.wfile.write(f"id: {event['id']}\nevent: {event['kind']}\ndata: {data}\n\n".encode())
                        after = event['id']
                    self.wfile.flush()
                    if not active:
                        break
                    self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass
    return Handler


def main():
    token = os.environ.get('TERMINAL_API_TOKEN', '')
    if len(token) < 24 or not token.isascii():
        raise SystemExit('Set a random ASCII TERMINAL_API_TOKEN with at least 24 characters.')
    raw = os.environ.get('TERMINAL_AGENT_ARGV', '')
    jobs = Jobs(os.environ.get('TERMINAL_DATA_DIR', 'data'), os.environ.get('TERMINAL_WORKDIR', '.'),
                json.loads(raw) if raw else None)
    server = None
    def stop(*_):
        raise SystemExit(0)

    previous_sigterm = signal.signal(signal.SIGTERM, stop)
    print('Terminal API: http://127.0.0.1:8765', flush=True)
    try:
        server = LimitedHTTPServer(('127.0.0.1', 8765), make_handler(jobs, token))
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        jobs.close()
        if server is not None:
            server.server_close()
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == '__main__':
    main()
