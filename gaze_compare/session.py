"""One calibration transaction shared by all four engines.

No camera, GUI, or ML import at module import time. The HTTP server dispatches
all calls to one worker; fakes can exercise the state machine without a camera.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
import uuid

from .protocol import calibration_targets

ENGINES = ('eyetrax', 'gazefollower', 'eyegestures', 'webgazer')
PYTHON_ENGINES = ENGINES[:3]


def point_or_none(point):
    if point is None:
        return None
    values = [float(v) for v in point]
    return values if len(values) == 2 and all(math.isfinite(v) for v in values) else None


class SharedSession:
    def __init__(self, samples=30, backend_factory=None, reference_factory=None, progress=None):
        self.samples = samples
        self.backend_factory = backend_factory
        self.reference_factory = reference_factory
        self.progress = progress or (lambda name, engine=None: None)
        self.backends = {}
        self.reference_tool = None
        self.temp = None
        self.phase = 'idle'
        self.session_id = None

    def close(self):
        for backend in self.backends.values():
            try:
                backend.close()
            except Exception:
                pass
        self.backends = {}
        if self.reference_tool is not None:
            try:
                self.reference_tool.close()
            except Exception:
                pass
        self.reference_tool = None
        if self.temp is not None:
            self.temp.cleanup()
        self.temp = None
        self.phase = 'idle'
        self.session_id = None

    def start(self, payload):
        width, height = payload.get('width'), payload.get('height')
        camera = payload.get('camera_size')
        if any(type(v) is not int or not 200 <= v <= 20000 for v in (width,height)):
            raise ValueError('Invalid viewport')
        if (not isinstance(camera,list) or len(camera) != 2 or
            any(type(v) is not int or not 120 <= v <= 1280 for v in camera) or
            camera[0]*camera[1] > 1280*720):
            raise ValueError('Invalid camera frame size')
        # Called only by the explicit Start/Recalibrate UI action.
        self.close()
        self.width, self.height, self.camera_size = width, height, camera
        self.calibration_targets = calibration_targets(width, height)
        self.session_id = uuid.uuid4().hex
        self.phase = 'initializing'
        self.temp = tempfile.TemporaryDirectory(prefix='gaze-shared-')
        try:
            if self.backend_factory:
                self.backends = self.backend_factory(width, height, Path(self.temp.name))
            else:
                from .backends import create
                for name in PYTHON_ENGINES:
                    self.progress('engine.initialize', name)
                    self.backends[name] = create(name,width,height,Path(self.temp.name)/name)
            if self.reference_factory:
                self.reference_tool = self.reference_factory()
            else:
                self.progress('reference.initialize')
                from .reference import ReferenceOutline
                self.reference_tool = ReferenceOutline()
        except Exception:
            self.close()
            raise
        self.features = {name: [] for name in PYTHON_ENGINES}
        self.labels, self.accepted_ids, self.manifest = [], [], []
        self.counts = [0]*len(self.calibration_targets)
        self.point_index = 0
        self.last_seq = -1
        self.fit_counts = {name: 0 for name in ENGINES}
        self.reference = None
        self.reference_frame_id = None
        self.live_pose = None
        self.pose_time = 0
        self.started_at = time.time()
        self.calibration_id = None
        self.phase = 'calibrating'
        return self.snapshot()

    def require_session(self, supplied):
        if not self.session_id or supplied != self.session_id:
            raise ValueError('Session changed or closed. Use one browser tab and explicitly recalibrate.')

    def snapshot(self):
        if not self.session_id:
            return {'phase': self.phase, 'session_id': None}
        return deepcopy(dict(session_id=self.session_id, phase=self.phase,
            counts=self.counts, point_index=self.point_index, samples_per_point=self.samples,
            accepted_count=len(self.accepted_ids), fit_counts=self.fit_counts,
            reference=self.reference, reference_frame_id=self.reference_frame_id,
            calibration_id=self.calibration_id, width=self.width,height=self.height,
            calibration_targets=deepcopy(self.calibration_targets)))

    def frame(self, payload, frame, frame_hash):
        self.require_session(payload.get('session_id'))
        if payload.get('viewport') != [self.width,self.height]:
            raise ValueError('Viewport changed. Explicit recalibration is required.')
        if list(frame.shape[:2][::-1]) != self.camera_size:
            raise ValueError('Camera resolution changed. Explicit recalibration is required.')
        seq = payload.get('seq')
        if type(seq) is not int or seq <= self.last_seq:
            raise ValueError('Duplicate or stale frame')
        self.last_seq = seq
        mode = payload.get('mode')
        response = {'seq':seq, 'accepted':False, 'point':None, 'engine':payload.get('engine')}
        if mode == 'waiting' and self.phase == 'calibrating':
            return {**self.snapshot(), **response}
        if mode == 'collect':
            if self.phase != 'calibrating':
                raise ValueError('Calibration is frozen; new samples are forbidden until explicit recalibration.')
            target = payload.get('target_id')
            if type(target) is not int or target != self.point_index or not 0 <= target < len(self.counts):
                raise ValueError('Wrong calibration target')
            observations = {}
            for name in PYTHON_ENGINES:
                self.progress('engine.process', name)
                observations[name] = self.backends[name].process(frame)
            reasons = {name: 'ok' if obs.valid and obs.features is not None else obs.reason
                       for name,obs in observations.items()}
            wg_valid = payload.get('webgazer_valid') is True
            reasons['webgazer'] = 'ok' if wg_valid else 'no_eyes'
            accepted = wg_valid and all(obs.valid and obs.features is not None for obs in observations.values())
            if accepted and self.reference is None:
                self.progress('reference.capture')
                reference = self.reference_tool.capture(frame)
                if reference is None:
                    accepted = False
                    reasons['reference'] = 'silhouette_or_head_missing'
                else:
                    self.reference = deepcopy(reference)
                    self.reference_frame_id = seq
            if accepted:
                xy = list(self.calibration_targets[target])
                # Atomic logical commit: every model receives this exact frame ID
                # and the same target; no model is fitted yet.
                for name,obs in observations.items():
                    self.features[name].append(obs.features.copy())
                self.labels.append(xy)
                self.accepted_ids.append(seq)
                self.manifest.append({'frame_id':seq,'sha256_png':frame_hash,'target_id':target,'target':xy})
                self.counts[target] += 1
                if self.counts[target] == self.samples:
                    self.point_index += 1
            response.update(accepted=accepted, reasons=reasons)
        elif mode == 'track':
            if self.phase != 'ready':
                raise ValueError('Complete the one shared calibration first')
            engine = payload.get('engine')
            if engine not in ENGINES:
                raise ValueError('Unknown engine')
            begin = time.perf_counter()
            if engine != 'webgazer':
                self.progress('engine.process', engine)
                obs = self.backends[engine].process(frame)
                response['point'] = point_or_none(obs.point) if obs.valid else None
                response['reason'] = obs.reason
            response['inference_ms'] = (time.perf_counter()-begin)*1000
            if time.monotonic()-self.pose_time >= .30:
                self.progress('reference.observe')
                self.live_pose = self.reference_tool.observe(frame)
                self.pose_time = time.monotonic()
            response['live_pose'] = self.live_pose
        else:
            raise ValueError('Invalid phase/action')
        return {**self.snapshot(), **response}

    def finish(self, payload):
        self.require_session(payload.get('session_id'))
        if self.phase != 'calibrating':
            raise ValueError('Models are already frozen; repeated fitting is forbidden')
        if self.point_index != len(self.calibration_targets) or any(n != self.samples for n in self.counts):
            raise ValueError('All nine targets need the same number of jointly valid frames')
        # Browser has retained its own feature vector for each successful commit.
        # A lost HTTP response cannot silently produce different training sets.
        if payload.get('webgazer_frame_ids') != self.accepted_ids:
            raise ValueError('WebGazer frame IDs differ from Python calibration; explicitly recalibrate')
        self.phase = 'fitting'
        try:
            for name in PYTHON_ENGINES:
                self.progress('engine.fit', name)
                self.backends[name].fit(self.features[name], self.labels)
                self.fit_counts[name] += 1
        except Exception:
            self.phase = 'failed'
            raise
        self.fit_counts['webgazer'] = 1
        self.calibration_id = hashlib.sha256(json.dumps(self.manifest,separators=(',',':')).encode()).hexdigest()
        self.features = {name: [] for name in PYTHON_ENGINES}
        self.phase = 'ready'
        return {**self.snapshot(), 'audit':self.audit()}

    def audit(self):
        if self.phase != 'ready':
            raise ValueError('Calibration is not complete')
        return dict(calibration_id=self.calibration_id, calibration_kind='shared_9_png_v3_online',
            accepted_frame_ids=list(self.accepted_ids), samples=len(self.accepted_ids),
            target_counts=list(self.counts), fit_counts=dict(self.fit_counts),
            calibration_targets=deepcopy(self.calibration_targets),
            fit_counts_scope="initial_calibration_only",
            width=self.width,height=self.height,camera_size=self.camera_size,
            reference_frame_id=self.reference_frame_id, manifest=deepcopy(self.manifest),
            automatic_training=True,
            online_learning={'engine':'webgazer','source':'click_and_mousemove',
                             'active_engine_only':True,'persistence':False},
            engine_versions={'eyetrax':'0.4.0','gazefollower':'1.0.2',
            'eyegestures':'3.2.4','webgazer':'3.5.3'})
