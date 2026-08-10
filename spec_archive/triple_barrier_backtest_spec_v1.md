# 스펙: Triple-Barrier 기반 자산군 시그널 백테스트 (설계안, 미구현)

> **상태: 보류 — 설계만 확정, 구현 대기.** 이 문서는 `investment_assistant_spec.md`(메인 스펙)와 별도로 관리한다. 실제 구현에 착수하면 그때 메인 스펙의 새 `[기능 N]` 섹션과 버전 changelog로 통합하고, 이 파일은 다른 기능들과 동일한 방식으로 `triple_barrier_backtest_spec_v1.md` 등으로 보존한다. `paper_trading_spec.md`와 같은 성격의 문서 — 아직 메인 스펙에 편입되지 않은 활성 설계 문서.

## 1. 배경 및 목표

지금까지의 시스템(`signal_engine.get_mechanical_action`)은 "오늘 매수/HOLD/매도가 뭔지"만 결정론적으로 알려줄 뿐, 그 판정이 **실제로 얼마나 잘 맞았는지**는 검증한 적이 없다. 이 기능은:

- `data_fetcher.ASSET_CLASS_TICKERS` 12종 각각에 대해, 과거 매일의 매수/HOLD/매도 판정을 **Triple-Barrier 기법**으로 라벨링한 "실제 결과"와 교차 검증해 히트레이트(적중률) 통계를 낸다.
- 머신러닝/딥러닝 모델은 **이번 스코프에서 명시적으로 제외** — 순수 통계 기반 백테스트만 다룬다. ML 확장은 이 백테스트가 검증된 뒤의 별도 후속 과제.
- "경제 사이클 계산"에 이 결과를 활용하는 것은 이 스펙의 스코프가 아니다 — 개별 자산군 판정의 적중률 통계까지만 다루고, 여러 자산군을 종합해 사이클 지표로 만드는 방법은 이 백테스트 결과를 본 뒤 별도로 설계한다(6절 참고).

## 2. Triple-Barrier 라벨링 정의

시작일 `t`, 보유 기간 `horizon_days`(기본 63영업일 ≈ 3개월), 상단/하단 임계치 `upper_pct`/`lower_pct`(기본 각각 10%)에 대해:

- **상단 장벽(Profit)**: `Close[t] * (1 + upper_pct)`
- **하단 장벽(Stop)**: `Close[t] * (1 - lower_pct)`
- **수직 장벽(Time)**: `t + horizon_days` 영업일

`t+1`부터 수직 장벽까지 순서대로 스캔해, **먼저 닿는 장벽**으로 라벨을 확정한다:

```
label = +1 (상승)  — High가 상단 장벽에 먼저 도달
label = -1 (하락)  — Low가 하단 장벽에 먼저 도달
label =  0 (보합)  — 수직 장벽까지 둘 다 도달하지 못함
```

같은 날 상단/하단이 동시에 조건을 만족하는 극단적 경우(갭 등)는 보수적으로 하락(-1)을 우선한다(장중 저가가 먼저 찍혔을 가능성을 배제할 수 없으므로).

**경계 조건 — 최근 `horizon_days`는 라벨 미확정**: 각 자산의 마지막 `horizon_days`(기본 63)영업일은 아직 3개월치 미래 데이터가 없어 라벨을 확정할 수 없다. 이 구간은 `label = None`("판정 보류")으로 남기고 통계 집계에서 제외한다 — 억지로 보합(0)으로 채우면 실제로는 아직 결과를 모르는 것과 진짜 보합을 구분할 수 없게 된다.

## 3. 데이터 요구사항

- **분석 시작일**: `2014-09-17` — 12개 자산군 중 가장 늦게 상장한 BTC-USD의 최초 거래일. 이 시점부터는 12개 전부 데이터가 존재하므로, 이 스코프에서는 "일부 자산군에 데이터가 없다"는 결측 케이스가 발생하지 않는다(자산군마다 상장일이 다르다는 문제 자체가 분석 시작일을 이 지점으로 잡는 것으로 자연히 해소됨).
- **실제 fetch 시작일**: 분석 시작일보다 충분히 앞서야 한다 — `signal_engine.compute_signals`가 Donchian-100/ATR-14/일목균형표(52일+26일 선행 ≈ 78봉) 롤링 윈도우를 쓰므로, 최소 100영업일(≈5개월) 앞선 시점부터 데이터를 받아야 2014-09-17 시점에 이미 지표가 워밍업되어 있다. 여유를 둬 **2014-06-01**부터 fetch.
- **소스**: 현재 Drive에 적재된 5년 롤링 스냅샷과는 별개다 — 이 백테스트는 yfinance에서 직접 장기 히스토리를 새로 받아온다(`data_fetcher.fetch_ohlcv(ticker, start="2014-06-01")` 재사용 가능, 12종뿐이라 API 부담 없음).
- **저장 위치**: 매일 갱신되는 프로덕션 Drive 데이터와 섞이면 안 되므로, 로컬 전용 캐시(예: `backtest_cache/{ticker}.parquet`, `.gitignore` 대상)에 별도 보관 — 재실행할 때마다 yfinance를 다시 호출하지 않기 위함. Drive에는 올리지 않는다(이 백테스트는 일회성/주기적 분석 작업이지 크론이 관리하는 실시간 서비스가 아니므로).

