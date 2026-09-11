# 톰 바소 스타일 추세추종 투자 어시스턴트 명세

현재 버전: **v3.64 (2026-09-12)**

## 변경 이력과 아카이브

| 버전 | 날짜 | 변경 |
| --- | --- | --- |
| v3.64 | 2026-09-12 | 공통 Python 패키지화, Streamlit 6개 탭 분리, React·연구·운영·문서 재배치, 실행 파이프라인 분리, 경로 중앙화, HTML·정적 JSON 총평 재사용. S&P 500 개별 종목 매수/매도 표와 복사 요약 제외. 기존 LLM 180초 타임아웃 수정 포함. |
| v3.63 | 2026-09-09 | OHLCV 유효성 검증, 불완전 대표 자산군 수집·추천 배치의 발행 차단. |

리팩토링 직전 명세 원문은 [v3.63 작업 전 스냅샷](archive/investment_assistant_spec_v3.63_before_v3.64.md)에 보존한다.
이전 버전별 전체 문서는 [archive/](archive/)에 보관한다. 아카이브는 당시 경로와 운영 상태의 기록이며 현재 실행 지침은 본 문서와 README를 따른다.
기존 에이전트 안내 원문도 [아카이브](archive/CLAUDE_before_v3.64.md)에 보존한다.

## 목적과 운영 범위

규칙 기반 추세추종으로 S&P 500 개별 종목과 대표 자산군의 매수/HOLD/매도를 판정한다.
LLM은 뉴스 설명과 시장 총평을 제공하며 판정이나 주문 수량을 결정하지 않는다.
실제 증권사 주문 기능은 없으며, 포지션 기록은 모의투자다.

대표 자산군은 `invest_assistant.universe.ASSET_CLASS_TICKERS`의 12종이다.

| 분류 | 티커 |
| --- | --- |
| 주식 | SPY, QQQ |
| 암호화폐 | BTC-USD |
| 귀금속 | GLD |
| 채권 | TLT, IEF |
| 원자재 | DBC, USO, UNG, DBA, DBB |
| 통화 | UUP |

## 구조와 실행

[디렉토리 구조·이전 경로 대응표](../architecture/layout.md)가 모듈 배치의 기준이다.
Python 3.11 이상에서 `python -m pip install -e .`로 설치한다.

| 작업 | 저장소 루트에서 실행할 명령 |
| --- | --- |
| Streamlit | `streamlit run apps/streamlit/app.py` |
| 초기 수집 | `python -m invest_assistant.pipelines.collect init` |
| 일일 수집 | `python -m invest_assistant.pipelines.collect update` |
| 구성종목 동기화 | `python -m invest_assistant.pipelines.collect sync` |
| 일일 추천·발행 | `python -m invest_assistant.pipelines.recommend` |
| 전체 백테스트 | `python -m invest_assistant.pipelines.backtest full-universe` |
| 회귀 테스트 | `python -m unittest discover -s tests -v` |

공통 코드에 Streamlit 의존성을 넣지 않는다. UI의 위젯·세션 상태·캐시는 `apps/streamlit/`에 둔다.
공개 산출물은 기존 `docs/`와 기존 URL을 유지한다. 개발 문서는 `documentation/`, 비공개 로컬 산출물은 Git 제외 `artifacts/`에 둔다.

## 데이터와 품질

시세는 yfinance 일별 OHLCV, 저장은 Google Drive의 종목별 Parquet 파일이다.
Drive는 OAuth 사용자 인증을 사용하며 `.env`, `client_secret.json`, `token.json`은 버전 관리에서 제외한다.
환경변수로 인증 JSON을 전달하는 기존 부트스트랩 기능을 유지한다.
기본 경로는 저장소 루트이며 설치형 배포는 `INVEST_ASSISTANT_HOME`으로 기준 경로를 지정한다.

S&P 500 구성종목 동기화는 대표 자산군을 편입·편출 판정에서 제외한다.
편출 종목의 과거 데이터는 보존한다. 기본 5년 수집과 기존 증분 갱신을 유지한다.
종목 간 요청 지연은 `YFINANCE_REQUEST_DELAY_SEC`(기본 0.5초)를 따른다.

수집·저장·시그널 계산 전에 OHLCV 결측·비유한 값·가격 및 거래량 유효성을 검증한다.
잘못된 조회 응답은 최대 3회 시도하고, 지속 실패한 데이터는 저장하지 않는다.
대표 자산군 수집 실패나 추천 누락은 배치를 실패 처리해 불완전 발행을 막는다.

## 지표와 매매 규칙

- Donchian 20일·100일 채널은 오늘을 제외한 과거 값으로 계산한다(`shift(1)`).
- 종가의 채널 상단 돌파는 매수, 트레일링 스탑 이탈은 매도다. 정확한 판정 순서는 `analysis/signals.py`를 유지한다.
- ATR은 14일 Wilder 방식이며, 트레일링 스탑은 기간 고점에서 ATR 3배를 뺀다.
- 수량은 `(계좌자산 × 위험비율) // (3 × ATR)`, 기본 위험비율은 1%다.
- Bollinger Bands와 일목균형표는 참고 지표이며 매매 판정·수량을 변경하지 않는다.
- 거래량 급증은 표시·후보 정렬용이며, 거래량이 적다는 이유로 매수 신호를 차단하지 않는다.
- 차트의 매수/청산 마커는 신호가 새로 발생한 날에 표시한다.

## 추천·뉴스·LLM

