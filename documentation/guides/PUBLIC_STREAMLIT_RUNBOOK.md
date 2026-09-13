# 공개 Streamlit 실행 절차

## 도메인 없이 로컬 확인

저장소 루트에서 Docker Engine과 Compose v2를 준비하고 실행한다. 공개 앱에는 .env나 인증 파일이 필요하지 않다.

```powershell
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.local.yml config --quiet
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.local.yml up -d --build
```

브라우저에서 `http://127.0.0.1:8501`에 접속한다. 종료:

```powershell
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.local.yml down
```

검증:

```powershell
python -m unittest discover -s tests -v
python scripts/smoke_container.py
```

스모크 테스트는 별도 Compose 프로젝트 `ai-invest-smoke`, localhost 18501을 사용하고 테스트 후 제거한다.
GitHub의 Python regression tests 워크플로도 동일한 컨테이너 검증을 실행한다.

2026-09-13 검증: 로컬 Python 24개 테스트 및 Ruff F/I 검사 통과.
로컬 Docker 엔진이 응답하지 않아 컨테이너는 GitHub Linux 러너에서 검증했다.
이미지 빌드, health, 비루트·무인증 실행, 공개 UI 및 재시작 검증이 [CI에서 통과](https://github.com/garam827/ai_invest_assistant/actions/runs/34760951691)했다.
실제 GCP·Tunnel·부하 검증은 아직 수행하지 않았다.

## GCP 사전 확인

프로젝트 ID, VM 이름·존·머신 타입, 디스크 종류·용량, 외부 IP 및 NAT 사용 여부, 무료 혜택 상태를 확인한다.
비밀번호, 서비스 계정 키, OAuth 토큰, 결제 카드 정보는 공유하지 않는다.
Cloud Shell에서 아래 읽기 전용 명령을 사용할 수 있다.

```bash
gcloud config get-value project
gcloud compute instances list --format="table(name,zone.basename(),machineType.basename(),status,networkInterfaces[0].accessConfigs[0].natIP)"
gcloud compute disks list --format="table(name,zone.basename(),type.basename(),sizeGb)"
gcloud compute routers list --format="table(name,region.basename())"
```

라우터가 있다면 해당 리전·라우터의 NAT 구성을 추가 확인한다. 위 명령만으로 청구 여부를 확정할 수는 없다.
월 0원 조건 충족 여부를 검토하기 전 새 VM·IP·NAT·디스크를 만들지 않는다.

## 나중에 도메인 연결

GCP 비용 검토와 VM 준비 후 Cloudflare에 도메인을 연결하고 named Tunnel을 생성한다.
Tunnel 공개 호스트의 서비스 주소는 `http://streamlit-app:8501`로 지정한다. 전체 공개이므로 Access 로그인 정책은 적용하지 않는다.
토큰 파일은 저장소 밖에 보관하며 컨테이너가 읽을 수 있는 최소 권한을 부여한다.
Linux VM에서 아래 자리표시자를 실제 값으로 교체한 후 실행한다.

```bash
export CLOUDFLARED_IMAGE='cloudflare/cloudflared:<검증한-버전-또는-다이제스트>'
export CLOUDFLARED_TOKEN_FILE='/절대경로/tunnel-token'
export APP_IMAGE_TAG="$(git rev-parse --short HEAD)"
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.tunnel.yml config --quiet
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.tunnel.yml up -d --build
```

Cloudflared는 token-file을 지원하는 2025.4.0 이상을 선택한다. 기본 Compose만으로는 외부 접속 경로가 없다.
로컬 override를 운영 Tunnel 구성에 추가할 필요는 없다.
실제 HTTPS 접속, 차트 상호작용, WebSocket 유지, 재시작 후 재접속을 확인한다.

## 스냅샷 갱신과 복구

운영 전용의 깨끗한 체크아웃에서 `git pull --ff-only`로 발행 데이터를 갱신한다. 자동 갱신은 아직 구성하지 않았다.
앱은 docs 디렉토리를 마운트하므로 이미지 재빌드 없이 데이터가 반영된다. 최대 5분 캐시 후 페이지를 새로고침한다.
코드 변경 시에는 새 커밋별 APP_IMAGE_TAG로 빌드한다. 배포 커밋과 이전 이미지 태그를 기록한다.
문제가 생기면 이전 APP_IMAGE_TAG를 지정하고 같은 Compose 파일로 `up -d --no-build`하여 이전 이미지를 사용한다.
마운트 데이터는 이미지와 독립적이므로 데이터 문제는 검증된 이전 스냅샷으로 별도 복구한다.
VM 및 Docker 재시작 후 restart 정책을 확인하고 `/_stcore/health`와 Compose 로그를 확인한다.

공개 서버에는 인증키를 복사하지 않는다. 기존 GitHub 배치의 API 사용료는 별도이며 이 서버 설정이 배치 비용을 제한하지 않는다.
