"""Shared settings for the temperature-forecast models.

Everything that must match between training and live prediction lives here,
so the two cannot drift apart.
"""
from pathlib import Path

# What we predict: the temperature RISE (deg C) this many minutes ahead.
HORIZONS_MIN = (1, 5, 15, 30)

# Every run is resampled onto this spacing (seconds) before anything else.
INTERVAL_S = 10.0

# History the GRU sees (seconds), and the look-backs used for tabular features.
WINDOW_S = 300.0
LAG_S = (60, 300, 600)

# Raw sensor columns every training file must contain.
BASE_COLS = ["voltage_v", "current_a", "rpm", "temp_c", "ambient_temp_c"]

# Features derived only from the past (never from the future).
ENGINEERED = ["power_w", "current_sq", "temp_above_ambient"] + [
    f"{name}_{lag}s" for lag in LAG_S for name in ("dtemp", "i_mean", "rpm_mean")
]
FEATURE_NAMES = BASE_COLS + ENGINEERED

# Inputs for each time step of the GRU window.
GRU_COLS = BASE_COLS + ["power_w", "temp_above_ambient"]

TARGET_NAMES = [f"y_{m}m" for m in HORIZONS_MIN]

# Accepted spellings for CSV headers -> canonical names.
COLUMN_ALIASES = {
    "voltage": "voltage_v", "v": "voltage_v", "voltage_v": "voltage_v",
    "current": "current_a", "i": "current_a", "current_a": "current_a",
    "rpm": "rpm", "speed_rpm": "rpm", "speed": "rpm",
    "temp": "temp_c", "temp_c": "temp_c", "stator_temp_c": "temp_c",
    "motor_temp_c": "temp_c",
    "ambient": "ambient_temp_c", "ambient_temp_c": "ambient_temp_c",
    "timestamp_ms": "timestamp_ms", "run_id": "run_id",
}

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
SEED = 42
