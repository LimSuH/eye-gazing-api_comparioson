"""Optional pip installation and OFFLINE restore of bundled browser assets.

No shell evaluation, npm, external inference server, or admin access is needed.
"""
import argparse
import base64
import hashlib
import io
import sys
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from launcher_common import ROOT, require_supported_python

WEBGAZER_URL = "https://registry.npmjs.org/webgazer/-/webgazer-3.5.3.tgz"
WEBGAZER_SHA512 = "i6P97fWeixASmHWrJxgLUICugqV6qljIafi2ne6p0WYXAuldpwoaFRkedKFcu/qm95d128gdUxhOr336estXOw=="


def required_web_files():
    paths = ["vendor/webgazer.js", "vendor/webgazer.js.map", "vendor/WebGazer-LICENSE.md"]
    paths += ["vendor/webgazer-src/"+name for name in
              ("ridgeReg.mjs", "util_regression.mjs", "util.mjs", "mat.mjs", "params.mjs")]
    paths += ["mediapipe/face_mesh/"+name for name in
              ("face_mesh.js", "face_mesh.binarypb",
               "face_mesh_solution_wasm_bin.js", "face_mesh_solution_wasm_bin.wasm",
               "face_mesh_solution_simd_wasm_bin.js", "face_mesh_solution_simd_wasm_bin.wasm",
               "face_mesh_solution_simd_wasm_bin.data", "face_mesh_solution_packed_assets.data",
               "face_mesh_solution_packed_assets_loader.js", "README.md", "index.d.ts", "package.json")]
    return [ROOT/"web"/path for path in paths]


def install_web_assets():
    print("동봉한 원본 아카이브에서 WebGazer/MediaPipe 파일을 복원합니다. 다운로드하지 않습니다.", flush=True)
    archive_path = ROOT/"third_party/sources/webgazer-3.5.3.tgz"
    if not archive_path.is_file():
        raise RuntimeError(f"원본 아카이브 누락: {archive_path}. ZIP 전체를 다시 풀어 주세요.")
    data = archive_path.read_bytes()
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != WEBGAZER_SHA512:
        raise RuntimeError("WebGazer archive checksum mismatch")
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name == "package/dist/webgazer.js":
                target = ROOT/"web/vendor/webgazer.js"
            elif member.name == "package/dist/webgazer.js.map":
                target = ROOT/"web/vendor/webgazer.js.map"
            elif member.name == "package/LICENSE.md":
                target = ROOT/"web/vendor/WebGazer-LICENSE.md"
            elif member.name in {"package/src/ridgeReg.mjs", "package/src/util_regression.mjs", "package/src/util.mjs",
                                  "package/src/mat.mjs", "package/src/params.mjs"}:
                # Original, unmodified WebGazer regressor and dependencies.
                # Its addData/predict provide click and cursor online learning.
                target = ROOT/"web/vendor/webgazer-src"/PurePosixPath(member.name).name
            elif member.name.startswith("package/dist/mediapipe/face_mesh/"):
                tail = PurePosixPath(member.name).relative_to("package/dist/")
                if ".." in tail.parts:
                    raise RuntimeError("Unsafe archive path")
                target = ROOT/"web"/tail
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            count += 1
    if not all(p.is_file() for p in required_web_files()):
        raise RuntimeError("WebGazer archive is missing required runtime files")
    print(f"WebGazer 복원 완료: {count}개 로컬 파일 (원본의 0-byte .data도 정상 파일)", flush=True)


def main():
    p = argparse.ArgumentParser(description="현재 Python 한 환경에 설치. Conda 환경을 만들지 않습니다.")
    p.add_argument("--only", choices=["webgazer"], help="pip/인터넷 없이 동봉 브라우저 파일만 복원")
    args = p.parse_args()
    try:
        if args.only != "webgazer":
            require_supported_python()
            print("설치 대상 Python:", sys.executable, flush=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT/"requirements.txt")], check=True)
        install_web_assets()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, tarfile.TarError) as exc:
        print("설치 실패:", exc)
        return 1
    print("설치 완료. python run.py 실행 후 http://localhost:8765 에 직접 접속하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
