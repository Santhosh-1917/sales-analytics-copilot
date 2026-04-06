# src/analytics/anomalies.py
# Phase 3.1: 4-rule anomaly detection engine
# Run: python src/analytics/anomalies.py

import json
import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()


def get_engine():
    """Import lazily to avoid circular import issues."""
    from src.pipeline.ingest import get_engine as _get_engine
    return _get_engine()


# ─── RULE 1: MARGIN COMPRESSION ───────────────────────────────────────────────

def _rule_margin_compression(engine, period: str | None) -> list[dict]:
    """
    Detect periods where revenue grew but profit shrank.
    Flags where revenue_mom > +2% AND profit_mom < -1%.
    """
    query = text(
        "SELECT period, total_revenue, total_profit, margin_pct "
        "FROM v_monthly_kpis ORDER BY period"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    df = df.sort_values("period").reset_index(drop=True)
    df["revenue_mom"] = df["total_revenue"].pct_change() * 100
    df["profit_mom"] = df["total_profit"].pct_change() * 100

    mask = (df["revenue_mom"] > 2.0) & (df["profit_mom"] < -1.0)
    if period:
        mask = mask & (df["period"] == period)

    anomalies = []
    for _, row in df[mask].iterrows():
        pmom = float(row["profit_mom"])
        if pmom < -5.0:
            severity = "high"
        elif pmom < -3.0:
            severity = "medium"
        else:
            severity = "low"

        anomalies.append({
            "flag": "margin_compression",
            "severity": severity,
            "segment": "all",
            "delta": round(pmom, 4),
            "period": row["period"],
        })

    return anomalies


# ─── RULE 2: DISCOUNT EROSION ─────────────────────────────────────────────────

def _rule_discount_erosion(
    engine, period: str | None, discount_threshold: float
) -> list[dict]:
    """
    Detect categories/periods where average discount exceeds the threshold.
    View stores avg_discount_pct as a percentage already (ROUND(AVG * 100, 2)).
    """
    query = text(
        "SELECT period, category, avg_discount_pct "
        "FROM v_category_performance ORDER BY period, category"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    # Aggregate to category-period level (sub_category rows are already grouped in the view)
    df_agg = (
        df.groupby(["period", "category"], as_index=False)
        .agg(avg_discount_pct=("avg_discount_pct", "mean"))
    )

    mask = df_agg["avg_discount_pct"] > discount_threshold
    if period:
        mask = mask & (df_agg["period"] == period)

    anomalies = []
    for _, row in df_agg[mask].iterrows():
        disc = float(row["avg_discount_pct"])
        delta = round(disc - discount_threshold, 4)
        if disc > 40.0:
            severity = "high"
        elif disc > 30.0:
            severity = "medium"
        else:
            severity = "low"

        anomalies.append({
            "flag": "discount_erosion",
            "severity": severity,
            "segment": row["category"],
            "delta": delta,
            "period": row["period"],
        })

    return anomalies


# ─── RULE 3: REGIONAL OUTLIER ─────────────────────────────────────────────────

def _rule_regional_outlier(engine, period: str | None) -> list[dict]:
    """
    Flag regions whose margin_pct falls more than 2 standard deviations below
    the mean for that period.
    """
    query = text(
        "SELECT period, region, margin_pct "
        "FROM v_regional_performance ORDER BY period, region"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    # Aggregate to region-period level (states roll up)
    df_agg = (
        df.groupby(["period", "region"], as_index=False)
        .agg(margin_pct=("margin_pct", "mean"))
    )

    if period:
        df_agg = df_agg[df_agg["period"] == period]

    anomalies = []
    for prd, grp in df_agg.groupby("period"):
        if len(grp) < 2:
            continue
        mean_m = grp["margin_pct"].mean()
        std_m = grp["margin_pct"].std()
        if std_m == 0 or np.isnan(std_m):
            continue

        for _, row in grp.iterrows():
            z = (float(row["margin_pct"]) - mean_m) / std_m
            if z < -2.0:
                if z < -3.0:
                    severity = "high"
                elif z < -2.5:
                    severity = "medium"
                else:
                    severity = "low"

                anomalies.append({
                    "flag": "regional_outlier",
                    "severity": severity,
                    "segment": row["region"],
                    "delta": round(z, 4),
                    "period": prd,
                })

    return anomalies


# ─── RULE 4: MoM GROWTH REVERSAL ──────────────────────────────────────────────

def _rule_growth_reversal(engine, period: str | None) -> list[dict]:
    """
    Detect when a positive revenue growth trend flips to 2+ consecutive negative
    periods.  The trigger period is the first negative after a positive run.
    """
    query = text(
        "SELECT period, revenue_mom_pct, profit_mom_pct "
        "FROM v_growth_rates ORDER BY period"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    df = df.dropna(subset=["revenue_mom_pct"]).reset_index(drop=True)

    anomalies = []
    n = len(df)
    for i in range(1, n - 1):
        prev = float(df.loc[i - 1, "revenue_mom_pct"])
        curr = float(df.loc[i, "revenue_mom_pct"])
        nxt = float(df.loc[i + 1, "revenue_mom_pct"])

        # Positive run ended AND next is also negative → reversal confirmed
        if prev > 0 and curr < 0 and nxt < 0:
            trigger_period = df.loc[i, "period"]
            if period and trigger_period != period:
                continue

            delta = round(curr, 4)
            if abs(delta) > 10.0:
                severity = "high"
            elif abs(delta) > 5.0:
                severity = "medium"
            else:
                severity = "low"

            anomalies.append({
                "flag": "growth_reversal",
                "severity": severity,
                "segment": "revenue",
                "delta": delta,
                "period": trigger_period,
            })

    return anomalies


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def detect_anomalies(
    period: str | None = None,
    discount_threshold: float = 25.0,
) -> list[dict]:
    """
    Run all four anomaly-detection rules and return a combined, sorted list.

    Parameters
    ----------
    period : str | None
        ISO month string 'YYYY-MM' to filter results. None = all periods.
    discount_threshold : float
        Percentage threshold for discount-erosion rule (default 25.0 = 25%).

    Returns
    -------
    list[dict]
        Each dict has keys: flag, severity, segment, delta, period.
        Sorted by period descending, then severity (high first).
    """
    engine = get_engine()

    results: list[dict] = []
    results.extend(_rule_margin_compression(engine, period))
    results.extend(_rule_discount_erosion(engine, period, discount_threshold))
    results.extend(_rule_regional_outlier(engine, period))
    results.extend(_rule_growth_reversal(engine, period))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(
        key=lambda x: (
            x["period"],
            severity_order.get(x["severity"], 99),
        ),
        reverse=False,
    )
    # Reverse chronological
    results = list(reversed(results))

    return results


# ─── STANDALONE RUNNER ────────────────────────────────────────────────────────

if __name__ == "__main__":
    anomalies = detect_anomalies()
    print(json.dumps(anomalies, indent=2, default=str))
    print(f"\nTotal anomalies detected: {len(anomalies)}")
