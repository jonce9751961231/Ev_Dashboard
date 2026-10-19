"""Two baselines and four ML models behind one small interface.

Every model predicts the temperature RISE (deg C) at each horizon in
config.HORIZONS_MIN and returns an array of shape (N, n_horizons).

Baselines (not candidates, only yardsticks):
    persistence  - "temperature stays the same"
    physics_fit  - first-order heating curve with parameters fitted to data
Models:
    ridge, random_forest, lightgbm, gru
"""
from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path

import joblib
import numpy as np

from . import config as C
from .data import Batch

try:                                   # optional dependency
    import lightgbm as lgb
except ImportError:                    # pragma: no cover
    lgb = None
try:                                   # optional dependency
    import torch
    from torch import nn
except ImportError:                    # pragma: no cover
    torch = None
    nn = None


class BaseModel:
    name = "base"
    needs_seq = False
    is_baseline = False

    @classmethod
    def available(cls) -> bool:
        return True

    def fit(self, train: Batch, val: Batch) -> "BaseModel":
        return self

    def predict(self, batch: Batch) -> np.ndarray:
        raise NotImplementedError

    def save(self, folder: Path) -> Path | None:
        return None

    @classmethod
    def load(cls, folder: Path) -> "BaseModel":
        return cls()


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------
class Persistence(BaseModel):
    name = "persistence"
    is_baseline = True

    def predict(self, batch):
        return np.zeros((len(batch), len(C.HORIZONS_MIN)))


class PhysicsFit(BaseModel):
    """dT(h) = (T_inf - T) * (1 - exp(-h / tau)),
    T_inf = ambient + a*I^2 + b*rpm/1000 + c, with tau, a, b, c fitted."""
    name = "physics_fit"
    is_baseline = True

    def __init__(self, params: dict | None = None):
        self.params = params

    @staticmethod
    def _delta(p, T, amb, cur, rpm):
        t_inf = amb + p[1] * cur ** 2 + p[2] * rpm / 1000.0 + p[3]
        h = np.array(C.HORIZONS_MIN, dtype=float) * 60.0
        return (t_inf - T)[:, None] * (1.0 - np.exp(-h[None, :] / p[0]))

    def fit(self, train, val):
        from scipy.optimize import least_squares
        rng = np.random.default_rng(C.SEED)
        idx = rng.choice(len(train), size=min(len(train), 20000), replace=False)
        T, amb, cur, rpm = (train.col(c)[idx] for c in
                            ("temp_c", "ambient_temp_c", "current_a", "rpm"))
        y = train.y[idx]
        fit = least_squares(lambda p: (self._delta(p, T, amb, cur, rpm) - y).ravel(),
                            x0=[300.0, 0.5, 1.0, 0.0],
                            bounds=([10, -50, -50, -50], [50000, 50, 50, 50]),
                            x_scale="jac")
        self.params = dict(zip(("tau_s", "a", "b", "c"), map(float, fit.x)))
        return self

    def predict(self, batch):
        p = [self.params[k] for k in ("tau_s", "a", "b", "c")]
        return self._delta(p, batch.col("temp_c"), batch.col("ambient_temp_c"),
                           batch.col("current_a"), batch.col("rpm"))

    def save(self, folder):
        path = Path(folder) / "physics_fit.json"
        path.write_text(json.dumps(self.params, indent=2))
        return path

    @classmethod
    def load(cls, folder):
        return cls(json.loads((Path(folder) / "physics_fit.json").read_text()))


# --------------------------------------------------------------------------
# Machine-learning models
# --------------------------------------------------------------------------
class RidgeModel(BaseModel):
    name = "ridge"

    def fit(self, train, val):
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        best = None
        for alpha in (0.1, 1.0, 10.0, 100.0, 1000.0):     # alpha picked on val
            pipe = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
            pipe.fit(train.X, train.y)
            err = float(np.abs(pipe.predict(val.X) - val.y).mean())
            if best is None or err < best[0]:
                best = (err, alpha, pipe)
        _, self.alpha, self.pipe = best
        return self

    def predict(self, batch):
        return self.pipe.predict(batch.X)

    def save(self, folder):
        path = Path(folder) / "ridge.joblib"
        joblib.dump(self.pipe, path)
        return path

    @classmethod
    def load(cls, folder):
        m = cls()
        m.pipe = joblib.load(Path(folder) / "ridge.joblib")
        return m


class ForestModel(BaseModel):
    name = "random_forest"

    def fit(self, train, val):
        from sklearn.ensemble import RandomForestRegressor
        self.forest = RandomForestRegressor(
            n_estimators=200, min_samples_leaf=5, max_features=0.5,
            n_jobs=-1, random_state=C.SEED)
        self.forest.fit(train.X, train.y)
        return self

    def predict(self, batch):
        return self.forest.predict(batch.X)

    def save(self, folder):
        path = Path(folder) / "random_forest.joblib"
        joblib.dump(self.forest, path, compress=3)
        return path

    @classmethod
    def load(cls, folder):
        m = cls()
        m.forest = joblib.load(Path(folder) / "random_forest.joblib")
        return m


