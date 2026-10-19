"""Metrics, timing and the human-readable comparison report."""
from __future__ import annotations

import time

import numpy as np

from .data import Batch


def horizon_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """MAE and RMSE per horizon, in deg C. (Error on the temperature rise is
    identical to error on the absolute future temperature.)"""
    err = y_pred - y_true
    return {"mae": np.abs(err).mean(axis=0).tolist(),
            "rmse": np.sqrt((err ** 2).mean(axis=0)).tolist()}


def skill(mae: list, baseline_mae: list) -> list:
    """1.0 = perfect, 0.0 = no better than 'temperature stays the same'."""
    return [1.0 - m / b if b > 0 else 0.0 for m, b in zip(mae, baseline_mae)]


def time_inference(model, batch: Batch, repeats: int = 30) -> float:
    """Milliseconds for one single-sample prediction."""
    one = Batch(batch.X[:1], batch.feature_names,
                seq=None if batch.seq is None else batch.seq[:1])
    model.predict(one)                                   # warm-up
    start = time.perf_counter()
    for _ in range(repeats):
        model.predict(one)
    return (time.perf_counter() - start) / repeats * 1000.0


def _row(label: str, values: list, fmt: str) -> str:
    cells = " | ".join(format(v, fmt) for v in values)
    return f"| {label} | {cells} |"


def build_report(results: list, meta: dict) -> str:
    hz = meta["horizons_min"]
    head = " | ".join(f"+{m} min" for m in hz)
    sep = "|---|" + "---|" * (len(hz) + 1)
    base = next(r for r in results if r["name"] == "persistence")["test"]["mae"]

    out = ["# Temperature forecast: model comparison", "",
           f"Generated: {meta['trained_at']}", "",
           "## Data", "",
           f"- Runs: {meta['n_runs']}  |  usable rows: {meta['n_rows']}  "
           f"(train {meta['n_train']} / val {meta['n_val']} / test {meta['n_test']})",
           f"- Sample spacing: {meta['interval_s']:g} s",
           f"- Split: {meta['split']}", ""]
    for w in meta["warnings"]:
        out.append(f"> WARNING: {w}")
    if meta["warnings"]:
        out.append("")

    out += ["## Test error (MAE, deg C, lower is better)", "",
            f"| Model | {head} | mean |", sep]
    for r in results:
        mae = r["test"]["mae"]
        out.append(_row(r["name"], mae + [float(np.mean(mae))], ".3f"))

    out += ["", "## Test error (RMSE, deg C, lower is better)", "",
            f"| Model | {head} | mean |", sep]
    for r in results:
        rmse = r["test"]["rmse"]
        out.append(_row(r["name"], rmse + [float(np.mean(rmse))], ".3f"))

    out += ["", "## Skill vs persistence (test; 0 = no better than "
            "'temperature stays the same', 1 = perfect)", "",
            f"| Model | {head} | mean |", sep]
    for r in results:
        if r["name"] == "persistence":
            continue
        s = skill(r["test"]["mae"], base)
        out.append(_row(r["name"], s + [float(np.mean(s))], ".2f"))

    out += ["", "## Cost", "",
            "| Model | val mean MAE | size (KB) | ms per prediction |", "|---|---|---|---|"]
    for r in results:
        out.append(f"| {r['name']} | {r['val_mean_mae']:.3f} | "
                   f"{r['size_kb']:.0f} | {r['infer_ms']:.2f} |")

    out += ["", "## Result", "",
            f"- Selected model: **{meta['best_model']}** "
            "(lowest mean validation MAE among ridge / random_forest / "
            "lightgbm / gru).",
            f"- Beats both baselines on the test set: "
            f"**{'yes' if meta['beats_baselines'] else 'NO'}**."]
    if not meta["beats_baselines"]:
        out.append("- A model that cannot beat the baselines adds no value; "
                   "record more varied runs before relying on it.")
    return "\n".join(out) + "\n"
