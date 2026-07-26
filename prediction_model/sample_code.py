import numpy as np
import pandas as pd

# ---------------------------------------------------------
# 1. 데이터 로드 및 기본 데이터 정제
# ---------------------------------------------------------
file_path = 'signal_history.csv'
df = pd.read_csv(file_path)

# 날짜 기준 정렬 및 필터링
df = df.sort_values(by='날짜')
start_date = '2007-04-18'

df_cleaned = df.loc[df['날짜'] >= start_date].copy()
df_cleaned.set_index('날짜', inplace=True)

if '링크' in df_cleaned.columns:
    df_cleaned.drop(columns='링크', inplace=True)

# ---------------------------------------------------------
# 2. 신호(Signal) One-Hot 인코딩 매핑
# ---------------------------------------------------------
# 원-핫 매핑 순서 지정: [H, S, B, -]
signal_mapping = {
    'H': np.array([1, 0, 0, 0]),
    'S': np.array([0, 1, 0, 0]),
    'B': np.array([0, 0, 1, 0]),
    '-': np.array([0, 0, 0, 1]),
}

# 모든 셀을 4차원 벡터로 변환
df_transformed = df_cleaned.map(lambda x: signal_mapping.get(x, signal_mapping['-']))

# (전체 일수, 종목 수, 4) 형태의 3차원 NumPy 배열로 변환
array = np.array(df_transformed.to_numpy().tolist())

# ---------------------------------------------------------
# 3. 슬라이딩 윈도우(Sliding Window) 기반 X, y 데이터셋 구축
# ---------------------------------------------------------
X_window_size = 30
y_window_size = 30

X_data = []
y_data = []

# 전체 데이터 길이
total_len = len(array)

# 윈도우를 1씩 이동하며 추출 가능한 최대 index까지 반복
for idx in range(total_len - X_window_size - y_window_size + 1):
    # 인덱스 범위 설정
    X_l = idx
    X_r = idx + X_window_size
    y_l = X_r
    y_r = X_r + y_window_size
    
    # 1) X 데이터 추출: (30, 종목수, 4)
    X_array = array[X_l : X_r]
    
    # 2) y 데이터 추출 (NumPy 고속 벡터화 연산)
    # y_slice 형태: (30, 종목수, 4) -> 0:H, 1:S, 2:B, 3:-
    y_slice = array[y_l : y_r]
    
    # 각 종목별 30일간 [H, S, B, -] 신호 발생 비율 계산 (shape: 종목수, 4)
    mean_probs = y_slice.mean(axis=0)
    
    # 원하는 출력 순서인 [B, H, S] 비율만 추출 (인덱스 2:B, 0:H, 1:S)
    probs_bhs = mean_probs[:, [2, 0, 1]] # shape: (종목수, 3)
    
    # 리스트에 추가
    X_data.append(X_array)
    y_data.append(probs_bhs)

# ---------------------------------------------------------
# 4. 최종 NumPy 배열 변환 및 Shape 확인
# ---------------------------------------------------------
X_data = np.array(X_data)  # (샘플 수, 30, 종목수, 4)
y_data = np.array(y_data)  # (샘플 수, 종목수, 3)

print("=== 데이터셋 구축 완료 ===")
print(f"X_data Shape : {X_data.shape}")  # (N, 30, num_stocks, 4)
print(f"y_data Shape : {y_data.shape}")  # (N, num_stocks, 3)