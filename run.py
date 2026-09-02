"""Start the one localhost GUI using the interpreter selected in PyCharm."""
import argparse
import sys
from launcher_common import require_supported_python


def main():
    require_supported_python()
    p=argparse.ArgumentParser(description='한 번의 공통 보정 + 4종 GUI 전환')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--samples',type=int,default=30)
    args=p.parse_args()
    print('Python:',sys.executable,flush=True)
    from verify_bundle import assert_bundle, package_resource_errors
    count=assert_bundle(strict=False)
    print(f'배포 파일 검사 완료: {count}개. 실행 리소스를 다운로드하지 않습니다.',flush=True)
    errors=package_resource_errors()
    if errors:
        raise RuntimeError('\n'.join(errors))
    from gaze_compare.webserver import main as serve
    serve(['--port',str(args.port),'--samples',str(args.samples)])


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,OSError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
