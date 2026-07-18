# Google Drive API 연동 설정 가이드 (OAuth 사용자 인증)

`drive_db.py`가 Google Drive에 접근하기 위한 인증 설정 절차입니다. 원래는 서비스 계정 키(JSON)로 인증할 계획이었으나, GCP 프로젝트에 조직 정책 `iam.disableServiceAccountKeyCreation`이 적용되어 있어 서비스 계정 키 자체를 발급할 수 없었습니다. 대신 **OAuth 사용자 인증**(본인 구글 계정으로 로그인/동의)으로 전환했습니다. 관련 스펙 변경 이력은 [investment_assistant_spec.md](investment_assistant_spec.md)의 버전 이력(v2.1, v2.2) 참고.

## 1. GCP 프로젝트 준비
- [console.cloud.google.com](https://console.cloud.google.com)에서 프로젝트 생성 또는 기존 프로젝트 선택
- 결제 계정 연결 불필요 (Drive API는 무료)

## 2. Google Drive API 활성화
"API 및 서비스 → 라이브러리" → **"Google Drive API"** 검색 → 사용 설정

## 3. OAuth 동의 화면 설정
"API 및 서비스 → OAuth 동의 화면"
- User Type: **외부(External)** (개인 Gmail 계정이면 이것만 선택 가능)
- 앱 이름/지원 이메일: 아무 값이나 입력
- **테스트 사용자에 로그인에 사용할 본인 이메일을 반드시 추가 (필수, 건너뛰면 안 됨)** — "대상" 또는 "테스트 사용자" 섹션에서 "+ 사용자 추가"로 등록. 이 단계를 빼먹으면 로그인 시도 자체가 `액세스 차단됨: <앱 이름>은(는) Google 인증 절차를 완료하지 않았습니다` 오류로 막힌다 (앱이 "테스트" 상태인 동안은 테스트 사용자 목록에 없는 계정은 아예 로그인할 수 없음).
- 게시 상태는 "테스트"로 두어도 동작함 (미검증 앱 경고가 뜨면 "고급 → 이동(안전하지 않음)"으로 진행)

## 4. OAuth 클라이언트 ID 발급
"API 및 서비스 → 사용자 인증 정보 → + 사용자 인증 정보 만들기 → OAuth 클라이언트 ID"
- 애플리케이션 유형: **데스크톱 앱**
- 생성 후 JSON 다운로드 → 프로젝트 루트에 **`client_secret.json`**으로 저장 (`.gitignore`에 이미 등록되어 커밋되지 않음)

## 5. Drive 폴더 준비
1. 본인 Google Drive에 데이터를 저장할 폴더 생성 (예: `invest-assistant-db`)
2. 서비스 계정 방식과 달리 **폴더를 따로 공유할 필요 없음** — 본인 계정으로 로그인하므로 본인 Drive에 있는 폴더에 바로 접근 가능
3. 폴더를 열었을 때 주소창의 `.../folders/` 뒤 문자열이 **폴더 ID**

## 6. `.env` 작성
`.env.example`을 복사해 `.env`로 저장 후 아래 값 채우기:
```
GOOGLE_OAUTH_CLIENT_SECRET_PATH=client_secret.json
GOOGLE_OAUTH_TOKEN_PATH=token.json
DRIVE_FOLDER_ID=<5단계에서 확인한 폴더 ID>
```

## 7. 최초 인증 (브라우저 필요)
```
python -c "from drive_db import DriveDB; print(DriveDB().list_tickers())"
```
- 브라우저가 자동으로 열리며 구글 로그인 및 권한 동의 요청
- 동의 후 터미널에 `[]`(빈 리스트)가 출력되면 성공
- 이 과정에서 `token.json`이 생성되며, 이후 실행부터는 브라우저 없이 캐시된 토큰으로 자동 인증됨

## 트러블슈팅

**"액세스 차단됨: `<앱 이름>`은(는) Google 인증 절차를 완료하지 않았습니다"**
→ 3단계의 테스트 사용자 등록을 빼먹은 것. OAuth 동의 화면 → 테스트 사용자에 지금 로그인하려는 계정을 정확히 추가하고 몇 초 후 재시도.

## 주의: Cloud Run 등 헤드리스(무인) 환경에서 자동화할 때
- 스케줄러가 매일 Cloud Run을 호출하는 배치 환경에서는 브라우저를 띄울 수 없으므로, **로컬에서 7단계를 한 번 실행해 만든 `token.json`을 배포 시 함께 가져가야** 합니다 (예: Secret Manager나 컨테이너 이미지에 안전하게 포함).
- OAuth 동의 화면이 "테스트" 상태로 남아 있으면 리프레시 토큰이 **7일 후 만료**될 수 있습니다. 장기 무인 운영을 하려면 동의 화면 게시 상태를 "프로덕션"으로 전환하는 것을 권장합니다 (개인 사용 목적이면 Google 검증 없이도 전환 가능한 경우가 많으나, 요청 범위에 따라 검증이 요구될 수 있으니 전환 시 콘솔 안내를 확인할 것).
- 토큰이 만료되면 `drive_db._load_credentials`가 다시 `InstalledAppFlow`를 띄우려다 헤드리스 환경에서 실패합니다 — 이 경우 로컬에서 `token.json`을 재생성해 재배포해야 합니다.
