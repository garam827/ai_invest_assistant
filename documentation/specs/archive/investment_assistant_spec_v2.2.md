# 프로젝트 명세서: 톰 바소(Tom Basso) 스타일의 추세추종 투자 어시스턴트 챗봇 (최종 확정안)

본 문서는 전설적인 트레이더 톰 바소의 투자 철학(기계적 시스템, 규칙 기반 대응, ATR 기반 변동성 관리 및 포지션 사이징)을 반영한 LLM 기반 투자 어시스턴트 챗봇을 **Vibe Coding(프롬프트 기반 AI 코딩)**으로 구축하기 위한 최종 마스터 가이드라인입니다.

---

## 버전 이력 (Changelog)

| 버전 | 날짜 | 변경 내용 |
| --- | --- | --- |
| v1.0 | (최초 작성) | 최초 확정안. LLM 엔진: GCP Vertex AI (Gemini 1.5 Pro). 전체 내용은 [investment_assistant_spec_v1.md](investment_assistant_spec_v1.md) 참고 |
| v2.0 | 2026-07-18 | **LLM 엔진을 GCP Vertex AI(Gemini)에서 OpenRouter로 변경** (비용 절감 목적). 기본 모델: `nvidia/nemotron-3-nano-30b-a3b:free`. 이에 따라 인증 방식(서비스 계정 → API 키)과 관련 섹션(1.1, 1.2, 기능3) 갱신. 전체 내용은 [investment_assistant_spec_v2.md](investment_assistant_spec_v2.md) 참고 |
| v2.1 | 2026-07-18 | **구글 드라이브 인증 방식을 서비스 계정 키 → OAuth 사용자 인증으로 변경.** 조직 정책(`iam.disableServiceAccountKeyCreation`)이 서비스 계정 키 발급 자체를 차단하는 GCP 프로젝트여서, 서비스 계정 키 대신 OAuth 클라이언트(데스크톱 앱)로 사용자 본인 계정에 동의를 받는 방식으로 전환. 설정 절차는 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 참고. 전체 내용은 [investment_assistant_spec_v2.1.md](investment_assistant_spec_v2.1.md) 참고 |
| v2.2 | 2026-07-18 | **OAuth 인증 트러블슈팅 추가**: OAuth 동의 화면이 "테스트" 상태일 때 로그인 계정이 "테스트 사용자" 목록에 없으면 `액세스 차단됨: ...은(는) Google 인증 절차를 완료하지 않았습니다` 오류가 발생함을 [기능 1]과 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md)에 명시. 코드 변경 없음, 문서만 갱신 |

> 과거 버전 전체 내용은 `investment_assistant_spec_v{N}.md` 파일로 보존합니다. 이 파일(`investment_assistant_spec.md`)은 항상 최신 버전을 담습니다.

---

## 1. 시스템 아키텍처 & 환경 (Architecture)

### 1.1 기술 스택
- **Frontend / Chat UI**: Streamlit
- **Data Source**: yfinance (Yahoo Finance API)
- **Database (Virtual)**: Google Drive API + Apache Parquet (`.parquet`)
- **LLM Engine**: OpenRouter (기본 모델 `nvidia/nemotron-3-nano-30b-a3b:free`, `OPENROUTER_MODEL_NAME` 환경변수로 교체 가능)
- **Infrastructure**: GCP Cloud Run (Docker Container 배포) + Cloud Scheduler (일별 데이터 수집 실행 트리거)

### 1.2 데이터 흐름 (Data Flow)
1. **매일 장 마감 후**: Cloud Scheduler가 Cloud Run 엔드포인트를 호출하여 데이터 수집 스크립트 가동.
2. **yfinance API 수집**: 미국 S&P 500 전 종목의 당일 OHLCV 데이터를 수집.
3. **구글 드라이브 가상 DB 적재**: OAuth 사용자 인증(캐싱된 토큰)을 통해 지정 폴더 내 `[Ticker].parquet` 파일에 당일 데이터를 Append 및 중복 제거(Upsert).
4. **시그널 엔진 작동**: 누적된 데이터를 바탕으로 Donchian Channel 및 ATR 자동 계산.
5. **LLM 브리핑**: 시그널(매수/매도) 발생 종목의 당일 Yahoo Finance 뉴스를 긁어와 OpenRouter LLM(Nemotron)이 팩트 기반 요약.
6. **사용자 UI**: Streamlit 대시보드 및 챗봇 창에서 분석 결과 확인 및 대화 유저 인터페이스 제공.

---

## 2. 세부 기능 개발 가이드라인 (Vibe Coding용)