## 4. 모듈 설계 — `backtest.py` (신설)

기존 모듈 분리 원칙(한 파일 = 한 관심사)을 따르고, `signal_engine`의 기존 함수를 그대로 재사용한다 — 매수/HOLD/매도 판정 로직을 중복 구현하지 않는다.

```python
BACKTEST_CACHE_DIR = "backtest_cache"
ANALYSIS_START = "2014-09-17"
FETCH_START = "2014-06-01"  # 워밍업 여유분 포함

def fetch_backtest_history(tickers: list[str], force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """티커별로 FETCH_START부터 오늘까지 전체 히스토리를 yfinance에서 받아 로컬 parquet 캐시에 저장.
    캐시가 있으면 재다운로드하지 않음(force_refresh=True면 무시하고 재수집)."""

def compute_triple_barrier_labels(
    df: pd.DataFrame,
    upper_pct: float = 0.10,
    lower_pct: float = 0.10,
    horizon_days: int = 63,
) -> pd.DataFrame:
    """df(Date/Open/High/Low/Close)에 label(-1/0/+1/None)과 touch_date 컬럼을 추가해 반환.
    signal_engine과 마찬가지로 순수 함수, I/O 없음."""

def run_backtest(tickers: dict | None = None) -> pd.DataFrame:
    """ASSET_CLASS_TICKERS 기본. 티커별로 fetch_backtest_history + signal_engine.compute_signals
    (매수/HOLD/매도 액션) + compute_triple_barrier_labels를 결합해,
    (ticker, date, action, label, touch_date) 행으로 이루어진 통합 DataFrame을 반환.
    ANALYSIS_START 이전 행은 워밍업용으로만 쓰고 결과에서 제외."""

def summarize_hit_rates(results: pd.DataFrame) -> pd.DataFrame:
    """액션(매수/HOLD/매도) × 라벨(상승/보합/하락) 교차표를 자산군 전체 통합 + 자산군별로 각각 산출
    (건수와 비율 %). label이 None(판정 보류)인 행은 집계에서 제외."""
```

- `run_backtest`는 `signal_engine.compute_signals`/`get_mechanical_action`을 그대로 호출 — 백테스트만을 위한 별도 시그널 로직을 새로 만들지 않는다(프로덕션과 동일한 규칙으로 검증해야 의미가 있음).
- 데이터 규모가 자산당 최대 수천 행(12종 × 약 12년)이라 단순 반복/`pandas` 연산으로 충분히 빠르다 — numba 등 별도 가속 불필요.

## 5. 산출물

- `summarize_hit_rates`의 결과를 CSV로 저장(예: `backtest_cache/hit_rates_summary.csv`)하고 콘솔에도 출력 — 이번 스코프에서는 Streamlit UI나 일일 리포트에 통합하지 않는다(일회성/주기적 분석 목적이지 상시 서비스 기능이 아님).
- 자산군별 결과와 12종 통합 결과를 모두 산출해, "돈치안/ATR 매수 시그널이 전체적으로/자산군별로 실제 3개월 내 몇 %가 상승했는가"를 바로 확인할 수 있게 한다.

## 6. v1 스코프에서 명시적으로 제외하는 것 (향후 확장 아이디어)

- **머신러닝/딥러닝 모델**: 이번 요청에서 명시적으로 제외됨. 이 백테스트로 기존 규칙의 히트레이트를 먼저 확인한 뒤, 필요하면 별도 스펙으로 ML 모델(예: S&P 500 503종목까지 학습 데이터로 확장) 논의.
- **경제 사이클 지표로의 집계**: 여러 자산군의 라벨/히트레이트를 하나의 "사이클" 지표로 합성하는 방법은 이 백테스트 결과를 검토한 뒤 별도로 설계한다.
- **ATR 기반 동적 장벽**: 지금은 고정 ±10%. 저변동성 자산(TLT/IEF)과 고변동성 자산(BTC-USD)에 같은 임계치를 적용하는 것이 타당한지는 이 결과를 본 뒤 판단 — 필요시 `atr_multiplier` 기반 장벽으로 교체 가능하도록 함수 시그니처에 여지를 둔다.
- **크론/실시간 자동화 연동**: 이 백테스트는 스크립트로 수동 실행하는 분석 작업이며, `collect.yml`/`recommend.yml` 등 기존 자동화 파이프라인에 편입하지 않는다.

## 7. 구현 순서 제안 (착수 시 참고용)

1. `fetch_backtest_history` — 12종 장기 히스토리 로컬 캐시 구축(1회 실행으로 충분, 이후 재실행 시 캐시 재사용).
2. `compute_triple_barrier_labels` — 합성 데이터(상승/하락/보합 케이스를 인위적으로 만든 소규모 DataFrame)로 단위 검증 후, 실제 자산 데이터에 적용.
3. `run_backtest` — `signal_engine`과 결합해 전체 파이프라인 연결, 2014-09-17 이후 구간만 결과에 포함되는지 확인.
4. `summarize_hit_rates` — 자산군별 + 통합 교차표 산출, CSV 저장.
5. 결과 검토 후, Streamlit/리포트 노출 여부나 ML 확장 여부를 다음 단계로 논의.
