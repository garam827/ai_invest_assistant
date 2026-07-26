# 스펙: 자산군 시그널 예측 모델 (설계안, 4단계 구현 — 일일 리포트 통합 완료)

> **상태: 4단계(일일 리포트 통합) 구현 완료 — 더 복잡한 모델·Streamlit UI 통합은 미구현.** 이 문서는 `investment_assistant_spec.md`(메인 스펙)와 별도로 관리하되, 4단계부터는 `report_builder.py`/`recommendation_engine.py`(프로덕션 모듈)를 실제로 건드리므로 그 변경 자체는 메인 스펙 v3.41 changelog와 `CLAUDE.md`에도 함께 기록했다 — `prediction_model/` 안의 학습·데이터 파이프라인 자체는 여전히 이 문서에서만 관리하는 "로컬 연구" 영역, 그 산출물을 프로덕션 리포트가 읽어가는 지점만 메인 스펙에도 반영하는 이원 구조다. `paper_trading_spec.md`가 구현 완료 후 메인 스펙에 완전히 흡수된 것과 달리, 이 스펙은 학습 파이프라인이 계속 로컬 전용으로 남아있는 한 계속 별도 문서로 유지한다.

## 1. 배경 및 목표

`recommendation_engine.backfill_signal_history_deep`이 만드는 `_signal_history.json`(및 Streamlit "리포트 히스토리" 탭의 CSV 다운로드, [기능 5] 참고)은 12개 자산군 × 날짜별로 매수(`B`)/HOLD(`H`)/매도(`S`)/미상장(`-`) 액션만 남긴다. 이 프로젝트의 시그널 그 자체(`signal_engine.get_mechanical_action`)는 항상 규칙 기반 결정론적 판정이라 절대 흔들리지 않지만, "앞으로 30일간 각 자산군이 매수/HOLD/매도 상태에 있을 비율이 어떻게 될까"는 그 규칙만으로는 알 수 없다 — 이 스펙은 최근 시그널·가격 패턴으로 그 근사 확률을 예측하는 보조 모델을 만드는 것이 목표다.

**원래 시도(`prediction_model/sample_code.py`)**: 위 CSV의 B/H/S/- 값만 원-핫 인코딩해 슬라이딩 윈도우(과거 30일 → 향후 30일 비율)로 X/y를 구성했다. 이 방식은 이미 한 번 압축된 신호(원-핫 4차원)만 입력으로 쓰기 때문에 정보 손실이 크다 — 예를 들어 "돌파 직후"와 "돌파 후 20일째"가 둘 다 그냥 `B`(또는 `H`로 전환 후)로만 보여 구분이 안 된다.

**이 스펙의 접근**: 같은 목표(과거 시그널 패턴 → 향후 액션 비율 예측)를 유지하되, 입력을 원-핫 대신 `signal_engine.compute_signals`가 이미 계산해두고 버려지던 ATR/Donchian 수치까지 포함한 피처로 확장한다. 모델 아키텍처·학습 코드는 아직 스코프 밖이다 — 먼저 그 피처 데이터셋과 학습용 (X, y) 배열 자체를 만들어 검증했다(1~2단계, 아래 3~5절).

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

## 5. X/y 데이터셋 구축 (`prediction_model/dataset_builder.py`, 구현 완료)

`sample_code.py`의 슬라이딩 윈도우 골격(과거 `X_window_size`일 → 향후 `y_window_size`일 각 티커의 B/H/S 비율)을 그대로 유지하되, `feature_history.csv`(3~4절)를 입력으로 쓰도록 재작성했다.

- **`load_wide_features`**: 롱포맷 `feature_history.csv`를 `(날짜, 티커)` 기준 3차원 배열 `(전체 일수, 12, 9피처)`로 피벗한다. 9피처 = 액션 원-핫 4개(`[H, S, B, 미상장]`, `sample_code.py`와 동일한 순서) + 수치 피처 5개(`atr_norm_return`, `dist_donchian20_atr`, `dist_trailing_stop_atr`, `days_since_breakout_scaled`, `days_since_exit_scaled`). 어떤 티커가 아직 상장되지 않은 날짜(예: 2014년 이전의 BTC-USD, 2007-01-05 이전의 DBB)는 기본값으로 "미상장" 원-핫 + 중립(0) 수치 피처가 채워진다.
  - `days_since_*`는 상한 없는 값이라 다른 피처와 스케일이 안 맞아서, `DAYS_SINCE_CAP`(252영업일 ≈ 1년)로 클리핑한 뒤 `[0, 1]`로 정규화했다 — `NaN`(그 티커 히스토리에서 아직 한 번도 발생 안 함)은 "가장 오래된 상태"와 동일하게 취급해 `1.0`으로 채운다.
