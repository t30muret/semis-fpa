"""Forecast models. Each takes a history (oldest first) and returns forecasts for h = 1..4.

Revenue
  naive_rev  seasonal naive: same quarter last year x (1 + trailing 4-quarter YoY growth)
  ets_rev    Holt-Winters on log revenue: damped additive trend + additive seasonality
Gross margin (percentage points)
  naive_gm   last quarter's margin carried forward (random walk)
  ets_gm     Holt-Winters on the margin level: no trend + additive seasonality

Holt-Winters is written out below (numpy + scipy) rather than imported, so every
equation is visible and explainable in an interview.
"""
import numpy as np
from scipy.optimize import minimize

M = 4  # quarters per season


# ---------------------------------------------------------------- Holt-Winters
def _hw_filter(y, alpha, beta, gamma, phi, trend):
    """Run the additive Holt-Winters recursions; return one-step errors and final state."""
    level = y[:M].mean()
    slope = (y[M:2 * M].mean() - y[:M].mean()) / M if trend else 0.0
    season = list(y[:M] - level)
    errors = []
    for t in range(M, len(y)):
        s_old = season[t - M]
        fitted = level + phi * slope + s_old
        errors.append(y[t] - fitted)
        prev_level = level
        level = alpha * (y[t] - s_old) + (1 - alpha) * (prev_level + phi * slope)
        if trend:
            slope = beta * (level - prev_level) + (1 - beta) * phi * slope
        season.append(gamma * (y[t] - prev_level - phi * slope) + (1 - gamma) * s_old)
    return np.array(errors), level, slope, season


def holt_winters(y, horizons, trend=True, damped=True):
    """Fit smoothing parameters by minimising squared one-step errors, then forecast."""
    y = np.asarray(y, dtype=float)

    def unpack(p):
        alpha, beta, gamma, phi = p
        return alpha, (beta if trend else 0.0), gamma, (phi if (trend and damped) else 1.0)

    def sse(p):
        e, *_ = _hw_filter(y, *unpack(p), trend)
        return float(e @ e)

    bounds = [(0.01, 0.99), (0.01, 0.5), (0.01, 0.99), (0.80, 0.98)]
    best = None
    for start in ([0.5, 0.1, 0.2, 0.9], [0.2, 0.05, 0.1, 0.95], [0.8, 0.2, 0.3, 0.85]):
        res = minimize(sse, start, bounds=bounds, method="L-BFGS-B")
        if best is None or res.fun < best.fun:
            best = res
    alpha, beta, gamma, phi = unpack(best.x)
    _, level, slope, season = _hw_filter(y, alpha, beta, gamma, phi, trend)

    out = []
    for h in horizons:
        damp = sum(phi ** i for i in range(1, h + 1)) if trend else 0.0
        s = season[len(y) - M + (h - 1) % M]
        out.append(level + damp * slope + s)
    return np.array(out)


# ---------------------------------------------------------------- models
def naive_rev(rev, horizons):
    rev = np.asarray(rev, dtype=float)
    growth = rev[-4:].sum() / rev[-8:-4].sum() - 1 if len(rev) >= 8 else 0.0
    return np.array([rev[-4 + (h - 1) % 4] * (1 + growth) for h in horizons])


def ets_rev(rev, horizons, window=40):
    y = np.log(np.asarray(rev, dtype=float)[-window:])
    return np.exp(holt_winters(y, horizons, trend=True, damped=True))


def naive_gm(gm, horizons):
    return np.full(len(horizons), float(gm[-1]))


def ets_gm(gm, horizons, window=24):
    y = np.asarray(gm, dtype=float)[-window:]
    return holt_winters(y, horizons, trend=False)


MODELS = {
    "revenue": {"naive_rev": naive_rev, "ets_rev": ets_rev},
    "gross_margin_pct": {"naive_gm": naive_gm, "ets_gm": ets_gm},
}
BASELINE = {"revenue": "naive_rev", "gross_margin_pct": "naive_gm"}