`recommendations/engine.py`가 개별 종목 추천과 시그널 이력을 담당한다.
뉴스는 Exa API로 조회하고 Drive에 날짜별 캐시·아카이브한다.
LLM은 매수·매도 설명에 사용하며 HOLD 설명은 규칙 기반이다.
뉴스·LLM 실패 시 규칙 기반 설명으로 대체하고 기계적 판정을 보존한다.
기존 프롬프트와 데이터 최신성 검사를 유지한다.

프로바이더·키·모델은 `config.py` 환경변수 설정을 따른다. `LLM_REQUEST_TIMEOUT_SEC` 기본값은 180초다.
`SKIP_LLM_AND_NEWS`는 뉴스·LLM 생략용이며, Streamlit의 개별 LLM 사용 토글과 별개다.
시장 총평은 `pipelines/recommend.py`에서 한 번 생성해 레포트와 정적 JSON에 동일하게 전달한다.
해외 매크로 이슈 설명은 별도 뉴스 기반이며 실패하면 해당 섹션을 생략한다.

## 화면

Streamlit은 단일 화면의 6개 탭을 유지한다.

1. 소개: 프로그램 목표·투자 철학·지표 설명.
2. 대표 자산군 분석: 자산군·종목·기간 선택, 공통 차트·추천.
3. S&P 500 종목 차트: 섹터·종목·기간 선택, 공통 차트·추천.
4. 데이터 적재: 수동 전체 수집과 진행 로그.
5. 리포트 히스토리: 실제·테스트 레포트 조회, 시그널 이력.
6. 모의투자: 포지션 개설·청산·손익.

기존 폼 제출 시점, 위젯 키, 캐시 TTL, 세션 상태 동작을 유지한다.
종목 차트는 `components/ticker_chart.py`, 조회 캐시는 `services.py`로 분리한다.
React는 `apps/web/`의 읽기 전용 사이트이며 Python 서버나 Drive API를 직접 호출하지 않는다.
대화형 챗과 Streamlit 전체 종목 후보 스캔 화면은 구현 범위에 포함하지 않는다.

## 레포트·발행

일일 레포트는 대표 자산군 요약, 시장 총평, 매크로 지표·이슈, 최근 시그널 이력,
모의투자, 대표 자산군 매수/매도 분석·뉴스·차트, HOLD 차트 및 저장된 백테스트 요약을 제공한다.
선택 데이터가 없거나 조회에 실패한 경우 기존 섹션별 생략 동작을 유지한다.
S&P 500 개별 종목 매수/매도 표는 HTML과 복사 Markdown에서 제외한다.
S&P 500 시그널 계산과 React용 JSON은 유지한다.

`reporting/report.py`는 HTML·Markdown·차트를 구성하고 `storage/reports.py`는 저장·조회를 담당한다.
LLM·뉴스 텍스트는 HTML 이스케이프한다. 서버의 차트 PNG 생성에 의존하지 않는다.
레포트는 Drive의 `_report_{date}.html`과 `docs/reports/{date}.html`에 저장한다.
React 데이터는 `docs/data/`에 저장한다. Telegram은 요약과 레포트 URL을 전달한다.

`IS_TEST_REPORT`는 추천 JSON과 레포트에 `_test` 접미어를 사용한다.
테스트 레포트는 공개 폴더에도 저장하지만 실제 시그널 이력·React 최신 JSON을 덮어쓰지 않는다.
과거 시점 백필은 현재 정적 JSON과 Telegram 발송을 생략한다.

## 자동화·배포

GitHub Actions의 `collect.yml` 성공 후 `recommend.yml`이 실행되는 구조를 유지한다.
두 워크플로는 패키지 설치 후 테스트를 수행하고 `python -m` 명령으로 실행한다.
React 배포는 `apps/web/`에서 빌드하며 기존 `docs/` 경로로 발행한다.
Docker 관련 파일은 `infrastructure/`, 설치 스크립트는 `scripts/`에 둔다.

Streamlit 외부 서버의 실제 신규 배포는 이번 리팩토링에 포함하지 않는다.
배포 방식·Drive 인증 갱신·접근 권한·리소스·비용은 후속 서버 배포 검토에서 정한다.
검토 결과는 [Streamlit 서버 배포 검토](../guides/STREAMLIT_DEPLOYMENT_REVIEW.md)에 정리했다.
`test.yml`은 소스 변경 시 Ubuntu/Python 3.11에서 설치형 패키지와 회귀 테스트를 검증한다.

## 모의투자·백테스트·연구

모의투자 개설·청산은 UI에서만 실행하며 일일 파이프라인은 포지션을 조회만 한다.
백테스트는 수동 실행으로 계산하고, 일일 레포트는 Drive의 저장된 요약만 읽는다.
기존 Triple-Barrier 라벨·거래 시뮬레이션·Kelly·자산곡선 계산은 유지한다.
상세 연구 설계는 [백테스트 명세](archive/triple_barrier_backtest_spec_v1.md)와
[예측 모델 명세](prediction_model_spec.md)를 참고한다.

예측 모델은 `research/prediction_model/`, 노트북 도우미는 `research/notebooks/`에 둔다.
실행 시 `sys.path`나 프로세스 작업 디렉토리를 바꾸지 않고 설치된 패키지를 사용한다.
예측 모델은 일일 추천 파이프라인에서 학습·추론하지 않으며 레포트에도 표시하지 않는다.

## 검증 기준

데이터 품질·LLM 타임아웃 회귀, 패키지 간 레포트·총평 전달, Streamlit 6개 탭의
초기 렌더링과 종목 그룹 전환, React 프로덕션 빌드를 확인한다.
외부 서비스는 테스트에서 대체하며 검증을 위해 실제 발행이나 유료 API 호출을 실행하지 않는다.
