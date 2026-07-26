# 스펙: 자산군 시그널 예측 모델 (설계안, 1단계 구현)

> **상태: 1단계(피처 엔지니어링) 구현 완료 — 모델 설계·학습·평가는 미구현.** 이 문서는 `investment_assistant_spec.md`(메인 스펙)와 별도로 관리한다. `paper_trading_spec.md`/`triple_barrier_backtest_spec.md`와 같은 성격의 문서 — 실제 모델까지 완성되면 그때 메인 스펙에 새 `[기능 N]` 섹션과 버전 changelog로 통합하고, 이 파일은 `prediction_model_spec_v1.md` 등으로 보존한다.

## 1. 배경 및 목표

`recommendation_engine.backfill_signal_history_deep`이 만드는 `_signal_history.json`(및 Streamlit "리포트 히스토리" 탭의 CSV 다운로드, [기능 5] 참고)은 12개 자산군 × 날짜별로 매수(`B`)/HOLD(`H`)/매도(`S`)/미상장(`-`) 액션만 남긴다. 이 프로젝트의 시그널 그 자체(`signal_engine.get_mechanical_action`)는 항상 규칙 기반 결정론적 판정이라 절대 흔들리지 않지만, "앞으로 30일간 각 자산군이 매수/HOLD/매도 상태에 있을 비율이 어떻게 될까"는 그 규칙만으로는 알 수 없다 — 이 스펙은 최근 시그널·가격 패턴으로 그 근사 확률을 예측하는 보조 모델을 만드는 것이 목표다.

**원래 시도(`prediction_model/sample_code.py`)**: 위 CSV의 B/H/S/- 값만 원-핫 인코딩해 슬라이딩 윈도우(과거 30일 → 향후 30일 비율)로 X/y를 구성했다. 이 방식은 이미 한 번 압축된 신호(원-핫 4차원)만 입력으로 쓰기 때문에 정보 손실이 크다 — 예를 들어 "돌파 직후"와 "돌파 후 20일째"가 둘 다 그냥 `B`(또는 `H`로 전환 후)로만 보여 구분이 안 된다.

**이 스펙의 접근**: 같은 목표(과거 시그널 패턴 → 향후 액션 비율 예측)를 유지하되, 입력을 원-핫 대신 `signal_engine.compute_signals`가 이미 계산해두고 버려지던 ATR/Donchian 수치까지 포함한 피처로 확장한다. 모델·학습 파이프라인은 이번 1단계 스코프가 아니다 — 먼저 그 피처 데이터셋 자체를 만들어 검증했다.

## 2. 데이터 파이프라인

| 파일 | 상태 | 내용 |
| --- | --- | --- |
| `prediction_model/signal_history.csv` | 기존(Streamlit 다운로드 결과 수동 배치) | 날짜 × 12개 티커, `B`/`H`/`S`/`-`만. `sample_code.py`가 소비하는 원본. |
| `prediction_model/feature_history.csv` | **신설, `feature_engineering.py`로 생성** | 날짜 × 티커 롱포맷(각 행이 티커 하나의 하루), `action` 컬럼은 위와 동일한 B/H/S/HOLD 문자열이지만 여기에 ATR 정규화 수치 피처가 추가됨(아래 3절). |
| `prediction_model/ohlcv_cache/{ticker}.parquet` | 신설, 로컬 전용 캐시 | `data_fetcher.fetch_ohlcv(ticker, start="2007-01-01")` 결과를 재실행마다 다시 받지 않기 위한 캐시 — `triple_barrier_backtest_spec.md`의 `backtest_cache/`와 동일한 원칙. |

`ohlcv_cache/`와 `*.csv` 둘 다 `.gitignore`에 추가했다 — 둘 다 재실행하면 그대로 다시 만들어지는 산출물이고(`feature_history.csv`는 7MB대라 저장소에 커밋할 이유가 없음), Drive에도 올리지 않는다(이 파이프라인은 크론이 관리하는 실시간 서비스가 아니라 로컬 연구용 스크립트 — `backtest.py`와 동일한 위치).

