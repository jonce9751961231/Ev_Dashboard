"""Smoke tests for the ML pipeline. Run from the project root:

    python -m pytest core_server/ml/tests -q
"""
import numpy as np
import pytest

from core_server.ml import config as C
from core_server.ml import data
from core_server.ml.predictor import ThermalPredictor
from core_server.ml.synth import simulate_run, write_demo_csvs
from core_server.ml.train_all import main as train_main


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("ml")
    files = write_demo_csvs(root / "runs", n_runs=7, minutes=120)
    out = root / "artifacts"
    registry = train_main(["--data", *files, "--out", str(out), "--gru-epochs", "8"])
    return out, registry, files


def test_targets_use_real_future_only():
    df = simulate_run(minutes=60, interval_s=10.0, rng=np.random.default_rng(1))
    ds = data.build_dataset({"r": df[C.BASE_COLS]}, 10.0)
    # 60 min run = 360 steps. Rows within 30 min (180 steps) of the end have no
    # real future, so they must be dropped rather than back-filled.
    assert ds.frame["pos"].max() <= 360 - 180 - 1


def test_split_has_no_overlap(trained):
    _, _, files = trained
    runs = data.load_runs(files, 10.0)
    ds = data.build_dataset(runs, 10.0)
    parts, _ = data.split_dataset(ds)
    seen = [set(v.tolist()) for v in parts.values()]
    assert not (seen[0] & seen[1]) and not (seen[0] & seen[2]) and not (seen[1] & seen[2])


def test_models_beat_persistence_on_demo_data(trained):
    _, registry, _ = trained
    models = registry["models"]
    persistence = models["persistence"]["test_mean_mae"]
    # Ridge must clearly beat "temperature stays the same" on demo data.
    assert models["ridge"]["test_mean_mae"] < 0.9 * persistence
    # The honesty flag must exist; whether it is True depends on the data.
    assert isinstance(registry["beats_baselines"], bool)


def test_gru_windows_end_on_the_current_row(trained):
    """The last step of every GRU window must be the row being predicted, and
    earlier steps must be strictly earlier readings of the same run."""
    _, _, files = trained
    ds = data.build_dataset(data.load_runs(files, 10.0), 10.0)
    idx = np.arange(0, len(ds.frame), 37)
    batch = data.make_batch(ds, idx)
    g = [batch.feature_names.index(c) for c in C.GRU_COLS]
    assert batch.seq.shape == (len(idx), ds.window_steps, len(C.GRU_COLS))
    assert np.allclose(batch.seq[:, -1, :], batch.X[:, g])
    # second-to-last step is exactly one grid step earlier in the same run
    rows = ds.frame.iloc[idx]
    for k in (0, len(idx) // 2, len(idx) - 1):
        rid, pos = rows.iloc[k]["run_id"], int(rows.iloc[k]["pos"])
        assert np.allclose(batch.seq[k, -2, :], ds.series[rid][pos - 1])


def test_gru_trains_and_reloads(tmp_path, trained):
    pytest.importorskip("torch")
    from core_server.ml.models import GRUModel, load_model
    _, _, files = trained
    ds = data.build_dataset(data.load_runs(files, 10.0), 10.0)
    parts, _ = data.split_dataset(ds)
    tr, va, te = (data.make_batch(ds, parts[k]) for k in ("train", "val", "test"))
    model = GRUModel(epochs=5).fit(tr, va)
    before = model.predict(te)
    assert before.shape == te.y.shape and np.isfinite(before).all()
    model.save(tmp_path)
    after = load_model("gru", tmp_path).predict(te)
    assert np.allclose(before, after, atol=1e-5)


def test_predictor_warms_up_then_forecasts(trained):
    out, _, _ = trained
    predictor = ThermalPredictor(out)
    assert predictor.predict() is None
    df = simulate_run(minutes=30, interval_s=1.0, rng=np.random.default_rng(3))
    result = None
    for k, row in enumerate(df.itertuples()):
        predictor.push(row.voltage_v, row.current_a, row.rpm, row.temp_c,
                       row.ambient_temp_c, now=float(k))
        result = predictor.predict()
    assert result is not None
    assert set(result["forecast_c"]) == {f"{m}m" for m in C.HORIZONS_MIN}