- **`build_xy`**: `X`는 30일 윈도우 원본 피처 그대로(`(N, 30, 12, 9)`). `y`는 원래 그다음 30일간 각 티커의 액션 원-핫을 평균 낸 `[B, H, S]` 비율(`(N, 12, 3)`, `sample_code.py`와 동일한 타깃 정의)이었으나, **6절에서 설명하는 이유로 `log((매수일수+1) / (매도일수+1))` 스칼라(`(N, 12)`)로 교체했다** — HOLD/미상장 비중과 무관하게 매수일수 대 매도일수만 비교하는 타깃이라, 아래에서 발견했던 "세 값이 100%로 합산되지 않는" 문제 자체가 애초에 발생하지 않는다.
  - **이전 버전에서 발견한 것(교체의 계기)**: `[B, H, S]` 비율의 세 값이 항상 1로 합산되지는 않았다 — 해당 30일 구간에 그 티커가 "미상장" 상태였던 날짜 비율만큼 합이 1보다 작아졌다(예: BTC-USD 상장 이전 구간의 샘플은 합이 0, 상장 이후·상시 거래 자산은 합이 1). 버그는 아니었지만(설계대로의 동작), 실제 리포트에서 이 수치를 본 사용자가 "왜 100%가 아니냐"고 지적해 6절의 로그 비율 타깃으로 교체하는 계기가 됐다.
- **`walk_forward_split`**: 무작위 셔플이 아니라 **시간순** 분할 — 검증 구간 이전 `PURGE_GAP`(=`X_WINDOW + Y_WINDOW - 1` = 59)개 샘플은 훈련셋에서 제외한다. 인접 슬라이딩 윈도우 샘플끼리 최대 59일이 겹치므로(4절에서 논의한 리키지 문제), 이 퍼지 구간 없이 시간순으로만 자르면 훈련 샘플의 `y` 구간이 검증 구간까지 침범할 수 있다.

**실행 결과 검증**: `X.shape == (6212, 30, 12, 9)`, `y.shape == (6212, 12)`, 훈련 4,910 / 검증 1,243 샘플(퍼지 59개 제외), 날짜 범위 2007-01-03~2026-07-26. `X`/`y` 모두 `NaN` 없음 확인.

산출물은 `prediction_model/dataset.npz`(`X`, `y`, `train_idx`, `val_idx`, `tickers`, `feature_names`, `dates` 포함, 약 1.9MB)로 저장되며, `feature_history.csv`와 마찬가지로 재실행하면 그대로 다시 만들어지는 산출물이라 `.gitignore` 대상이다.

## 6. 베이스라인 모델 (`prediction_model/train_baseline.py`, 구현 완료)

6,270일(사실상 슬라이딩 윈도우가 겹쳐 훨씬 적은 독립 샘플 수)이라는 규모를 감안해, 처음부터 LSTM/Transformer 같은 무거운 시퀀스 모델 대신 **티커별로 독립된 `RandomForestRegressor`**(scikit-learn, 새 의존성 추가 없음)부터 시작했다 — 과적합 리스크가 크기 때문에 단순한 모델로 성능 하한선을 먼저 확보하는 원칙(`triple_barrier_backtest_spec.md`가 "규칙 히트레이트부터 확인 후 ML 확장을 별도 스펙으로 논의"라고 못박은 것과 동일한 단계적 접근).