### [기능 1] 구글 드라이브 연동 및 데이터 수집 엔진
- **인증 방식**: OAuth 사용자 인증(데스크톱 앱 클라이언트, `client_secret.json`)으로 사용자 본인 구글 계정에 최초 1회 동의를 받고, 발급된 리프레시 토큰을 `token.json`에 캐싱하여 이후 무인 재인증. (서비스 계정 키는 조직 정책 `iam.disableServiceAccountKeyCreation`으로 발급이 차단되어 사용 불가 — 상세 배경 및 설정 절차는 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 참고)
- **알려진 함정**: OAuth 동의 화면이 "테스트" 게시 상태일 때, 로그인하려는 구글 계정이 "테스트 사용자" 목록에 등록되어 있지 않으면 `액세스 차단됨: <앱 이름>은(는) Google 인증 절차를 완료하지 않았습니다` 오류로 로그인 자체가 막힌다. OAuth 동의 화면에서 로그인에 쓸 계정을 테스트 사용자로 반드시 먼저 추가할 것.
- **초기 적재 (Initial Ingestion)**: 첫 실행 시 S&P 500 전 종목의 **최근 5년 치 일봉 데이터**를 수집하여 종목별 `[Ticker].parquet` 파일로 저장 후 드라이브 지정 폴더에 업로드.
- **일별 업데이트**: 매일 신규 데이터를 가져와 기존 파르케 파일 하단에 병합(Concat)하고, 날짜 기준 중복 데이터를 제거(`drop_duplicates`)하여 저장.

### [기능 2] 톰 바소식 추세추종 시그널 & 포지션 사이징 엔진
- **돈천 채널 (Donchian Channel)**: N일 기준(기본값 20일 및 100일 듀얼 셋) 최고가 및 최저가 밴드 계산.
  - *매수 시그널*: 당일 종가가 N일 최고가를 상향 돌파 시 발생.
  - *매도/청산 시그널*: 당일 종가가 최근 최고가 대비 정해진 추적 손절 라인을 하향 돌파 시 발생.
- **ATR (Average True Range)**: 14일 웰스 와일더(Wells Wilder) 이동평균 방식으로 변동성 계산.
- **스톱 오더 및 포지션 사이징 공식**:
  - *진입 이후 최고가 기준 추적 손절 라인*: $\text{최고가} - (3 \times \text{ATR})$
  - *매수 가능 수량*:
    $$\text{매수 수량} = \frac{\text{사용자 설정 총 자산} \times \text{리스크 비율(기본 1%)}}{\text{손절 폭 }(3 \times \text{ATR})}$$

### [기능 3] 뉴스 스크래핑 및 '평온함(Serenity)' LLM 분석
- **뉴스 수집**: 시그널이 발생한 종목 코드를 기반으로 Yahoo Finance 뉴스 RSS피드 혹은 관련 URL 크롤링하여 당일 헤드라인과 요약문 수집.
- **LLM 프롬프트 가이드 (OpenRouter 연동)**:
  > "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. 다음 수집된 [종목 뉴스]를 분석하여 시장의 단기적인 탐욕이나 공포(노이즈)를 철저히 배제하라. 오직 이 뉴스가 장기 추세를 강화하는 팩트인지, 아니면 무시해도 되는 소음인지 평온하고 이성적인 시각으로 요약 브리핑을 작성하라."
- **인증 방식**: OpenRouter API 키(`OPENROUTER_API_KEY`)를 헤더에 담아 OpenAI 호환 `/chat/completions` 엔드포인트로 직접 호출 (별도 SDK 불필요).
- **모델**: 기본값은 무료 티어 `nvidia/nemotron-3-nano-30b-a3b:free`. 무료 모델은 요청 빈도 제한/가용성 변동이 있을 수 있으므로, 브리핑 생성 실패 시 재시도 없이 스킵하고 다음 종목으로 진행할 것.

### [기능 4] Streamlit 웹 대시보드 및 챗봇 인터페이스
- **화면 구성**:
  - **Tab 1: 오늘의 시그널**: 금일 장 마감 기준 20일/100일 상방 돌파 매수 추천 종목 리스트, 각 종목의 현재 ATR 값, 추천 매수 수량 가이드 테이블 시각화.
  - **Tab 2: 평온한 어시스턴트 (Chat)**: 사용자가 "오늘 AAPL의 추적 손절가는 얼마야?", "오늘 포지션 사이징 리스크를 2%로 올리면 어떻게 해야 해?"라고 질문하면 가상 DB의 파르케 데이터를 읽어 계산 후 답변하는 LLM 에이전트 창.

---

## 3. 코드 작성 시 주의사항 & 예외 처리 규칙

1. **API 할당량 관리**: yfinance 대량 호출 시 차단 위험을 방지하기 위해 종목 간 `time.sleep(0.5)` 등 미세한 딜레이를 부여할 것.
2. **Parquet I/O 최적화**: 구글 드라이브에서 매번 전체 파일을 다운로드하는 리스크를 줄이기 위해, 당일 조회 빈도가 높은 데이터는 Streamlit 백엔드의 내장 캐시(`st.cache_data`)를 적극 활용할 것.
3. **가짜 돌파 필터**: 가격 돌파 발생 시, 당일 거래량이 '최근 20일 평균 거래량의 1.5배 이상'인 종목만 대시보드 상단에 우선순위로 노출할 것.
4. **LLM 프로바이더 장애 대응**: OpenRouter 무료 티어 모델 호출이 실패해도 전체 배치가 중단되지 않도록, 종목별로 예외를 잡아 로그만 남기고 다음 종목으로 계속 진행할 것.
