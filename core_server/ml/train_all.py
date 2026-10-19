"""Train and compare the four models on recorded runs.

Example (from the project root):
    python -m core_server.ml.train_all --data datasets/runs/*.csv --interval-s 10

Files without a timestamp_ms column are assumed evenly spaced; tell the script
the spacing with --source-interval-s (seconds between rows).
"""
from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config as C
from . import data
from .evaluate import build_report, horizon_metrics, time_inference
from .models import CANDIDATES, GRUModel, MODEL_CLASSES


def _parse(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="+", required=True,
                    help="CSV files or glob patterns, one run per file")
    ap.add_argument("--interval-s", type=float, default=C.INTERVAL_S,
                    help="resample every run to this spacing (default %(default)s s)")
    ap.add_argument("--source-interval-s", type=float, default=None,
                    help="row spacing of files WITHOUT timestamp_ms "
                         "(default: same as --interval-s)")
    ap.add_argument("--out", default=str(C.ARTIFACT_DIR))
    ap.add_argument("--split", choices=["auto", "runs", "chrono"], default="auto")
    ap.add_argument("--skip", nargs="*", default=[], help="model names to skip")
    ap.add_argument("--gru-epochs", type=int, default=60)
    return ap.parse_args(argv)


def _expand(patterns):
    files = []
    for pat in patterns:          # Windows shells do not expand globs themselves
        hits = sorted(glob.glob(pat))
        files.extend(hits if hits else [pat])
    return files


def main(argv=None) -> dict:
    args = _parse(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    runs = data.load_runs(_expand(args.data), args.interval_s, args.source_interval_s)
    ds = data.build_dataset(runs, args.interval_s)
    parts, split_desc = data.split_dataset(ds, mode=args.split)
    batches = {k: data.make_batch(ds, idx) for k, idx in parts.items()}
    print(f"Runs: {len(runs)}   rows: train {len(parts['train'])} / "
          f"val {len(parts['val'])} / test {len(parts['test'])}")
    print(f"Split: {split_desc}\n")

    warnings = []
    if len(runs) < 5:
        warnings.append(f"Only {len(runs)} run(s); results are indicative at best. "
                        "Record 10-15 varied runs for a trustworthy comparison.")
    if len(parts["train"]) < 1500:
        warnings.append(f"Only {len(parts['train'])} training rows; deep and "
                        "boosted models need more data to shine.")
    if "demo" in " ".join(runs).lower():
        warnings.append("Run names contain 'demo': synthetic data. Do not quote "
                        "these numbers as real-motor results.")

    candidates = [MODEL_CLASSES["persistence"](), MODEL_CLASSES["physics_fit"]()]
    candidates += [GRUModel(epochs=args.gru_epochs) if n == "gru" else MODEL_CLASSES[n]()
                   for n in CANDIDATES]

    results = []
    for model in candidates:
        if model.name in args.skip:
            continue
        if not model.available():
            print(f"[skip] {model.name}: dependency not installed "
                  f"(see requirements-ml.txt)")
            continue
        print(f"[train] {model.name} ...", flush=True)
        try:
            model.fit(batches["train"], batches["val"])
            val_mae = horizon_metrics(batches["val"].y, model.predict(batches["val"]))
            test = horizon_metrics(batches["test"].y, model.predict(batches["test"]))
            path = model.save(out)
        except Exception as exc:                      # keep going; report it
            print(f"  FAILED: {exc!r}")
            warnings.append(f"{model.name} failed to train: {exc!r}")
            continue
        results.append({
            "name": model.name, "baseline": model.is_baseline,
            "file": path.name if path else None,
            "val_mean_mae": float(np.mean(val_mae["mae"])), "test": test,
            "size_kb": path.stat().st_size / 1024 if path else 0.0,
            "infer_ms": time_inference(model, batches["test"]),
        })
        print(f"  test mean MAE {np.mean(test['mae']):.3f} C")

    ml = [r for r in results if not r["baseline"]]
    if not ml:
        raise SystemExit("No ML model trained successfully.")
    best = min(ml, key=lambda r: r["val_mean_mae"])      # chosen on VALIDATION only
    base_means = [np.mean(r["test"]["mae"]) for r in results if r["baseline"]]
    beats = bool(np.mean(best["test"]["mae"]) < min(base_means))

    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "interval_s": args.interval_s, "horizons_min": list(C.HORIZONS_MIN),
        "n_runs": len(runs), "n_rows": len(ds.frame),
        "n_train": len(parts["train"]), "n_val": len(parts["val"]),
        "n_test": len(parts["test"]), "split": split_desc,
        "warnings": warnings, "best_model": best["name"], "beats_baselines": beats,
    }
    (out / "report.md").write_text(build_report(results, meta), encoding="utf-8")
    registry = {
        **{k: meta[k] for k in ("trained_at", "interval_s", "horizons_min",
                                "split", "best_model", "beats_baselines")},
        "feature_names": C.FEATURE_NAMES, "gru_cols": C.GRU_COLS,
        "lag_s": list(C.LAG_S), "window_steps": ds.window_steps,
        "models": {r["name"]: {"file": r["file"], "val_mean_mae": r["val_mean_mae"],
                               "test_mean_mae": float(np.mean(r["test"]["mae"])),
                               "test_mean_rmse": float(np.mean(r["test"]["rmse"])),
                               "size_kb": float(r["size_kb"]),
                               "infer_ms": float(r["infer_ms"])}
                   for r in results},
    }
    (out / "registry.json").write_text(json.dumps(registry, indent=2))

    print(f"\nSelected: {best['name']} (lowest validation error). "
          f"Beats baselines on test: {'yes' if beats else 'NO'}")
    for w in warnings:
        print(f"WARNING: {w}")
    print(f"Report:   {out / 'report.md'}\nRegistry: {out / 'registry.json'}")
    return registry


if __name__ == "__main__":
    main()
