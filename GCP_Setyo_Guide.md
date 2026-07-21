맨땅에서 시작해 GCP 인프라 프로비저닝, IAM 및 OAuth 권한 제어, 깃허브 보안 토큰 우회, 그리고 Docker 컨테이너라이징까지의 모든 **트라이얼 앤 에러(Trial & Error)** 과정을 하나의 완벽한 엔지니어링 가이드로 통합 정리했습니다.

이 문서는 향후 FastAPI, Airflow, Kubernetes로 인프라를 확장할 때도 핵심 뼈대가 될 것입니다.

# GCP Compute Engine & Docker 기반 배포 가이드

## 1. 아키텍처 개요 (Architecture Overview)

본 인프라는 소스코드가 노출되는 것을 방지하기 위해 깃허브 토큰 및 텔레그램 API 키 등의 민감 정보를 **GCP Secret Manager**에서 안전하게 관리합니다. VM이 부팅될 때 시작 스크립트(Startup Script)가 구동 되면서 권한 체계와 인프라 구성을 자동으로 완료하는 구조입니다.

Plaintext

```
[GCP Compute Engine 부팅]
        ↓
[OAuth Scope & IAM 검증] → Secret Manager에서 GitHub Token 추출
        ↓
[Apt Lock 해제 대기] → Docker 엔진 및 Docker Compose 플러그인 설치
        ↓
[Git Clone (x-access-token)] → Repository 소스 다운로드
        ↓
[Docker 런타임 빌드] → Streamlit 대시보드 백그라운드 가동 (Port 8501)
```

## 2. GCP 기본 인프라 설정 (GCP Basic Setup)

### ① 프로젝트 및 Compute Engine 인스턴스 생성

- **Region / Zone:** 오리건(`us-west1`) 또는 아이오와(`us-central1`) 등 free-tier 또는 타겟 리전 선택
    
- **Machine Type:** `e2-micro` (vCPU 2개, Memory 1GB)
    
- **OS:** Ubuntu 22.04 LTS 또는 최신 가용 버전
    

### ② 중요: VM 액세스 범위 (OAuth Scopes) 설정

> **트라이얼 앤 에러 교훈:** IAM 권한이 완벽해도 VM 자체의 API 접근 범위(Scope)가 막혀있으면 `PERMISSION_DENIED` 에러가 발생합니다. VM 생성 시(또는 중지 후 수정 화면에서) 반드시 아래 옵션을 선택해야 합니다.

- **설정 위치:** VM 인스턴스 수정 ➔ **액세스 범위(Access Scopes)**
    
- **선택 항목:** **모든 Cloud API에 대한 전체 액세스 허용(Allow full access to all Cloud APIs)**
    

### ③ 방화벽 규칙(Firewall Rules) 설정

Streamlit의 기본 포트인 8501을 외부 네트워크에 개방합니다.

- **메뉴 경로:** 네트워크 보안 ➔ 방화벽(Firewall) ➔ 방화벽 규칙 만들기
    
- **이름:** `allow-streamlit`
    
- **대상(Target):** 네트워크의 모든 인스턴스
    
- **소스 IPv4 범위:** `0.0.0.0/0`
    
- **프로토콜 및 포트:** 지정된 프로토콜 및 포트 체크 ➔ `tcp: 8501`
    

## 3. 보안 및 자격 증명 설정 (Security & IAM)

### ① GitHub Personal Access Token 생성

- **경로:** GitHub ➔ Settings ➔ Developer Settings ➔ Personal Access Tokens (Classic 또는 Fine-grained)
    
- **권한(Scope):** `repo` (또는 `Contents: Read-only`)
    
    - _참고:_ 읽기 전용 권한이어도 스크립트의 클론 규격을 맞추면 정상 작동합니다.
        

### ② GCP Secret Manager 등록

- **메뉴 경로:** 보안 ➔ Secret Manager ➔ 보안 비밀 만들기
    
- **이름:** `ai-invest-assistant-github-token`
    
- **보안 비밀 값:** 깃허브에서 발급받은 토큰 값(`ghp_xxx...`) 붙여넣기

