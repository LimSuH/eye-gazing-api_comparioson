## Eye Gazer-웹캠 시선 추적 api 비교
<img width="1534" height="862" alt="image" src="https://github.com/user-attachments/assets/8192f04a-7b2e-4582-97bd-7c37d5e5778e" />

### 설치와 실행

```bash
conda env create -n [env name] -f environment.yaml
python -m pip install -r requirements.txt
```

```bash
python run.py
```

터미널의 **HTTP server READY** 메시지가 뜬 뒤 다음 로컬 호스트 접속  
**http://127.0.0.1:8765/**  
**http://localhost:8765/**  

</br>

### 시작
웹캠 권한 허용 후 9점 보정 실행
파란 점을 보고 SPACE 혹은 클릭, 다음 점에서도 반복합니다.

완료 후 **EyeTrax / GazeFollower / EyeGestures / WebGazer** 버튼으로 시선 추적 API를 바꿀 수 있습니다.  
WebGazer 선택 시 추가 보정이 필요할 수 있습니다.
