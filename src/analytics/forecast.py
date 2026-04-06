# src/analytics/forecast.py
# Phase 3: ARIMA + Prophet forecasting engine
# Run: python -m src.analytics.forecast

import json
import warnings
import pandas as pd
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore")


def _get_engine():
    from src.pipeline.ingest import get_engine
    return get_engine()


# ─── DATA RETRIEVAL ───────────────────────────────────────────────────────────

def _get_monthly_series(metric: str, segment: str | None = None) -> pd.DataFrame:
    """
    Fetch a monthly time series from KPI views and return it in Prophet format.

    Parameters
    ----------
    metric : str
        'revenue' or 'profit'.
    segment : str | None
        Category name (e.g. 'Furniture') or region name (e.g. 'West'),
        or None for the aggregate across all segments.

    Returns
    -------
    pd.DataFrame
        Columns: ds (datetime), y (metric value). Sorted ascending by ds.
    """
    engine = _get_engine()
    col = "total_revenue" if metric == "revenue" else "total_profit"

    if segment is None:
        df = pd.read_sql(
            text(f"SELECT period, {col} AS y FROM v_monthly_kpis ORDER BY period"),
            engine,
        )
    else:
        # Try category first, fall back to region
        cat_df = pd.read_sql(
            text(
                f"SELECT period, SUM({col}) AS y "
                f"FROM v_category_performance "
                f"WHERE category = :seg GROUP BY period ORDER BY period"
            ),
            engine,
            params={"seg": segment},
        )
        if not cat_df.empty:
            df = cat_df
        else:
            reg_df = pd.read_sql(
                text(
                    f"SELECT period, SUM({col}) AS y "
                    f"FROM v_regional_performance "
                    f"WHERE region = :seg GROUP BY period ORDER BY period"
                ),
                engine,
                params={"seg": segment},
            )
            df = reg_df

    if df.empty:
        raise ValueError(f"No data found for metric='{metric}', segment='{segment}'")

    # Convert 'YYYY-MM' period string to datetime (first of month)
    df["ds"] = pd.to_datetime(df["period"] + "-01")
    df = df[["ds", "y"]].sort_values("ds").reset_index(drop=True)
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    return df


# ─── ARIMA ────────────────────────────────────────────────────────────────────

def _forecast_arima(series: pd.DataFrame, horizon: int, order: tuple = (1, 1, 1)) -> list[dict]:
    """
    Fit an ARIMA model and return horizon-step forecasts with 80% CI.

    Parameters
    ----------
    series : pd.DataFrame
        Columns: ds (datetime), y (float).
    horizon : int
        Number of months to forecast.
    order : tuple
        ARIMA (p, d, q) order (default (1, 1, 1)).

    Returns
    -------
    list[dict]
        Each dict: period (YYYY-MM), forecast, lower_80, upper_80, model.
    """
    from statsmodels.tsa.arima.model import ARIMA

    model = ARIMA(series["y"].values, order=order)
    fit = model.fit()
    fc = fit.get_forecast(steps=horizon)
    pred = fc.predicted_mean
    ci = fc.conf_int(alpha=0.2)  # 80% CI

    last_date = series["ds"].iloc[-1]
    results = []
    for i in range(horizon):
        period_dt = last_date + pd.DateOffset(months=i + 1)
        results.append({
            "period": period_dt.strftime("%Y-%m"),
            "forecast": round(float(pred[i]), 2),
            "lower_80": round(float(ci[i, 0]), 2),
            "upper_80": round(float(ci[i, 1]), 2),
            "model": "arima",
        })
    return results


# ─── PROPHET ──────────────────────────────────────────────────────────────────

def _forecast_prophet(series: pd.DataFrame, horizon: int) -> list[dict]:
    """
    Fit a Prophet model and return horizon-step forecasts with 80% CI.

    Parameters
    ----------
    series : pd.DataFrame
        Columns: ds (datetime), y (float).
    horizon : int
        Number of months to forecast.

    Returns
    -------
    list[dict]
        Each dict: period (YYYY-MM), forecast, lower_80, upper_80, model.
    """
    from prophet import Prophet

    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.80,
        uncertainty_samples=500,
    )
    m.fit(series)

    future = m.make_future_dataframe(periods=horizon, freq="MS")
    forecast = m.predict(future)

    # Return only the future rows
    future_fc = forecast.tail(horizon)[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()

    results = []
    for _, row in future_fc.iterrows():
        results.append({
            "period": row["ds"].strftime("%Y-%m"),
            "forecast": round(float(row["yhat"]), 2),
            "lower_80": round(float(row["yhat_lower"]), 2),
            "upper_80": round(float(row["yhat_upper"]), 2),
            "model": "prophet",
        })
    return results


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def get_forecast(
    metric: str = "revenue",
    horizon: int = 3,
    segment: str | None = None,
    model: str = "prophet",
) -> dict:
    """
    Forecast a KPI metric for the next `horizon` months.

    Parameters
    ----------
    metric : str
        'revenue' or 'profit'.
    horizon : int
        Months ahead to forecast (default 3).
    segment : str | None
        Category or region name, or None for aggregate.
    model : str
        'prophet' (default) or 'arima'. Falls back to prophet if arima fails.

    Returns
    -------
    dict
        Keys: metric, segment, horizon, model, forecasts (list[dict]).
        Each forecast: period (YYYY-MM), forecast, lower_80, upper_80, model.
    """
    series = _get_monthly_series(metric, segment)

    warning = None
    if model == "arima":
        try:
            forecasts = _forecast_arima(series, horizon)
        except Exception as e:
            warning = f"ARIMA failed ({e}), fell back to Prophet"
            forecasts = _forecast_prophet(series, horizon)
            model = "prophet"
    else:
        forecasts = _forecast_prophet(series, horizon)

    result = {
        "metric": metric,
        "segment": segment,
        "horizon": horizon,
        "model": model,
        "forecasts": forecasts,
    }
    if warning:
        result["warning"] = warning
    return result


# ─── STANDALONE RUNNER ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Revenue forecast (Prophet, 3 months) ===")
    fc = get_forecast(metric="revenue", horizon=3, model="prophet")
    print(json.dumps(fc, indent=2))

    print("\n=== Profit forecast (ARIMA, 3 months) ===")
    fc2 = get_forecast(metric="profit", horizon=3, model="arima")
    print(json.dumps(fc2, indent=2))
