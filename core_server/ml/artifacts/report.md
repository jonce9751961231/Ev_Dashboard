# Temperature forecast: model comparison

Generated: 2026-10-19T09:28:22

## Data

- Runs: 12  |  usable rows: 3600  (train 2400 / val 600 / test 600)
- Sample spacing: 10 s
- Split: whole-run split: 8 train / 2 val / 2 test runs (test runs: demo_run01, demo_run08)

> WARNING: Run names contain 'demo': synthetic data. Do not quote these numbers as real-motor results.

## Test error (MAE, deg C, lower is better)

| Model | +1 min | +5 min | +15 min | +30 min | mean |
|---|---|---|---|---|---|
| persistence | 0.588 | 2.621 | 5.164 | 7.811 | 4.046 |
| physics_fit | 0.542 | 2.095 | 4.339 | 6.149 | 3.281 |
| ridge | 0.181 | 1.546 | 4.498 | 6.059 | 3.071 |
| random_forest | 0.251 | 2.242 | 6.087 | 7.282 | 3.965 |
| lightgbm | 0.178 | 2.080 | 5.231 | 6.843 | 3.583 |
| gru | 0.272 | 1.795 | 4.926 | 6.415 | 3.352 |

## Test error (RMSE, deg C, lower is better)

| Model | +1 min | +5 min | +15 min | +30 min | mean |
|---|---|---|---|---|---|
| persistence | 0.737 | 3.217 | 6.220 | 8.458 | 4.658 |
| physics_fit | 0.736 | 2.826 | 5.278 | 7.139 | 3.995 |
| ridge | 0.330 | 2.250 | 5.399 | 7.306 | 3.821 |
| random_forest | 0.399 | 3.033 | 6.991 | 8.412 | 4.709 |
| lightgbm | 0.331 | 2.717 | 6.224 | 7.709 | 4.245 |
| gru | 0.393 | 2.497 | 5.813 | 7.464 | 4.041 |

## Skill vs persistence (test; 0 = no better than 'temperature stays the same', 1 = perfect)

| Model | +1 min | +5 min | +15 min | +30 min | mean |
|---|---|---|---|---|---|
| physics_fit | 0.08 | 0.20 | 0.16 | 0.21 | 0.16 |
| ridge | 0.69 | 0.41 | 0.13 | 0.22 | 0.36 |
| random_forest | 0.57 | 0.14 | -0.18 | 0.07 | 0.15 |
| lightgbm | 0.70 | 0.21 | -0.01 | 0.12 | 0.25 |
| gru | 0.54 | 0.31 | 0.05 | 0.18 | 0.27 |

## Cost

| Model | val mean MAE | size (KB) | ms per prediction |
|---|---|---|---|
| persistence | 3.325 | 0 | 0.00 |
| physics_fit | 2.851 | 0 | 0.02 |
| ridge | 2.460 | 2 | 0.31 |
| random_forest | 4.018 | 4790 | 42.51 |
| lightgbm | 3.079 | 59 | 7.02 |
| gru | 2.389 | 19 | 1.56 |

## Result

- Selected model: **gru** (lowest mean validation MAE among ridge / random_forest / lightgbm / gru).
- Beats both baselines on the test set: **NO**.
- A model that cannot beat the baselines adds no value; record more varied runs before relying on it.
