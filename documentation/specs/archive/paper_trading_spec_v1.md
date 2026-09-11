# 스펙: 모의 투자(포워드 테스팅) 기능 (설계안, 미구현)

> **상태: 보류 — 설계만 확정, 구현 대기.** 이 문서는 `investment_assistant_spec.md`(메인 스펙)와 별도로 관리한다. 실제 구현에 착수하면 그때 메인 스펙의 새 `[기능 N]` 섹션과 버전 changelog로 통합하고, 이 파일은 다른 기능들과 동일한 방식으로 `paper_trading_spec_v1.md` 등으로 보존한다.

## 1. 배경 및 목표

지금까지의 시스템은 "오늘 매수/HOLD/매도 판정이 뭔지"만 알려준다. 실제로 그 판정을 따라 매수했다면 지금 수익률이 얼마인지는 사용자가 직접 계산해야 했다. 이 기능은:

- 사용자가 "특정일에 특정 종목을 종가에 매수했다"는 가상의 포지션을 기록해 두면,
- 매일 발송되는 일일 리포트/텔레그램에 그 포지션의 **현재 수익률**을 자동으로 계산해 함께 보여주고,
- 포지션 추가/청산은 사용자가 언제든 바꿀 수 있어야 한다(인터랙티브).

**핵심 설계 결정**: 인터랙션(포지션 추가/청산)은 **Streamlit 앱**에서만 처리한다. 이 프로젝트의 크론(`collect.yml`/`recommend.yml`)은 완전 무인·읽기 전용으로 설계돼 있고, 사람이 뭔가 입력하는 경로는 전부 Streamlit UI로 통일돼 있다(폼, `st.session_state` 등 기존 패턴 재사용). 텔레그램 봇 API는 지금 **발송 전용**으로만 쓰이고 명령 수신(webhook/polling)을 처리하는 부분이 전혀 없으므로, "텔레그램에서 `/매수 SPY` 입력" 같은 방식은 상시 리스닝 서버를 새로 구축해야 하는 훨씬 큰 작업이라 채택하지 않는다.

## 2. 데이터 모델

Drive에 새 JSON 메타데이터 파일 `_paper_trades.json`을 둔다 (`_universe.json`, `_recommendations_{date}.json`과 동일한 `DriveDB.load_json`/`save_json` 메커니즘 재사용, 별도 저장소 계층 불필요).

```json
{
  "positions": [
    {
      "id": "a1b2c3d4",
      "ticker": "SPY",
      "quantity": 10,
      "entry_date": "2026-07-15",
      "entry_price": 738.20,
      "status": "open",
      "exit_date": null,
      "exit_price": null,
      "note": "",
      "created_at": "2026-07-15T09:12:00Z"
    }
  ]
}
```

- **`id`**: `uuid4().hex[:8]` 정도의 짧은 무작위 식별자. 같은 종목을 여러 번 매수/매도할 수 있으므로 티커만으로는 포지션을 구분할 수 없다.
- **`quantity`**: 매수 수량(주식 수). 금액이 아니라 수량 기준 — 수익률(%) 계산은 수량과 무관하지만, 절대 손익(원화/달러 금액)을 보여주려면 필요.
- **`entry_price`**: 기본값은 `entry_date`의 실제 종가(해당 종목의 Drive Parquet에서 조회)로 자동 채움 — "종가에 매수했다면"이라는 요구사항을 그대로 반영. 사용자가 다른 체결가를 가정하고 싶으면 직접 수정 가능하게 입력 필드는 열어둔다.
- **`status`**: `"open"` | `"closed"`. v1 스코프에서는 부분 청산(scale-out)은 지원하지 않는다 — 포지션은 통째로 열리고 통째로 닫힌다(아래 4절 참고).
- **포지션 대상 티커**: `data_fetcher.ASSET_CLASS_TICKERS`뿐 아니라 S&P 500 개별 종목도 포함 — 두 경우 모두 `drive_db.load_ticker(ticker)`로 시세를 조회할 수 있으므로 제한할 이유가 없다.

## 3. 모듈 설계 — `paper_trading.py` (신설)

기존 모듈 분리 패턴(한 파일 = 한 관심사, I/O는 `drive_db`에 위임)을 그대로 따른다.

```python
PAPER_TRADES_FILENAME = "_paper_trades.json"

def load_positions(drive_db) -> list[dict]: ...
def save_positions(drive_db, positions: list[dict]) -> None: ...

def open_position(drive_db, ticker: str, entry_date: str, quantity: float, entry_price: float | None = None) -> dict:
    """entry_price가 None이면 entry_date의 실제 종가를 자동 조회해서 채운다."""

def close_position(drive_db, position_id: str, exit_date: str, exit_price: float | None = None) -> dict:
    """exit_price가 None이면 exit_date(기본: 오늘)의 최신 종가를 자동 조회해서 채운다."""

def compute_position_returns(drive_db, positions: list[dict]) -> list[dict]:
    """각 포지션에 다음 필드를 덧붙여 반환:
    - open 포지션: current_price(최신 종가), unrealized_pnl(금액), unrealized_pnl_pct(%)
    - closed 포지션: realized_pnl(금액), realized_pnl_pct(%)
    가격 조회는 이미 Drive에 적재된 시세를 재사용 — 새로운 외부 API 호출 없음(yfinance/Exa/OpenRouter 전부 호출하지 않음).
    """
```

