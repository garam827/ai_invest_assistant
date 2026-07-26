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
- **`build_xy`**: `X`는 30일 윈도우 원본 피처 그대로(`(N, 30, 12, 9)`), `y`는 그다음 30일간 각 티커의 액션 원-핫만 평균 내 `[B, H, S]` 비율로 재정렬한 것(`(N, 12, 3)`) — 타깃 정의 자체는 `sample_code.py`와 동일, 계산 대상 배열만 더 풍부해졌다.
  - `y`의 세 값이 항상 1로 합산되지는 않는다는 점이 예상대로 확인됨 — 해당 30일 구간에 그 티커가 "미상장" 상태였던 날짜 비율만큼 합이 1보다 작아진다(예: BTC-USD 상장 이전 구간의 샘플은 `y` 합이 0). 버그가 아니라 설계대로의 동작.
- **`walk_forward_split`**: 무작위 셔플이 아니라 **시간순** 분할 — 검증 구간 이전 `PURGE_GAP`(=`X_WINDOW + Y_WINDOW - 1` = 59)개 샘플은 훈련셋에서 제외한다. 인접 슬라이딩 윈도우 샘플끼리 최대 59일이 겹치므로(4절에서 논의한 리키지 문제), 이 퍼지 구간 없이 시간순으로만 자르면 훈련 샘플의 `y` 구간이 검증 구간까지 침범할 수 있다.

**실행 결과 검증**: `X.shape == (6212, 30, 12, 9)`, `y.shape == (6212, 12, 3)`, 훈련 4,910 / 검증 1,243 샘플(퍼지 59개 제외), 날짜 범위 2007-01-03~2026-07-26. `X`/`y` 모두 `NaN` 없음 확인. SPY(상시 상장)는 모든 샘플에서 `y` 합이 1, BTC-USD는 상장 전 샘플에서 합이 0, 상장 후 샘플에서 합이 1 — 미상장 처리가 의도대로 동작함을 실제 배열로 확인했다.

산출물은 `prediction_model/dataset.npz`(`X`, `y`, `train_idx`, `val_idx`, `tickers`, `feature_names`, `dates` 포함, 약 1.9MB)로 저장되며, `feature_history.csv`와 마찬가지로 재실행하면 그대로 다시 만들어지는 산출물이라 `.gitignore` 대상이다.

## 6. 베이스라인 모델 (`prediction_model/train_baseline.py`, 구현 완료)

6,270일(사실상 슬라이딩 윈도우가 겹쳐 훨씬 적은 독립 샘플 수)이라는 규모를 감안해, 처음부터 LSTM/Transformer 같은 무거운 시퀀스 모델 대신 **티커별로 독립된 `RandomForestRegressor`**(scikit-learn, 새 의존성 추가 없음)부터 시작했다 — 과적합 리스크가 크기 때문에 단순한 모델로 성능 하한선을 먼저 확보하는 원칙(`triple_barrier_backtest_spec.md`가 "규칙 히트레이트부터 확인 후 ML 확장을 별도 스펙으로 논의"라고 못박은 것과 동일한 단계적 접근).

- **모델 구조**: 티커마다 별도 모델 — 그 티커 자신의 `(30일, 9피처)` 윈도우를 270차원으로 펼쳐 입력, `[매수, HOLD, 매도]` 3차원 비율을 동시에 회귀(`RandomForestRegressor`는 다중 출력을 기본 지원). 자산군 간 교차 신호(다른 11개 티커의 동시 상태)는 이번 베이스라인에서는 쓰지 않는다 — 우선 "그 자산 자신의 최근 패턴만으로 얼마나 맞힐 수 있는가"부터 확인.
- **상장 전 구간 제외**: `X` 윈도우의 마지막 날(예측 시점)에 그 티커가 "미상장" 원-핫이면 훈련/검증 양쪽에서 그 샘플을 제외한다 — 실제로는 예측을 요청할 일이 없는 시점(아직 상장 안 됐거나, 주식/ETF의 주말처럼 애초에 거래가 없는 날)이므로 학습에도 평가에도 넣지 않는 게 맞다. 이 필터를 거치면 BTC-USD(매일 거래)는 검증 샘플이 1,243개 그대로 남지만, 나머지 11개(평일만 거래)는 854개로 줄어든다 — 버그가 아니라 "주말에 대한 예측은 애초에 의미 없다"는 필터가 의도대로 동작한 것.
- **비교 기준선**: 무작위가 아니라 "훈련 구간의 평균 B/H/S 비율을 항상 예측"하는 단순 베이스라인과 비교 — 모델이 30일 윈도우의 실제 패턴에서 뭔가를 배웠는지, 그냥 평균으로 회귀했는지 구분하기 위함.

**실제 실행 결과** (MAE, 낮을수록 좋음 — 티커별 개선폭 내림차순):

| 티커 | 모델 MAE | 베이스라인 MAE | 개선폭 | 검증 샘플 수 |
| --- | --- | --- | --- | --- |
| BTC-USD | 0.1473 | 0.1741 | 0.0268 | 1,243 |
| SPY | 0.0828 | 0.1075 | 0.0247 | 854 |
| QQQ | 0.0901 | 0.1097 | 0.0196 | 854 |
| USO | 0.1187 | 0.1373 | 0.0186 | 854 |
| UUP | 0.1170 | 0.1350 | 0.0180 | 854 |
| TLT | 0.1223 | 0.1401 | 0.0179 | 854 |
| DBB | 0.1209 | 0.1379 | 0.0169 | 854 |
| DBA | 0.1191 | 0.1356 | 0.0166 | 854 |
| UNG | 0.1214 | 0.1373 | 0.0159 | 854 |
| GLD | 0.1137 | 0.1289 | 0.0152 | 854 |
| DBC | 0.1119 | 0.1265 | 0.0145 | 854 |
| IEF | 0.1173 | 0.1288 | 0.0115 | 854 |

