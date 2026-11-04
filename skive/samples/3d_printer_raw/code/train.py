# author: 김민수
# 정상 데이터만으로 Autoencoder를 학습하고 임계값을 정한다.
import numpy as np
import torch
from torch import nn


class AutoEncoder(nn.Module):
    def __init__(self, dim: int = 9):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(dim, 6), nn.ReLU(), nn.Linear(6, 3))
        self.dec = nn.Sequential(nn.Linear(3, 6), nn.ReLU(), nn.Linear(6, dim))

    def forward(self, x):
        return self.dec(self.enc(x))


def fit(model, normal: torch.Tensor, epochs: int = 200):
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(model(normal), normal)
        loss.backward()
        opt.step()


def pick_threshold(errors: np.ndarray, percentile: float = 99.0) -> float:
    # 검증용 정상 데이터의 재구성 오차 상위 백분위수를 임계값으로 사용
    return float(np.percentile(errors, percentile))
