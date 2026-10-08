import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .jobs import Jobs


def make_handler(jobs, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

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
            except (BrokenPipeError, ConnectionResetError):
                pass
    return Handler


def main():
    token = os.environ.get('TERMINAL_API_TOKEN', '')
    if len(token) < 24 or not token.isascii():
        raise SystemExit('Set a random ASCII TERMINAL_API_TOKEN with at least 24 characters.')
    raw = os.environ.get('TERMINAL_AGENT_ARGV', '')
    jobs = Jobs(os.environ.get('TERMINAL_DATA_DIR', 'data'), os.environ.get('TERMINAL_WORKDIR', '.'),
                json.loads(raw) if raw else None)
    server = ThreadingHTTPServer(('127.0.0.1', 8765), make_handler(jobs, token))
    print('Terminal API: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