class LightGBMModel(BaseModel):
    name = "lightgbm"

    @classmethod
    def available(cls):
        return lgb is not None

    def fit(self, train, val):
        self.models = []
        for j in range(train.y.shape[1]):                 # one model per horizon
            m = lgb.LGBMRegressor(
                n_estimators=600, learning_rate=0.05, num_leaves=15,
                min_child_samples=20, subsample=0.8, subsample_freq=1,
                colsample_bytree=0.8, random_state=C.SEED, verbose=-1)
            with warnings.catch_warnings():   # newer LightGBM renames eval_set
                warnings.filterwarnings("ignore", message=".*eval_set.*")
                m.fit(train.X, train.y[:, j],
                      eval_set=[(val.X, val.y[:, j])], eval_metric="l1",
                      callbacks=[lgb.early_stopping(30, verbose=False)])
            self.models.append(m)
        return self

    def predict(self, batch):
        return np.column_stack([m.predict(batch.X) for m in self.models])

    def save(self, folder):
        path = Path(folder) / "lightgbm.joblib"
        joblib.dump(self.models, path, compress=3)
        return path

    @classmethod
    def load(cls, folder):
        m = cls()
        m.models = joblib.load(Path(folder) / "lightgbm.joblib")
        return m


if torch is not None:
    class _GRUNet(nn.Module):
        def __init__(self, n_in, hidden, n_out):
            super().__init__()
            self.gru = nn.GRU(n_in, hidden, batch_first=True)
            self.head = nn.Linear(hidden, n_out)

        def forward(self, x):
            out, _ = self.gru(x)
            return self.head(out[:, -1])


class GRUModel(BaseModel):
    """Reads the last WINDOW_S seconds of sensor history as a sequence."""
    name = "gru"
    needs_seq = True

    def __init__(self, hidden=32, epochs=60, patience=8, lr=2e-3, batch_size=256):
        self.hidden, self.epochs, self.patience = hidden, epochs, patience
        self.lr, self.batch_size = lr, batch_size

    @classmethod
    def available(cls):
        return torch is not None

    def _tensor(self, seq):
        return torch.tensor((seq - self.x_mean) / self.x_std, dtype=torch.float32)

    def fit(self, train, val):
        torch.manual_seed(C.SEED)
        g = train.seq.shape[2]
        flat = train.seq.reshape(-1, g)
        self.x_mean, self.x_std = flat.mean(axis=0), flat.std(axis=0) + 1e-6
        self.y_std = train.y.std(axis=0) + 1e-6
        self.net = _GRUNet(g, self.hidden, train.y.shape[1])
        xt = self._tensor(train.seq)
        yt = torch.tensor(train.y / self.y_std, dtype=torch.float32)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        loss_fn = nn.SmoothL1Loss()
        best_err, best_state, wait = float("inf"), None, 0
        for _ in range(self.epochs):
            self.net.train()
            order = torch.randperm(len(xt))
            for i in range(0, len(xt), self.batch_size):
                b = order[i:i + self.batch_size]
                opt.zero_grad()
                loss_fn(self.net(xt[b]), yt[b]).backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                opt.step()
            err = float(np.abs(self.predict(val) - val.y).mean())
            if err < best_err - 1e-4:                    # early stopping on val
                best_err, wait = err, 0
                best_state = copy.deepcopy(self.net.state_dict())
            else:
                wait += 1
                if wait >= self.patience:
                    break
        self.net.load_state_dict(best_state)
        self.net.eval()
        return self

    def predict(self, batch):
        self.net.eval()
        with torch.no_grad():
            out = self.net(self._tensor(batch.seq)).numpy()
        return out * self.y_std

    def save(self, folder):
        path = Path(folder) / "gru.pt"
        torch.save({"state": self.net.state_dict(), "hidden": self.hidden,
                    "x_mean": self.x_mean.tolist(), "x_std": self.x_std.tolist(),
                    "y_std": self.y_std.tolist()}, path)
        return path

    @classmethod
    def load(cls, folder):
        blob = torch.load(Path(folder) / "gru.pt", map_location="cpu",
                          weights_only=True)
        m = cls(hidden=blob["hidden"])
        m.x_mean, m.x_std = np.array(blob["x_mean"]), np.array(blob["x_std"])
        m.y_std = np.array(blob["y_std"])
        m.net = _GRUNet(len(m.x_mean), m.hidden, len(m.y_std))
        m.net.load_state_dict(blob["state"])
        m.net.eval()
        return m


MODEL_CLASSES = {c.name: c for c in
                 (Persistence, PhysicsFit, RidgeModel, ForestModel,
                  LightGBMModel, GRUModel)}
CANDIDATES = ("ridge", "random_forest", "lightgbm", "gru")


def load_model(name: str, folder) -> BaseModel:
    return MODEL_CLASSES[name].load(Path(folder))
