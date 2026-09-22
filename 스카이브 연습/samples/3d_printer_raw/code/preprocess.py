# author: 김민수
# 센서 원본 CSV를 윈도우 단위 특징으로 변환한다.
import numpy as np
import pandas as pd

WINDOW_SEC = 2
SAMPLE_HZ = 50


def denoise(series: pd.Series) -> pd.Series:
    # 이동중앙값으로 스파이크 노이즈 제거
    return series.rolling(5, center=True, min_periods=1).median()


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    size = WINDOW_SEC * SAMPLE_HZ
    rows = []
    for start in range(0, len(df) - size + 1, size):
        window = df.iloc[start : start + size]
        feats = {}
        for col in ["nozzle_temp", "bed_temp", "vibration"]:
            values = denoise(window[col]).to_numpy()
            feats[f"{col}_mean"] = float(np.mean(values))
            feats[f"{col}_std"] = float(np.std(values))
            feats[f"{col}_max"] = float(np.max(values))
        rows.append(feats)
    return pd.DataFrame(rows)