- **모델 구조**: 티커마다 별도 모델 — 그 티커 자신의 `(30일, 9피처)` 윈도우를 270차원으로 펼쳐 입력. 자산군 간 교차 신호(다른 11개 티커의 동시 상태)는 이번 베이스라인에서는 쓰지 않는다 — 우선 "그 자산 자신의 최근 패턴만으로 얼마나 맞힐 수 있는가"부터 확인.
- **타깃: 매수/매도 로그 비율 (초기 버전에서 교체)**: 처음에는 `[매수, HOLD, 매도]` 3차원 비율을 그대로 회귀했으나, 두 가지 문제가 드러나 `log((매수일수+1) / (매도일수+1))`(스무딩된 로그 비율) 단일 스칼라로 교체했다 — ① 3차원 비율의 세 값이 항상 100%로 합산되지 않아 혼란스러웠다(2절에서 설명한 것처럼, 날짜축이 BTC-USD의 주말 거래일까지 포함하는 합집합이라 주중만 거래하는 11개 티커는 주말마다 "미상장"과 동일한 카테고리로 채워짐 — 실제 리포트에서 SPY가 "매수 6.9% + HOLD 46.4% + 매도 12.6% = 65.9%"로 나와 사용자가 직접 지적함); ② 로그 비율은 HOLD/미상장 비중과 무관하게 매수일수 대 매도일수만 비교하므로 이 문제 자체를 우회한다. `+1` 스무딩(Laplace)은 30일 윈도우에 매수일이 0일인 경우(과거 기저율상 흔함, 6.1절 참고)의 0으로 나누기를 막는다. 자세한 구현은 `dataset_builder.build_xy`의 docstring 참고.
- **상장 전 구간 제외**: `X` 윈도우의 마지막 날(예측 시점)에 그 티커가 "미상장" 원-핫이면 훈련/검증 양쪽에서 그 샘플을 제외한다 — 실제로는 예측을 요청할 일이 없는 시점(아직 상장 안 됐거나, 주식/ETF의 주말처럼 애초에 거래가 없는 날)이므로 학습에도 평가에도 넣지 않는 게 맞다. 이 필터를 거치면 BTC-USD(매일 거래)는 검증 샘플이 1,243개 그대로 남지만, 나머지 11개(평일만 거래)는 854개로 줄어든다 — 버그가 아니라 "주말에 대한 예측은 애초에 의미 없다"는 필터가 의도대로 동작한 것.
- **비교 기준선**: 무작위가 아니라 "훈련 구간의 평균 추세 점수를 항상 예측"하는 단순 베이스라인과 비교 — 모델이 30일 윈도우의 실제 패턴에서 뭔가를 배웠는지, 그냥 그 자산의 역사적 평균으로 회귀했는지 구분하기 위함. 이 평균값(`historical_avg_score`) 자체도 결과에 함께 저장해 리포트에 노출한다(7절) — 예측값을 0이 아니라 그 자산의 과거 평균과 비교해야 의미 있는 해석이 되기 때문(6.1절 참고).

**실제 실행 결과** (MAE, 낮을수록 좋음 — 티커별 개선폭 내림차순):

| 티커 | 모델 MAE | 베이스라인 MAE | 개선폭 | 과거 평균 점수 | 검증 샘플 수 |
| --- | --- | --- | --- | --- | --- |
| SPY | 1.1540 | 1.4571 | 0.3030 | −0.0525 | 854 |
| QQQ | 1.1574 | 1.3647 | 0.2073 | +0.0393 | 854 |
| UUP | 1.5029 | 1.6843 | 0.1814 | −1.0942 | 854 |
| USO | 1.2658 | 1.4314 | 0.1656 | −0.7893 | 854 |
| DBB | 1.2743 | 1.4184 | 0.1441 | −1.0427 | 854 |
| DBA | 1.3812 | 1.5239 | 0.1427 | −1.1010 | 854 |
| GLD | 1.2711 | 1.4133 | 0.1421 | −0.9277 | 854 |
| BTC-USD | 1.2315 | 1.3657 | 0.1342 | −1.0061 | 1,243 |
| TLT | 1.2597 | 1.3871 | 0.1273 | −0.9981 | 854 |
| DBC | 1.2220 | 1.3401 | 0.1180 | −0.8059 | 854 |
| IEF | 1.2436 | 1.3459 | 0.1023 | −0.9188 | 854 |
| UNG | 0.9842 | 1.0706 | 0.0864 | −1.5119 | 854 |

