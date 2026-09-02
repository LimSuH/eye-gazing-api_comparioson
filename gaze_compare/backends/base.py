from dataclasses import dataclass
from typing import Any


@dataclass
class Observation:
    point: Any = None
    features: Any = None
    valid: bool = False
    reason: str = "no_face"


class Backend:
    description = ""

    def __init__(self, width, height, work_dir):
        self.width, self.height = width, height
        self.work_dir = work_dir
        self.ready = False

    def process(self, frame):
        raise NotImplementedError

    def fit(self, features, targets):
        raise NotImplementedError

    def close(self):
        pass
