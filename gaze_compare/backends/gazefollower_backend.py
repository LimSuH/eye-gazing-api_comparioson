"""Use GazeFollower's actual MGazeNet + SVR components with our common UI.

This intentionally bypasses its camera thread, native GUI and output filter.
The native default normalized [0,1] screen labels are retained for SVR.
"""
import time
from pathlib import Path
import cv2
import numpy as np
from gazefollower.logger import Log
from gazefollower.face_alignment import MediaPipeFaceAlignment
from gazefollower.gaze_estimator import MGazeNetGazeEstimator
from gazefollower.calibration import SVRCalibration
from .base import Backend, Observation


class GazeFollowerBackend(Backend):
    description = "GazeFollower 1.0.2 / bundled MGazeNet + native SVR / no HeuristicFilter"

    def __init__(self, width, height, work_dir):
        super().__init__(width, height, work_dir)
        # We bypass GazeFollower's main controller, which normally initializes
        # its class-level logger. Even a successful SVR calibration calls Log.d.
        # Keep this file outside the temporary model directory: Windows cannot
        # remove a directory while its FileHandler remains open.
        self.log_path = Path(__file__).resolve().parents[2] / "logs" / "gazefollower.log"
        if getattr(getattr(Log, "instance", None), "logger", None) is None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            Log.init(str(self.log_path))
        self.face = MediaPipeFaceAlignment()
        model_path = Path(__file__).resolve().parents[2]/'models/gazefollower/base.mnn'
        if not model_path.is_file():
            raise RuntimeError(f'동봉 GazeFollower 모델 누락: {model_path}. ZIP 전체를 다시 풀어 주세요.')
        self.estimator = MGazeNetGazeEstimator(model_path=str(model_path))
        # A fresh isolated directory avoids importing a previous user's model.
        work_dir.mkdir(parents=True, exist_ok=True)
        self.calibration = SVRCalibration(model_save_path=str(work_dir))

    def process(self, frame):
        # Match the official WebCamCamera: both model stages receive RGB.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face = self.face.detect(time.time_ns(), rgb)
        info = self.estimator.detect(rgb, face)
        if not info.status or info.features is None:
            return Observation(reason="face_or_eye_missing")
        if face.left_eye_openness <= 10 or face.right_eye_openness <= 10:
            return Observation(reason="eye_closed")
        if not np.isfinite(info.features).all():
            return Observation(reason="nonfinite_features")
        point = None
        if self.ready:
            ok, xy = self.calibration.predict(info.features, info.raw_gaze_coordinates)
            if not ok:
                raise RuntimeError("GazeFollower calibration was not fitted")
            point = np.asarray(xy) * np.array([self.width, self.height])
        return Observation(point=point, features=info.features.copy(), valid=True, reason="ok")

    def fit(self, features, targets):
        if self.ready:
            raise RuntimeError("Calibration is frozen. Start an explicit recalibration first.")
        labels = np.asarray(targets, dtype=np.float32) / [self.width, self.height]
        ok, _, _ = self.calibration.calibrate(np.asarray(features, dtype=np.float32), labels)
        if not ok:
            raise RuntimeError("GazeFollower SVR calibration failed; recalibrate with visible eyes")
        self.ready = True

    def close(self):
        self.face.face_mesh.close()
        self.estimator.release()
        self.calibration.release()