- 가격 데이터는 매일 크론이 이미 갱신해 둔 Drive Parquet을 그대로 쓴다 — 이 기능 때문에 새로운 시세 수집 로직이 필요하지 않다.
- 종목이 아직 Drive에 없거나(오타 등) 데이터가 없으면 `current_price`를 `None`으로 두고 UI/리포트에서 "가격 조회 실패" 정도로만 표시 — 크론 전체를 막지 않는다(기존 리포트 생성 실패 격리 원칙과 동일).

## 4. Streamlit UI — 새 탭 "모의 투자"

기존 5개 탭(소개/대표 자산군 분석/종목 차트/데이터 적재/리포트 히스토리) 뒤에 6번째 탭으로 추가.

- **포지션 추가 폼** (`st.form`): 티커 선택(자산군 10+1종 + S&P 500 유니버스 통합 검색), 매수일(`st.date_input`, 기본값 오늘), 수량, 체결가(기본값: 선택한 날짜의 실제 종가를 자동 채워 보여주고 편집 가능하게). 제출 시 `open_position` 호출 → `_paper_trades.json` 갱신.
- **보유 중(open) 포지션 표**: 티커/매수일/매수가/수량/현재가/미실현 손익(금액+%). 손익은 양수 초록/음수 빨강으로 색상 표시(기존 액션 배지 색상 팔레트 재사용). 각 행에 "청산" 버튼 → 청산일/청산가(기본값 오늘 종가) 입력 후 `close_position` 호출.
- **청산 내역(closed) 표**: 접힌 `<details>` 또는 `st.expander`로 하단에 — 과거 실현 손익 기록.
- 캐싱: 포지션 목록 자체는 자주 바뀌므로 짧은 TTL 또는 조작 직후 `st.cache_data.clear()`로 무효화(기존 "데이터 적재" 탭이 완료 후 캐시를 비우는 패턴과 동일). 가격 조회(`drive_db.load_ticker`)는 이미 `app.py`에 있는 `load_ticker_data`(`ttl=3600`) 캐시를 그대로 재사용.

## 5. 일일 리포트/텔레그램 통합

- **`report_builder.py`**: 요약 표와 매수/매도 시그널 카드 사이(또는 그 아래)에 "모의 투자 현황" 섹션 추가 — 보유 중인 포지션을 표로(티커/매수일·가/수량/현재가/수익률), 없으면 섹션 자체를 생략. 청산 내역은 리포트에는 굳이 안 보여줘도 됨(Streamlit에서만 확인).
- **`telegram_notifier.py`**: 기존 표 요약 아래에 보유 포지션이 있을 때만 한 줄씩 추가(예: `📌 SPY +3.2% (매수가 738.20 → 현재 761.85)`) — 포지션이 없으면 이 블록 자체를 생략해 메시지가 불필요하게 길어지지 않게 한다.
- 둘 다 `paper_trading.compute_position_returns(drive_db, positions)`을 그대로 호출 — 리포트/텔레그램 쪼는 쪽에서 수익률을 다시 계산하는 로직을 중복 작성하지 않는다.
- `recommendation_engine.run_asset_class_recommendations`가 리포트를 만드는 시점에 `paper_trading.load_positions`+`compute_position_returns`를 호출해 `report_builder.build_daily_report_html`에 전달하는 흐름이 될 것 — 기존 "이미 계산된 데이터를 재사용하고 새로 호출하지 않는다" 원칙과 일관되게, 포지션 조회 자체도 외부 API 호출이 전혀 없다.

## 6. v1 스코프에서 명시적으로 제외하는 것 (향후 확장 아이디어)

- **부분 청산/추가 매수(스케일 인·아웃)**: 포지션은 한 번에 열고 한 번에 닫는다. 여러 번 나눠 사고팔고 싶으면 별도 포지션(다른 `id`)으로 여러 개 여는 방식으로 대체.
- **자동매매 연동(시스템이 스스로 진입/청산)**: 지금 스코프는 "사용자가 직접 기록하는" 수동 모의 투자다. 향후 확장으로, `signal_engine.get_mechanical_action`이 매수/매도를 낼 때마다 자동으로 포지션을 열고 닫는 "시스템 자체를 포워드 테스팅하는 모드"를 추가할 수 있다 — 이건 완전히 별도 기능(백테스트/포워드테스트 성과 트래킹)이라 지금 스코프에 넣지 않는다.
- **포트폴리오 단위 총 손익/리스크 지표**: 개별 포지션 수익률만 다루고, 전체 포트폴리오의 합산 수익률·샤프비율 같은 지표는 다루지 않는다.
- **환율/통화 처리**: 모든 대상 티커가 이미 USD 표시(비트코인도 `BTC-USD`)라 별도 통화 변환이 필요 없다.

## 7. 구현 순서 제안 (착수 시 참고용)

1. `paper_trading.py` 모듈 + 로컬 단위 테스트(가짜 DriveDB로 열기/닫기/수익률 계산 검증).
2. Streamlit "모의 투자" 탭 (폼 + 표 + 청산 버튼) — 단독으로도 바로 쓸 수 있는 완결된 기능.
3. `report_builder.py`에 섹션 추가 + 로컬 목업 테스트.
4. `telegram_notifier.py`에 한 줄 추가 + 실제 텔레그램 테스트 발송.
5. `recommendation_engine.py`에서 위 둘을 호출하도록 연결.
6. 실제 워크플로 `workflow_dispatch`로 end-to-end 검증 후, 메인 스펙(`investment_assistant_spec.md`)에 새 버전으로 통합.