**앱 자체 시크릿도 함께 등록** — 4번 시작 스크립트가 이 이름들을 그대로 조회하므로 이름을 반드시 맞출 것(로컬 `.env`/`client_secret.json`/`token.json` 값을 그대로 옮겨오면 됨, 준비 절차는 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 참고 — Compute Engine도 브라우저를 못 띄우는 헤드리스 환경이라 `token.json`은 로컬에서 미리 인증을 마친 것을 그대로 가져와야 함):

```
gcloud secrets create drive-folder-id --data-file=<(printf '%s' "<DRIVE_FOLDER_ID 값>")
gcloud secrets create openrouter-api-key --data-file=<(printf '%s' "<OPENROUTER_API_KEY 값>")
gcloud secrets create exa-api-key --data-file=<(printf '%s' "<EXA_API_KEY 값>")
gcloud secrets create google-oauth-client-secret-json --data-file=client_secret.json
gcloud secrets create google-oauth-token-json --data-file=token.json
```

### ③ IAM 서비스 계정 권한 부여

VM 내부의 `gcloud` 명령어가 Secret Manager의 값을 긁어올 수 있도록 서비스 계정에 최소 권한을 부여합니다.

- **메뉴 경로:** IAM 및 관리자 ➔ IAM
    
- **대상 주체:** Compute Engine 기본 서비스 계정 (`{프로젝트번호}-compute@developer.gserviceaccount.com`)
    
- **부여할 역할(Role):** **Secret Manager 비밀 고문 (Secret Manager Secret Accessor)**
    

## 4. 통합 자동화 시작 스크립트 (Production Startup Script)

> **트라이얼 앤 에러 교훈:** > 1. 부팅 직후 우분투 자동 업데이트가 `apt`를 점유하여 스크립트가 터지는 현상을 방지하기 위해 `fuser` 기반 락(Lock) 대기 로직을 추가했습니다.
> 
> 2. 깃허브 403 Forbidden 및 Write Access 거부 에러를 해결하기 위해 멱등성이 보장된 `x-access-token` 주소 규격을 채택했습니다.
> 
> 3. 보안을 위해 토큰 사용 즉시 `unset` 처리하며, 소유권을 기본 유저(`UID 1000`)에게 양도하여 향후 SSH 디버깅 시 권한 문제를 원천 차단합니다.
> 
> 4. 글로벌 표준 배포를 위해 **모든 한글 주석을 제거**했습니다.

Bash

``` bash
#!/bin/bash

set -e

export DEBIAN_FRONTEND=noninteractive

LOG_FILE="/var/log/startup-script-custom.log"

truncate -s 0 "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== START ====="

echo "Waiting for system apt locks to release..."
sleep 15
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 ; do
    echo "Waiting for other apt process to finish..."
    sleep 2
done

echo "Installing base packages..."
apt-get update -y
apt-get install -y git curl

if ! command -v docker >/dev/null 2>&1; then
    echo "Installing Docker via official script..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
fi

echo "Installing Docker Compose Plugin..."
apt-get update -y
apt-get install -y docker-compose-plugin

systemctl enable docker
systemctl start docker

echo "Waiting for Docker daemon..."
timeout 120 bash -c '
until docker info >/dev/null 2>&1; do
    sleep 2
done
'

echo "Docker daemon is ready"

echo "Fetching GitHub token..."
TOKEN=$(gcloud secrets versions access latest \
    --secret=ai-invest-assistant-github-token)

HOME_DIR=$(getent passwd 1000 | cut -d: -f6)

if [ -z "$HOME_DIR" ]; then
    echo "Failed to detect default user home directory"
    exit 1
fi

cd "$HOME_DIR"

if [ -d ai_invest_assistant ]; then
    echo "Removing existing repository..."
    rm -rf ai_invest_assistant
fi

echo "Cloning repository..."
git clone https://x-access-token:${TOKEN}@github.com/garam827/ai_invest_assistant.git

unset TOKEN

DEFAULT_USER=$(id -nu 1000)

cd ai_invest_assistant

# 앱 자체 시크릿(.env + Drive OAuth JSON 2개)은 별도 Secret Manager 항목에서 가져온다 —
# git clone은 .gitignore된 파일(.env/client_secret.json/token.json)을 절대 포함하지 않으므로
# 여기서 직접 채워 넣어야 docker compose가 정상 기동한다.
echo "Fetching application secrets..."
cat > .env <<ENVEOF
DRIVE_FOLDER_ID=$(gcloud secrets versions access latest --secret=drive-folder-id)
OPENROUTER_API_KEY=$(gcloud secrets versions access latest --secret=openrouter-api-key)
EXA_API_KEY=$(gcloud secrets versions access latest --secret=exa-api-key)
STREAMLIT_ENABLE_LLM=false
ENVEOF

gcloud secrets versions access latest --secret=google-oauth-client-secret-json > client_secret.json
gcloud secrets versions access latest --secret=google-oauth-token-json > token.json

chown -R ${DEFAULT_USER}:${DEFAULT_USER} \
    "${HOME_DIR}/ai_invest_assistant"
chmod 600 .env client_secret.json token.json

docker compose pull || true

echo "Starting Docker Compose..."
docker compose up -d --build

echo "===== END ====="
```