12개 자산군 **전부** 단순 평균 베이스라인보다 낮은 MAE를 기록 — 모델이 30일 윈도우 패턴에서 뭔가 유의미한 걸 배우고 있다는 최소한의 근거는 확보됐다(로그 스케일 타깃이라 이전 버전의 MAE 0.01~0.03과 절대 수치를 직접 비교할 수는 없지만, 개선 방향과 "전부 베이스라인을 이긴다"는 결론은 동일). `historical_avg_score`가 대부분 음수인 것도 6.1절에서 설명하는 구조적 이유와 정확히 일치 — QQQ(+0.0393)와 SPY(−0.0525)만 0에 가까운데, 둘 다 과거 매수 비율(13~14%)이 다른 자산군보다 상대적으로 높았던 티커들이다(앞선 세션에서 확인한 액션 분포 참고).

### 6.1. 왜 매도 시그널이 구조적으로 매수보다 우세한가

이 절은 사용자 요청으로 스펙과 리포트(7절) 양쪽에 명시한다. 실제 과거 전체 기간(2007~) 액션 분포를 세어보면:

| 티커 | HOLD | 매도 | 매수 |
| --- | --- | --- | --- |
| SPY | 68.4% | 18.1% | 13.5% |
| QQQ | 67.5% | 18.4% | 14.1% |
| DBA | 58.7% | 33.2% | 8.1% |
| DBB | 56.3% | 35.3% | 8.4% |
| DBC | 58.4% | 32.2% | 9.4% |
| GLD | 57.1% | 32.9% | 10.0% |
| IEF | 58.3% | 33.1% | 8.6% |
| TLT | 57.2% | 34.5% | 8.3% |
| UNG | 49.2% | 44.8% | 6.0% |
| USO | 59.2% | 32.0% | 8.8% |
| UUP | 56.0% | 35.4% | 8.6% |
| BTC-USD | 59.5% | 31.8% | 8.7% |

12개 전부(주식류 SPY/QQQ가 상대적으로 덜하긴 하지만) 매도로 분류된 날이 매수로 분류된 날보다 훨씬 많다. 이유는 `signal_engine.get_mechanical_action`의 두 판정 정의가 시간적으로 비대칭이기 때문이다:

- **매수**(`Breakout_20`/`Breakout_100`): 그날 종가가 20일 또는 100일 최고가를 **새로 갱신**해야만 발동한다 — 채널 자체가 매일 다시 계산되므로, 하루짜리 뾰족한(punctuated) 이벤트에 가깝다.
- **매도**(`Exit_Signal`): 종가가 트레일링 스탑(최근 고점 − 3×ATR) 아래로 내려가면 발동하고, 가격이 다시 그 위로 회복할 때까지 **여러 날 연속으로 유지**될 수 있다 — 조정·횡보·하락 구간 내내 지속되는 상태(state)에 가깝다.

즉 "매도가 매수보다 많다"는 이 시스템이 비관적이라는 뜻이 아니라, 두 신호의 **발동 방식 자체가 다르다**는 데서 오는 구조적 결과다. 그래서 `추세 점수(log(매수/매도))`가 음수로 나오는 것은 정상이고, **그 자산의 과거 평균 점수보다 지금 더 높은지/낮은지**가 실제로 유의미한 비교다 — 이 문구를 그대로 리포트 disclaimer에도 넣었다(7절).

모델 파일(`prediction_model/models/{ticker}_rf.joblib`, 약 47MB)과 결과 CSV는 재실행하면 다시 만들어지는 산출물이라 `.gitignore` 대상이다.

## 7. 일일 리포트 통합 (`prediction_model/generate_predictions.py` + `report_builder.py`, 구현 완료)

사용자가 "베이스라인 결과가 나온 상태에서 바로 리포트에 넣고, 대신 신뢰도를 같이 보여주자"고 결정 — 원래 이 문서 초안에서 "유의미한 결과가 나온 뒤에야 논의"로 미뤄뒀던 항목이지만, 신뢰도(검증 MAE 개선율)를 함께 노출하는 조건으로 먼저 붙였다.

