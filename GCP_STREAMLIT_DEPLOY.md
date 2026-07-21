# Streamlit 앱을 GCP(Cloud Run)에 배포하는 가이드

`app.py`(Streamlit UI)를 GCP에 공개 배포하기 위한 절차입니다. 크론(`collect.yml`/`recommend.yml`)은 이미 GitHub Actions에서 무인으로 돌고 있으므로, 이 문서는 오직 **사람이 직접 접속해서 보는 Streamlit 대시보드**를 배포하는 것만 다룹니다.

> **결제 계정 관련 유의**: 이 프로젝트는 과거 [기능 1]의 자동화(수집 크론)를 GCP Cloud Run + Cloud Scheduler로 하려다 조직 정책과 결제 계정 미연결 이슈로 GitHub Actions로 전환한 이력이 있습니다(`investment_assistant_spec.md` 버전 이력 v2.8 참고). Cloud Run 자체는 월 무료 티어가 넉넉하지만(요청 200만 건/월 등), **결제 계정이 프로젝트에 연결되어 있어야 Cloud Run API 자체가 활성화**됩니다. 이번엔 Streamlit 대시보드만 배포하는 것이므로 결제 계정을 다시 연결해야 진행할 수 있습니다.

## 배포 방식: 왜 Cloud Run인가

| 방식 | 비고 |
| --- | --- |
| **Cloud Run (추천)** | 컨테이너 기반 서버리스. 트래픽 없으면 인스턴스 0개로 줄어 비용 없음(콜드 스타트는 감수). Streamlit처럼 상시 프로세스가 필요한 웹 앱에 표준적인 선택. |
| App Engine (Standard) | Python 런타임 자체 지원은 되지만 WebSocket 기반 상시 연결(Streamlit이 씀)과 궁합이 덜 좋고 설정이 더 번거로움. |
| Compute Engine (VM) | 완전한 제어가 가능하지만 인스턴스를 끄지 않는 한 계속 과금되고, OS 패치 등 직접 관리 부담이 생김. |

이 문서는 **Cloud Run**만 다룹니다.

## 사전 준비물 체크리스트

