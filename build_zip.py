"""Package the complete project, including binary runtime assets. No app startup."""
import hashlib
import json
from pathlib import Path
import zipfile

from setup_envs import required_web_files
from verify_bundle import assert_bundle

ROOT = Path(__file__).resolve().parent
TOP_FILES = (
    'README.md','CHANGES.md','VALIDATION.md','THIRD_PARTY_NOTICES.md',
    'run.py','launcher_common.py','setup_envs.py','doctor.py',
    'verify_bundle.py','build_zip.py','requirements.txt','constraints.txt','environment.yaml',
)
TREES = ('gaze_compare','web','tests','models','third_party')


def release_files(root=ROOT):
    files = [root/name for name in TOP_FILES]
    for tree in TREES:
        # Never filter by text extensions: .wasm/.data/.task/.mnn are essential.
        files.extend(path for path in (root/tree).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo'))
    for path in files:
        if not path.is_file():
            raise RuntimeError(f'패키징 파일 누락: {path}')
    return sorted(files)


def main():
    must_exist = required_web_files()+[
        ROOT/'models/mediapipe/face_landmarker.task', ROOT/'models/gazefollower/base.mnn',
        ROOT/'third_party/sources/webgazer-3.5.3.tgz',
    ]
    for path in must_exist:
        if not path.is_file():
            raise RuntimeError(f'필수 실행 리소스 누락: {path}')
    files = release_files()
    manifest = {'format':1,'revision':'2026-09-02-visible-calibration-targets-1',
                'note':'Sizes and hashes include intentionally empty upstream files. Python interpreter and pip wheels are not bundled.',
                'files':[{'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]}
    manifest_path = ROOT/'bundle_manifest.json'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert_bundle(ROOT)
    output = ROOT.with_suffix('.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in files+[manifest_path]:
            archive.write(path,Path(ROOT.name)/path.relative_to(ROOT))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP CRC check failed')
    print(f'{output}: {len(files)+1} files, {output.stat().st_size:,} bytes. Complete bundle / CRC OK.')


if __name__ == '__main__':
    main()
