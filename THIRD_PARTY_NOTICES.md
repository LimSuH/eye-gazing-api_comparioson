# 사용한 프로젝트와 공식 출처

이 ZIP은 비교용 연결 코드, 설치 설정, WebGazer/MediaPipe 브라우저 실행 파일, EyeTrax용 FaceLandmarker 모델과 GazeFollower MGazeNet 모델을 포함합니다. Python 인터프리터와 OS별 pip 패키지 설치본, 사용자 학습 데이터는 포함하지 않습니다. 각 라이브러리와 모델에는 원저작자의 라이선스가 적용됩니다. 원본 아카이브·고지·출처·해시는 `third_party/`에 보관했습니다. 아래 정보는 별도 상업 이용 허가를 제공하지 않습니다.

| 프로젝트 | 연결 버전 | 배포에 표시된 라이선스 | 공식 출처 |
| --- | --- | --- | --- |
| EyeTrax | 0.4.0 | MIT | [GitHub](https://github.com/ck-zhang/eyetrax), [PyPI 버전](https://pypi.org/project/eyetrax/0.4.0/) |
| GazeFollower | 1.0.2 | CC BY-NC-SA | [GitHub](https://github.com/GanchengZhu/GazeFollower), [PyPI 버전](https://pypi.org/project/gazefollower/1.0.2/) |
| EyeGestures | 3.2.4 | GPLv3, 별도 상업 라이선스 안내 있음 | [GitHub](https://github.com/NativeSensors/EyeGestures), [PyPI 버전](https://pypi.org/project/eyeGestures/3.2.4/) |
| WebGazer | 3.5.3 | GPL-3.0-or-later | [공식 웹사이트](https://webgazer.cs.brown.edu/), [GitHub](https://github.com/brownhci/WebGazer), [npm 버전](https://www.npmjs.com/package/webgazer/v/3.5.3) |
| MediaPipe | Python 0.10.21 / JS는 WebGazer 배포물 | Apache-2.0 프로젝트; 모델·배포물의 고지도 확인 | [공식 저장소](https://github.com/google-ai-edge/mediapipe), [Face Landmarker 문서](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) |
| MNN | 3.6.1 | Apache-2.0 프로젝트 | [공식 저장소](https://github.com/alibaba/MNN) |

GazeFollower는 비상업 조건을 포함합니다. EyeGestures/WebGazer를 제품에 통합하거나 재배포할 때는 해당 버전의 전체 라이선스와 저작권 고지를 직접 검토하세요. WebGazer 원본 `LICENSE.md`를 `web/vendor/WebGazer-LICENSE.md`로 포함했고 GNU GPL v3 전문은 `third_party/licenses/GPL-3.0.txt`에 있습니다. GazeFollower와 MediaPipe 배포물의 라이선스도 보존했습니다. 하위 의존성(OpenCV, NumPy, scikit-learn, pygame 등)의 고지는 각 설치 배포물을 참고하세요.

## 배포 API에 맞춘 연결

- EyeTrax: 원본 `GazeEstimator`를 상속한 `BufferGazeEstimator`를 사용합니다. 생성자만 조정해 동봉 모델을 Python에서 읽고 MediaPipe `BaseOptions.model_asset_buffer`에 전달합니다. Windows에서 네이티브 모델 경로가 잘못 연결되는 문제를 피하며 `model_asset_path`는 설정하지 않습니다. 기본 초기 상태와 FaceLandmarker 설정은 0.4.0 원본과 같고, `extract_features`, `train`, `predict`, `close`는 원본을 그대로 상속합니다. 초기화 비교용 원본 `gaze.py`와 MIT 라이선스를 `third_party/`에 포함했습니다. 전역 함수나 설치된 패키지 파일은 수정하지 않습니다.
- GazeFollower: `MediaPipeFaceAlignment.detect`, `MGazeNetGazeEstimator.detect`, `SVRCalibration.calibrate/predict`를 사용합니다. 원본 카메라 스레드·UI·HeuristicFilter는 사용하지 않습니다. 따라서 GazeFollower 기본 프로그램과 완전히 같은 전체 파이프라인은 아닙니다.
- EyeGestures 3.2.4: `EyeGestures_v3.getLandmarks()`의 원본 눈/머리 특징과 원본 Fourier 특징 필터를 사용합니다. `Calibrator_v2.reg_x/reg_y`의 원본 Ridge(alpha=0.5)를 공통 표본으로 직접 한 번 학습합니다. 내부 `step()`·25점 루프·백그라운드 학습·출력 평균화를 사용하지 않습니다. 이 내부 속성에 의존하므로 임의 버전 업그레이드는 지원하지 않습니다. v4/Rust API는 사용하지 않습니다.
- WebGazer: npm 3.5.3의 `TFFaceMesh.getEyePatches()`와 `util.getEyeFeats()`로 특징을 얻습니다. 수정하지 않은 `ridgeReg.mjs`, `util_regression.mjs`, `util.mjs`, `mat.mjs`, `params.mjs`를 ZIP에 포함했습니다. 공통 특징/좌표로 원본 RidgeReg의 초기 버퍼를 채우고, 실제 사용자 클릭·커서 이동을 원본 `addData()`에 전달합니다. 원본 `predict()`가 계수를 계속 계산합니다. 초기 표본을 모두 포함하도록 클릭 버퍼 용량을 초기 표본 수+50으로 확장하며, 기존 ZIP의 Kalman 비사용 설정은 유지합니다. 두 번째 카메라를 열지 않도록 `webgazer.begin()` 대신 자체 카메라/이벤트 수명을 관리합니다. 브라우저 세션 간 학습 데이터 영속 저장은 하지 않습니다.
- 표시용 기준 윤곽: MediaPipe Python의 FaceMesh와 SelfieSegmentation으로 머리와 사람 실루엣을 추출합니다. 이 결과는 엔진 입력을 추가 보정하는 데 사용하지 않습니다.

WebGazer 원본 tarball의 SHA-512를 검사했고, 그 안의 실행 파일을 바이트 그대로 포함했습니다. Python 패키지는 requirements.txt에 명시한 버전으로 PyPI에서 설치합니다. GazeFollower 생성자의 공식 `model_path`에 원래 배포물과 동일한 동봉 `base.mnn`을 전달합니다. 설치된 원본 패키지 파일을 덮어쓰지 않고 연결 계층에서 입력·보정·예측 흐름을 제어합니다. 위 설명처럼 일부 내부 속성 및 소스 모듈도 사용하므로 각 원본 데모와 동일한 전체 처리 경로는 아닙니다. 현재 프로젝트 실행에는 WebGazer 재빌드나 Node/npm 설치가 필요 없습니다.
