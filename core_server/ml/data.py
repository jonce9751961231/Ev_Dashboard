"""Load recorded runs, build features/targets, and split without leakage.

Key rules (these are what make the model scores honest):
  * Features use only the past. Targets are the temperature CHANGE at each
    horizon, taken from the real future. Rows with no real future are dropped
    (never back-filled).
  * Splits are by whole run, or by time order with a purge gap. Never shuffled.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from . import config as C


def steps(seconds: float, interval_s: float) -> int:
    return max(1, int(round(seconds / interval_s)))


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {c: C.COLUMN_ALIASES.get(c.strip().lower(), c.strip().lower())
              for c in df.columns}
    return df.rename(columns=rename)


def _resample(df: pd.DataFrame, interval_s: float,
              source_interval_s: float) -> pd.DataFrame:
    """Put one run on a regular grid. Gaps stay as NaN (they are never faked)."""
    if "timestamp_ms" in df.columns and df["timestamp_ms"].notna().all():
        t = (df["timestamp_ms"] - df["timestamp_ms"].iloc[0]) / 1000.0
    else:
        t = pd.Series(np.arange(len(df)) * source_interval_s, index=df.index)
    sub = df[C.BASE_COLS].copy()
    sub.index = pd.to_timedelta(t.to_numpy(), unit="s")
    grid = sub.resample(pd.Timedelta(seconds=interval_s)).mean()
    # Bridge only tiny holes (<= 3 steps); longer gaps stay NaN.
    return grid.interpolate(limit=3, limit_area="inside").reset_index(drop=True)


def load_runs(paths, interval_s: float = C.INTERVAL_S,
              source_interval_s: float | None = None) -> dict[str, pd.DataFrame]:
    """Return {run_id: DataFrame on a regular grid} from one or more CSV files.

    One file = one run, unless the file has a run_id column.
    source_interval_s is the row spacing for files without timestamp_ms.
    """
    source_interval_s = source_interval_s or interval_s
    runs: dict[str, pd.DataFrame] = {}
    for path in paths:
        stem = Path(path).stem
        df = _canonical_columns(pd.read_csv(path))
        missing = [c for c in C.BASE_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}. "
                             f"Need {C.BASE_COLS} (plus optional timestamp_ms, run_id).")
        for col in C.BASE_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")  # blanks -> NaN
        if "run_id" in df.columns:
            groups = [(f"{stem}:{rid}", g.reset_index(drop=True))
                      for rid, g in df.groupby("run_id", sort=False)]
        else:
            groups = [(stem, df)]
        for rid, g in groups:
            runs[rid] = _resample(g, interval_s, source_interval_s)
    if not runs:
        raise ValueError("No runs loaded.")
    return runs


# --------------------------------------------------------------------------
# Features and targets
# --------------------------------------------------------------------------
def add_features(df: pd.DataFrame, interval_s: float) -> pd.DataFrame:
    """Past-only features. Used for BOTH training and live prediction."""
    out = df.copy()
    out["power_w"] = out["voltage_v"] * out["current_a"]
    out["current_sq"] = out["current_a"] ** 2
    out["temp_above_ambient"] = out["temp_c"] - out["ambient_temp_c"]
    for lag in C.LAG_S:
        k = steps(lag, interval_s)
        out[f"dtemp_{lag}s"] = out["temp_c"] - out["temp_c"].shift(k)
        out[f"i_mean_{lag}s"] = out["current_a"].rolling(k, min_periods=k).mean()
        out[f"rpm_mean_{lag}s"] = out["rpm"].rolling(k, min_periods=k).mean()
    return out


def add_targets(df: pd.DataFrame, interval_s: float) -> pd.DataFrame:
    out = df.copy()
    for m, name in zip(C.HORIZONS_MIN, C.TARGET_NAMES):
        k = steps(m * 60, interval_s)
        out[name] = out["temp_c"].shift(-k) - out["temp_c"]
    return out


@dataclass
class Dataset:
    frame: pd.DataFrame               # one row per usable sample
    series: dict[str, np.ndarray]     # run_id -> (T, G) GRU inputs on the grid
    run_lengths: dict[str, int]
    interval_s: float
    window_steps: int


def build_dataset(runs: dict[str, pd.DataFrame], interval_s: float) -> Dataset:
    window = steps(C.WINDOW_S, interval_s)
    frames, series, lengths = [], {}, {}
    for rid, df in runs.items():
        feat = add_targets(add_features(df, interval_s), interval_s)
        window_ok = (feat[C.GRU_COLS].notna().all(axis=1)
                     .rolling(window).sum() == window)
        keep = (feat[C.FEATURE_NAMES].notna().all(axis=1)
                & feat[C.TARGET_NAMES].notna().all(axis=1) & window_ok)
        feat["run_id"] = rid
        feat["pos"] = np.arange(len(feat))
        series[rid] = feat[C.GRU_COLS].to_numpy(dtype=float)
        lengths[rid] = len(feat)
        frames.append(feat[keep])
    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        raise ValueError(
            "No usable rows. Each run needs to be longer than the longest "
            "look-back (10 min) plus the longest horizon (30 min).")
    return Dataset(frame, series, lengths, interval_s, window)


# --------------------------------------------------------------------------
# Batches handed to the models
# --------------------------------------------------------------------------
@dataclass
class Batch:
    X: np.ndarray                          # (N, F) tabular features
    feature_names: list
    y: np.ndarray | None = None            # (N, H) temperature rise targets
    seq: np.ndarray | None = None          # (N, W, G) GRU windows

    def col(self, name: str) -> np.ndarray:
        return self.X[:, self.feature_names.index(name)]

    def __len__(self) -> int:
        return len(self.X)


def make_batch(ds: Dataset, idx: np.ndarray, with_seq: bool = True) -> Batch:
    rows = ds.frame.iloc[idx]
    X = rows[C.FEATURE_NAMES].to_numpy(dtype=float)
    y = rows[C.TARGET_NAMES].to_numpy(dtype=float)
    seq = None
    if with_seq:
        w, g = ds.window_steps, len(C.GRU_COLS)
        seq = np.empty((len(rows), w, g))
        run_ids = rows["run_id"].to_numpy()
        pos = rows["pos"].to_numpy()
        for rid in np.unique(run_ids):
            m = run_ids == rid
            wins = sliding_window_view(ds.series[rid], w, axis=0)  # (T-w+1, G, w)
            seq[m] = wins[pos[m] - w + 1].transpose(0, 2, 1)
    return Batch(X, list(C.FEATURE_NAMES), y, seq)


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------
def split_dataset(ds: Dataset, val_frac: float = 0.15, test_frac: float = 0.15,
                  mode: str = "auto", seed: int = C.SEED):
    """Return ({'train','val','test': row positions}, description).

    mode 'runs'  : whole runs go to one split (needs >= 5 runs for 'auto').
    mode 'chrono': inside every run, early part trains, middle validates, last
                   part tests. Rows whose target window reaches into the next
                   segment are purged, so no future data leaks backwards.
    """
    frame = ds.frame
    run_ids = list(ds.run_lengths)
    if mode == "auto":
        mode = "runs" if len(run_ids) >= 5 else "chrono"

    if mode == "runs":
        order = [str(r) for r in np.random.default_rng(seed).permutation(run_ids)]
        n_test = max(1, round(test_frac * len(order)))
        n_val = max(1, round(val_frac * len(order)))
        assign = {r: "test" for r in order[:n_test]}
        assign |= {r: "val" for r in order[n_test:n_test + n_val]}
        assign |= {r: "train" for r in order[n_test + n_val:]}
        labels = frame["run_id"].map(assign).to_numpy()
        parts = {p: np.flatnonzero(labels == p) for p in ("train", "val", "test")}
        desc = (f"whole-run split: {len(order) - n_test - n_val} train / "
                f"{n_val} val / {n_test} test runs (test runs: "
                f"{', '.join(order[:n_test])})")
    elif mode == "chrono":
        k_max = steps(max(C.HORIZONS_MIN) * 60, ds.interval_s)
        rid_arr = frame["run_id"].to_numpy()
        pos = frame["pos"].to_numpy()
        pieces = {"train": [], "val": [], "test": []}
        for rid in run_ids:
            m = rid_arr == rid
            n = ds.run_lengths[rid]
            b1 = int(n * (1 - val_frac - test_frac))
            b2 = int(n * (1 - test_frac))
            pieces["train"].append(np.flatnonzero(m & (pos < b1 - k_max)))
            pieces["val"].append(np.flatnonzero(m & (pos >= b1) & (pos < b2 - k_max)))
            pieces["test"].append(np.flatnonzero(m & (pos >= b2)))
        parts = {p: np.concatenate(v) for p, v in pieces.items()}
        desc = (f"time-ordered split inside each of {len(run_ids)} run(s): first "
                f"{1 - val_frac - test_frac:.0%} train, next {val_frac:.0%} val, "
                f"last {test_frac:.0%} test, with a {k_max * ds.interval_s / 60:.0f}-min "
                f"purge gap")
    else:
        raise ValueError(f"unknown split mode {mode!r}")

    for name, idx in parts.items():
        if len(idx) == 0:
            raise ValueError(
                f"The {name} split is empty. You need more or longer runs "
                f"(try --split chrono, or record more runs).")
    return parts, desc
