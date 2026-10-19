"""Generate DEMO runs for trying the pipeline. NOT real motor data.

    python -m core_server.ml.synth --out datasets/demo --runs 8

Each run is a first-order thermal system driven by random step loads, with
sensor noise. Because the model is this simple, scores on demo data say
nothing about how well the models will do on your real motor.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

TAU_S, A_PER_A2, B_PER_KRPM = 600.0, 0.8, 1.5     # hidden "motor" constants


def simulate_run(minutes: float = 120, interval_s: float = 10.0,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    rng = rng or np.random.default_rng(0)
    n = int(minutes * 60 / interval_s)
    ambient = rng.uniform(20, 36)
    temp = ambient + rng.uniform(0, 8)
    load = np.zeros(n)
    i = 0
    while i < n:                                   # random step loads, 3-15 min
        length = int(rng.uniform(3, 15) * 60 / interval_s)
        load[i:i + length] = rng.choice([0.0, 0.3, 0.6, 1.0])
        i += length
    rows = []
    for k in range(n):
        current = 0.0 if load[k] == 0 else 0.5 + 4.5 * load[k]
        rpm = 0.0 if load[k] == 0 else 600 + 2600 * load[k]
        t_inf = ambient + A_PER_A2 * current ** 2 + B_PER_KRPM * rpm / 1000.0
        temp += interval_s * (t_inf - temp) / TAU_S
        rows.append({
            "timestamp_ms": int(k * interval_s * 1000),
            "voltage_v": 12.0 - 0.3 * current + rng.normal(0, 0.05),
            "current_a": max(0.0, current + rng.normal(0, 0.08)),
            "rpm": max(0.0, rpm + rng.normal(0, 20)),
            "temp_c": temp + rng.normal(0, 0.05),
            "ambient_temp_c": ambient + rng.normal(0, 0.05),
        })
    return pd.DataFrame(rows)


def write_demo_csvs(folder, n_runs: int = 8, minutes: float = 120,
                    interval_s: float = 10.0, seed: int = 0) -> list:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    paths = []
    for r in range(1, n_runs + 1):
        path = folder / f"demo_run{r:02d}.csv"
        simulate_run(minutes, interval_s, rng).to_csv(path, index=False)
        paths.append(str(path))
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="datasets/demo")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--minutes", type=float, default=120)
    args = ap.parse_args()
    for p in write_demo_csvs(args.out, args.runs, args.minutes):
        print("wrote", p)
