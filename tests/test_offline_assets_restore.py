"""Restore the real bundled tarball into an empty tree with networking blocked."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import setup_envs


class OfflineAssetsTests(unittest.TestCase):
    def test_empty_web_tree_is_restored_offline_including_valid_zero_byte_file(self):
        source=Path(__file__).resolve().parents[1]/'third_party/sources/webgazer-3.5.3.tgz'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive=root/'third_party/sources/webgazer-3.5.3.tgz'
            archive.parent.mkdir(parents=True)
            shutil.copyfile(source,archive)
            with patch.object(setup_envs,'ROOT',root), patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')), patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
                setup_envs.install_web_assets()
                self.assertTrue(all(p.is_file() for p in setup_envs.required_web_files()))
                self.assertEqual((root/'web/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.data').stat().st_size,0)
                self.assertEqual((root/'web/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.wasm').stat().st_size,6161697)
                self.assertTrue((root/'web/vendor/webgazer.js.map').is_file())


if __name__ == '__main__':
    unittest.main()
