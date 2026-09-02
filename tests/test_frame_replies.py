"""Use fake models and in-memory HTTP streams; never bind a server or camera."""
from concurrent.futures import Future
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from gaze_compare.frame_replies import FrameReplies
from gaze_compare.session import PYTHON_ENGINES, SharedSession
from gaze_compare.webserver import Application, Handler
from test_shared_session import FakeBackend, FakeReference, Frame


SESSION = 'a'*32


class InMemorySocket:
    def __init__(self, request, *, fail_on_call=None):
        self.incoming = io.BytesIO(request)
        self.output = bytearray()
        self.calls = 0
        self.fail_on_call = fail_on_call
    def settimeout(self, seconds):
        pass
    def makefile(self, *args):
        return self.incoming
    def sendall(self, value):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ConnectionResetError('synthetic response connection reset')
        self.output.extend(value)


class ImmediateWorker:
    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


def request(method, path, data=None, *, token='test-token', session=None, close=True):
    body = json.dumps(data).encode() if data is not None else b''
    headers = [f'{method} {path} HTTP/1.1', 'Host: localhost:8765',
               f'X-Gaze-Token: {token}', 'Content-Type: application/json',
               f'Content-Length: {len(body)}']
    if session is not None:
        headers.append(f'X-Gaze-Session: {session}')
    if close:
        headers.append('Connection: close')
    return ('\r\n'.join(headers)+'\r\n\r\n').encode()+body


