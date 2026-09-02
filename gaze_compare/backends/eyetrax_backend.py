from pathlib import Path
import numpy as np
from .eyetrax_memory import BufferGazeEstimator
from .base import Backend, Observation


class EyeTraxBackend(Backend):
    description = "EyeTrax 0.4.0 / default Ridge / no extra output filter"

    def __init__(self, width, height, work_dir):
        super().__init__(width, height, work_dir)
        model_path = Path(__file__).resolve().parents[2]/'models/mediapipe/face_landmarker.task'
        if not model_path.is_file():
            raise RuntimeError(f'동봉 EyeTrax 모델 누락: {model_path}. ZIP 전체를 다시 풀어 주세요.')
        self.estimator = BufferGazeEstimator(model_path)

    def process(self, frame):
        features, blink = self.estimator.extract_features(frame)
        if features is None or blink or not np.isfinite(features).all():
            return Observation(reason="blink" if blink else "no_face")
        point = self.estimator.predict(np.asarray([features]))[0] if self.ready else None
        return Observation(point=point, features=features, valid=True, reason="ok")

    def fit(self, features, targets):
        if self.ready:
            raise RuntimeError("Calibration is frozen. Start an explicit recalibration first.")
        self.estimator.train(np.asarray(features), np.asarray(targets))
        self.ready = True

    def close(self):
        self.estimator.close()
