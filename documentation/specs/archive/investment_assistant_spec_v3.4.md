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
| v2.3 | 2026-07-18 | **S&P 500 종목 유니버스 동기화(`sync_universe`) 추가.** 기존 일별 업데이트는 Drive에 이미 저장된 티커 목록만 갱신할 뿐 지수 편입/편출을 감지하지 못했음. 매일 업데이트 실행 전 위키피디아의 현재 구성종목과 Drive 저장 목록을 비교해, 신규 편입 종목은 5년치 백필 후 합류시키고 편출 종목은 과거 데이터는 보존하되 활성 목록(`_universe.json`)에서 제외하도록 변경. [기능 1]에 반영. 전체 내용은 [investment_assistant_spec_v2.3.md](investment_assistant_spec_v2.3.md) 참고 |
| v2.4 | 2026-07-18 | **[기능 4] Streamlit 대시보드 착수 (Cloud Run/Scheduler 크론 설정은 결제 계정 미연결로 보류, 수동 버튼 방식으로 대체).** ① 메인 페이지(`app.py`): "S&P 500 검색 & 데이터 적재" 버튼 하나로 `sync_universe`+`run_daily_update`를 수동 실행, 진행 로그 실시간 스트리밍. ② 종목 차트 페이지(`pages/1_종목_차트.py`): 캔들차트 + Donchian/트레일링 스탑 라인 오버레이 + 거래량/ATR 서브플롯, 기본 6개월 표시, 지표 설명, 섹터(GICS Sector, 위키피디아에서 함께 수집해 `_universe.json`에 저장)별 종목 필터, 섹터 선택은 즉시 반영되지만 종목/기간 조회는 폼으로 감싸 버튼 클릭 시에만 렌더링, HTS 스타일(테두리, 우측 세로 범례, unified hover, 등락 색상 표시 가격 헤더). [기능 4]에 반영. 전체 내용은 [investment_assistant_spec_v2.4.md](investment_assistant_spec_v2.4.md) 참고 |
| v2.5 | 2026-07-18 | **대표 자산군 추세추종 확장 + LLM 매매 추천 + 과거 시그널 마킹 + UI 3탭 재구성.** ① [기능1]: S&P 500 지수 자체(및 금/미국채/원자재)는 직접 거래가 불가능하므로 유동성 높은 ETF 프록시(SPY/GLD/TLT/DBC)를 S&P 500 편입/편출 로직과 분리해 별도로 수집·관리(`data_fetcher.ASSET_CLASS_TICKERS`, `run_asset_class_update`). ② [기능2]: 동일한 Donchian/ATR/트레일링 스탑 규칙이 개별 종목뿐 아니라 자산군 ETF에도 그대로 적용됨을 명시, 볼린저 밴드(20일 SMA±2표준편차, 참고용) 추가, 매수/청산 "최초 발생일"만 표시하는 Buy_Trigger/Sell_Trigger 컬럼 추가. ③ [기능3]: 뉴스 노이즈 필터링 브리핑에 더해, 뉴스+현재 시그널 상태를 함께 근거로 매수/HOLD/매도를 결론 내리는 `generate_recommendation` 추가. ④ [기능4]: 화면을 사이드바 멀티페이지 대신 탭 3개(대표 자산군 분석 / 종목 차트(S&P 500) / 데이터 적재)로 재구성. 두 차트 탭은 공통 렌더러를 공유하며, "조회" 버튼 클릭 시 차트에 과거 매수/청산 시그널 발생일을 삼각형 마커로 표시하고 LLM 매매 추천을 함께 보여줌. 데이터 적재 탭의 버튼은 S&P 500 유니버스 동기화+전종목 갱신+자산군 ETF 갱신을 한 번에 실행(`run_full_collection`). [기능1~4] 전체 갱신. 전체 내용은 [investment_assistant_spec_v2.5.md](investment_assistant_spec_v2.5.md) 참고 |
| v2.6 | 2026-07-19 | **탭1 콘텐츠 보강 + LLM 캐싱/투명성 강화 + 자산군 대폭 확장.** ① [기능4]: 탭1에 프로그램 목표 및 톰 바소 철학 설명을 추가하고, 지표 설명 표를 각 차트 하단(반복 노출)에서 탭1 상단(한 곳)으로 이동. ② [기능3]: `generate_recommendation` 캐시 TTL을 1시간→24시간으로 강화해 LLM 과다 호출 방지, 분석에 사용된 뉴스 기사를 카드(제목/링크/발행처·시각/요약) 형태로 함께 표시. ③ [기능1]: 뉴스 기사를 Drive에 날짜별 아카이브(`_news_{date}.json`, `news_fetcher.archive_news`)로 저장 — 기사 링크(없으면 제목) 기준 중복 적재 방지. ④ [기능1]: 대표 자산군을 4종 → 10종으로 확장 — 비트코인(`BTC-USD`), 미국 중기국채/7-10년물(`IEF`) 신규 추가, 원자재를 `DBC`(종합) 외 `USO`(원유)/`UNG`(천연가스)/`DBA`(농산물)/`CPER`(구리)로 세분화. `ASSET_CLASS_TICKERS`가 `{티커: {label, category}}` 구조로 변경되고, 탭1 UI도 탭2의 섹터→종목 패턴과 동일하게 카테고리(주식/암호화폐/귀금속/채권/원자재) → 세부 종목 2단계 선택으로 개편. [기능1·3·4] 전체 갱신. 전체 내용은 [investment_assistant_spec_v2.6.md](investment_assistant_spec_v2.6.md) 참고 |
| v2.7 | 2026-07-19 | **탭 구조 재편(소개 탭 신설) + 뉴스 수집을 Exa API로 전환.** ① [기능4]: 화면을 4탭(소개 / 대표 자산군 분석 / 종목 차트(S&P 500) / 데이터 적재)으로 재편. 프로그램 목표·톰 바소 철학·지표 설명을 분석 기능이 없는 별도 "소개" 탭으로 분리하고(v2.6에서 "대표 자산군 분석" 탭에 섞여있던 것을 이동), 실제 지표 분석은 2번째 탭부터 시작하도록 정리. 페이지 최상단의 앱 전체 제목(`st.title`)은 삭제(탭 안 헤더로는 유지). ② [기능3]: 뉴스 수집을 yfinance 내장 피드에서 **Exa 검색 API**(`news_fetcher.fetch_ticker_news_exa`, `category: "news"`, 최근 7일 기본)로 전환 — LLM 매매 추천(`get_recommendation`)이 이제 이 함수를 호출한다. 응답 형식은 기존과 동일(title/summary/publisher/link/published_at)하게 매핑해 뉴스 카드 표시·Drive 아카이빙 등 다운스트림 로직은 변경 없음. `publisher`는 Exa 응답의 `author`가 없으면 기사 URL 도메인으로 대체. [기능3·4] 전체 갱신. 전체 내용은 [investment_assistant_spec_v2.7.md](investment_assistant_spec_v2.7.md) 참고 |
| v2.8 | 2026-07-19 | **자동화 인프라(GitHub Actions + Telegram) 전체 구축, LLM 장애 내성 강화, 종목 설명 추가, 차트 한글 깨짐/기간 수정, 데드 코드 정리.** 새 [기능 5] 섹션으로 정리. 핵심: ① GCP Cloud Run/Scheduler 대신 **GitHub Actions**(`collect.yml`+`recommend.yml`, `workflow_run`으로 연쇄)로 실제 무인 자동화 완성 — 데이터 신선도 게이트(`_is_data_fresh`, 4일)로 "워크플로는 성공했지만 개별 종목만 조용히 실패"한 경우를 걸러냄. ② 매수/HOLD/매도 판정을 `signal_engine.get_mechanical_action`으로 완전히 결정론화(네트워크 호출 없음) — HOLD인 날은 뉴스/LLM 호출을 아예 생략해 API 사용량과 rate limit 위험을 크게 줄이고, 매수/매도인 날 LLM 호출이 실패해도 `_build_rule_based_explanation`으로 폴백해 판정 자체는 절대 유실되지 않도록 함(실제 429 상황에서 검증). ③ **텔레그램 알림**(`telegram_notifier.py`) 추가 — 크론에서만 발동, 전체 요약 텍스트 + 매수/매도 종목만 차트 이미지 첨부. ④ 종목별 설명 추가 — 자산군 10종은 큐레이션, S&P 500 503종목은 위키피디아에서 이미 긁던 데이터(회사명+GICS 세부업종)를 `_universe.json`에 재활용 저장, Streamlit 양쪽 탭과 텔레그램 모두에 노출. ⑤ 텔레그램 차트 한글 깨짐 수정(kaleido가 헤드리스 Chromium으로 렌더링하는데 Ubuntu 러너에 한글 폰트가 없어 발생 — `fonts-nanum` 설치 + 명시적 폰트 패밀리 지정) 및 전체 히스토리 대신 **최근 6개월**만 표시하도록 수정. ⑥ 코드 리팩토링: `chart_builder.py`로 차트 생성 로직 통합(`slice_to_period` 공용화로 Streamlit/텔레그램 기간 슬라이싱 중복 제거), 완전히 대체되어 아무도 호출하지 않던 `news_fetcher.fetch_ticker_news`(yfinance)·`fetch_news_for_tickers`·`openrouter_briefing.generate_briefings` 삭제. [기능1~5] 전체 갱신. 전체 내용은 [investment_assistant_spec_v2.8.md](investment_assistant_spec_v2.8.md) 참고 |
| v2.9 | 2026-07-19 | **텔레그램 일일 요약을 표 형태로 재구성.** Telegram Bot API는 `MarkdownV2`/`HTML`/레거시 `Markdown` 어느 parse_mode에서도 GFM 테이블 문법이나 HTML `<table>`을 렌더링하지 않는다 — 실질적으로 가능한 표 형태는 등폭 서체 코드블록(`` ``` ``) 안에 컬럼을 정렬하는 방법뿐이다. `telegram_notifier.format_summary`를 종목별 문장 나열(이모지+굵게 액션+종가+설명) 대신, 티커/구분(카테고리)/액션/종가 4열 표로 재작성 — 한글(매수/매도)과 영문(HOLD)이 섞여도 어긋나지 않도록 `unicodedata.east_asian_width`로 전각 문자를 2칸으로 계산해 정렬(`_display_width`/`_pad`). 이모지는 열 폭이 클라이언트마다 달라 행 안에 넣으면 정렬이 깨지므로 표 밖 범례 한 줄(🟢 매수 ⚪ HOLD 🔴 매도)로만 사용. 종목 설명은 표에서 제거(매수/매도 종목은 어차피 차트 이미지 캡션에 설명이 포함됨) — 대신 짧은 카테고리(주식/암호화폐/귀금속/채권/원자재)를 표시. 실제 텔레그램 앱에서 정렬 확인 완료. [기능 5] 갱신. 전체 내용은 [investment_assistant_spec_v2.9.md](investment_assistant_spec_v2.9.md) 참고 |
| v3.0 | 2026-07-19 | **자산군 10종 통합 일일 리포트(LLM 종합 해설 포함)를 GitHub Pages로 공개 발행.** ① 새 `report_builder.py`: 그날의 판정 결과로 HTML 리포트 1장을 생성 — 상단에 LLM 교차 자산 총평(`openrouter_briefing.generate_portfolio_overview`, "미스터 세레니티" 톤으로 여러 자산군에 걸친 동시 시그널만 담백하게 짚고 전망은 배제, 판정 자체는 절대 바꾸지 않는 해설 전용), 티커/자산/구분/액션/종가 요약 표, 10종목 전체의 캔들차트(Plotly `fig.to_html()`로 임베드 — 브라우저가 클라이언트에서 렌더링). ② 리포트는 Drive에 `_report_{date}.html`로도 저장되고(Streamlit "리포트 히스토리" 탭이 재계산 없이 다시 보여줌), `docs/reports/{date}.html`로도 로컬에 기록되어 `recommend.yml`이 커밋+푸시 — **GitHub Pages**(저장소 Settings에서 `master` 브랜치 `/docs` 폴더로 활성화, `https://garam827.github.io/ai_invest_assistant/`)가 이 파일을 그대로 공개 URL로 서빙한다. ③ 텔레그램은 이제 종목별 차트 이미지를 따로 첨부하지 않고, 표 요약 메시지 끝에 리포트 URL 링크 한 줄만 추가 — 하루 메시지 수가 최대 6건에서 1건으로 줄었다. ④ **kaleido/헤드리스 Chromium 렌더링 전면 제거**: 차트가 더 이상 정적 PNG로 서버 렌더링되지 않고 브라우저(Streamlit UI, GitHub Pages 리포트 페이지 모두)에서 JS로 렌더링되므로, v2.8~v2.9의 CJK 폰트 설치 문제 자체가 사라짐 — `recommend.yml`의 `fonts-nanum` 설치 스텝과 `requirements.txt`의 `kaleido` 의존성을 삭제. ⑤ Streamlit에 새 탭 **"리포트 히스토리"** 추가(날짜 선택 → 저장된 리포트를 `st.iframe`으로 그대로 표시). [기능 1·3·4·5] 전체 갱신. 전체 내용은 [investment_assistant_spec_v3.0.md](investment_assistant_spec_v3.0.md) 참고 |
| v3.1 | 2026-07-19 | **매수/매도 종목의 뉴스+LLM 분석을 리포트에 노출, 접이식 UI로 재구성.** `recommendation_engine.get_recommendation_for_ticker`가 매수/매도 종목에 한해 이미 Exa 뉴스를 수집하고 LLM 서술 분석을 만들고 있었는데([기능 3]), `report_builder.py`는 그 결과(`results[ticker]['news']`/`['text']`)를 전혀 쓰지 않고 버리고 있었다 — 이번 버전에서 그대로 리포트에 노출시켰다(뉴스 API를 새로 호출하지 않고 이미 계산된 값을 재사용). ① 매수/매도 종목마다 "시그널 카드"(`<section class="signal-card">`)를 만들어 액션 배지·LLM(또는 규칙 기반 폴백) 분석 텍스트·참고 뉴스 카드(제목·링크·발행처·요약)를 표시. ② 페이지 비대화 대응: 각 카드의 차트는 `<details>` 접이식 위젯 안에 넣어 기본은 접힌 상태로 시작하고, HOLD 종목(뉴스/분석 없음)은 개별 카드 대신 페이지 하단의 접힌 "HOLD 종목 차트" 블록 하나로 묶었다. ③ 요약 표의 매수/매도 티커 셀이 해당 시그널 카드로 점프하는 앵커 링크가 됨. ④ LLM 출력·Exa 기사 제목/요약처럼 외부에서 온 텍스트는 모두 `html.escape`로 이스케이프해 리포트에 삽입(꺾쇠괄호 등이 포함된 LLM 응답이 마크업을 깨뜨리지 않도록). 실제 GitHub Pages URL에서 시그널 카드 10개·뉴스 카드 25개 정상 렌더링 확인. [기능 3·5] 갱신. 전체 내용은 [investment_assistant_spec_v3.1.md](investment_assistant_spec_v3.1.md) 참고 |
| v3.2 | 2026-07-20 | **대표 자산군에 나스닥(`QQQ`) 추가 (10종 → 11종).** `data_fetcher.ASSET_CLASS_TICKERS`에 `QQQ`(나스닥 100 추종 ETF, 기술주 비중 높음, "주식" 카테고리 — `SPY`와 동일 카테고리)를 추가. S&P 500 지수 자체를 `SPY`로 추적하는 것과 동일한 논리로, 나스닥 지수 역시 원지수 대신 유동성 높은 ETF 프록시(`QQQ`)로 추적한다. `ASSET_CLASS_TICKERS` 딕셔너리 값 추가 외에 다른 코드 변경은 필요 없었다 — 수집(`run_asset_class_update`)·시그널·추천·리포트·텔레그램·Streamlit UI(카테고리 셀렉트박스 포함) 전부 이 딕셔너리를 기준으로 동작하도록 이미 설계돼 있었기 때문(`data_fetcher._update_one_ticker`가 신규 티커도 자동으로 5년치 백필). [기능 1] 갱신. 전체 내용은 [investment_assistant_spec_v3.2.md](investment_assistant_spec_v3.2.md) 참고 |
| v3.3 | 2026-07-20 | **리포트 PC 여백 개선 + Exa 뉴스 검색어를 매크로 지향으로 교체.** ① [기능 5]: `report_builder.py`의 리포트 컨테이너 `max-width`를 1000px → 1400px(`width: 94%`)로 넓히고, 뉴스 카드를 세로 나열 대신 반응형 그리드(`grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))`)로 배치 — 데스크톱 화면에서 좌우 여백이 과도했던 문제와, 넓어진 공간을 그냥 비워두지 않고 카드가 자동으로 여러 열로 배치되게 함께 해결. ② [기능 3]: `ASSET_CLASS_TICKERS`의 각 자산군 항목에 `news_query`(영문, 매크로 지향 검색어) 필드를 추가하고, `recommendation_engine.get_recommendation_for_ticker`가 뉴스 수집 시 티커 대신 이 쿼리를 우선 사용하도록 변경. 문제였던 것: `GLD stock news`처럼 티커 그대로 검색하면 "GLD 몇 % 하락"류의 단순 가격 기사나 시세 페이지만 나오고, 그 등락의 배경(금리·달러·중앙은행 수요 등)을 설명하는 뉴스는 거의 안 나왔음 — `gold price outlook macro drivers analysis`처럼 프록시가 추종하는 실물 자산 이름 + 매크로 키워드로 바꾸자 Fed 금리·중앙은행 금 매입·지정학 리스크 등 실제 유용한 기사로 대체됨(로컬 비교 테스트로 확인). S&P 500 개별 종목처럼 `news_query`가 없는 경우는 기존 그대로 `"{티커} stock news"`를 쓴다(티커 자체가 회사이므로 문제 없음). [기능 3·5] 갱신. 전체 내용은 [investment_assistant_spec_v3.3.md](investment_assistant_spec_v3.3.md) 참고 |
| v3.4 | 2026-07-20 | **리포트 여백 추가 개선 — v3.3의 1400px도 넓은 모니터에서는 여전히 부족하다는 피드백.** `body`의 `max-width` 자체를 없애고(`max-width: none`) `width: 97%`만으로 화면 폭에 맞춰 거의 끝까지 늘어나게 변경 — 표·차트·뉴스 그리드는 이제 컨테이너 폭 제한이 없다. 다만 총평(`.overview`)·개별 분석(`.analysis`) 문단은 너무 넓으면 한 줄이 지나치게 길어져 가독성이 떨어지므로 `max-width: 900px`로 별도 제한 — "표/차트/뉴스는 화면 폭 전부, 긴 글줄은 읽기 편한 폭으로"라는 원칙으로 분리했다. [기능 5] 갱신 |

> 과거 버전 전체 내용은 `investment_assistant_spec_v{N}.md` 파일로 보존합니다. 이 파일(`investment_assistant_spec.md`)은 항상 최신 버전을 담습니다.

---

## 1. 시스템 아키텍처 & 환경 (Architecture)

### 1.1 기술 스택
- **Frontend / Chat UI**: Streamlit
- **Data Source**: yfinance (Yahoo Finance API) — S&P 500 개별 종목 + 대표 자산군 ETF 프록시(아래 [기능 1] 참고)
- **Database (Virtual)**: Google Drive API + Apache Parquet (`.parquet`)
- **LLM Engine**: OpenRouter (기본 모델 `nvidia/nemotron-3-ultra-550b-a55b:free`, `OPENROUTER_MODEL_NAME` 환경변수로 교체 가능)
- **Infrastructure**: **GitHub Actions** — `collect.yml`(장 마감 후 스케줄) + `recommend.yml`(`workflow_run`으로 연쇄 실행)로 완전 자동화됨. 원래 계획은 GCP Cloud Run + Cloud Scheduler였으나 결제 계정 연결 이슈로 보류하다가, 카드 등록 없이 쓸 수 있는 GitHub Actions로 전환해 v2.8에서 실제 배포 완료 (자세한 내용은 [기능 5] 참고). Streamlit 앱은 로컬 실행 또는 별도 호스팅(Streamlit Community Cloud 등, 미착수)이며, 앱 안의 "데이터 적재" 탭 버튼은 크론과 별개로 수동 실행도 가능하게 남겨둔 것.
- **리포트 호스팅**: `recommend.yml`이 매일 생성하는 통합 일일 리포트(자세한 내용은 [기능 5] 참고)는 **GitHub Pages**(저장소 `master` 브랜치 `/docs` 폴더, `https://garam827.github.io/ai_invest_assistant/`)로 공개 발행된다 — v3.0에서 도입, 별도 계정/과금 없이 GitHub Actions와 같은 저장소 안에서 해결.
- **알림**: 텔레그램 봇으로 크론 실행 결과(매수/HOLD/매도 요약 표 + 전체 리포트 링크)를 발송 (자세한 내용은 [기능 5] 참고, 설정은 [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md))

### 1.2 데이터 흐름 (Data Flow)
1. **매일 장 마감 후**: GitHub Actions `collect.yml`이 스케줄(평일 22:30 UTC)로 가동.
2. **종목 유니버스 동기화**: 위키피디아의 현재 S&P 500 구성종목과 Drive 저장 목록을 비교(`sync_universe`). 신규 편입 종목은 5년치 백필 후 합류, 편출 종목은 데이터 보존하되 활성 목록에서 제외. 결과(활성/비활성 목록, 섹터, 종목 설명)를 `_universe.json`에 기록.
3. **yfinance API 수집**: 활성 유니버스 전 종목 + 대표 자산군 11종(`ASSET_CLASS_TICKERS` — S&P 500 1종/나스닥 1종/비트코인 1종/금 1종/미국 장·중기국채 2종/원자재 5종)의 당일 OHLCV 데이터를 수집.
4. **구글 드라이브 가상 DB 적재**: OAuth 사용자 인증(캐싱된 토큰)을 통해 지정 폴더 내 `[Ticker].parquet` 파일에 당일 데이터를 Append 및 중복 제거(Upsert).
5. **`collect.yml` 성공 시 `recommend.yml`이 `workflow_run`으로 자동 연쇄 실행**. 대표 자산군 11종에 한해(S&P 500 개별 종목 제외):
   a. **신선도 게이트**: 종목별 마지막 저장일이 4일 이상 지났으면 그 종목은 건너뜀(부분 실패 대응).
   b. **시그널 엔진 작동 + 기계적 판정**: Donchian Channel/ATR을 계산해 `signal_engine.get_mechanical_action`으로 매수/HOLD/매도를 네트워크 호출 없이 결정론적으로 산출.
   c. **HOLD면 여기서 종료** (뉴스/LLM 호출 없음). **매수/매도면**: Exa API로 최근 뉴스를 수집하고 OpenRouter LLM(Nemotron)에 뉴스+시그널 상태를 근거로 서술형 설명을 요청 — 실패하면 규칙 기반 설명으로 자동 대체(판정 자체는 항상 확정됨).
   d. **통합 일일 리포트 생성 (`report_builder.py`, v3.0)**: 11종목 전체 요약 표 + LLM 교차 자산 총평(`generate_portfolio_overview`) + 종목별 캔들차트를 HTML 한 장으로 합쳐, Drive(`_report_{date}.html`)와 로컬 `docs/reports/{date}.html`에 저장.
   e. **GitHub Pages 발행**: `recommend.yml`이 `docs/reports/{date}.html`을 커밋+푸시 — 저장소에 미리 연결해 둔 GitHub Pages가 그 커밋을 자동 반영해 `https://garam827.github.io/ai_invest_assistant/reports/{date}.html`로 공개.
   f. **텔레그램 발송**: 11종목 전체를 티커/구분/액션/종가 표로 정리한 요약 텍스트(v2.9, 등폭 코드블록) + 위 리포트 URL 링크를 한 메시지로 발송(v3.0부터 종목별 차트 이미지 첨부는 하지 않음 — 차트는 링크된 리포트 안에 이미 다 있음).
6. **사용자 UI**: Streamlit 대시보드에서 대표 자산군/S&P 500 개별 종목을 언제든 대화형으로 조회·분석(크론과 별개, 텔레그램 미발송). "리포트 히스토리" 탭에서는 Drive에 저장된 과거 통합 리포트를 재계산 없이 그대로 다시 볼 수 있다.

---

## 2. 세부 기능 개발 가이드라인 (Vibe Coding용)

### [기능 1] 구글 드라이브 연동 및 데이터 수집 엔진
- **인증 방식**: OAuth 사용자 인증(데스크톱 앱 클라이언트, `client_secret.json`)으로 사용자 본인 구글 계정에 최초 1회 동의를 받고, 발급된 리프레시 토큰을 `token.json`에 캐싱하여 이후 무인 재인증. (서비스 계정 키는 조직 정책 `iam.disableServiceAccountKeyCreation`으로 발급이 차단되어 사용 불가 — 상세 배경 및 설정 절차는 [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md) 참고)
- **알려진 함정**: OAuth 동의 화면이 "테스트" 게시 상태일 때, 로그인하려는 구글 계정이 "테스트 사용자" 목록에 등록되어 있지 않으면 `액세스 차단됨: <앱 이름>은(는) Google 인증 절차를 완료하지 않았습니다` 오류로 로그인 자체가 막힌다. OAuth 동의 화면에서 로그인에 쓸 계정을 테스트 사용자로 반드시 먼저 추가할 것.
- **초기 적재 (Initial Ingestion)**: 첫 실행 시 S&P 500 전 종목의 **최근 5년 치 일봉 데이터**를 수집하여 종목별 `[Ticker].parquet` 파일로 저장 후 드라이브 지정 폴더에 업로드.
- **일별 업데이트**: 매일 신규 데이터를 가져와 기존 파르케 파일 하단에 병합(Concat)하고, 날짜 기준 중복 데이터를 제거(`drop_duplicates`)하여 저장. 조회 시작일은 "오늘 기준 N일 전"이 아니라 **해당 종목에 저장된 마지막 날짜 기준 N일 전**으로 잡는다 — 크론이 며칠 못 돌았어도 다음 성공 실행이 그 갭을 전부 다시 채우는 자가 치유 구조.
- **종목 유니버스 동기화 (S&P 500 편입/편출 대응)**: 일별 업데이트 실행 전 `sync_universe`가 위키피디아 최신 구성종목과 Drive 저장 목록을 diff한다.
  - *신규 편입*: Drive에 파일이 없는 종목은 `run_initial_ingestion`으로 5년치를 먼저 백필한 뒤 활성 목록에 포함 (Donchian 100일/ATR 계산에 필요한 히스토리 확보 목적).
  - *편출*: 더 이상 S&P 500이 아닌 종목은 **Parquet 파일을 삭제하지 않고 보존**(과거 데이터 리서치 가치)하되, 활성 목록에서 제외하여 이후 일별 업데이트와 시그널 스캔 대상에서 빠지게 한다.
  - 결과는 Drive 폴더 내 `_universe.json`(`active_tickers`, `inactive_tickers`, `sectors`, `descriptions`, `synced_at`)에 기록되며, 이후 모든 일별 업데이트/시그널 대시보드는 `list_tickers()`가 아니라 이 `active_tickers`를 종목 유니버스의 기준으로 삼는다. `sectors`는 위키피디아 테이블의 GICS Sector 컬럼을 함께 수집한 종목→섹터 매핑으로, Streamlit 종목 차트 페이지의 섹터 필터에 쓰인다. `descriptions`는 아래 자산군 설명 항목 참고.
- **대표 자산군 ETF/현물 수집 (S&P 500 개별 종목 외 자산군 확장)**: S&P 500 지수, 나스닥 지수, 비트코인, 금, 미국 국채, 원자재는 원지수·현물을 직접 거래할 수 없거나(또는 거래량 데이터가 부실하거나) yfinance에서 안정적으로 조회하기 어려운 경우가 있어, 유동성이 높고 거래량 데이터가 확실한 **ETF(또는 BTC-USD 현물) 프록시**로 대신 추적한다.
  | 카테고리 | 자산 | 티커 |
  | --- | --- | --- |
  | 주식 | S&P 500 (미국 대형주) | `SPY` |
  | 주식 | 나스닥 100 (Nasdaq-100, 기술주 비중 높음) | `QQQ` |
  | 암호화폐 | 비트코인 | `BTC-USD` |
  | 귀금속 | 금 (Gold) | `GLD` |
  | 채권 | 미국 장기국채 (20년+) | `TLT` |
  | 채권 | 미국 중기국채 (7-10년) | `IEF` |
  | 원자재 | 원자재 종합 (Broad Commodities) | `DBC` |
  | 원자재 | 원유 (Crude Oil) | `USO` |
  | 원자재 | 천연가스 (Natural Gas) | `UNG` |
  | 원자재 | 농산물 (Agriculture) | `DBA` |
  | 원자재 | 구리 (Copper) | `CPER` |
  - `data_fetcher.ASSET_CLASS_TICKERS`에 `{티커: {"label": 표시명, "category": 카테고리, "description": 한 줄 설명}}` 구조의 고정 목록(11종 모두 큐레이션된 설명 포함)으로 관리하며, `run_asset_class_update`가 초기 백필/일별 업데이트를 S&P 500과 동일한 로직(`_update_one_ticker`)으로 처리한다.
  - S&P 500 개별 종목의 설명은 별도 큐레이션 없이, `sync_universe`가 위키피디아 테이블에서 이미 긁고 있는 **Security(회사명)** + **GICS Sub-Industry(세부업종)** 컬럼을 `"{회사명} ({세부업종})"` 형식으로 조합해 `_universe.json`의 `descriptions`에 함께 저장한다 (추가 요청 없이 기존 수집 데이터 재활용). Streamlit 종목 차트 탭과 [기능 5]의 통합 일일 리포트 요약 표 모두 이 설명을 부제/자산명으로 노출한다.
  - S&P 500 편입/편출 diff 대상(`sync_universe`)에서는 명시적으로 제외한다 — 이 자산들은 애초에 S&P 500 구성종목이 아니므로, 제외하지 않으면 매번 "편출 종목"으로 잘못 분류된다.
  - 원자재는 `DBC`(종합) 하나만으로는 개별 원자재 등락을 알 수 없어, 에너지(원유·천연가스)·농산물·산업금속(구리) 대표 종목으로 세분화했다. 구리는 경기 선행지표로도 흔히 참고된다.
- **뉴스 아카이브 (`news_fetcher.archive_news`)**: LLM 매매 추천에 사용된 뉴스 기사를 Drive에 **날짜별 JSON 파일**(`_news_{YYYY-MM-DD}.json`, `{티커: [뉴스, ...]}` 구조)로 저장한다. 기사 **링크**(없으면 제목)를 키로 중복을 검사해, 같은 날 같은 기사를 이미 저장했다면 다시 적재하지 않는다. `DriveDB.load_json`/`save_json`(범용 JSON 메타데이터 저장, `_universe.json`과 동일한 메커니즘)을 재사용해 별도 저장소 계층 추가 없이 구현.

### [기능 2] 톰 바소식 추세추종 시그널 & 포지션 사이징 엔진
`signal_engine.py`는 종목 유형을 가리지 않는 순수 계산 엔진이다 — OHLCV 데이터프레임만 주어지면 개별 S&P 500 종목이든 대표 자산군 ETF/현물(`ASSET_CLASS_TICKERS`, [기능 1] 참고)이든 동일한 규칙을 그대로 적용한다. S&P 500 지수 자체에 대한 추세추종 매매 전략도, 나아가 비트코인·채권·원자재에 대한 전략도 이런 방식(유동성 높은 프록시 + 동일 규칙)으로 세울 수 있다는 것이 v2.5~v2.6의 결론이다.

- **돈천 채널 (Donchian Channel)**: N일 기준(기본값 20일 및 100일 듀얼 셋) 최고가 및 최저가 밴드 계산.
  - *매수 시그널*: 당일 종가가 N일 최고가를 상향 돌파 시 발생.
  - *매도/청산 시그널*: 당일 종가가 최근 최고가 대비 정해진 추적 손절 라인을 하향 돌파 시 발생.
- **ATR (Average True Range)**: 14일 웰스 와일더(Wells Wilder) 이동평균 방식으로 변동성 계산.
- **볼린저 밴드 (Bollinger Bands, 참고용 보조 지표)**: 20일 SMA ± 2표준편차. 매수/매도 규칙에 직접 관여하지 않고, 차트에서 단기 과매수/과매도·변동성 스퀴즈를 참고하는 용도로만 표시.
- **매수/청산 "최초 발생일" 마킹**: 돌파/청산 조건은 추세가 지속되는 동안 여러 날 연속으로 참(True)일 수 있어, 매일 반복 표시하면 차트가 지저분해진다. `Buy_Trigger`/`Sell_Trigger` 컬럼은 그 조건이 전날 대비 새로 발생한 날에만 참이 되도록 계산하여, 차트에 "언제 진입/청산했으면 좋았을지"를 과거 데이터 위에 마커로 표시하는 데 쓰인다.
- **스톱 오더 및 포지션 사이징 공식**:
  - *진입 이후 최고가 기준 추적 손절 라인*: $\text{최고가} - (3 \times \text{ATR})$
  - *매수 가능 수량*:
    $$\text{매수 수량} = \frac{\text{사용자 설정 총 자산} \times \text{리스크 비율(기본 1%)}}{\text{손절 폭 }(3 \times \text{ATR})}$$

### [기능 3] 뉴스 스크래핑 및 '평온함(Serenity)' LLM 분석
- **뉴스 수집 (Exa API)**: 분석 대상 종목/자산의 최근 뉴스를 **Exa 검색 API**(`https://api.exa.ai/search`, `news_fetcher.fetch_ticker_news_exa`)로 수집한다. 쿼리는 기본 `"{티커} stock news"`, `category: "news"`로 뉴스 사이트에 한정, 기본 최근 7일(`config.EXA_NEWS_LOOKBACK_DAYS`)로 검색하고 `contents.summary`로 요약도 함께 받는다. 응답의 `author`가 없으면 기사 URL 도메인을 발행처로 대체한다. 인증은 `x-api-key` 헤더에 `EXA_API_KEY`. (이전에는 yfinance 내장 뉴스 피드를 썼으나 v2.7에서 Exa로 전환, v2.8에서 옛 `news_fetcher.fetch_ticker_news`/`fetch_news_for_tickers`를 코드에서 완전히 삭제했다.)
  - **자산군 프록시는 매크로 지향 쿼리로 대체 (v3.3)**: `ASSET_CLASS_TICKERS`의 각 항목에 `news_query`(영문) 필드가 있으면 `recommendation_engine`이 티커 대신 이 쿼리로 검색한다. `"GLD stock news"`처럼 ETF 티커 그대로 검색하면 "GLD 몇 % 하락"류의 단순 가격/시세 기사만 나오고 그 등락을 설명하는 매크로 뉴스는 거의 안 나오기 때문 — `"gold price outlook macro drivers analysis"`처럼 프록시가 추종하는 실물 자산 이름 + 매크로 키워드로 바꾸면 금리·중앙은행 수요·지정학 리스크 등 실제로 추세 판단에 쓸 만한 기사가 나온다(로컬 비교 테스트로 확인). S&P 500 개별 종목처럼 `news_query`가 없는 티커는 그대로 `"{티커} stock news"`를 쓴다 — 티커 자체가 회사이므로 문제가 없다.
- **LLM 프롬프트 가이드 (OpenRouter 연동)**:
  > "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. 다음 수집된 [종목 뉴스]를 분석하여 시장의 단기적인 탐욕이나 공포(노이즈)를 철저히 배제하라. 오직 이 뉴스가 장기 추세를 강화하는 팩트인지, 아니면 무시해도 되는 소음인지 평온하고 이성적인 시각으로 요약 브리핑을 작성하라."
- **인증 방식**: OpenRouter API 키(`OPENROUTER_API_KEY`)를 헤더에 담아 OpenAI 호환 `/chat/completions` 엔드포인트로 직접 호출 (별도 SDK 불필요).
- **모델**: 기본값은 무료 티어 `nvidia/nemotron-3-ultra-550b-a55b:free`. 무료 모델은 요청 빈도 제한/가용성 변동이 있을 수 있으므로, 브리핑 생성 실패 시 재시도 없이 스킵하고 다음 종목으로 진행할 것.
- **매매 추천 (`generate_recommendation`, Streamlit 차트 탭과 [기능 5]의 일일 리포트 양쪽에서 사용)**: 뉴스 노이즈 필터링 브리핑과는 별도로, 뉴스 + 현재 시그널 상태(종가, ATR, 20일/100일 돌파 여부, 트레일링 스탑, 청산 시그널, 거래량 급증 여부)를 함께 프롬프트에 담아 **매수 / HOLD / 매도** 중 하나를 결론으로 요구한다.
  - 시스템 프롬프트는 "뉴스의 감정이나 예측으로 판단하지 말고, 시그널 상태와 뉴스가 그 추세를 뒷받침하는 팩트인지만 걸러 규칙에 따라 결론 내려라"로 고정되어, 순수 뉴스 브리핑과 동일하게 노이즈를 배제하는 톤을 유지한다.
  - 응답 첫 줄은 반드시 `추천: 매수` / `추천: HOLD` / `추천: 매도` 형식으로 시작하도록 지시하고, 코드에서 정규식으로 파싱해 UI에 색상(초록/회색/빨강) 배지로 표시한다. 파싱 실패 시 안전하게 `HOLD`로 처리.
  - Streamlit에서는 종목 차트의 "조회" 버튼을 누를 때 함께 실행되며, 매 rerun마다 재호출되지 않도록 `(티커, 최신 데이터 날짜)`를 캐시 키로 하고 **TTL 24시간**으로 캐싱한다 — `st.tabs`는 보이지 않는 탭의 코드도 매 rerun마다 실행되므로, 이 캐싱이 없으면 다른 탭에서의 조작만으로도 LLM이 반복 호출된다.
  - 분석에 사용한 뉴스 기사는 카드(제목·링크, 발행처·발행시각, 요약) 형태로 표시하고(Streamlit UI, 그리고 v3.1부터는 크론이 만드는 일일 리포트의 매수/매도 시그널 카드에도 동일하게), 동시에 Drive에 날짜별로 아카이브한다 ([기능 1]의 `news_fetcher.archive_news` 참고) — 무엇을 근거로 그 추천이 나왔는지 사후에 검증 가능하도록. 크론 경로(`recommendation_engine.run_asset_class_recommendations`)에서 계산된 `text`/`news`는 `results` 딕셔너리에 담겨 그대로 `report_builder.py`로 전달되므로, 리포트를 만들기 위해 뉴스/LLM을 다시 호출하지는 않는다.

### [기능 4] Streamlit 웹 대시보드 및 챗봇 인터페이스
단일 페이지(`app.py`)에 `st.tabs`로 화면을 구분한다 (사이드바 멀티페이지 `pages/` 구조는 v2.5에서 제거 — 사용자가 명시적으로 페이지 대신 탭을 요청). 페이지 최상단의 앱 전체 제목(`st.title`)은 v2.7에서 삭제했다 — "소개" 탭 안의 헤더로만 남아있다.

**탭 1: 소개 (구현 완료)** — 분석 기능 없이 설명만 제공. 실제 지표 분석은 탭 2부터 시작한다.
- **이 프로그램에 대하여** (프로그램 목표 + 톰 바소 투자 철학 설명, expander로 항상 펼쳐진 상태)
- **사용된 지표 설명** (`st.table`, [기능 2]의 지표들 — 개별 차트마다 반복 표시하지 않고 이 탭에서만 한 번 제공)

**탭 2: 대표 자산군 분석 (구현 완료)** — S&P 500·나스닥 자체(및 비트코인/금/미국채/원자재)에 대한 추세추종 전략. [기능 1]의 `ASSET_CLASS_TICKERS`를 카테고리(주식/암호화폐/귀금속/채권/원자재) → 세부 종목 2단계로 선택(탭 3의 섹터→종목 패턴과 동일). 카테고리 변경은 즉시 반영되고, 세부 종목·기간 선택 후 "조회"를 눌러야 차트가 렌더링된다.

**탭 3: 종목 차트 (S&P 500) (구현 완료)** — 개별 종목 상세 뷰. 섹터(GICS Sector) → 종목 → 표시 기간(기본 6개월) 순으로 선택. 섹터 변경은 즉시 종목 목록에 반영되지만, 실제 조회(Drive 로드 + 지표 계산 + 차트 렌더링)는 폼으로 감싸 "조회" 버튼을 눌러야만 실행됨(불필요한 재계산 방지). 지표 설명은 탭 1에만 있고 이 탭에서는 반복하지 않는다.

탭 2·탭 3은 동일한 차트 렌더러(`render_ticker_chart`)를 공유한다:
- 캔들차트(plotly) 위에 볼린저 밴드(음영), Donchian 20일/100일 밴드, 트레일링 스탑을 라인으로 오버레이. 거래량(급증일 강조)과 ATR은 스케일이 달라 별도 서브플롯으로 분리.
- **과거 매수/청산 시그널 마킹**: `Buy_Trigger`/`Sell_Trigger`가 참인 날에 초록 세모(▲)/빨간 세모(▼) 마커를 표시해, 과거 데이터 위에서 톰 바소 규칙대로라면 언제 매수·청산했을지 시각적으로 보여줌.
- 상단에 종목명(또는 자산군명)·부제(섹터 또는 자산군 설명)·현재가(전일 대비 등락 색상 표시)·ATR·트레일링 스탑·오늘 시그널 요약.
- **LLM 매매 추천**: "조회" 버튼을 누르면 차트 렌더링과 함께 `openrouter_briefing.generate_recommendation`이 그 종목의 당일 뉴스 + 현재 시그널 상태를 근거로 매수/HOLD/매도를 추천하고, 색상 배지(초록/회색/빨강)와 근거 텍스트로 표시. `(티커, 최신 날짜)` 기준, TTL 24시간으로 캐싱되어 동일 데이터에 대해 반복 호출되지 않음.
- **분석에 사용된 뉴스 카드**: 추천 아래에 근거로 쓰인 뉴스 기사를 카드(제목·링크, 발행처·발행시각, 요약)로 나열. 같은 뉴스는 Drive에도 날짜별로 아카이브됨([기능 1]/[기능 3] 참고).
- HTS(홈트레이딩시스템) 스타일: 차트 테두리, 우측 세로 범례, 마우스 오버 시 크로스헤어형 통합 툴팁(`hovermode="x unified"`), 서브플롯 간 여백 확대.

**탭 4: 데이터 적재 (구현 완료, 원래 메인 페이지 위치에서 이동)** — 버튼 하나(`전체 데이터 적재`)로 `run_full_collection`(S&P 500 유니버스 동기화 + 전 종목 갱신 + 자산군 ETF 갱신)을 실행. v2.8부터는 GitHub Actions `collect.yml`이 매일 자동으로 동일 로직을 실행하므로, 이 버튼은 크론과 별개로 원할 때 즉시 갱신하고 싶을 때 쓰는 수동 실행 경로다. 실행 중 로그를 화면에 실시간 스트리밍하고, 완료 시 활성/신규편입/편출/자산군 종목 수를 요약 표시. 완료 후 종목 목록·시세 캐시를 즉시 비워, 같은 세션에서 바로 다른 탭으로 이동해도 새 데이터가 반영됨.

**탭 5: 리포트 히스토리 (구현 완료, v3.0 신설)** — 크론이 매일 Drive에 저장하는 통합 일일 리포트(`_report_{date}.html`, [기능 5] 참고)를 날짜 선택(`st.selectbox`) 후 `st.iframe`으로 그대로 렌더링. 재계산 없이 저장된 HTML을 그대로 보여주는 것이라 가볍다. 날짜 목록은 `st.cache_data(ttl=3600)`, 리포트 본문은 `st.cache_data(ttl=86400)`로 캐싱(과거 리포트는 다시 바뀌지 않으므로 긴 TTL).

**미구현**:
- **오늘의 시그널 전체 스캔 테이블**: `signal_engine.scan_for_signals`로 전 종목을 한 번에 스캔해 돌파+거래량 급증 종목을 우선순위로 보여주는 테이블 뷰.
- **평온한 어시스턴트 (Chat)**: 사용자가 "오늘 AAPL의 추적 손절가는 얼마야?", "오늘 포지션 사이징 리스크를 2%로 올리면 어떻게 해야 해?"라고 질문하면 가상 DB의 파르케 데이터를 읽어 계산 후 답변하는 LLM 에이전트 창.

### [기능 5] 자동화 인프라 (GitHub Actions) & 텔레그램 알림
원래 계획이던 GCP Cloud Run + Cloud Scheduler는 결제 계정 연결 이슈로 보류되었고, 카드 등록 없이 무료로 쓸 수 있는 **GitHub Actions**로 v2.8에서 실제 무인 자동화를 완성했다. 대표 자산군 11종(`ASSET_CLASS_TICKERS`)에 한해 매일 자동으로 매수/HOLD/매도 판정과 텔레그램 알림까지 수행하며, S&P 500 개별 종목 503개는 데이터 수집만 자동화하고 추천/알림은 Streamlit에서 사용자가 직접 조회한다 (LLM/뉴스 API 사용량을 대표 자산군으로 한정해 비용·rate limit을 관리).

- **워크플로 2개, `workflow_run`으로 연쇄**:
  - `.github/workflows/collect.yml`: 평일 22:30 UTC 스케줄(`cron: "30 22 * * 1-5"`) + `workflow_dispatch`(수동 실행)로 가동. `python data_fetcher.py update` 한 줄로 `sync_universe`+전 종목 갱신+자산군 ETF 갱신을 모두 수행.
  - `.github/workflows/recommend.yml`: `collect.yml`이 **성공적으로 완료됐을 때만**(`workflow_run` + `if: github.event.workflow_run.conclusion == 'success'`) 자동 연쇄 실행되거나, `workflow_dispatch`로 수동 실행 가능. `python recommendation_engine.py`로 대표 자산군 11종의 추천을 생성하고 텔레그램으로 발송.
  - 두 워크플로 공통으로 GitHub 저장소 Secrets 6개(`GOOGLE_OAUTH_CLIENT_SECRET_JSON`, `GOOGLE_OAUTH_TOKEN_JSON`, `DRIVE_FOLDER_ID`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL_NAME`, `EXA_API_KEY`)를 환경변수로 주입하며, `recommend.yml`은 텔레그램 발송을 위해 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 2개를 추가로 주입해 총 8개를 쓴다(`collect.yml`은 6개만).
- **데이터 신선도 게이트 (`recommendation_engine._is_data_fresh`)**: `collect.yml`이 전체적으로는 성공(exit 0)해도, `data_fetcher`의 종목별 `try/except`로 인해 일부 종목만 조용히 실패했을 수 있다. 종목별 마지막 저장일이 오늘 기준 `config.DATA_FRESHNESS_MAX_AGE_DAYS`(기본 4일)를 넘으면 그 종목은 추천 생성을 건너뛰어, 오래된 데이터로 잘못된 매수/매도 판정을 내리는 것을 방지한다.
- **매수/HOLD/매도 판정의 기계화 (`signal_engine.get_mechanical_action`)**: 판정은 항상 Donchian 돌파/트레일링 스탑 이탈 여부만으로 네트워크 호출 없이 결정론적으로 나온다 — LLM이나 뉴스 API 상태와 무관하게 항상 확정된다.
  - **HOLD인 날은 뉴스 수집·LLM 호출을 아예 생략**한다 (하루 대부분은 HOLD이므로 API 사용량이 크게 준다).
  - **매수/매도인 날**: Exa로 뉴스를 수집하고 OpenRouter LLM에 뉴스+시그널 상태로 서술형 설명을 요청한다. LLM이 반환한 액션이 기계적 판정과 다르면 로그만 남기고 **기계적 판정을 그대로 사용**한다(액션은 LLM이 바꿀 수 없음).
  - **LLM/뉴스 호출이 실패해도** (실제 OpenRouter 무료 모델 429 상황으로 검증됨) 판정 자체는 절대 유실되지 않는다 — `_build_rule_based_explanation`이 "어떤 숫자 규칙이 발동했는지"를 명시한 결정론적 설명 텍스트로 자동 대체한다.
  - 그날의 전체 판정 결과는 Drive에 `_recommendations_{YYYY-MM-DD}.json`으로도 저장된다(`run_asset_class_recommendations`) — 텔레그램 발송이 실패하더라도 판정 이력 자체는 남는다.
- **통합 일일 리포트 (`report_builder.py`, v3.0 신설)**: 그날의 11종목 판정 결과 하나로 HTML 리포트 한 장을 만든다(`build_daily_report_html`).
  - **LLM 교차 자산 총평 (`openrouter_briefing.generate_portfolio_overview`)**: 개별 종목 판정과는 별개로, 11종목의 액션/종가를 한 번에 프롬프트에 담아 "여러 자산군에 걸쳐 동시에 나타나는 추세"만 감정 없이 한 문단으로 종합 해설하도록 요청한다. 시스템 프롬프트에 "판정을 절대 바꾸거나 재해석하지 않는다"를 명시해, 이 총평이 개별 종목의 매수/HOLD/매도 판정에 영향을 주지 않도록 못 박는다(기계적 판정과 완전히 분리된 해설 전용 — [기능 3]의 `generate_recommendation`과 동일한 원칙). LLM 호출이 실패해도 총평 없이 표+차트만으로 리포트 생성 자체는 계속 진행된다.
  - **요약 표**: 티커/자산/구분/액션/종가 HTML 표. 매수/매도 종목의 티커 셀은 아래 시그널 카드로 점프하는 앵커 링크(`#ticker-{티커}`)가 된다.
  - **매수/매도 시그널 카드 (v3.1)**: 매수/매도 종목마다 `<section class="signal-card">` 하나씩 — 액션 배지(색상은 요약 표와 동일), `get_recommendation_for_ticker`가 이미 계산해 둔 LLM 서술 분석(또는 규칙 기반 폴백 텍스트, [기능 3] 참고)을 그대로 표시, 그 아래 참고 뉴스 카드(제목·링크·발행처·요약, `results[ticker]['news']`를 재사용 — 뉴스를 다시 수집하지 않음). 차트는 `<details><summary>📈 차트 보기</summary>...</details>` 접이식 위젯 안에 넣어 기본은 접힌 상태로 시작 — 분석/뉴스 텍스트가 먼저 보이고 차트는 필요할 때만 펼치게 해 페이지 첫인상을 가볍게 유지한다.
  - **HOLD 종목**: 뉴스/LLM 분석이 없으므로(HOLD인 날은 [기능 5]의 신선도 게이트 이후 단계에서 애초에 뉴스/LLM 호출 자체를 생략) 개별 카드 대신, 페이지 맨 아래 하나의 접힌 `<details>` 블록("HOLD 종목 차트 보기 (N개, 참고용)")에 차트만 모아 둔다. 시그널 카드에 이미 차트가 있는 종목은 이 블록에서 제외해 같은 차트를 두 번 그리지 않는다.
  - 모든 차트는 `chart_builder.build_ticker_chart_figure` → Plotly `fig.to_html(include_plotlyjs=...)`로 임베드한다(리포트 전체에서 첫 차트만 Plotly JS를 CDN에서 로드, 나머지는 재사용). 브라우저가 클라이언트 사이드에서 렌더링하므로 서버 쪽 이미지 렌더링(kaleido 등)이 전혀 필요 없다 — 아래 참고.
  - **XSS/마크업 깨짐 방지**: LLM 분석 텍스트와 Exa 기사 제목/요약처럼 리포트가 직접 생성하지 않은 외부 텍스트는 모두 `html.escape()`로 이스케이프한 뒤 삽입한다 — LLM 응답에 `<`/`>` 등이 섞여도 리포트 마크업이 깨지지 않도록.
  - **데스크톱 여백/뉴스 카드 레이아웃 (v3.3, v3.4에서 추가 조정)**: 처음엔 컨테이너 `max-width`를 1000px → 1400px로 넓혔으나 큰 모니터에서는 여전히 여백이 많다는 피드백을 받아, v3.4에서 `max-width` 제한 자체를 없애고 `width: 97%`로 화면 폭에 맞춰 늘어나도록 재조정했다. 표·차트·뉴스 그리드(`repeat(auto-fit, minmax(320px, 1fr))`)는 이 넓은 폭을 그대로 쓰지만, 총평/개별 분석 문단(`.overview`/`.analysis`)은 줄 길이가 너무 길어지면 읽기 불편해지므로 `max-width: 900px`로 별도 제한 — "표·차트는 화면 폭 전부, 긴 글줄은 읽기 편한 폭"으로 원칙을 나눴다.
  - **저장 위치 2곳**: (a) Drive에 `_report_{date}.html`로 저장 — Streamlit "리포트 히스토리" 탭이 재계산 없이 그대로 다시 보여줌. (b) 로컬 `docs/reports/{date}.html`로도 저장 — `recommend.yml`이 이 파일을 커밋+푸시해 GitHub Pages가 공개 서빙(`https://garam827.github.io/ai_invest_assistant/reports/{date}.html`). 결과가 비어 있으면(전 종목 신선도 게이트 탈락 등) 리포트 생성 자체를 건너뛰고, `docs/reports` 디렉터리가 없으면 `recommend.yml`의 발행 스텝도 조용히 스킵한다.
  - **리포트 생성 실패는 크론 전체를 막지 않음**: LLM/Drive/Git 어느 단계에서 실패하든 예외를 잡아 로그만 남기고, 이미 계산된 매수/HOLD/매도 판정과 텔레그램 발송은 그대로 진행된다(`_recommendations_{date}.json` 저장 실패 시의 폴백과 동일한 원칙).
- **kaleido/헤드리스 렌더링 전면 제거 (v3.0)**: v2.8~v2.9에서는 텔레그램에 종목별 차트를 PNG로 첨부하기 위해 kaleido(헤드리스 Chromium)를 썼고, 이 때문에 Ubuntu 러너에 CJK 폰트를 설치해야 하는 문제가 있었다. v3.0부터는 차트가 모두 브라우저에서 JS로 렌더링되는 리포트 페이지에 임베드되므로 서버 쪽 이미지 렌더링 자체가 사라졌다 — `recommend.yml`의 `fonts-nanum` 설치 스텝과 `requirements.txt`의 `kaleido` 의존성을 삭제했다. `chart_builder.FONT_FAMILY`는 여전히 유지(브라우저 폰트 힌트 목적으로는 여전히 유용하지만, 더 이상 "설치가 필수인 CI 환경 이슈"는 아니다).
- **텔레그램 알림 (`telegram_notifier.py`, 설정은 [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md))**: `recommendation_engine.run_asset_class_recommendations`가 크론 경로에서만 호출하며, Streamlit의 개별 조회(`get_recommendation_for_ticker`)에서는 절대 호출하지 않는다(그렇지 않으면 사용자가 차트를 조회할 때마다 알림이 스팸처럼 발송됨). v3.0부터 메시지 1건만 보낸다: 11종목 전체를 **표 형태**로 정리한 요약(Telegram Bot API는 어떤 parse_mode에서도 GFM/HTML 테이블을 렌더링하지 않으므로, 등폭 서체 코드블록 안에 티커/구분/액션/종가 4열을 정렬 — `unicodedata.east_asian_width`로 한글·영문 폭 차이 보정, 이모지는 표 밖 범례 한 줄로만 사용, v2.9) 끝에 위 통합 리포트의 GitHub Pages URL 링크를 덧붙인다(`format_summary(results, report_url=...)`). 종목별 차트 이미지를 개별 첨부하던 v2.8~v2.9 방식은 폐지 — 차트는 이제 링크된 리포트 안에 전부 있으므로, 하루 메시지 수가 최대 6건(요약 1 + 차트 최대 5)에서 1건으로 줄었다.
- **종목 설명 노출**: [기능 1]에서 마련한 `ASSET_CLASS_TICKERS`의 큐레이션 설명과 `_universe.json`의 위키피디아 기반 설명이 리포트 요약 표와 Streamlit 양쪽 차트 탭에 노출된다(텔레그램 요약 표는 지면상 전체 설명 대신 짧은 카테고리만 표시, v2.9).

---

## 3. 코드 작성 시 주의사항 & 예외 처리 규칙

1. **API 할당량 관리**: yfinance 대량 호출 시 차단 위험을 방지하기 위해 종목 간 `time.sleep(0.5)` 등 미세한 딜레이를 부여할 것.
2. **Parquet I/O 최적화**: 구글 드라이브에서 매번 전체 파일을 다운로드하는 리스크를 줄이기 위해, 당일 조회 빈도가 높은 데이터는 Streamlit 백엔드의 내장 캐시(`st.cache_data`)를 적극 활용할 것. (`app.py`에 적용됨: `DriveDB` 연결은 `st.cache_resource`, 종목 목록/시세 조회는 `st.cache_data(ttl=3600)`, LLM 매매 추천은 `(티커, 최신 날짜)` 키로 캐싱)
3. **가짜 돌파 필터**: 가격 돌파 발생 시, 당일 거래량이 '최근 20일 평균 거래량의 1.5배 이상'인 종목만 대시보드 상단에 우선순위로 노출할 것.
4. **LLM 프로바이더 장애 대응**: OpenRouter 무료 티어 모델 호출이 실패해도 전체 배치가 중단되지 않도록, 종목별로 예외를 잡아 로그만 남기고 다음 종목으로 계속 진행할 것.
5. **자산군 ETF는 S&P 500 편입/편출 로직에서 항상 제외**: `sync_universe`가 참조하는 "저장된 티커" 집합에서 `ASSET_CLASS_TICKERS`를 빼고 diff할 것. 빼지 않으면 이 자산군들(SPY/QQQ/BTC-USD/GLD/TLT/IEF/DBC/USO/UNG/DBA/CPER)이 매번 "S&P 500에서 편출된 종목"으로 잘못 분류된다.
6. **매수/매도 판정은 절대 네트워크 호출에 의존하지 말 것**: 액션(매수/HOLD/매도)은 항상 `signal_engine.get_mechanical_action`(순수 계산, 네트워크 없음)으로만 결정한다. LLM/뉴스 API는 매수·매도 시그널이 발생한 날에만 서술형 설명을 덧붙이는 용도로만 쓰고, 그 호출이 실패해도 규칙 기반 설명(`recommendation_engine._build_rule_based_explanation`)으로 대체할 뿐 판정 자체를 HOLD로 낮추거나 유실시켜서는 안 된다.
7. **차트는 항상 클라이언트(브라우저) 사이드에서 렌더링할 것, 서버 쪽 헤드리스 이미지 렌더링을 다시 들이지 말 것**: v2.8~v2.9에서는 텔레그램 첨부용으로 kaleido(헤드리스 Chromium)를 썼다가 CI에 CJK 폰트가 없어 한글이 깨지는 문제를 겪었다. v3.0에서 `fig.to_html()` 기반 리포트 임베드로 전환하며 이 클래스의 문제 자체를 없앴으니, 향후에도 정적 이미지가 꼭 필요한 게 아니라면 굳이 kaleido/`to_image`를 다시 추가하지 말 것.
8. **일일 리포트 생성 실패가 크론의 나머지 단계를 막아서는 안 됨**: `report_builder.build_daily_report_html`/`save_report` 실패(LLM, Drive, Git 커밋·푸시 어느 단계든)는 예외를 잡아 로그만 남기고, 이미 확정된 매수/HOLD/매도 판정 저장과 텔레그램 발송은 그대로 진행할 것 — 리포트는 부가 산출물이지 판정의 전제조건이 아니다.
9. **LLM 교차 자산 총평은 개별 종목 판정에 관여하지 않게 분리할 것**: `openrouter_briefing.generate_portfolio_overview`는 해설 전용이며, 규칙 6과 마찬가지로 `signal_engine.get_mechanical_action`이 정한 개별 판정을 절대 바꾸거나 재해석하지 않는다. 시스템 프롬프트에 이 제약을 명시적으로 못박을 것.
10. **LLM/외부 API 응답을 HTML에 그대로 꽂지 말 것**: `report_builder.py`처럼 LLM 서술 텍스트나 Exa 뉴스 제목/요약을 f-string으로 HTML에 삽입할 때는 반드시 `html.escape()`(또는 동급 이스케이프)를 거칠 것 — 이 텍스트들은 우리가 생성한 게 아니라 외부에서 온 값이라, `<`/`>` 등이 섞이면 마크업이 깨지거나 의도치 않은 태그가 삽입될 수 있다.
11. **재사용 가능한 데이터를 다시 계산/재호출하지 말 것**: `recommendation_engine.get_recommendation_for_ticker`가 이미 만든 뉴스/LLM 분석 결과(`results[ticker]`)는 리포트·텔레그램·Streamlit 어디서 쓰든 그대로 재사용한다. 같은 데이터를 위해 Exa/OpenRouter를 다시 호출하는 코드를 추가하지 말 것 — API 사용량/비용/rate limit 관리 원칙([기능 5] 참고)과 직결된다.
