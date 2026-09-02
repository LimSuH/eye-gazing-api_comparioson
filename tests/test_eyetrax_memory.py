"""Run the real EyeTrax constructor against fake MediaPipe, never a model runner."""
import ast
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


@contextmanager
def fixture():
    @dataclass
    class BaseOptions:
        model_asset_path: str = None
        model_asset_buffer: bytes = None
        delegate: object = None

    state = SimpleNamespace(options=[], allow_native_path=False, close_count=0)
    def close(): state.close_count += 1
    runner = SimpleNamespace(close=close)
    def create_from_options(options):
        state.options.append(options)
        if options.base_options.model_asset_path is not None and not state.allow_native_path:
            raise RuntimeError('Unable to open site-packages/C:\\Users\\user\\face_landmarker.task, errno=22')
        return runner
    vision = module('mediapipe.tasks.python.vision',
                    FaceLandmarkerOptions=lambda **kwargs: SimpleNamespace(**kwargs),
                    RunningMode=SimpleNamespace(VIDEO='VIDEO'),
                    FaceLandmarker=SimpleNamespace(create_from_options=create_from_options))
    mp = module('mediapipe')
    create_model = lambda name, **kwargs: SimpleNamespace(name=name, kwargs=kwargs)
    # Compile only upstream's class and factory definitions. They call the fakes
    # below. No cv2/numpy/MediaPipe package or inference code is imported.
    source = ROOT/'third_party/sources/eyetrax_gaze_0.4.0.py'
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in ('GazeEstimator', '_create_face_landmarker')]
    namespace = {'deque':deque, 'create_model':create_model,
                 '_ensure_face_landmarker_task':lambda path: Path(path)}
    unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]+nodes, type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit),str(source),'exec'),namespace)
    Native = namespace['GazeEstimator']
    fakes = {
        'mediapipe':mp,
        'mediapipe.tasks':module('mediapipe.tasks'),
        'mediapipe.tasks.python':module('mediapipe.tasks.python', vision=vision),
        'mediapipe.tasks.python.vision':vision,
        'mediapipe.tasks.python.core':module('mediapipe.tasks.python.core'),
        'mediapipe.tasks.python.core.base_options':module('mediapipe.tasks.python.core.base_options', BaseOptions=BaseOptions),
        'eyetrax':module('eyetrax', GazeEstimator=Native),
        'eyetrax.models':module('eyetrax.models', create_model=create_model),
    }
    spec = importlib.util.spec_from_file_location('_eyetrax_memory_test',ROOT/'gaze_compare/backends/eyetrax_memory.py')
    bridge = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,fakes), patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
        spec.loader.exec_module(bridge)
        bridge.version = lambda name: '0.4.0'
        yield bridge, Native, state


class EyeTraxMemoryTests(unittest.TestCase):
    def test_original_path_error_is_bypassed_with_exact_bytes(self):
        with fixture() as (bridge, Native, state), tempfile.TemporaryDirectory() as folder:
            model = Path(folder)/'한글 모델 with spaces.task'
            content = b'fake task bytes; never loaded by a real model'
            model.write_bytes(content)
            # The fake native resolver reproduces the user's path failure.
            with self.assertRaisesRegex(RuntimeError,'errno=22'):
                Native(face_landmarker_model=str(model))
            estimator = bridge.BufferGazeEstimator(model)
            asset = state.options[-1].base_options
            self.assertIsNone(asset.model_asset_path)
            self.assertEqual(asset.model_asset_buffer,content)
            estimator.close()
            self.assertEqual(state.close_count,1)

    def test_native_state_options_and_methods_remain_unchanged(self):
        with fixture() as (bridge, Native, state), tempfile.TemporaryDirectory() as folder:
            model = Path(folder)/'model.task'
            model.write_bytes(b'fake model')
            state.allow_native_path = True
            native = Native(face_landmarker_model=str(model))
            native_options = vars(state.options[-1]).copy()
            state.allow_native_path = False
            buffered = bridge.BufferGazeEstimator(model)
            buffer_options = vars(state.options[-1]).copy()
            native_options.pop('base_options'); buffer_options.pop('base_options')
            self.assertEqual(native_options,buffer_options)
            self.assertEqual(vars(native),vars(buffered))
            self.assertEqual(native._ear_history.maxlen,buffered._ear_history.maxlen)
            for name in ('extract_features','train','predict','close'):
                self.assertIs(getattr(type(buffered),name),getattr(Native,name))

    def test_windows_filename_never_reaches_mediapipe(self):
        with fixture() as (bridge, Native, state):
            windows_path = r'C:\Users\user\한글 폴더\models\face_landmarker.task'
            data = b'model contents'
            with patch.object(bridge,'Path',return_value=SimpleNamespace(read_bytes=lambda:data)) as reader:
                bridge.BufferGazeEstimator(windows_path)
            reader.assert_called_once_with(windows_path)
            self.assertIsNone(state.options[-1].base_options.model_asset_path)
            self.assertEqual(state.options[-1].base_options.model_asset_buffer,data)

    def test_missing_or_empty_model_fails_without_creating_a_runner(self):
        with fixture() as (bridge, Native, state), tempfile.TemporaryDirectory() as folder:
            model = Path(folder)/'model.task'
            with self.assertRaises(FileNotFoundError): bridge.BufferGazeEstimator(model)
            model.write_bytes(b'')
            with self.assertRaisesRegex(RuntimeError,'비어 있습니다'): bridge.BufferGazeEstimator(model)
            self.assertEqual(state.options,[])

    def test_unknown_version_fails_before_using_native_private_state(self):
        with fixture() as (bridge, Native, state):
            bridge.version = lambda name: '0.5.0'
            with self.assertRaisesRegex(RuntimeError,'eyetrax==0.4.0'):
                bridge.BufferGazeEstimator('not-read.task')
            self.assertEqual(state.options,[])


if __name__ == '__main__':
    unittest.main()