## 3. 피처 정의 (`feature_engineering.py`, 구현 완료)

`signal_engine.compute_signals`가 계산하는 컬럼(ATR/Donchian/Trailing_Stop/Breakout_20/Breakout_100/Exit_Signal)을 그대로 재사용하고, 새 시그널 로직은 추가하지 않는다. 티커별로 하루 한 행, 컬럼:

- `action`: `signal_engine.get_mechanical_action`으로 계산한 그날의 매수/HOLD/매도 (기존과 동일한 규칙).
- `close`, `atr`: 원본 값 그대로.
- `atr_norm_return`: `(오늘 종가 - 어제 종가) / ATR` — 저변동성 자산(TLT)과 고변동성 자산(BTC-USD)을 같은 스케일로 비교 가능하게 정규화한 일간 수익률.
- `dist_donchian20_atr`: `(종가 - Donchian_Upper_20) / ATR` — 20일 상단 채널까지 남은/넘어선 거리(ATR 단위). 양수면 이미 돌파, 크기가 돌파 강도를 나타냄.
- `dist_trailing_stop_atr`: `(종가 - Trailing_Stop) / ATR` — 트레일링 스탑까지 남은 여유.
- `days_since_breakout`: 마지막 20일/100일 돌파 이후 경과 영업일 수 — "지금이 막 돌파한 시점인지, 오래된 추세인지" 구분.
- `days_since_exit`: 마지막 청산 시그널 이후 경과 영업일 수.

`days_since_*`는 해당 티커 히스토리에서 아직 한 번도 발생하지 않은 구간(초반 워밍업)에는 `NaN`으로 남는다 — 억지로 0이나 큰 수로 채우면 "이미 발생했지만 오래됐다"와 "애초에 발생한 적 없다"를 구분할 수 없다(`triple_barrier_backtest_spec.md`가 라벨 미확정 구간을 `None`으로 남기는 것과 같은 이유).

**실행 결과 검증**: 12개 티커 전체 실행 시 58,336행 생성, DBB는 2007-01-05부터(CPER→DBB 교체 이후 시작일과 일치), `days_since_breakout`의 `NaN` 개수는 티커별로 20~80행 수준(초반 워밍업 구간에만 국한, 예상 범위 내). ATR 등 지표가 아직 워밍업 안 된 첫 13~14행은 `atr`/`atr_norm_return` 등이 `NaN`으로 정상 처리됨.

## 4. 모듈 설계 — `prediction_model/feature_engineering.py` (구현 완료)

```python
OHLCV_CACHE_DIR = "prediction_model/ohlcv_cache"
FEATURE_HISTORY_PATH = "prediction_model/feature_history.csv"
FETCH_START = "2007-01-01"

def _cached_ohlcv(ticker: str, force_refresh: bool = False) -> pd.DataFrame: ...
def _days_since(flags: pd.Series) -> pd.Series: ...
def build_ticker_features(ticker: str, force_refresh: bool = False) -> pd.DataFrame: ...
def build_feature_history(tickers: dict | None = None, force_refresh: bool = False) -> pd.DataFrame: ...
```

`data_fetcher`/`signal_engine`/`config`를 부모 디렉토리에서 import하기 위해 스크립트 상단에서 `sys.path`에 리포 루트를 추가한다(리포에 별도 패키징이 없으므로 `backtest.py` 계획과 마찬가지로 스크립트 단독 실행 전제).

## 5. X/y 데이터셋 구축 (`sample_code.py` 방식, 아직 원-핫 기반 — 피처 버전으로 확장은 미구현)

