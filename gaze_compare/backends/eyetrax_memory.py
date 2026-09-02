"""EyeTrax 0.4.0 initialization with an in-memory MediaPipe model.

Only construction changes. Feature extraction, blink detection, Ridge fitting,
prediction, saving and close remain inherited from the original GazeEstimator.
Default instance state follows EyeTrax 0.4.0 (MIT); its original source/license
are included under third_party. No global monkeypatch or site-packages edit.
"""
from collections import deque
from importlib.metadata import version
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from eyetrax import GazeEstimator
from eyetrax.models import create_model


class BufferGazeEstimator(GazeEstimator):
    def __init__(self, model_path):
        installed = version('eyetrax')
        if installed != '0.4.0':
            raise RuntimeError(f'EyeTrax {installed}는 이 연결 코드의 대상이 아닙니다. eyetrax==0.4.0이 필요합니다.')
        # Python handles the OS path. Never pass C:\... to MediaPipe's native
        # resource resolver, which can prepend site-packages on Windows after
        # another MediaPipe solution has set the shared resource directory.
        model_bytes = Path(model_path).read_bytes()
        if not model_bytes:
            raise RuntimeError('FaceLandmarker 모델이 비어 있습니다. ZIP 전체를 다시 풀어 주세요.')
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_bytes),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        # Preserve the exact native default Ridge and blink-history state.
        # Build Ridge before the native runner so a Ridge initialization error
        # cannot leave a successfully created FaceLandmarker unclosed.
        self.model = create_model('ridge')
        self._ear_history = deque(maxlen=50)
        self._blink_ratio = 0.8
        self._min_history = 15
        self._mp_last_ts_ms = 0
        self._mp = mp
        self._face_landmarker = vision.FaceLandmarker.create_from_options(options)