- **크론은 여전히 학습·예측을 하지 않는다**: `prediction_model/generate_predictions.py`(로컬/수동 실행)가 `train_baseline.py`가 저장한 모델(`prediction_model/models/*.joblib`)로 최신 30일 윈도우에 대한 예측을 만들어, Drive에 `_prediction_simulation.json`으로 저장한다. `recommendation_engine.run_asset_class_recommendations`는 그 파일을 `drive_db.load_json`으로 **읽기만** 한다 — 파일이 없거나 로드 실패해도 다른 선택적 섹션(모의 투자, 시그널 이력)과 동일하게 그 섹션만 생략된다. 필터명 상수(`_prediction_simulation.json`)는 `recommendation_engine.PREDICTION_SIMULATION_FILENAME`과 `generate_predictions.PREDICTION_SIMULATION_FILENAME` 두 곳에 각각 정의돼 있으므로(순환 참조 방지를 위해 `prediction_model/`을 프로덕션 모듈이 import하지 않음, 4절 참고) 파일명을 바꿀 땐 두 곳 다 같이 고칠 것.
- **버그: "가장 최근 날짜"가 종목마다 다름**: 최초 구현은 `feature_history.csv`를 피벗한 전체 배열의 마지막 행(모든 티커 공통 날짜축의 최신 날짜)을 그대로 예측 시점으로 썼다. 그런데 BTC-USD는 주말에도 거래해 배열의 마지막 행이 토요일/일요일이 되는 경우가 있고, 그날은 나머지 11개 자산군엔 애초에 시세 자체가 없어 "미상장" 원-핫으로 채워진다(2절/`dataset_builder.py`의 union-of-dates 처리와 동일한 원리) — 그 결과 실제 실행에서 BTC-USD 하나만 예측되고 나머지 11개는 전부 스킵되는 문제가 발생했다. `generate_predictions._latest_window(array, ticker_idx, x_window)`로 수정해, 티커마다 "그 티커 자신의 마지막 실제 거래일"까지 배열을 거슬러 올라가 그 날짜로 끝나는 30일 윈도우를 찾도록 고쳤다. 그 결과 `_prediction_simulation.json`의 각 티커 예측에 자기 자신의 `as_of_date`가 따로 붙는다(주식/ETF는 보통 금요일, BTC-USD는 그 이후 주말 날짜까지) — 리포트 표에도 "기준일" 컬럼으로 그대로 노출한다.
- **`report_builder._build_prediction_simulation_html`**: "AI 예측 시뮬레이션 (실험적)" 섹션을 페이지 맨 끝(HOLD 차트 블록 뒤)에 추가 — 표(티커/자산/기준일/**추세 점수(예측)**/**과거 평균 점수**/신뢰도)와 함께, 노란 경고색 `.prediction-disclaimer` 박스로 (1) "위 기계적 판정과는 완전히 별개이며 그 판정을 절대 대체하지 않는다"(LLM 총평·일목균형표와 동일한 advisory-only 원칙, 이 문서의 CLAUDE.md 규칙 16 참고), (2) 추세 점수의 정의(`log((매수일수+1)/(매도일수+1))`), (3) **왜 대부분 음수로 나오는지의 구조적 이유**(6.1절 내용을 리포트 disclaimer 문구에도 그대로 포함 — 사용자가 스펙과 리포트 양쪽에 반드시 표시해달라고 명시적으로 요청)를 명시한다. 예측값이 그 티커의 `historical_avg_score`보다 높으면 초록(`pnl-positive`), 낮으면 빨강(`pnl-negative`)으로 표시해 "0 기준이 아니라 자기 자신의 과거 평균 기준으로 비교"라는 원칙을 색상으로도 드러낸다. "신뢰도" 컬럼은 `train_baseline.py`가 계산해둔 `improvement_pct`(단순 평균 예측 대비 검증 MAE 개선율, %) 그대로 — 절대적인 정확도 보증이 아니라는 문구도 함께 넣었다.
- **검증**: 실제 Drive의 `feature_history.csv`/학습된 모델로 `generate_predictions.py`를 재실행해 12개 자산군 전부 정상적으로 예측이 생성되고(수정 전엔 1개만) `_prediction_simulation.json`이 Drive에 저장되는 것을 확인, `report_builder.build_daily_report_html`을 그 실제 데이터로 로컬 호출해 표/색상/경고 문구가 의도대로 렌더링되는 것도 확인했다. 타깃을 로그 비율로 바꾼 뒤 재학습·재생성까지 다시 실행해, 예를 들어 DBA(추세 점수 +0.111, 과거 평균 −1.101)처럼 최근이 그 자산의 평소보다 매수 우세로 예측된 케이스와 IEF/TLT/UNG처럼 평소보다도 더 매도 쪽으로 치우친 케이스가 실제로 색상 구분되어 나타나는 것을 확인했다.
- **LLM 해설 추가 (`openrouter_briefing.generate_prediction_commentary`, 사용자 요청)**: 표+정적 disclaimer만으로는 "이 숫자들을 종합하면 어떤 그림인지" 한눈에 안 들어온다는 이유로, 12개 자산군의 추세 점수·과거 평균을 프롬프트에 담아 한 문단으로 종합 해설하는 LLM 호출을 추가했다. 전용 시스템 프롬프트(`PREDICTION_COMMENTARY_SYSTEM_PROMPT`)가 6.1절의 "음수는 정상, 0이 아니라 과거 평균과 비교" 원칙을 그대로 반영하고, `generate_portfolio_overview`/`generate_recommendation`과 동일하게 "기계적 판정을 절대 바꾸지 않는다"와 "가격·방향성 예측·전망 문장 금지"를 명시한다 — 이 모델 자체가 이미 신호 빈도에 대한 예측이라, LLM이 거기에 가격 전망까지 얹지 않도록 막는 것이 핵심. `build_daily_report_html`이 `generate_portfolio_overview`와 동일한 패턴(`config.SKIP_LLM_AND_NEWS` 게이트 + try/except)으로 호출해 `_build_prediction_simulation_html`의 새 `commentary` 인자로 넘긴다 — 실패해도 표+disclaimer만으로 섹션은 그대로 렌더링된다. 실제 OpenRouter 호출로 검증 — 응답이 "BTC/DBA/DBB/DBC/GLD/USO/UUP는 과거 평균 상회, IEF/TLT/UNG는 평균 하회, QQQ/SPY는 양의 평균에서 음의 영역으로 전환" 등 실제 숫자 근거로 자산군별 상대 비교를 서술하는 것을 확인했다(가격 예측 문장 없이).

