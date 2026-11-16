# Bybit iPhone Paper Trading Dashboard

## 이 패키지의 목적
아이폰 Safari에서 접속하는 반응형 웹 대시보드 + 서버 측 모의매매 엔진입니다.
Bybit V5 공개 시세 API만 사용합니다. API Key/Secret이 없고 실제 주문 API를 호출하지 않습니다.

## 기본 전략 및 설정
- 가상 초기자금: 1,000 USDT
- BTCUSDT 레버리지 가정: 3x
- 거래대금 상위 알트 10개 레버리지 가정: 5x
- USDT 선형 무기한 종목
- 15분봉: EMA20/EMA50, MACD, RSI, 거래량 확인
- ATR 기반 손절, 손절폭의 2배 익절
- 거래당 위험 예산: 잔고의 0.5%
- UTC 일일 손실 제한: 당일 시작 잔고 대비 2%
- 포지션 한 개만 보유
- 편도 수수료 가정: 0.055%

## 로컬 테스트
Python 3.10+ 필요:
1. 압축 해제
2. 터미널에서 폴더로 이동
3. `pip install -r requirements.txt`
4. `python app.py`
5. 같은 네트워크의 PC/휴대폰에서 `http://컴퓨터의-로컬-IP:8080` 접속

## 무료 클라우드에서 테스트하기 (아이폰만으로 설정 가능)
1. GitHub에 새 Public 또는 Private 저장소를 만듭니다.
2. 이 압축을 iPhone 파일 앱에서 해제한 뒤 `app.py`, `requirements.txt`, `templates/index.html`을 저장소에 업로드합니다. `templates` 폴더 구조를 유지하세요.
3. Render에서 New > Web Service로 GitHub 저장소를 연결합니다.
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python app.py`
6. Instance Type: `Free`를 선택합니다.
7. Advanced > Environment Variables에 `PAPER_PASSWORD`를 추가하고 충분히 긴 임의 비밀번호를 설정합니다. 비밀번호를 코드나 GitHub 저장소에 적지 마세요.
8. 배포가 끝나면 `onrender.com` 주소를 Safari에서 열고 사용자 이름 `paper`와 설정한 비밀번호로 로그인합니다.

## 인터넷에서 24시간 사용하려면
이 앱을 Python 웹서비스를 지원하는 클라우드 호스팅에 배포해야 합니다.
예: Render의 Web Service 또는 유사한 상시 실행 Python 호스트.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app` (gunicorn을 requirements.txt에 추가해야 함) 또는 `python app.py`
- 인스턴스가 잠들지 않는 플랜을 사용해야 백그라운드 스캔이 계속됩니다.
- 배포 플랫폼의 영구 디스크를 `/var/data`에 연결하고 환경변수 `DATA_DIR=/var/data`를 설정하면 상태 파일을 보존할 수 있습니다.
- 단일 인스턴스/단일 프로세스로 실행하세요. 여러 워커를 켜면 각 워커가 별도 모의매매 루프를 만들 수 있습니다.
- 호스팅 업체가 제공하는 HTTPS 주소를 아이폰 Safari에서 열면 됩니다.

## 아이폰에서 홈 화면에 추가
Safari에서 배포된 주소를 연 뒤 공유 버튼 → '홈 화면에 추가'.

## 중요한 제한
- 무료 Render 서비스는 15분 동안 외부 요청이 없으면 잠들고, 재시작/잠자기 때 로컬 파일이 사라집니다. Safari를 닫거나 아이폰이 백그라운드로 가면 스캔이 중단될 수 있으므로 무료 버전은 화면을 열어둔 테스트용입니다.
- 이건 검증 전 실험용 프로토타입이며 수익성 보장 전략이 아닙니다.
- 공개 API 응답, 서버 장애, 네트워크 단절에 따라 스캔이 중단될 수 있습니다.
- 포지션 손절/익절은 주기적으로 조회한 15분봉 종가로 확인하는 단순 모의체결입니다. 급변 시 실제 가격 경로와 다릅니다.
- 펀딩비, 슬리피지, 최소 주문 수량, 틱 사이즈, 부분 체결은 반영하지 않았습니다.
- 서버가 재시작되면 실행 상태는 자동 복구되지 않을 수 있습니다. 상태 파일은 보존되지만 안전을 위해 수동으로 다시 시작해야 합니다.
- 실제 거래소 주문 기능은 포함되어 있지 않습니다.
