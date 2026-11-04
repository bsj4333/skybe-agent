# author: 김민수
import numpy as np
from sklearn.ensemble import IsolationForest


def make_features(temp: np.ndarray, window: int = 30) -> np.ndarray:
    # 서서히 벗어나는 이상을 잡기 위해 절대값 대신 변화율과 구간 편차를 사용
    diff = np.diff(temp, prepend=temp[0])
    rows = []
    for i in range(window, len(temp)):
        seg = temp[i - window : i]
        rows.append([diff[i], seg.std(), seg.mean() - temp[:window].mean()])
    return np.array(rows)


def fit_detector(features: np.ndarray) -> IsolationForest:
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=0)
    model.fit(features)
    return model
