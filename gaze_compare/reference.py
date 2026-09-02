"""Reference outlines are captured once, never fed into gaze calibration."""
import cv2
import mediapipe as mp
import numpy as np

FACE_OVAL = [10,338,297,332,284,251,389,356,454,323,361,288,397,365,
             379,378,400,377,152,148,176,149,150,136,172,58,132,93,
             234,127,162,21,54,103,67,109]


class ReferenceOutline:
    def __init__(self):
        self.face = mp.solutions.face_mesh.FaceMesh(static_image_mode=True,
                                                   max_num_faces=1, refine_landmarks=True)
        self.segmenter = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=0)

    def observe(self, frame):
        result = self.face.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            return None
        landmarks = result.multi_face_landmarks[0].landmark
        poly = [[float(landmarks[i].x), float(landmarks[i].y)] for i in FACE_OVAL]
        xs, ys = zip(*poly)
        return {"head": poly, "center": [(min(xs)+max(xs))/2, (min(ys)+max(ys))/2],
                "head_width": max(xs)-min(xs)}

    def capture(self, frame):
        head = self.observe(frame)
        if head is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        probabilities = self.segmenter.process(rgb).segmentation_mask
        mask = np.uint8(probabilities > .5)*255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        h, w = mask.shape
        if cv2.contourArea(contour) < w*h*.015:
            return None
        contour = cv2.approxPolyDP(contour, 1.4, True).reshape(-1,2)
        if len(contour) > 400:
            contour = contour[np.linspace(0, len(contour)-1, 400).astype(int)]
        return {**head, "silhouette": (contour / [w,h]).tolist(), "camera_size": [w,h]}

    def close(self):
        self.face.close()
        self.segmenter.close()
