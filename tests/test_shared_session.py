"""Pure protocol tests: no ML imports, model loading, webcam, server, or GUI."""
import unittest
from types import SimpleNamespace

from gaze_compare.session import SharedSession, PYTHON_ENGINES
from gaze_compare.protocol import calibration_targets


class Frame:
    shape=(480,640,3)
    def __init__(self, number, missing=None):
        self.number=number
        self.missing=missing


class FakeBackend:
    def __init__(self,name):
        self.name=name
        self.fit_calls=[]
        self.seen=[]
        self.closed=False
    def process(self,frame):
        self.seen.append(frame.number)
        valid=frame.missing!=self.name
        return SimpleNamespace(valid=valid,features=[frame.number] if valid else None,
                               reason='ok' if valid else 'no_face',point=[120,240])
    def fit(self,features,labels):
        self.fit_calls.append(([f[:] for f in features],[y[:] for y in labels]))
    def close(self):
        self.closed=True


class FakeReference:
    def __init__(self):
        self.captured=[]
        self.closed=False
    def observe(self,frame):
        return dict(head=[[.4,.2],[.6,.4]],center=[.5,.3],head_width=.2)
    def capture(self,frame):
        self.captured.append(frame.number)
        return {**self.observe(frame),'silhouette':[[.3,.2],[.7,.8]],'camera_size':[640,480]}
    def close(self):
        self.closed=True


class SharedSessionTests(unittest.TestCase):
    def setUp(self):
        self.created=[]
        def factory(w,h,d):
            backends={name:FakeBackend(name) for name in PYTHON_ENGINES}
            self.created.append(backends)
            return backends
        self.s=SharedSession(samples=2,backend_factory=factory,reference_factory=FakeReference)
        self.s.start(dict(width=1000,height=800,camera_size=[640,480]))
        self.addCleanup(self.s.close)
        self.seq=0
    def frame(self,mode='collect',**overrides):
        n=self.seq
        self.seq+=1
        missing=overrides.pop('missing',None)
        payload=dict(session_id=self.s.session_id,seq=n,viewport=[1000,800],mode=mode,
                     target_id=self.s.point_index,engine='eyetrax',webgazer_valid=True)
        payload.update(overrides)
        return self.s.frame(payload,Frame(n,missing),f'sha-{n}')
    def collect_all(self):
        for _ in range(18):
            self.assertTrue(self.frame()['accepted'])
    def finish(self):
        return self.s.finish(dict(session_id=self.s.session_id,webgazer_frame_ids=list(self.s.accepted_ids)))

    def test_joint_acceptance_excludes_bad_frames_from_every_model(self):
        self.assertFalse(self.frame(missing='gazefollower')['accepted'])
        self.assertFalse(self.frame(webgazer_valid=False)['accepted'])
        self.assertTrue(self.frame()['accepted'])
        for name in PYTHON_ENGINES:
            self.assertEqual(self.s.features[name],[[2]])
        self.assertEqual(self.s.accepted_ids,[2])
        self.assertEqual(self.s.labels,[[500,400]])

    def test_all_models_receive_identical_frame_ids_and_targets_once(self):
        self.collect_all()
        result=self.finish()
        expected_targets=[p[:] for p in calibration_targets(1000,800) for _ in range(2)]
        for backend in self.s.backends.values():
            self.assertEqual(len(backend.fit_calls),1)
            features,labels=backend.fit_calls[0]
            self.assertEqual(features,[[n] for n in range(18)])
            self.assertEqual(labels,expected_targets)
        self.assertEqual(result['audit']['fit_counts'],dict.fromkeys((*PYTHON_ENGINES,'webgazer'),1))
        self.assertTrue(result['audit']['automatic_training'])
        self.assertEqual(result['audit']['online_learning']['engine'],'webgazer')
        self.assertEqual(result['audit']['fit_counts_scope'],'initial_calibration_only')

    def test_lost_browser_commit_or_incomplete_grid_cannot_fit(self):
        with self.assertRaises(ValueError): self.finish()
        self.collect_all()
        with self.assertRaisesRegex(ValueError,'frame IDs differ'):
            self.s.finish(dict(session_id=self.s.session_id,webgazer_frame_ids=self.s.accepted_ids[:-1]))
        self.assertTrue(all(not b.fit_calls for b in self.s.backends.values()))
        self.finish()

    def test_switching_prediction_keeps_models_and_reference_fixed(self):
        self.collect_all()
        self.finish()
        baseline=self.s.snapshot()['reference']
        original_id=self.s.calibration_id
        for engine in (*PYTHON_ENGINES,'webgazer')*3:
            result=self.frame(mode='track',engine=engine)
            self.assertEqual(result['reference'],baseline)
            self.assertEqual(result['calibration_id'],original_id)
        self.assertTrue(all(len(b.fit_calls)==1 for b in self.s.backends.values()))
        self.assertEqual(self.s.reference_tool.captured,[0])
        with self.assertRaisesRegex(ValueError,'frozen'): self.frame()
        with self.assertRaisesRegex(ValueError,'frozen'): self.finish()

    def test_reference_snapshot_cannot_modify_the_frozen_baseline(self):
        result=self.frame()
        result['reference']['head'][0][0]=999
        self.assertEqual(self.s.reference['head'][0][0],.4)
        for _ in range(5): self.frame()
        self.assertEqual(self.s.reference_tool.captured,[0])

    def test_explicit_restart_closes_old_models_and_resets_once(self):
        self.collect_all(); self.finish()
        old_models=list(self.s.backends.values())
        old_reference=self.s.reference_tool
        old_session=self.s.session_id
        self.s.start(dict(width=1000,height=800,camera_size=[640,480]))
        self.assertTrue(all(b.closed for b in old_models))
        self.assertTrue(old_reference.closed)
        self.assertNotEqual(self.s.session_id,old_session)
        self.assertIsNone(self.s.reference)
        self.assertEqual(self.s.accepted_ids,[])
        with self.assertRaises(ValueError): self.s.require_session(old_session)
        self.frame()
        self.assertEqual(self.s.reference_tool.captured,[self.seq-1])

    def test_resize_and_stale_frames_are_rejected_without_training(self):
        with self.assertRaisesRegex(ValueError,'Viewport changed'):
            self.frame(viewport=[999,800])
        self.frame()
        with self.assertRaisesRegex(ValueError,'stale frame'):
            self.frame(seq=1)
        self.assertTrue(all(not b.fit_calls for b in self.s.backends.values()))

    def test_partial_fit_failure_blocks_tracking_and_repeated_fit(self):
        self.collect_all()
        def fail(*args): raise RuntimeError('synthetic training failure')
        self.s.backends['gazefollower'].fit=fail
        with self.assertRaises(RuntimeError): self.finish()
        self.assertEqual(self.s.phase,'failed')
        with self.assertRaises(ValueError): self.frame(mode='track')
        with self.assertRaises(ValueError): self.finish()


if __name__=='__main__':
    unittest.main()
