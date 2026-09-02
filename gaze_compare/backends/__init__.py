"""Lazy imports keep ML initialization inside the one serial model worker."""


def create(name, width, height, work_dir):
    if name == "eyetrax":
        from .eyetrax_backend import EyeTraxBackend
        return EyeTraxBackend(width, height, work_dir)
    if name == "gazefollower":
        from .gazefollower_backend import GazeFollowerBackend
        return GazeFollowerBackend(width, height, work_dir)
    if name == "eyegestures":
        from .eyegestures_backend import EyeGesturesBackend
        return EyeGesturesBackend(width, height, work_dir)
    raise ValueError(name)
