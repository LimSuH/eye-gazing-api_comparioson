"""Local browser GUI. One serial worker owns all three Python gaze engines."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import traceback
from urllib.parse import parse_qs, urlsplit

from .protocol import config
from .session import SharedSession
from .runtime_diagnostics import RuntimeDiagnostics
from .frame_replies import FrameReplies

ROOT = Path(__file__).resolve().parents[1]
REVISION = '2026-09-02-visible-calibration-targets-1'
WEB_ENTRYPOINTS = ('index.html','app.js','diagnostics.js','style.css','webgazer-adapter.js','favicon.svg')


def health_payload():
    """Inspect files only: no model import, camera, or session mutation."""
    from setup_envs import required_web_files
    from verify_bundle import manifest_entries
    expected = {entry['path']:entry['bytes'] for entry in manifest_entries()}
    paths = [ROOT/'web'/name for name in WEB_ENTRYPOINTS] + required_web_files()
    files = []
    for path in paths:
        exists = path.is_file()
        files.append({'url':'/'+path.relative_to(ROOT/'web').as_posix(),
                      'exists':exists,'bytes':path.stat().st_size if exists else None,
                      'expected_bytes':expected.get(path.relative_to(ROOT).as_posix())
                      if path.relative_to(ROOT/'web').parts[0] in ('vendor','mediapipe') else None})
    return {'application':'gaze-api-compare','revision':REVISION,'web_files':files}


class Application:
    def __init__(self, samples, diagnostics):
        self.diagnostics = diagnostics
        self.session = SharedSession(samples=samples, progress=diagnostics.stage)
        self.replies = FrameReplies()

    def dispatch(self, path, data):
        if path == '/api/start':
            self.replies.clear()
        if path == '/api/frame':
            self.session.require_session(data.get('session_id'))
        key = self.replies.begin(data.get('session_id'), data.get('seq')) if path == '/api/frame' else None
        self.diagnostics.begin(path, data.get('seq'))
        try:
            result = self._dispatch(path, data)
            if key is not None:
                self.diagnostics.stage('response.encode')
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
                # Publish BEFORE the HTTP handler attempts any socket write.
                self.replies.finish(key, 200, body)
        except Exception as exc:
            if key is not None:
                status = 400 if isinstance(exc, (ValueError, TypeError, KeyError)) else 500
                body = json.dumps({'error':f'{type(exc).__name__}: {exc}'}, ensure_ascii=False).encode('utf-8')
                self.replies.finish(key, status, body)
            self.diagnostics.failed()
            raise
        self.diagnostics.complete()
        return result

    def _dispatch(self, path, data):
        if path == '/api/start':
            return self.session.start(data)
        self.session.require_session(data.get('session_id'))
        if path == '/api/frame':
            self.diagnostics.stage('frame.decode')
            import cv2
            import numpy as np
            encoded=data.get('image')
            if not isinstance(encoded,str) or len(encoded)>5500000:
                raise ValueError('Invalid image size')
            raw=base64.b64decode(encoded,validate=True)
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Only lossless PNG frames are accepted')
            # Bound declared dimensions before allocating a decoded image.
            if len(raw)<24:
                raise ValueError('Invalid PNG')
            dimensions=[int.from_bytes(raw[16:20],'big'),int.from_bytes(raw[20:24],'big')]
            if dimensions != self.session.camera_size:
                raise ValueError('Camera image size changed')
            frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError('Could not decode image')
            return self.session.frame(data,frame,hashlib.sha256(raw).hexdigest())
        if path == '/api/finish':
            return self.session.finish(data)
        if path == '/api/end':
            self.replies.clear()
            self.diagnostics.stage('session.close')
            self.session.close()
            return {'phase':'idle'}
        raise ValueError('Unknown endpoint')


class Handler(SimpleHTTPRequestHandler):
    # Persistent connections avoid a fresh TCP connection for every PNG frame.
    # All JSON and static responses carry Content-Length (including errors).
    protocol_version = 'HTTP/1.1'
    timeout = 30
    extensions_map={**SimpleHTTPRequestHandler.extensions_map,
                    '.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm'}

    def __init__(self,*args,web_root,**kwargs):
        super().__init__(*args,directory=str(web_root),**kwargs)

    def valid_host(self):
        port=self.server.server_port
        return self.headers.get('Host') in {f'localhost:{port}',f'127.0.0.1:{port}'}

    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Permissions-Policy','camera=(self), microphone=()')
        if getattr(self, 'close_connection', False):
            self.send_header('Connection', 'close')
        super().end_headers()

    def send_json(self,status,data,head_only=False):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        return self.send_bytes(status, body, head_only=head_only)

    def send_bytes(self, status, body, head_only=False):
        diagnostics = getattr(self.server, 'diagnostics', None)
        endpoint = urlsplit(self.path).path
        seq = getattr(self, 'frame_seq', None)
        try:
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
                self.wfile.flush()
        except OSError:
            self.close_connection = True
            if diagnostics is not None:
                diagnostics.transfer(endpoint, seq, 'write_failed', status, len(body), error=True)
            # Headers or part of the body may already be sent. Do not attempt
            # a second HTTP status/body on this damaged connection.
            return False
        if diagnostics is not None and not head_only:
            diagnostics.transfer(endpoint, seq, 'server_write_completed', status, len(body))
        return True

    def do_GET(self):
        self.serve_read(head_only=False)

    def do_HEAD(self):
        self.serve_read(head_only=True)

    def serve_read(self,head_only):
        self.frame_seq = None
        if not self.valid_host():
            self.send_error(403)
            return
        path=urlsplit(self.path).path
        if path == '/api/config':
            self.send_json(200,{**config(),'token':self.server.token,
                               'samples_per_point':self.server.app.session.samples},head_only=head_only)
        elif path == '/api/health':
            # Remains responsive while the serial model worker is occupied.
            payload = health_payload()
            diagnostics = getattr(self.server, 'diagnostics', None)
            if diagnostics is not None:
                payload['last_operation'] = diagnostics.snapshot()
            self.send_json(200,payload,head_only=head_only)
        elif path == '/api/frame-result':
            # Read cached JSON only. No worker, camera, inference, or fitting.
            port = self.server.server_port
            if (self.headers.get('X-Gaze-Token') != self.server.token or
                self.headers.get('Origin') not in (None, f'http://localhost:{port}', f'http://127.0.0.1:{port}')):
                self.send_json(403, {'error':'Forbidden'}, head_only=head_only)
                return
            try:
                query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
                if set(query) != {'seq'} or len(query['seq']) != 1:
                    raise ValueError('Expected one frame sequence')
                seq = int(query['seq'][0])
                state, reply = self.server.app.replies.lookup(self.headers.get('X-Gaze-Session'), seq)
                self.frame_seq = seq
                if state == 'ready':
                    status, body = reply
                    self.send_bytes(status, body, head_only=head_only)
                elif state == 'pending':
                    self.send_json(202, {'pending':True, 'seq':seq}, head_only=head_only)
                else:
                    self.send_json(404, {'error':'No saved reply for this exact session and frame'}, head_only=head_only)
            except (ValueError, TypeError) as exc:
                self.send_json(400, {'error':str(exc)}, head_only=head_only)
        elif path == '/' or path in {'/'+name for name in WEB_ENTRYPOINTS} or path.startswith(('/vendor/','/mediapipe/')):
            if head_only:
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_error(404)

    def list_directory(self,path):
        self.send_error(403)
        return None

    def do_POST(self):
        self.frame_seq = None
        port=self.server.server_port
        if (not self.valid_host() or self.headers.get('X-Gaze-Token')!=self.server.token or
            self.headers.get('Content-Type','').split(';')[0]!='application/json' or
            self.headers.get('Origin') not in (None,f'http://localhost:{port}',f'http://127.0.0.1:{port}')):
            self.close_connection = True  # Rejected request body is still unread.
            self.send_json(403,{'error':'Forbidden'})
            return
        body_consumed = False
        try:
            if self.headers.get('Transfer-Encoding') is not None:
                raise ValueError('Transfer-Encoding is not supported; send a fixed-length JSON body')
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 6*1024*1024:
                self.close_connection = True
                raise ValueError('Request is too large or empty')
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.close_connection = True
                raise ValueError('Incomplete request body')
            body_consumed = True
            data=json.loads(raw)
            if not isinstance(data,dict):
                raise ValueError('Expected object')
            path=urlsplit(self.path).path
            if path == '/api/frame':
                self.frame_seq = data.get('seq')
            result=self.server.worker.submit(self.server.app.dispatch,path,data).result()
            self.send_json(200,result)
        except (ValueError,TypeError,KeyError) as exc:
            if not body_consumed:
                self.close_connection = True
            self.log_http_exception()
            self.send_json(400,{'error':str(exc)})
        except Exception as exc:
            if not body_consumed:
                self.close_connection = True
            # Preserve the underlying traceback in the user's Python terminal.
            self.log_http_exception()
            traceback.print_exc()
            self.send_json(500,{'error':f'{type(exc).__name__}: {exc}'})

    def log_http_exception(self):
        diagnostics = getattr(self.server, 'diagnostics', None)
        if diagnostics is not None:
            # Also covers request parsing and response serialization failures.
            # Do not put the request body or authentication headers in the log.
            diagnostics.logger.exception('HTTP request/response failure')

    def log_message(self,fmt,*args):
        # Avoid one console line per webcam frame. Errors remain visible.
        if len(args)>1 and str(args[1]).startswith(('4','5')):
            super().log_message(fmt,*args)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--samples',type=int,default=30)
    p.add_argument('--logs',type=Path,default=ROOT/'logs')
    args=p.parse_args(argv)
    if not 10 <= args.samples <= 60:
        p.error('--samples must be between 10 and 60')
    with RuntimeDiagnostics(args.logs) as diagnostics, ThreadPoolExecutor(max_workers=1,thread_name_prefix='gaze-models') as worker:
        app=Application(args.samples,diagnostics)
        with ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,web_root=ROOT/'web')) as server:
            server.token=secrets.token_urlsafe(32)
            server.app,server.worker=app,worker
            server.diagnostics=diagnostics
            print(f'HTTP server READY ({REVISION})\nOpen manually: http://127.0.0.1:{server.server_port}/\nAlternative: http://localhost:{server.server_port}/\nConnection check (no camera): http://127.0.0.1:{server.server_port}/api/health\nStop server: Ctrl+C\nCamera is opened by the browser, never by OpenCV.',flush=True)
            print(f'Automatic diagnostic logs: {args.logs.resolve()} (no webcam frames saved)',flush=True)
            try:
                server.serve_forever(poll_interval=.3)
            except KeyboardInterrupt:
                pass
            finally:
                worker.submit(app.session.close).result()


if __name__=='__main__':
    main()