class FrameReplyTests(unittest.TestCase):
    def setUp(self):
        self.logs = MagicMock()
        self.app = Application(1, self.logs)
        self.backends = {name:FakeBackend(name) for name in PYTHON_ENGINES}
        self.app.session = SharedSession(samples=1, backend_factory=lambda *_:self.backends,
                                         reference_factory=FakeReference)
        self.app.session.start(dict(width=1000,height=800,camera_size=[640,480]))
        self.addCleanup(self.app.session.close)
        dispatch = self.app._dispatch
        def fake_images(path, data):
            if path == '/api/frame':
                return self.app.session.frame(data,Frame(data['seq']),'fake-frame-hash')
            return dispatch(path, data)
        self.app._dispatch = fake_images
        self.server = SimpleNamespace(server_port=8765, token='test-token',
                                      app=self.app, diagnostics=self.logs, worker=ImmediateWorker())
    def payload(self, seq=0):
        return dict(session_id=self.app.session.session_id,seq=seq,viewport=[1000,800],
                    mode='collect',engine='eyetrax',target_id=self.app.session.point_index,
                    webgazer_valid=True)
    def serve(self, raw, **kwargs):
        connection = InMemorySocket(raw, **kwargs)
        # The real request parser/headers/body writer runs over fake streams.
        with patch('socket.socket', side_effect=AssertionError('No live sockets permitted')), patch.object(Handler, 'log_message'):
            Handler(connection, ('127.0.0.1', 12345), self.server, web_root='web')
        return bytes(connection.output)

    def test_lost_body_recovers_exact_reply_without_second_model_call_or_fit(self):
        data = self.payload()
        # First write sends headers; the second (JSON body) loses its connection.
        original = self.serve(request('POST','/api/frame',data), fail_on_call=2)
        self.assertIn(b'HTTP/1.1 200 OK', original)
        self.assertEqual(original.count(b'HTTP/1.1'), 1)  # No second status after a partial response.
        self.assertEqual(self.app.session.accepted_ids, [0])
        state, (status, saved) = self.app.replies.lookup(data['session_id'], 0)
        self.assertEqual((state,status), ('ready',200))
        self.assertEqual(saved, json.dumps(json.loads(saved),ensure_ascii=False,allow_nan=False).encode())
        # Recovery remains available even if dispatching to the model worker is prohibited.
        self.server.worker = MagicMock()
        self.server.worker.submit.side_effect = AssertionError('Recovery must not call a model')
        recovered = self.serve(request('GET','/api/frame-result?seq=0', session=data['session_id']))
        self.assertEqual(recovered.split(b'\r\n\r\n',1)[1], saved)
        self.assertEqual(self.app.session.accepted_ids, [0])
        self.assertEqual(self.app.session.reference_frame_id, 0)
        self.assertTrue(all(b.seen==[0] and not b.fit_calls for b in self.backends.values()))
        outcomes = [c.args[2] for c in self.logs.transfer.call_args_list]
        self.assertIn('write_failed', outcomes)
        self.assertIn('server_write_completed', outcomes)
        self.assertTrue(any(c.kwargs.get('error') for c in self.logs.transfer.call_args_list))

    def test_headers_failure_is_logged_once_and_does_not_write_error_on_broken_socket(self):
        self.serve(request('POST','/api/frame', self.payload()), fail_on_call=1)
        calls = self.logs.transfer.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[2], 'write_failed')

    def test_recovery_requires_token_exact_session_and_exact_sequence(self):
        data = self.payload()
        self.app.dispatch('/api/frame', data)
        self.assertIn(b'403 Forbidden', self.serve(request('GET','/api/frame-result?seq=0',token='wrong',session=data['session_id'])))
        self.assertIn(b'404 Not Found', self.serve(request('GET','/api/frame-result?seq=1',session=data['session_id'])))
        self.assertIn(b'404 Not Found', self.serve(request('GET','/api/frame-result?seq=0',session=SESSION)))
        self.assertIn(b'400 Bad Request', self.serve(request('GET','/api/frame-result?seq=-1',session=data['session_id'])))
        self.assertEqual(self.app.session.accepted_ids,[0])

    def test_pending_is_not_an_accepted_frame_and_errors_are_not_successes(self):
        data = self.payload()
        key = self.app.replies.begin(data['session_id'], 7)
        output = self.serve(request('GET','/api/frame-result?seq=7', session=data['session_id']))
        self.assertIn(b'202 Accepted', output)
        self.assertEqual(json.loads(output.split(b'\r\n\r\n',1)[1]), {'pending':True,'seq':7})
        self.app.replies.finish(key,500,b'{"error":"synthetic model error"}')
        output = self.serve(request('GET','/api/frame-result?seq=7', session=data['session_id']))
        self.assertIn(b'500 Internal Server Error',output)
        self.assertEqual(self.app.session.accepted_ids,[])

    def test_second_post_cannot_commit_same_frame_twice_and_close_expires_replies(self):
        data = self.payload()
        self.app.dispatch('/api/frame',data)
        with self.assertRaisesRegex(ValueError,'already submitted'):
            self.app.dispatch('/api/frame',data)
        self.assertEqual(self.app.session.accepted_ids,[0])
        self.assertTrue(all(b.seen==[0] for b in self.backends.values()))
        self.app.dispatch('/api/end',{'session_id':data['session_id']})
        self.assertEqual(self.app.replies.lookup(data['session_id'],0),('missing',None))

    def test_reply_cache_is_bounded_and_reading_never_reorders_or_mutates_it(self):
        replies = FrameReplies(capacity=4)
        for seq in range(12):
            key = replies.begin(SESSION,seq)
            replies.finish(key,200,json.dumps({'seq':seq}).encode())
        self.assertEqual(len(replies.entries),4)
        self.assertEqual(replies.lookup(SESSION,7),('missing',None))
        order = list(replies.entries)
        for _ in range(4):
            self.assertEqual(replies.lookup(SESSION,8)[1][0],200)
        self.assertEqual(list(replies.entries),order)
        with self.assertRaises(ValueError): replies.lookup(SESSION,True)
        replies.clear()
        self.assertEqual(replies.lookup(SESSION,11),('missing',None))

    def test_two_requests_use_one_http11_connection_with_correct_byte_lengths(self):
        data = self.payload()
        first = request('POST','/api/frame',data,close=False)
        second = request('GET','/api/frame-result?seq=0',session=data['session_id'])
        output = self.serve(first+second)
        for _ in range(2):
            headers, body = output.split(b'\r\n\r\n',1)
            self.assertTrue(headers.startswith(b'HTTP/1.1 200 OK'))
            length = int(next(line.split(b':',1)[1] for line in headers.split(b'\r\n') if line.startswith(b'Content-Length:')))
            reply = json.loads(body[:length])
            self.assertEqual(reply['seq'],0)
            self.assertTrue(reply['accepted'])
            output = body[length:]
        self.assertEqual(output,b'')
        self.assertEqual(self.app.session.accepted_ids,[0])

    def test_recovered_calibration_still_fits_each_model_once_on_same_frames(self):
        for seq in range(9):
            data = self.payload(seq)
            expected = self.app.dispatch('/api/frame', data)
            output = self.serve(request('GET',f'/api/frame-result?seq={seq}',session=data['session_id']))
            recovered = json.loads(output.split(b'\r\n\r\n',1)[1])
            self.assertEqual(recovered, expected)
        result = self.app.dispatch('/api/finish',dict(session_id=data['session_id'],webgazer_frame_ids=list(range(9))))
        self.assertEqual(result['fit_counts'],dict.fromkeys((*PYTHON_ENGINES,'webgazer'),1))
        for backend in self.backends.values():
            self.assertEqual(backend.seen,list(range(9)))
            self.assertEqual(len(backend.fit_calls),1)
            self.assertEqual(backend.fit_calls[0][0],[[seq] for seq in range(9)])
        self.assertEqual(self.app.session.reference_tool.captured,[0])
        self.assertTrue(result['audit']['automatic_training'])

    def test_rejecting_unread_post_body_closes_persistent_connection(self):
        data = self.payload()
        raw = request('POST','/api/frame',data,token='wrong',close=False)+request('GET','/api/health')
        output = self.serve(raw)
        self.assertIn(b'403 Forbidden',output)
        self.assertIn(b'Connection: close',output)
        self.assertEqual(output.count(b'HTTP/1.1'),1)
        self.assertEqual(self.app.session.accepted_ids,[])


if __name__ == '__main__':
    unittest.main()
