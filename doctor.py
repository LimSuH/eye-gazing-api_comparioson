"""Check package metadata only. Never open a camera or instantiate a model."""
import importlib.metadata as metadata
import platform
import sys
from launcher_common import require_supported_python


def main():
    require_supported_python()
    print('Python',sys.version.split()[0],platform.system(),platform.machine())
    required={'eyetrax':'0.4.0','gazefollower':'1.0.2','eyeGestures':'3.2.4',
              'mediapipe':'0.10.21','numpy':'1.26.4','MNN':'3.6.1',
              'opencv-python':'4.11.0.86','opencv-contrib-python':'4.11.0.86',
              'scikit-learn':'1.6.1','scipy':'1.15.3','screeninfo':'0.8.1'}
    bad=False
    for name,expected in required.items():
        try:
            actual=metadata.version(name)
            print(name,actual,'OK' if actual==expected else f'(expected {expected})')
            bad |= actual!=expected
        except metadata.PackageNotFoundError:
            print(name,'MISSING'); bad=True
    from verify_bundle import check_bundle, package_resource_errors
    try:
        entries,errors=check_bundle(strict=False)
        print(f'ZIP resources: {len(entries)} files checked')
        errors+=package_resource_errors()
        for error in errors: print(error)
        bad |= bool(errors)
    except (OSError,RuntimeError,ValueError,KeyError) as exc:
        print('ZIP resource check:',exc); bad=True
    print('카메라는 Python이 아니라 localhost에 접속한 브라우저가 엽니다.')
    print('메타데이터 검사일 뿐 모델 추론 성공이나 정확도를 보장하지 않습니다.')
    return int(bad)


if __name__=='__main__':
    raise SystemExit(main())