기존 `sample_code.py`의 슬라이딩 윈도우 골격(과거 `X_window_size`일 → 향후 `y_window_size`일 각 티커의 B/H/S 비율)은 그대로 유효한 아이디어다. 다음 단계(미구현)로 `feature_history.csv`를 같은 구조로 변환해야 한다 — `X`를 원-핫 4차원 대신 위 6개 수치 피처(+ 필요시 action 원-핫과 병행)로, 날짜×티커 순서를 맞춰 `(샘플 수, 30, 12, 피처 수)` 형태로 재구성.

**검증 시 반드시 짚어야 할 점(설계 메모, 사용자와 논의 완료)**: 슬라이딩 윈도우를 하루씩 이동하며 샘플을 뽑으면 인접 샘플끼리 최대 59일이 겹쳐 사실상 독립 표본이 아니다 — 무작위 셔플 train/test split을 쓰면 리키지가 생긴다. 실제 학습 단계에서는 **walk-forward(시간순 확장/롤링 윈도우) 검증**을 써야 한다(`triple_barrier_backtest_spec.md`가 라벨 경계에서 미래 데이터 누수를 피하는 것과 같은 원칙).

## 6. 모델 설계 방향 (미구현, 논의된 방향성만)

- 6,270일(사실상 훨씬 적은 독립 샘플 수)이라는 규모를 감안하면, 처음부터 LSTM/Transformer 같은 무거운 시퀀스 모델보다 **그래디언트 부스팅 트리(예: LightGBM)나 작은 GRU 베이스라인**부터 시작한다 — 과적합 리스크가 크기 때문에 단순한 모델로 성능 하한선을 먼저 확보.
- 입력은 원-핫 신호만이 아니라 3절의 ATR 정규화 피처를 함께 사용 — 원-핫만으로는 이미 손실된 정보(돌파 강도, 신호 신선도)를 복원할 수 없다.
- 베이스라인 이후 성능이 부족하면 그때 더 복잡한 아키텍처(시퀀스 모델)를 검토 — `triple_barrier_backtest_spec.md`가 "규칙 히트레이트부터 확인 후 ML 확장을 별도 스펙으로 논의"라고 못박은 것과 동일한 단계적 접근.

## 7. 이번 스코프에서 제외하는 것 (향후 확장 아이디어)

- **모델 아키텍처 확정·학습 코드**: 이번 1단계는 피처 데이터셋 구축까지만. 다음 세션에서 별도로 착수.
- **X/y 데이터셋 빌더를 `feature_history.csv` 기반으로 재작성**: `sample_code.py`는 여전히 원-핫 전용 — 피처 버전 빌더는 미구현.
- **Streamlit/일일 리포트 통합**: `triple_barrier_backtest_spec.md`와 동일하게, 이 예측 모델은 상시 서비스 기능이 아니라 로컬 연구 스크립트로 시작한다. 유의미한 결과가 나온 뒤에야 UI 노출 여부를 논의.
- **`_signal_history.json`/크론 자동화 연동**: 이 피처 파이프라인은 수동 실행 스크립트이며 `collect.yml`/`recommend.yml`에 편입하지 않는다.

## 8. 구현 순서 제안 (착수 시 참고용)

1. ~~`feature_engineering.py` — 12개 자산군 피처 데이터셋 구축~~ (완료, 이 문서 3~4절).
2. `feature_history.csv`를 `sample_code.py`와 같은 구조의 `(X, y)` 슬라이딩 윈도우 배열로 변환하는 빌더 작성 — 원-핫 대신 수치 피처 사용.
3. Walk-forward 분할 함수 작성(무작위 셔플 금지) — 학습/검증 구간이 시간순으로 겹치지 않는지 단위 검증.
4. 베이스라인 모델(그래디언트 부스팅 또는 작은 GRU) 학습 + 평가 지표 정의(예: 티커별 B/H/S 비율 예측 오차).
5. 결과 검토 후, 더 복잡한 모델이나 Streamlit/리포트 통합 여부를 다음 단계로 논의.
