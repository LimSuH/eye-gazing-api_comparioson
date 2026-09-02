"""EyeGestures v3 features and native Ridge, fitted on the shared 9-point data.

Do not call step(calibration=True), Calibrator.add, or the native 25-point loop.
The two original Ridge regressors are fitted once, synchronously. Native output
averaging is bypassed so all engines expose unfiltered coordinates in this UI.
"""
import numpy as np
from eyeGestures import EyeGestures_v3
from eyeGestures.utils import low_pass_filter_fourier
from .base import Backend, Observation


class _MissingFace(Exception):
    pass


class EyeGesturesBackend(Backend):
    description = "EyeGestures 3.2.4 v3 features + original Ridge(alpha=0.5); shared calibration"

    def __init__(self, width, height, work_dir):
        super().__init__(width, height, work_dir)
        self.estimator = EyeGestures_v3()
        self.estimator.addContext("shared")
        self.calibrator = self.estimator.clb["shared"]
        original_find = self.estimator.finder.find

        def checked_find(image):
            found = original_find(image)
            if found is None or not found.multi_face_landmarks:
                raise _MissingFace()
            return found

        self.estimator.finder.find = checked_find

    def process(self, frame):
        try:
            features, blink, _ = self.estimator.getLandmarks(frame)
        except _MissingFace:
            return Observation(reason="no_face")
        features = low_pass_filter_fourier(features, 200)
        if blink or not np.isfinite(features).all():
            return Observation(reason="blink" if blink else "nonfinite_features")
        point = self.calibrator.predict(features) if self.ready else None
        return Observation(point=point, features=features, valid=True, reason="ok")

    def fit(self, features, targets):
        if self.ready:
            raise RuntimeError("Calibration is frozen. Use the recalibration button.")
        x = np.asarray([np.asarray(f).ravel() for f in features], dtype=float)
        y = np.asarray(targets, dtype=float)
        # Use the library's actual regressors; no replacement gaze model.
        with self.calibrator.lock:
            self.calibrator.reg_x.fit(x, y[:,0])
            self.calibrator.reg_y.fit(x, y[:,1])
            self.calibrator.fitted = True
            self.calibrator.cv_not_set = False
        self.ready = True

    def close(self):
        self.estimator.finder.mp_face_mesh.close()
