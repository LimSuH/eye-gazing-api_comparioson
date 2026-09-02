"""Read-only release file checks. No server, browser, webcam or ML imports."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def manifest_entries(root=ROOT):
    path = Path(root)/'bundle_manifest.json'
    if not path.is_file():
        raise RuntimeError('bundle_manifest.json이 없습니다. 수정 ZIP의 모든 파일을 같은 폴더에 풀어 주세요.')
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = data.get('files', [])
    if data.get('format') != 1 or not entries:
        raise RuntimeError('잘못된 bundle_manifest.json입니다. 원본 ZIP을 다시 풀어 주세요.')
    seen = set()
    for entry in entries:
        name = entry['path']
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name or name in seen:
            raise RuntimeError(f'잘못된 배포 파일 경로: {name}')
        seen.add(name)
    return entries


def check_bundle(root=ROOT, strict=True):
    """Match size AND digest, including intentionally empty upstream files."""
    root = Path(root).resolve()
    errors = []
    entries = manifest_entries(root)
    for entry in entries:
        path = root/entry['path']
        if not path.resolve().is_relative_to(root):
            errors.append(f"폴더 밖 링크: {entry['path']}")
        elif not path.is_file():
            errors.append(f"누락: {entry['path']}")
        elif not strict and not entry['path'].startswith(('web/vendor/', 'web/mediapipe/', 'models/', 'third_party/')):
            continue  # Allow the user to edit their Python/GUI code.
        elif path.stat().st_size != entry['bytes']:
            errors.append(f"크기 불일치: {entry['path']} (예상 {entry['bytes']} bytes)")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            errors.append(f"내용 변경/손상: {entry['path']}")
    return entries, errors


def assert_bundle(root=ROOT, strict=True):
    entries, errors = check_bundle(root, strict=strict)
    if errors:
        raise RuntimeError('ZIP 파일 검사 실패:\n'+'\n'.join(errors)
                           +'\n자동 다운로드하지 않습니다. ZIP 전체를 새 폴더에 풀어 주세요. 직접 수정한 파일도 해시가 달라집니다.')
    return len(entries)


# These files are part of pip distributions, not first-run downloads.
# Inspect metadata paths without importing MediaPipe/GazeFollower (which can
# create model objects as an import side effect).
PACKAGE_RESOURCES = {
    'mediapipe': ('0.10.21', (
        'mediapipe/modules/face_detection/face_detection_short_range.tflite',
        'mediapipe/modules/face_landmark/face_landmark.tflite',
        'mediapipe/modules/face_landmark/face_landmark_with_attention.tflite',
        'mediapipe/modules/face_landmark/face_landmark_front_cpu.binarypb',
        'mediapipe/modules/selfie_segmentation/selfie_segmentation.tflite',
        'mediapipe/modules/selfie_segmentation/selfie_segmentation_landscape.tflite',
        'mediapipe/modules/selfie_segmentation/selfie_segmentation_cpu.binarypb',
    )),
    'gazefollower': ('1.0.2', ('gazefollower/res/model_weights/base.mnn',)),
}


def package_resource_errors():
    errors = []
    for name, (version, paths) in PACKAGE_RESOURCES.items():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            errors.append(f'{name}=={version} 미설치: python -m pip install -r requirements.txt')
            continue
        if dist.version != version:
            errors.append(f'{name} 버전 {dist.version}: 필요한 버전은 {version}')
        for relative in paths:
            path = Path(dist.locate_file(relative))
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f'{name} 설치 파일 누락/빈 파일: {path}\n'
                              f'복구: python -m pip install --force-reinstall --no-deps {name}=={version}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', action='store_true', help='설치한 Python 패키지의 내장 모델 파일도 검사')
    args = parser.parse_args()
    try:
        count = assert_bundle()
        print(f'ZIP files OK: {count} files (size + SHA-256; valid empty files included)')
        if args.packages:
            errors = package_resource_errors()
            if errors:
                print('\n'.join(errors))
                return 1
            print('Python package model files OK')
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(exc)
        return 1
    print('Read-only check: no app/server/browser/camera/model inference started.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