- [ ] GCP 프로젝트 (기존 프로젝트 재사용 가능 — Drive API용으로 이미 만든 프로젝트가 있다면 그걸 써도 됨)
- [ ] 결제 계정 연결
- [ ] [gcloud CLI](https://cloud.google.com/sdk/docs/install) 설치 및 로그인 (`gcloud auth login`)
- [ ] 로컬에 이미 인증 완료된 `token.json` (아래 3단계 참고 — 없으면 로컬에서 먼저 만들어야 함)
- [ ] `OPENROUTER_API_KEY`, `EXA_API_KEY`, `DRIVE_FOLDER_ID` 등 기존 `.env` 값들

---

## 1단계: 프로젝트 준비 + API 활성화

```
gcloud config set project <프로젝트 ID>

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  drive.googleapis.com
```

- `run.googleapis.com`: Cloud Run
- `artifactregistry.googleapis.com`: 컨테이너 이미지 저장소 (`gcloud run deploy --source .`를 쓰면 내부적으로 여기에 이미지를 빌드·푸시함)
- `secretmanager.googleapis.com`: 아래 4단계에서 자격증명을 안전하게 보관하는 데 사용
- `drive.googleapis.com`: 이미 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 단계에서 켰다면 생략 가능

## 2단계: 컨테이너 준비 (이미 완료됨)

저장소 루트에 `Dockerfile`과 `.dockerignore`를 이미 만들어 뒀습니다:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV STREAMLIT_SERVER_HEADLESS=true
EXPOSE 8080
CMD streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0
```

- Cloud Run은 컨테이너에 `$PORT` 환경변수(기본 8080)를 주입하고 그 포트로 리슨할 것을 요구합니다 — `--server.address=0.0.0.0`이 없으면 Cloud Run 내부에서 헬스체크가 실패합니다.
- kaleido(헤드리스 Chromium)를 더 이상 쓰지 않기 때문에(`investment_assistant_spec.md` v3.0 참고) 이 이미지에 폰트/브라우저 설치가 전혀 필요 없습니다 — `requirements.txt`도 순수 Python 패키지뿐입니다.
- 로컬에서 미리 빌드해보고 싶다면:
  ```
  docker build -t invest-assistant-ui .
  docker run -p 8080:8080 --env-file .env invest-assistant-ui
  ```
  (`.env`에 이미 있는 값 그대로 로컬 컨테이너 테스트 가능. `token.json`/`client_secret.json`은 `.dockerignore`에 있어 이미지에 안 들어가므로, 로컬 테스트 시에는 `-v` 마운트로 넣어주거나 아래 4단계 방식대로 환경변수로 주입해서 테스트할 것.)

## 3단계: Google Drive OAuth 토큰을 헤드리스용으로 준비

Cloud Run은 브라우저를 띄울 수 없는 완전 무인 환경입니다. `drive_db._load_credentials()`가 캐시된 `token.json`이 없으면 `InstalledAppFlow.run_local_server()`(브라우저 필요)를 시도하는데, 이는 Cloud Run에서 그대로 실패합니다.

**반드시 로컬에서 먼저 인증을 완료**해 둬야 합니다 — 이미 이 프로젝트를 로컬에서 써왔다면 `token.json`이 이미 있을 것입니다([GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 7단계 참고). 없다면:

```
python -c "from drive_db import DriveDB; print(DriveDB().list_tickers())"
```

이렇게 만들어진 `client_secret.json`/`token.json`의 **파일 내용 전체**를 4단계에서 Secret Manager에 등록합니다 — `config._bootstrap_secret_file`이 이미 이 패턴을 지원합니다(GitHub Actions에서 `GOOGLE_OAUTH_CLIENT_SECRET_JSON`/`GOOGLE_OAUTH_TOKEN_JSON` 환경변수로 검증된 것과 동일한 메커니즘, Cloud Run에서도 그대로 재사용).

> **주의**: OAuth 동의 화면이 "테스트" 상태로 남아 있으면 리프레시 토큰이 7일 후 만료될 수 있습니다([GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 트러블슈팅 참고). 상시 운영할 배포본이라면 동의 화면을 "프로덕션"으로 전환하는 걸 권장합니다.

## 4단계: Secret Manager에 자격증명 등록

```
gcloud secrets create drive-folder-id --data-file=<(printf '%s' "<DRIVE_FOLDER_ID 값>")
gcloud secrets create google-oauth-client-secret-json --data-file=client_secret.json
gcloud secrets create google-oauth-token-json --data-file=token.json
gcloud secrets create openrouter-api-key --data-file=<(printf '%s' "<OPENROUTER_API_KEY 값>")
gcloud secrets create exa-api-key --data-file=<(printf '%s' "<EXA_API_KEY 값>")
```

(이미 만든 시크릿 값을 바꾸고 싶으면 `create` 대신 `gcloud secrets versions add <이름> --data-file=...`)

## 5단계: 배포 — LLM은 끄고 배포 (v3.11 기능 활용)

이 앱은 공개 배포를 염두에 두고 이미 `config.STREAMLIT_ENABLE_LLM` 플래그가 준비되어 있습니다(`investment_assistant_spec.md` v3.11 참고) — 배포 시 `false`로 설정하면:
- 뉴스(Exa)는 수집하되 버튼을 눌러야만 실행되고,
- LLM(OpenRouter) 서술 분석은 생략되어 규칙 기반 설명으로 대체됩니다.

방문자 여러 명이 동시에 API 비용을 유발하지 않도록, **배포본에서는 이 값을 `false`로 설정하는 것을 강력히 권장**합니다.

```
gcloud run deploy invest-assistant-ui \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=2 \
  --memory=1Gi \
  --set-env-vars="STREAMLIT_ENABLE_LLM=false" \
  --set-secrets="DRIVE_FOLDER_ID=drive-folder-id:latest,\
GOOGLE_OAUTH_CLIENT_SECRET_JSON=google-oauth-client-secret-json:latest,\
GOOGLE_OAUTH_TOKEN_JSON=google-oauth-token-json:latest,\
OPENROUTER_API_KEY=openrouter-api-key:latest,\
EXA_API_KEY=exa-api-key:latest"
```

- `--region asia-northeast3`: 서울 리전 (한국에서 접속 시 지연 최소화)
- `--allow-unauthenticated`: 로그인 없이 누구나 URL로 접속 가능하게(공개 대시보드 목적과 일치). 특정 사람만 보게 하고 싶으면 이 플래그를 빼고 IAM으로 접근자를 제한.
- `--min-instances=0`: 트래픽 없을 때 완전히 스케일 다운 → 비용 없음(대신 첫 방문자는 콜드 스타트 지연 몇 초 감수)
- `--max-instances=2`: 예상치 못한 트래픽 폭주로 과금이 튀는 걸 막는 안전장치

배포가 끝나면 `https://invest-assistant-ui-xxxxx-an.a.run.app` 형태의 URL이 출력됩니다.

## 6단계: 확인

1. 출력된 URL 접속 → "소개" 탭이 정상적으로 뜨는지 확인
2. "대표 자산군 분석" 탭에서 종목 조회 → 차트는 즉시 뜨고, "Mr. Serenity의 매매 추천" 자리에는 "뉴스/분석 불러오기" 버튼만 있어야 함(LLM 꺼짐 확인)
3. 버튼을 눌러 뉴스가 정상 수집되는지, 규칙 기반 설명("LLM 분석 비활성화" 문구)이 뜨는지 확인
4. "데이터 적재" 탭 버튼은 그대로 작동하지만, 이미 GitHub Actions 크론이 매일 데이터를 채우고 있으므로 배포본에서는 굳이 누를 필요 없음 — 접근 제한을 걸고 싶다면 이 탭만 별도로 숨기는 것도 고려 가능(현재는 미구현, 필요 시 추가 요청)

## 비용 관리 팁

- `--min-instances=0` + `--max-instances=2`로 상한을 걸어두면 일반적인 개인 사용 트래픽에서는 무료 티어 안에서 충분히 운영 가능
- Cloud Run 자체 비용과는 별개로 **OpenRouter/Exa API는 여전히 진짜 비용**입니다 — `STREAMLIT_ENABLE_LLM=false` + 뉴스 버튼 트리거 + `news_fetcher.get_cached_news` 읽기 캐시(v3.11)가 이미 이 비용을 최소화하도록 설계되어 있습니다.
- GCP 콘솔의 "예산 및 알림"에서 월 예산 알림을 걸어두는 것을 권장합니다.

## 트러블슈팅

**배포는 성공했는데 접속하면 계속 로딩만 되거나 에러**
→ Cloud Run 로그 확인: `gcloud run services logs read invest-assistant-ui --region asia-northeast3`. 대부분 `DRIVE_FOLDER_ID`/시크릿 이름 오타이거나, `token.json`이 만료된 경우.

**`token.json`이 만료됨 (재인증 필요)**
→ 로컬에서 3단계를 다시 실행해 새 `token.json`을 받고, `gcloud secrets versions add google-oauth-token-json --data-file=token.json`으로 시크릿을 갱신한 뒤 재배포(`gcloud run deploy` 재실행, 이미지 변경 없어도 새 시크릿 버전을 반영하려면 재배포 필요).

**포트 관련 오류 (`Container failed to start`)**
→ `Dockerfile`의 `CMD`에 `--server.address=0.0.0.0`이 빠졌는지, 또는 `--server.port=${PORT:-8080}`이 아니라 고정 포트로 하드코딩되지 않았는지 확인.

**로컬 `.env`를 바꿨는데 배포본에 반영이 안 됨**
→ 이 프로젝트에서 반복적으로 겪은 함정입니다(`.env` ↔ GitHub Actions Secrets 때와 동일 — `investment_assistant_spec.md` 주의사항 12번 참고). 로컬 `.env`, GitHub Actions Secrets, GCP Secret Manager는 **셋 다 완전히 별개의 저장소**입니다. 값을 바꿨으면 `gcloud secrets versions add`로 GCP 쪽도 갱신하고 재배포해야 합니다.
