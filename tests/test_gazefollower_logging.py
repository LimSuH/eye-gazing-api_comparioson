"""Regression test for logger-before-components, without importing vision libs."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'gaze_compare/backends/gazefollower_backend.py'


def load_backend(log_class):
    def module(name,**attrs):
        value=ModuleType(name)
        value.__dict__.update(attrs)
        return value
    class Face:
        def __init__(self):
            log_class.d('face component creation')
            self.face_mesh=SimpleNamespace(close=lambda:None)
    class Estimator:
        def __init__(self,model_path):
            assert Path(model_path).is_file()
            log_class.d('estimator creation')
        def release(self): pass
    class Calibration:
        def __init__(self,model_save_path):
            log_class.d('calibration component creation')
            assert Path(model_save_path).is_dir()
        def calibrate(self,*args):
            # Upstream SVR also logs on its successful calibration path.
            log_class.d('Calibration completed')
            return True,0,None
        def release(self): pass
    fakes={'cv2':module('cv2'),'numpy':module('numpy'),
           'gazefollower':module('gazefollower'),
           'gazefollower.logger':module('gazefollower.logger',Log=log_class),
           'gazefollower.face_alignment':module('gazefollower.face_alignment',MediaPipeFaceAlignment=Face),
           'gazefollower.gaze_estimator':module('gazefollower.gaze_estimator',MGazeNetGazeEstimator=Estimator),
           'gazefollower.calibration':module('gazefollower.calibration',SVRCalibration=Calibration)}
    spec=importlib.util.spec_from_file_location('gaze_compare.backends._logging_regression',SOURCE)
    backend=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,fakes): spec.loader.exec_module(backend)
    return backend


class LoggerRegressionTests(unittest.TestCase):
    def test_initializes_before_components_and_reuses_across_recalibration(self):
        class Log:
            instance=None
            calls=[]
            @classmethod
            def init(cls,path):
                cls.calls.append(path)
                cls.instance=SimpleNamespace(logger=object())
            @classmethod
            def d(cls,message):
                if cls.instance is None or getattr(cls.instance,'logger',None) is None:
                    raise RuntimeError('Logger has not been initialized. Please call Log.init() first.')
        backend=load_backend(Log)
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)/'project'
            backend.__file__=str(project/'gaze_compare/backends/gazefollower_backend.py')
            bundled_model=project/'models/gazefollower/base.mnn'
            bundled_model.parent.mkdir(parents=True)
            bundled_model.write_bytes(b'fake model; never loaded')
            model_dir=Path(temp)/'temporary_models'
            first=backend.GazeFollowerBackend(1000,800,model_dir/'one')
            self.assertTrue(first.calibration.calibrate([],[])[0])
            first.close()
            second=backend.GazeFollowerBackend(1000,800,model_dir/'two')
            self.assertEqual(len(Log.calls),1)
            self.assertEqual(Path(Log.calls[0]),project/'logs/gazefollower.log')
            self.assertNotIn(model_dir,Path(Log.calls[0]).parents)
            second.close()


if __name__=='__main__': unittest.main()
