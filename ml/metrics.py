from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score, root_mean_squared_error


def regression_metrics(y_true, y_pred) -> dict[str, float]:
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    return {
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "mape_pct": round(float(mean_absolute_percentage_error(y_true, y_pred) * 100), 2),
        "rmse_rub": round(float(root_mean_squared_error(y_true, y_pred)), 2),
        "mae_rub": round(float(mean_absolute_error(y_true, y_pred)), 2),
    }
