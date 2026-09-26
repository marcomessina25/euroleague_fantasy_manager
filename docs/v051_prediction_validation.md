# V0.5.1 vs V0.5.0 Prediction Model Backtest Validation

**Status:** PASSED
**Samples Evaluated:** 946

## Overall Metric Comparison

| Metric | V0.5.0 (Baseline Prior) | V0.5.1 (Decomposed) | Delta | Improvement |
| :--- | :--- | :--- | :--- | :--- |
| **xP MAE** | 5.432 FP | 4.854 FP | -0.578 FP | 10.6% error reduction |
| **xP RMSE** | 6.991 | 6.716 | -0.275 | - |
| **Spearman Rank Corr** | 0.7440 | 0.7510 | +0.0070 | higher ranking fidelity |
| **xM MAE** | N/A | 7.16 min | - | minutes projection error |
| **1-sigma CI Coverage** | N/A | 55.9% | - | expected: ~68.3% |
| **90% CI Coverage** | N/A | 78.2% | - | expected: ~90.0% |

## By Position Breakdown

| Position | Samples | V0.5.0 MAE | V0.5.1 MAE | V0.5.0 Spearman | V0.5.1 Spearman | xM MAE |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Center | 350 | 6.901 | 6.900 | 0.7598 | 0.8203 | 12.34 |
| Forward | 312 | 4.447 | 3.780 | 0.7014 | 0.7269 | 4.13 |
| Guard | 284 | 4.702 | 3.514 | 0.6371 | 0.6957 | 4.09 |

## Regression Gate Verification
- **Requirement:** MAE(V0.5.1) <= MAE(V0.5.0) + 0.05
- **Realized:** 4.854 <= 5.482 -> **PASSED**