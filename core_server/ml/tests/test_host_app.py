"""Integration tests for host_app.py: ingest rules, hardware dropout, ML wiring.

Run from the project root:
    python -m pytest core_server/ml/tests -q
"""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from core_server import host_app as h
from core_server.ml.predictor import ThermalPredictor
from core_server.ml.synth import simulate_run, write_demo_csvs
from core_server.ml.train_all import main as train_main


@pytest.fixture()
def client():
    """Fresh module state for every test; ML off unless a test turns it on."""
    h.latest_live_telemetry = None
    h.latest_live_at = 0.0
    h.g_last_source = None
    saved = h.ml_predictor
    h.ml_predictor = None
    yield TestClient(h.app)
    h.ml_predictor = saved


def first_message(client):
    with client.websocket_connect("/ws/telemetry") as ws:
        return ws.receive_json()


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("host")
    files = write_demo_csvs(root / "runs", n_runs=6, minutes=120)
    out = root / "art"
    train_main(["--data", *files, "--out", str(out),
                "--skip", "random_forest", "lightgbm", "gru"])
    return out


def test_zero_readings_stay_zero(client):
    """Regression: a stopped motor used to be reported as 2000 RPM / 2 A."""
    r = client.post("/api/ingest", json={"v": 12.0, "i": 0.0, "rpm": 0, "temp": 31.5})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["current_a"] == 0.0 and data["rpm"] == 0 and data["power_w"] == 0.0


def test_missing_fields_are_rejected_not_invented(client):
    r = client.post("/api/ingest", json={"v": 12.0, "i": 1.0, "rpm": 900})  # no temperature
    assert r.status_code == 422
    assert "temp" in r.json()["missing_or_invalid"]
    assert h.latest_live_telemetry is None


def test_measured_ambient_is_used_and_flagged(client):
    r = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500,
                                         "temp": 40.0, "ambient_temp_c": 24.5})
    data = r.json()["data"]
    assert data["ambient_temp_c"] == 24.5 and data["ambient_measured"] is True
    r = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 40.0})
    assert r.json()["data"]["ambient_measured"] is False


def test_hardware_going_quiet_is_reported(client):
    client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 40.0})
    assert first_message(client)["source"] == "ESP32_WIFI_HARDWARE"
    h.latest_live_at = time.time() - 60          # ESP32 silent for a minute
    assert first_message(client)["source"] == "SIMULATOR_HARDWARE_OFFLINE"


def test_payload_says_when_no_ml_models_exist(client):
    msg = first_message(client)
    assert msg["predictions"]["forecast_status"] == "no_ml_models_trained"
    assert client.get("/api/ml/status").json()["available"] is False
    health = client.get("/api/health").json()
    assert "rf_ok" in health and health["ml_model"] is None


def test_ml_warms_up_then_forecasts(client, artifacts):
    h.ml_predictor = ThermalPredictor(artifacts)
    client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 40.0})
    msg = first_message(client)           # first message resets the buffer (new source)
    assert msg["predictions"]["forecast_status"] == "ml_warming_up"
    assert msg["predictions"]["warmup_seconds_left"] > 0

    df = simulate_run(minutes=20, interval_s=1.0, rng=np.random.default_rng(5))
    for k, row in enumerate(df.itertuples()):
        h.ml_predictor.push(row.voltage_v, row.current_a, row.rpm, row.temp_c,
                            row.ambient_temp_c, now=float(k))
    h.latest_live_at = time.time()
    msg = first_message(client)
    assert msg["predictions"]["forecast_status"] == "ml_ready"
    assert msg["predictions"]["forecast_model"] == "ridge"
    status = client.get("/api/ml/status").json()
    assert status["available"] is True and status["ready"] is True


def test_dynamic_dt_temp_rate_calculated(client):
    h.hardware_temp_history.clear()
    r1 = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 30.0})
    assert r1.status_code == 200
    assert r1.json()["data"]["dt_temp_rate"] == 0.0

    time.sleep(0.5)
    r2 = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 31.0})
    assert r2.status_code == 200
    rate = r2.json()["data"]["dt_temp_rate"]
    assert rate > 0.0


def test_api_key_auth_enforced(client):
    saved_key = h.AURA_API_KEY
    try:
        h.AURA_API_KEY = "test-secret-token"
        # Write endpoint without key -> 401
        r = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 30.0})
        assert r.status_code == 401

        # Write endpoint with wrong key -> 401
        r = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 30.0},
                        headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

        # Write endpoint with correct key in header -> 200
        r = client.post("/api/ingest", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 30.0},
                        headers={"X-API-Key": "test-secret-token"})
        assert r.status_code == 200

        # Write endpoint with correct key in query parameter -> 200
        r = client.post("/api/ingest?api_key=test-secret-token", json={"v": 12.0, "i": 2.0, "rpm": 1500, "temp": 30.0})
        assert r.status_code == 200
    finally:
        h.AURA_API_KEY = saved_key