## 8. 이번 스코프에서 제외하는 것 (향후 확장 아이디어)

- **더 복잡한 모델**: 그래디언트 부스팅(LightGBM), 시퀀스 모델(GRU/LSTM), 자산군 간 교차 신호를 함께 쓰는 멀티-티커 모델 — 베이스라인이 하한선을 넘긴 것만 확인된 상태라, 다음 단계로 시도해볼 후보들.
- **Streamlit UI 통합**: 리포트에는 붙었지만(7절), Streamlit 탭에 노출하는 건 아직 스코프 밖 — 필요하면 별도로 논의.
- **모델 학습·예측 생성의 크론 자동화**: `generate_predictions.py`를 포함한 `prediction_model/`의 모든 스크립트는 여전히 수동 실행이며 `collect.yml`/`recommend.yml`에 편입하지 않는다(7절 "크론은 여전히 학습·예측을 하지 않는다" 참고) — 리포트가 매번 최신 30일 윈도우로 예측을 갱신하려면, 이 파이프라인 전체를 크론에 편입해야 하는데 그건 이번 스코프가 아니다. 지금은 마지막으로 수동 실행한 시점의 예측이 그대로 리포트에 반복 노출된다(각 티커의 `as_of_date`로 신선도를 확인 가능).
- **`walk_forward_split`의 다중 폴드화**: 지금은 단일 train/val 분할뿐 — 여러 시점에서 반복 검증하는 롤링 walk-forward CV는 필요하면 확장.
- **하이퍼파라미터 튜닝**: `RandomForestRegressor`는 고정값(`n_estimators=200, max_depth=8, min_samples_leaf=5`)만 썼다 — 그리드서치 등은 베이스라인 유효성을 먼저 확인한 뒤의 과제.

## 9. 구현 순서 제안 (착수 시 참고용)

1. ~~`feature_engineering.py` — 12개 자산군 피처 데이터셋 구축~~ (완료, 이 문서 3~4절).
2. ~~`feature_history.csv`를 `(X, y)` 슬라이딩 윈도우 배열로 변환하는 빌더 작성 + walk-forward 분할~~ (완료, `dataset_builder.py`, 이 문서 5절).
3. ~~베이스라인 모델 학습 + 평가~~ (완료, `train_baseline.py`, 이 문서 6절 — 12개 자산군 전부 단순 평균 베이스라인보다 낮은 MAE).
4. ~~일일 리포트 통합~~ (완료, `generate_predictions.py` + `report_builder.py`, 이 문서 7절).
5. 결과 검토 후, 더 복잡한 모델이나 Streamlit UI 통합 여부를 다음 단계로 논의(8절 참고).
