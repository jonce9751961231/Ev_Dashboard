"""Live forecasting with whichever model the registry selected.

    predictor = ThermalPredictor()
    predictor.push(voltage_v, current_a, rpm, temp_c, ambient_temp_c)   # every sample
    result = predictor.predict()          # None until enough history has built up

The predictor averages incoming samples into the same spacing used in
training, then calls the SAME feature code as the trainer.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .data import Batch, add_features, steps
from .models import load_model


class ThermalPredictor:
    def __init__(self, artifact_dir=None, model_name: str | None = None):
        folder = Path(artifact_dir or C.ARTIFACT_DIR)
        registry_path = folder / "registry.json"
        if not registry_path.exists():
            raise FileNotFoundError(
                f"{registry_path} not found. Run: python -m core_server.ml.train_all "
                f"--data <your csv files>")
        self.registry = json.loads(registry_path.read_text())
        self.model_name = model_name or self.registry["best_model"]
        self.interval_s = float(self.registry["interval_s"])
        self.horizons = list(self.registry["horizons_min"])
        self.feature_names = list(self.registry["feature_names"])
        self.window_steps = int(self.registry["window_steps"])
        lag_steps = max(steps(lag, self.interval_s) for lag in self.registry["lag_s"])
        self.needed = max(lag_steps + 1, self.window_steps)
        self.folder = folder
        self._loaded_models = {}
        self.model = self._get_model(self.model_name)
        self._rows: deque = deque(maxlen=self.needed + 5)
        self.reset()

    def _get_model(self, name: str):
        if name not in self._loaded_models:
            self._loaded_models[name] = load_model(name, self.folder)
        return self._loaded_models[name]

    def set_model(self, name: str) -> str:
        if name not in self.registry["models"]:
            raise ValueError(f"Unknown model '{name}'. Available: {list(self.registry['models'].keys())}")
        self.model_name = name
        self.model = self._get_model(name)
        return self.model_name

    def reset(self) -> None:
        self._rows.clear()
        self._acc: list = []
        self._bin_start = None
        self._last_push = None

    def push(self, voltage_v, current_a, rpm, temp_c, ambient_temp_c, now=None) -> None:
        """Feed one raw sample. Missing or non-finite samples are ignored, and a
        long silence clears the history so stale data is never used."""
        now = time.monotonic() if now is None else now
        values = [voltage_v, current_a, rpm, temp_c, ambient_temp_c]
        if any(v is None or not math.isfinite(v) for v in values):
            return
        if self._last_push is not None and now - self._last_push > 3 * self.interval_s:
            self.reset()
        self._last_push = now
        if self._bin_start is None:
            self._bin_start = now
        self._acc.append(values)
        if now - self._bin_start >= self.interval_s:
            self._rows.append(np.mean(self._acc, axis=0))
            self._acc, self._bin_start = [], now

    def status(self) -> dict:
        have = len(self._rows)
        return {"ready": have >= self.needed, "have": have, "need": self.needed,
                "seconds_to_ready": max(0, self.needed - have) * self.interval_s,
                "model": self.model_name}

    def predict(self) -> dict | None:
        if len(self._rows) < self.needed:
            return None
        df = pd.DataFrame(list(self._rows), columns=C.BASE_COLS)
        feat = add_features(df, self.interval_s)
        last = feat.iloc[-1]
        X = last[self.feature_names].to_numpy(dtype=float)[None, :]
        if not np.isfinite(X).all():
            return None
        seq = None
        if self.model.needs_seq:
            seq = feat[C.GRU_COLS].to_numpy(dtype=float)[-self.window_steps:][None]
        delta = self.model.predict(Batch(X, self.feature_names, seq=seq))[0]
        temp = float(last["temp_c"])
        return {"model": self.model_name, "temp_now_c": temp,
                "forecast_c": {f"{m}m": temp + float(d)
                               for m, d in zip(self.horizons, delta)}}

    def predict_all(self) -> dict:
        """Returns predictions for all registered models so the UI can toggle instantly."""
        if len(self._rows) < self.needed:
            return {}
        df = pd.DataFrame(list(self._rows), columns=C.BASE_COLS)
        feat = add_features(df, self.interval_s)
        last = feat.iloc[-1]
        X = last[self.feature_names].to_numpy(dtype=float)[None, :]
        if not np.isfinite(X).all():
            return {}
        temp = float(last["temp_c"])
        seq = None
        results = {}
        for name in self.registry["models"].keys():
            try:
                m = self._get_model(name)
                m_seq = None
                if m.needs_seq:
                    if seq is None:
                        seq = feat[C.GRU_COLS].to_numpy(dtype=float)[-self.window_steps:][None]
                    m_seq = seq
                delta = m.predict(Batch(X, self.feature_names, seq=m_seq))[0]
                results[name] = {f"{h}m": round(temp + float(d), 2)
                                 for h, d in zip(self.horizons, delta)}
            except Exception:
                results[name] = None
        return results
