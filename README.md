# AI Invest Assistant

톰 바소 스타일의 규칙 기반 추세추종 분석, 일일 리포트, Streamlit 대시보드와 React 조회 사이트입니다.

## 로컬 실행

Python 3.11 이상에서 저장소 루트를 기준으로 실행합니다.

```powershell
python -m pip install -e .
Copy-Item .env.example .env
streamlit run apps/streamlit/app.py
```

`.env`에 Drive·뉴스·LLM 인증 정보를 설정합니다. 기존 `.env`와 OAuth 파일이 있으면 그대로 사용합니다.
Windows 개발환경 일괄 설치는 `scripts\setup.bat`, 연구용 추가 패키지는
`python -m pip install -r requirements-dev.txt -e .`로 설치합니다.

## 주요 명령

```powershell
python -m invest_assistant.pipelines.collect update
python -m invest_assistant.pipelines.recommend
python -m invest_assistant.pipelines.backtest full-universe
python -m unittest discover -s tests -v
```

수집 명령은 Drive 데이터를 갱신합니다. 추천 명령은 설정에 따라 Drive·공개 레포트·정적 JSON을 저장하고 Telegram을 발송합니다.
외부 호출 없이 검증하려면 위 테스트 명령을 사용합니다.

React 개발·빌드:

```powershell
cd apps/web
npm ci
npm run build
```

빌드 결과는 저장소 루트의 `docs/`에 기록하며, `docs/data/`와 `docs/reports/`는 보존합니다.

## 디렉토리

| 경로 | 역할 |
| --- | --- |
| `apps/streamlit/` | 6개 탭, UI 컴포넌트, Streamlit 캐시 |
| `apps/web/` | React·TypeScript 조회 사이트 원본 |
| `src/invest_assistant/` | 공통 분석·저장·추천·발행 패키지 |
| `research/` | 예측 모델과 노트북 실험 |
| `tests/` | 회귀·통합 테스트 |
| `infrastructure/`, `.github/workflows/`, `scripts/` | 컨테이너·자동화·설치 |
| `documentation/` | 현재 명세·구조·운영 가이드·이전 명세 |
| `docs/` | GitHub Pages 공개 산출물 |
| `artifacts/` | Git 제외 캐시·학습 데이터·모델·로그 |

Docker 실행은 저장소 루트에서 `docker compose -f infrastructure/docker-compose.yml up -d --build`입니다.
이 명령은 서버를 시작하므로 인증과 접근 정책을 정한 배포 환경에서 사용합니다.

설치형 배포의 데이터·인증 기준 디렉토리는 `INVEST_ASSISTANT_HOME`으로 지정합니다.
소스 체크아웃에서는 기본값이 저장소 루트입니다. 비밀 파일은 Git에 포함하지 않습니다.

- [현재 명세](documentation/specs/investment_assistant_spec.md)
- [구조와 이전 경로 대응표](documentation/architecture/layout.md)
- [Google Drive 인증](documentation/guides/GOOGLE_DRIVE_SETUP.md)
- [Telegram 설정](documentation/guides/TELEGRAM_SETUP.md)
- [Streamlit 서버 배포 검토](documentation/guides/STREAMLIT_DEPLOYMENT_REVIEW.md)
