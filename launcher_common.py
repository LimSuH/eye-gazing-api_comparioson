from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BACKENDS = ("eyetrax", "gazefollower", "eyegestures", "webgazer")


def require_supported_python():
    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        raise RuntimeError(
            f"현재 Python {sys.version_info.major}.{sys.version_info.minor}는 이 통합 구성과 맞지 않습니다.\n"
            "PyCharm에서 Python 3.11 (64-bit) 기반 가상환경 하나를 선택하세요.\n"
            "다른 프로젝트의 Python 3.14는 삭제하거나 변경할 필요가 없습니다."
        )
