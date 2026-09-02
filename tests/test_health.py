"""HTTP handlers invoked without binding a socket or constructing models."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaze_compare.webserver import Handler, WEB_ENTRYPOINTS, health_payload


class HealthTests(unittest.TestCase):
    def test_manifest_distinguishes_missing_empty_and_present_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'web').mkdir()
            (root/'web'/'index.html').write_text('test')
            (root/'web'/'app.js').write_bytes(b'')
            with patch('gaze_compare.webserver.ROOT', root), patch('setup_envs.required_web_files', return_value=[root/'web/vendor/missing.js']), patch('verify_bundle.manifest_entries', return_value=[]):
                data = health_payload()
            files = {item['url']:item for item in data['web_files']}
            self.assertEqual(files['/index.html']['bytes'], 4)
            self.assertTrue(files['/app.js']['exists'])
            self.assertEqual(files['/app.js']['bytes'], 0)
            self.assertFalse(files['/vendor/missing.js']['exists'])
            self.assertEqual(len(files), len(WEB_ENTRYPOINTS)+1)

    def test_health_bypasses_worker_and_does_not_require_a_session(self):
        handler = object.__new__(Handler)
        # There is deliberately no worker, app, or camera on this fake server.
        handler.server = SimpleNamespace(server_port=8765)
        handler.headers = {'Host':'127.0.0.1:8765'}
        handler.path = '/api/health'
        replies = []
        handler.send_json = lambda *args, **kwargs: replies.append((args, kwargs))
        with patch('gaze_compare.webserver.health_payload', return_value={'application':'gaze-api-compare'}):
            handler.do_GET()
            handler.do_HEAD()
        self.assertEqual(replies[0], ((200, {'application':'gaze-api-compare'}), {'head_only':False}))
        self.assertEqual(replies[1][1], {'head_only':True})

    def test_head_rejects_untrusted_host_and_non_web_paths(self):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(server_port=8765)
        handler.headers = {'Host':'example.com:8765'}
        handler.path = '/api/health'
        replies = []
        handler.send_error = replies.append
        handler.do_HEAD()
        handler.headers = {'Host':'localhost:8765'}
        handler.path = '/requirements.txt'
        handler.do_HEAD()
        self.assertEqual(replies, [403,404])


if __name__ == '__main__':
    unittest.main()
