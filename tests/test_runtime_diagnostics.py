"""Fault handling is mocked: no crash, model, webcam, or listening socket."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaze_compare.runtime_diagnostics import RuntimeDiagnostics
from gaze_compare.session import SharedSession, PYTHON_ENGINES
from gaze_compare.webserver import Application
from test_shared_session import FakeBackend, FakeReference, Frame


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.enable = self.stack.enter_context(patch('gaze_compare.runtime_diagnostics.faulthandler.enable'))
        self.disable = self.stack.enter_context(patch('gaze_compare.runtime_diagnostics.faulthandler.disable'))
        self.dump = self.stack.enter_context(patch('gaze_compare.runtime_diagnostics.faulthandler.dump_traceback_later'))
        self.cancel = self.stack.enter_context(patch('gaze_compare.runtime_diagnostics.faulthandler.cancel_dump_traceback_later'))

    def test_operation_is_durable_before_model_call_and_failure_preserves_engine(self):
        with RuntimeDiagnostics(self.directory) as logs:
            backends = {name:FakeBackend(name) for name in PYTHON_ENGINES}
            def broken(frame):
                record = json.loads((self.directory/'last_operation.json').read_text())
                self.assertEqual(record['state'], 'busy')
                self.assertEqual(record['stage'], 'engine.process')
                self.assertEqual(record['engine'], 'gazefollower')
                raise RuntimeError('synthetic native wrapper error')
            backends['gazefollower'].process = broken
            session = SharedSession(samples=2, backend_factory=lambda *_:backends,
                                    reference_factory=FakeReference, progress=logs.stage)
            self.addCleanup(session.close)
            session.start(dict(width=1000,height=800,camera_size=[640,480]))
            payload = dict(session_id=session.session_id,seq=7,viewport=[1000,800],
                           mode='collect',target_id=0,engine='eyetrax',webgazer_valid=True,
                           image='private-frame-do-not-log',token='private-token')
            app = Application(2, logs)
            app.session = session
            frame_hash = 'private-frame-hash'
            app._dispatch = lambda path, data:session.frame(data,Frame(7),frame_hash)
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                app.dispatch('/api/frame', payload)
            self.assertEqual(logs.snapshot()['state'], 'failed')
            self.assertEqual(logs.snapshot()['engine'], 'gazefollower')
            self.assertEqual(session.accepted_ids, [])
            self.assertTrue(all(not b.fit_calls for b in backends.values()))
            self.assertTrue(self.dump.called)
            self.assertTrue(self.cancel.called)
        output = '\n'.join(p.read_text() for p in self.directory.glob('*') if p.is_file())
        self.assertIn('synthetic native wrapper error', output)
        self.assertNotIn('private-frame-do-not-log', output)
        self.assertNotIn('private-token', output)
        self.assertNotIn('private-frame-hash', output)
        self.assertEqual(self.disable.call_count, 1)

    def test_success_cancels_watchdog_and_new_launch_preserves_previous_stage(self):
        with RuntimeDiagnostics(self.directory) as logs:
            logs.begin('/api/frame', 21)
            logs.stage('engine.process', 'eyetrax')
            logs.complete()
            expected = logs.snapshot()
            self.assertEqual(expected['state'], 'processed')
            self.assertTrue(self.cancel.called)
            self.assertFalse(self.dump.call_args.kwargs['exit'])
            # The faulthandler descriptor stays open while the server context lives.
            self.assertFalse(self.enable.call_args.kwargs['file'].closed)
        self.assertTrue(self.enable.call_args.kwargs['file'].closed)
        with RuntimeDiagnostics(self.directory) as logs:
            saved = json.loads((self.directory/'last_operation.previous.json').read_text())
            self.assertEqual(saved, expected)
            self.assertEqual(logs.snapshot()['state'], 'idle')

    def test_logging_write_error_does_not_break_or_reset_model_state(self):
        with RuntimeDiagnostics(self.directory) as logs:
            with patch.object(Path, 'write_text', side_effect=OSError('read-only folder')):
                logs.begin('/api/frame', 3)
                logs.stage('engine.process', 'eyegestures')
                logs.complete()
            self.assertEqual(logs.snapshot()['engine'], 'eyegestures')
            self.assertEqual(logs.snapshot()['state'], 'processed')
            self.assertTrue(logs.write_warning)

    def test_native_handler_failure_keeps_python_error_logging_available(self):
        self.enable.side_effect = OSError('synthetic unsupported fault handler')
        with RuntimeDiagnostics(self.directory) as logs:
            self.assertIsNone(logs.fault_file)
            logs.begin('/api/finish')
            try:
                raise ValueError('synthetic fitting failure')
            except ValueError:
                logs.failed()
        self.assertIn('synthetic fitting failure', (self.directory/'runtime.log').read_text())
        self.dump.assert_not_called()
        self.disable.assert_not_called()


if __name__ == '__main__':
    unittest.main()