12개 자산군 **전부** 단순 평균 베이스라인보다 낮은 MAE를 기록 — 모델이 30일 윈도우 패턴에서 뭔가 유의미한 걸 배우고 있다는 최소한의 근거는 확보됐다. 다만 개선폭 자체는 크지 않다(0.012~0.027) — "베이스라인이 하한선을 넘겼다" 정도로 보는 게 맞고, 실전에 쓸 만한 수준인지는 별도 판단이 필요하다.

모델 파일(`prediction_model/models/{ticker}_rf.joblib`, 약 47MB)과 결과 CSV는 재실행하면 다시 만들어지는 산출물이라 `.gitignore` 대상이다.

## 7. 일일 리포트 통합 (`prediction_model/generate_predictions.py` + `report_builder.py`, 구현 완료)

사용자가 "베이스라인 결과가 나온 상태에서 바로 리포트에 넣고, 대신 신뢰도를 같이 보여주자"고 결정 — 원래 이 문서 초안에서 "유의미한 결과가 나온 뒤에야 논의"로 미뤄뒀던 항목이지만, 신뢰도(검증 MAE 개선율)를 함께 노출하는 조건으로 먼저 붙였다.

- **크론은 여전히 학습·예측을 하지 않는다**: `prediction_model/generate_predictions.py`(로컬/수동 실행)가 `train_baseline.py`가 저장한 모델(`prediction_model/models/*.joblib`)로 최신 30일 윈도우에 대한 예측을 만들어, Drive에 `_prediction_simulation.json`으로 저장한다. `recommendation_engine.run_asset_class_recommendations`는 그 파일을 `drive_db.load_json`으로 **읽기만** 한다 — 파일이 없거나 로드 실패해도 다른 선택적 섹션(모의 투자, 시그널 이력)과 동일하게 그 섹션만 생략된다. 필터명 상수(`_prediction_simulation.json`)는 `recommendation_engine.PREDICTION_SIMULATION_FILENAME`과 `generate_predictions.PREDICTION_SIMULATION_FILENAME` 두 곳에 각각 정의돼 있으므로(순환 참조 방지를 위해 `prediction_model/`을 프로덕션 모듈이 import하지 않음, 4절 참고) 파일명을 바꿀 땐 두 곳 다 같이 고칠 것.
- **버그: "가장 최근 날짜"가 종목마다 다름**: 최초 구현은 `feature_history.csv`를 피벗한 전체 배열의 마지막 행(모든 티커 공통 날짜축의 최신 날짜)을 그대로 예측 시점으로 썼다. 그런데 BTC-USD는 주말에도 거래해 배열의 마지막 행이 토요일/일요일이 되는 경우가 있고, 그날은 나머지 11개 자산군엔 애초에 시세 자체가 없어 "미상장" 원-핫으로 채워진다(2절/`dataset_builder.py`의 union-of-dates 처리와 동일한 원리) — 그 결과 실제 실행에서 BTC-USD 하나만 예측되고 나머지 11개는 전부 스킵되는 문제가 발생했다. `generate_predictions._latest_window(array, ticker_idx, x_window)`로 수정해, 티커마다 "그 티커 자신의 마지막 실제 거래일"까지 배열을 거슬러 올라가 그 날짜로 끝나는 30일 윈도우를 찾도록 고쳤다. 그 결과 `_prediction_simulation.json`의 각 티커 예측에 자기 자신의 `as_of_date`가 따로 붙는다(주식/ETF는 보통 금요일, BTC-USD는 그 이후 주말 날짜까지) — 리포트 표에도 "기준일" 컬럼으로 그대로 노출한다.
- **`report_builder._build_prediction_simulation_html`**: "AI 예측 시뮬레이션 (실험적)" 섹션을 페이지 맨 끝(HOLD 차트 블록 뒤)에 추가 — 표(티커/자산/기준일/예상 매수·HOLD·매도%/신뢰도)와 함께, 노란 경고색 `.prediction-disclaimer` 박스로 "위 기계적 판정과는 완전히 별개이며 그 판정을 절대 대체하지 않는다"를 명시한다(LLM 총평·일목균형표와 동일한 advisory-only 원칙, 이 문서의 CLAUDE.md 규칙 16 참고). "신뢰도" 컬럼은 `train_baseline.py`가 계산해둔 `improvement_pct`(단순 평균 예측 대비 검증 MAE 개선율, %) 그대로 — 절대적인 정확도 보증이 아니라는 문구도 함께 넣었다.
- **검증**: 실제 Drive의 `feature_history.csv`/학습된 모델로 `generate_predictions.py`를 재실행해 12개 자산군 전부 정상적으로 예측이 생성되고(수정 전엔 1개만) `_prediction_simulation.json`이 Drive에 저장되는 것을 확인, `report_builder.build_daily_report_html`을 그 실제 데이터로 로컬 호출해 표/경고 문구가 의도대로 렌더링되는 것도 확인했다.

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
