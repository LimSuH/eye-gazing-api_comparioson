"""Release integrity regression tests; no network or model imports."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verify_bundle import check_bundle


class BundleTests(unittest.TestCase):
    def make_tree(self,root):
        data={'web/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.data':b'',
              'web/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.wasm':b'\0asm\1\0\0\0',
              'run.py':b'# editable source\n'}
        for name,body in data.items():
            path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
        manifest={'format':1,'files':[{'path':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
                                     for name,body in data.items()]}
        (root/'bundle_manifest.json').write_text(json.dumps(manifest))
        return data

    def test_original_empty_file_passes_but_deleted_or_truncated_resource_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); data=self.make_tree(root)
            self.assertEqual(check_bundle(root)[1],[])
            (root/next(name for name in data if name.endswith('.data'))).unlink()
            (root/next(name for name in data if name.endswith('.wasm'))).write_bytes(b'')
            errors=check_bundle(root)[1]
            self.assertEqual(len(errors),2)
            self.assertTrue(any('누락:' in error and '.data' in error for error in errors))
            self.assertTrue(any('크기 불일치:' in error and '.wasm' in error for error in errors))

    def test_same_length_corruption_fails_hash_and_user_code_can_be_edited(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); data=self.make_tree(root)
            (root/'run.py').write_text('# user edits source code\n')
            self.assertEqual(check_bundle(root,strict=False)[1],[])
            resource=next(name for name in data if name.endswith('.wasm'))
            (root/resource).write_bytes(b'XXXXXXXX')
            errors=check_bundle(root,strict=False)[1]
            self.assertEqual(len(errors),1)
            self.assertIn('내용 변경/손상:',errors[0])


if __name__ == '__main__':
    unittest.main()