**접속 주소:** `http://<가람님의_VM_외부_IP>:8501`


-------------------------------
부록

------------------------------------------

## 5. 인프라 운영 및 트러블슈팅 디버깅 시트

### ① 시작 스크립트 강제 재실행 (VM 재부팅 없이 즉시 반영)

시작 스크립트를 수정했거나, 중간에 프로세스가 멈춰 터미널에서 즉시 다시 돌리고 싶을 때는 인스턴스를 껐다 켤 필요 없이 아래 마스터 명령어를 실행합니다.

Bash

```
sudo google_metadata_script_runner startup
```

### ② 실시간 로그 모니터링

스크립트가 정상적으로 돌고 있는지, 깃 클론과 도커 빌드가 정상 진행 중인지 확인하려면 아래 로그를 추적합니다.

Bash

```
# 커스텀 로그 실시간 추적
tail -f /var/log/startup-script-custom.log

# 시스템 가동 레벨의 시작 스크립트 전체 로그 조회
sudo journalctl -u google-startup-scripts.service --no-pager
```

### ③ 일반 사용자 계정에 Docker 제어 권한 부여

일반 계정(`rkfka827` 등)으로 SSH 접속했을 때 `docker ps` 입력 시 `permission denied`가 발생하면, 해당 계정을 도커 그룹에 넣어 세션을 갱신해 주어야 합니다.

Bash

```
sudo usermod -aG docker $USER
newgrp docker
```

### ④ 인프라 우회 제어 치트키 (GCP Cloud Shell용)

인스턴스 내부의 OS 권한 체계가 완전히 꼬여 `sudo` 조차 먹히지 않을 때는, 외부 **GCP Cloud Shell**을 열어 마스터 키로 터널을 뚫고 내부 도커 엔진 상태를 강제 조회할 수 있습니다.

Bash

```
gcloud compute ssh instance-20260524-125459 \
    --zone=us-central1-a \
    --command="sudo docker ps"
```

## 6. 향후 인프라 고도화 로드맵 (Next Steps)

현재 완성한 **[Secret Manager + VM 내부 런타임 빌드]** 구조는 1대 단위의 가벼운 개발 환경 환경에서 매우 훌륭한 패턴입니다. 하지만 앞으로 시스템 규모를 확장할 계획이 있으므로, 인프라 진화 방향성을 다음과 같이 설정하는 것이 좋습니다.

1. **Intermediate 단계 (Artifact Registry 활용):**
    
    - VM 내부에서 매번 `git clone`을 받고 깡통 무대에서 리소스를 소모하며 빌드하는 대신, **GCP Artifact Registry**를 구축합니다.
        
    - 이미지 빌드는 외부에서 끝내고 VM은 오직 `docker pull`만 수행하여 인프라 프로비저닝 속도를 극대화합니다. 이 단계에 도달하면 VM 내부에서 Git 자체가 필요 없어집니다.
        
2. **Advanced 단계 (CI/CD 파이프라인 자동화):**
    
    - **GitHub Actions** 또는 **Jenkins**를 연동합니다.
        
    - 메인 브랜치에 코드가 `Push`되면 자동으로 Docker 이미지를 빌드 ➔ Artifact Registry에 Push ➔ 대상 VM에 원격 접속하여 컨테이너를 무중단 교체하는 완벽한 CD 환경을 구현합니다.