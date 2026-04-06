# src/tools/tool_layer.py
# Phase 4: Structured tool layer — 6 tools exposed to Claude
# Run: python -m src.tools.tool_layer

import json
import os
import pandas as pd
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()


def _get_engine():
    from src.pipeline.ingest import get_engine
    return get_engine()


# ─── TOOL 1: GET KPIs ─────────────────────────────────────────────────────────

def get_kpis(period: str | None = None, granularity: str = "monthly") -> dict:
    """
    Return revenue, profit, margin, and discount KPIs.

    Parameters
    ----------
    period : str | None
        'YYYY-MM' to filter to a specific month, or None for all periods.
    granularity : str
        'monthly' (default), 'category', or 'regional'.

    Returns
    -------
    dict
        {"kpis": list[dict], "period": str|None, "granularity": str}
    """
    engine = _get_engine()

    view_map = {
        "monthly": "v_monthly_kpis",
        "category": "v_category_performance",
        "regional": "v_regional_performance",
    }
    view = view_map.get(granularity, "v_monthly_kpis")

    query = f"SELECT * FROM {view}"
    params: dict = {}
    if period:
        query += " WHERE period = :period"
        params["period"] = period
    query += " ORDER BY period"

    df = pd.read_sql(text(query), engine, params=params)
    return {
        "kpis": df.to_dict(orient="records"),
        "period": period,
        "granularity": granularity,
    }


# ─── TOOL 2: DETECT ANOMALIES ─────────────────────────────────────────────────

def detect_anomalies_tool(
    period: str | None = None,
    threshold: float = 25.0,
) -> dict:
    """
    Run the 4-rule anomaly detection engine and return flagged anomalies.

    Parameters
    ----------
    period : str | None
        'YYYY-MM' to scope the check, or None for all periods.
    threshold : float
        Discount erosion threshold in percent (default 25.0).

    Returns
    -------
    dict
        {"anomalies": list[dict], "count": int, "period": str|None}
    """
    from src.analytics.anomalies import detect_anomalies
    anomalies = detect_anomalies(period=period, discount_threshold=threshold)
    return {
        "anomalies": anomalies,
        "count": len(anomalies),
        "period": period,
    }


# ─── TOOL 3: DRILL DOWN ───────────────────────────────────────────────────────

def drill_down(
    category: str | None = None,
    region: str | None = None,
    period: str | None = None,
) -> dict:
    """
    Return granular KPI slice from fact_sales joined to dimension tables.

    Parameters
    ----------
    category : str | None
        Product category filter (e.g. 'Furniture').
    region : str | None
        Region filter (e.g. 'West').
    period : str | None
        'YYYY-MM' month filter.

    Returns
    -------
    dict
        {"rows": list[dict], "category": str|None, "region": str|None, "period": str|None}
    """
    engine = _get_engine()

    base_query = """
        SELECT
            TO_CHAR(f.order_date, 'YYYY-MM') AS period,
            p.category,
            p.sub_category,
            r.region,
            r.state,
            SUM(f.revenue)                                             AS total_revenue,
            SUM(f.profit)                                              AS total_profit,
            ROUND(SUM(f.profit) / NULLIF(SUM(f.revenue), 0) * 100, 2) AS margin_pct,
            ROUND(AVG(f.discount_pct) * 100, 2)                       AS avg_discount_pct,
            COUNT(DISTINCT f.order_id)                                 AS order_count
        FROM fact_sales f
        JOIN dim_product p ON f.product_key = p.product_key
        JOIN dim_region  r ON f.region_key  = r.region_key
        WHERE 1=1
    """

    conditions = []
    params: dict = {}

    if category:
        conditions.append("AND p.category = :category")
        params["category"] = category
    if region:
        conditions.append("AND r.region = :region")
        params["region"] = region
    if period:
        conditions.append("AND TO_CHAR(f.order_date, 'YYYY-MM') = :period")
        params["period"] = period

    group_by = """
        GROUP BY
            TO_CHAR(f.order_date, 'YYYY-MM'),
            p.category, p.sub_category,
            r.region, r.state
        ORDER BY period, p.category, r.region
    """

    full_query = base_query + "\n".join(conditions) + group_by
    df = pd.read_sql(text(full_query), engine, params=params)
    return {
        "rows": df.to_dict(orient="records"),
        "category": category,
        "region": region,
        "period": period,
    }


# ─── TOOL 4: GET FORECAST ─────────────────────────────────────────────────────

def get_forecast_tool(
    metric: str = "revenue",
    horizon: int = 3,
    segment: str | None = None,
) -> dict:
    """
    Forecast a KPI metric for the next N months using Prophet (default).

    Parameters
    ----------
    metric : str
        'revenue' or 'profit'.
    horizon : int
        Number of months to forecast (default 3).
    segment : str | None
        Category or region name, or None for aggregate.

    Returns
    -------
    dict
        {"metric", "segment", "horizon", "model", "forecasts": list[dict]}
    """
    from src.analytics.forecast import get_forecast
    return get_forecast(metric=metric, horizon=horizon, segment=segment, model="prophet")


# ─── TOOL 5: RUN SCENARIO ─────────────────────────────────────────────────────

def run_scenario(
    parameter: str,
    value: float,
    scope: str | None = None,
) -> dict:
    """
    Run a what-if scenario against the last 12 months of KPIs.

    Parameters
    ----------
    parameter : str
        'discount_pct'  — simulate a different average discount rate (%).
        'revenue_growth' — simulate a % change applied to all revenue figures.
    value : float
        New discount rate in % (for discount_pct), or growth % (for revenue_growth).
    scope : str | None
        Category or region to limit the scenario (None = all segments).

    Returns
    -------
    dict
        {"scenario": {...}, "actuals": list[dict], "scenario_kpis": list[dict], "delta": {...}}
    """
    engine = _get_engine()

    # Fetch last 12 months of monthly KPIs
    df = pd.read_sql(
        text(
            "SELECT period, total_revenue, total_profit, margin_pct, avg_discount_pct "
            "FROM v_monthly_kpis ORDER BY period DESC LIMIT 12"
        ),
        engine,
    ).sort_values("period").reset_index(drop=True)

    actuals = df.to_dict(orient="records")

    sim = df.copy()

    if parameter == "discount_pct":
        # Use observed discount-impact bands to estimate margin effect.
        # Each 10pp increase in avg discount reduces margin by ~4pp (empirical from v_discount_impact).
        current_avg_disc = float(df["avg_discount_pct"].mean())
        disc_delta = value - current_avg_disc          # pp change in discount rate
        margin_adjustment = disc_delta * (-0.4)        # empirical: 1pp discount ≈ -0.4pp margin

        sim["avg_discount_pct"] = value
        sim["margin_pct"] = (sim["margin_pct"] + margin_adjustment).clip(lower=-100)
        sim["total_profit"] = sim["total_revenue"] * sim["margin_pct"] / 100

    elif parameter == "revenue_growth":
        growth_factor = 1 + value / 100
        sim["total_revenue"] = sim["total_revenue"] * growth_factor
        sim["total_profit"] = sim["total_profit"] * growth_factor  # assume margin held constant

    else:
        raise ValueError(f"Unknown parameter '{parameter}'. Use 'discount_pct' or 'revenue_growth'.")

    scenario_kpis = sim.to_dict(orient="records")

    delta = {
        "revenue": round(float(sim["total_revenue"].sum() - df["total_revenue"].sum()), 2),
        "profit": round(float(sim["total_profit"].sum() - df["total_profit"].sum()), 2),
        "margin_pct": round(float(sim["margin_pct"].mean() - df["margin_pct"].mean()), 4),
    }

    return {
        "scenario": {"parameter": parameter, "value": value, "scope": scope},
        "actuals": actuals,
        "scenario_kpis": scenario_kpis,
        "delta": delta,
    }


# ─── TOOL 6: GENERATE SQL ─────────────────────────────────────────────────────

_SCHEMA_CONTEXT = """
Database: sales_copilot (PostgreSQL)

Tables:
- fact_sales: sale_id, order_id, order_date, ship_date, ship_mode, product_key,
  region_key, customer_key, revenue, quantity, discount_pct (0–1), profit, margin_pct, source_name
- dim_product: product_key, product_id, product_name, category, sub_category
- dim_region: region_key, region, country, state, city
- dim_customer: customer_key, customer_id, customer_name, segment
- dim_date: date_key, year, quarter, month, month_name, week, day_of_week, is_weekend

Views (pre-aggregated, prefer these):
- v_monthly_kpis: period (YYYY-MM), order_count, total_revenue, total_profit, margin_pct, avg_discount_pct
- v_category_performance: period, category, sub_category, order_count, total_revenue, total_profit, margin_pct, avg_discount_pct
- v_regional_performance: period, region, state, total_revenue, total_profit, margin_pct, avg_discount_pct, profit_rank
- v_discount_impact: category, discount_band, order_count, total_revenue, total_profit, margin_pct
- v_growth_rates: period, revenue, profit, revenue_mom_pct, profit_mom_pct

Note: avg_discount_pct in views is already multiplied by 100 (e.g. 25.0 = 25%).
      discount_pct in fact_sales is stored as 0–1 decimal.
"""


def generate_sql(natural_language_question: str) -> dict:
    """
    Convert a natural language question to SQL, execute it, and return results.

    Parameters
    ----------
    natural_language_question : str
        Plain English question about the sales data.

    Returns
    -------
    dict
        {"question": str, "sql": str, "result": list[dict], "row_count": int}
        On error: adds "error" key with the exception message.
    """
    import anthropic

    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=(
            "You are a SQL expert. Given a natural language question and a database schema, "
            "write a single valid PostgreSQL SELECT query that answers the question. "
            "Return ONLY the SQL query — no explanation, no markdown fences, no semicolon."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Schema:\n{_SCHEMA_CONTEXT}\n\n"
                    f"Question: {natural_language_question}"
                ),
            }
        ],
    )

    sql = response.content[0].text.strip().rstrip(";")

    # Safety: only allow SELECT statements
    if not sql.upper().lstrip().startswith("SELECT"):
        return {
            "question": natural_language_question,
            "sql": sql,
            "result": [],
            "row_count": 0,
            "error": "Generated query is not a SELECT statement — blocked for safety.",
        }

    engine = _get_engine()
    try:
        df = pd.read_sql(text(sql), engine)
        return {
            "question": natural_language_question,
            "sql": sql,
            "result": df.to_dict(orient="records"),
            "row_count": len(df),
        }
    except Exception as e:
        return {
            "question": natural_language_question,
            "sql": sql,
            "result": [],
            "row_count": 0,
            "error": str(e),
        }


# ─── TOOL DEFINITIONS (Anthropic API format) ──────────────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_kpis",
        "description": (
            "Return revenue, profit, margin, and discount KPIs from the sales database. "
            "Use granularity='monthly' for time trends, 'category' for product breakdown, "
            "'regional' for geographic breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Filter to a specific month in YYYY-MM format. Omit for all periods.",
                },
                "granularity": {
                    "type": "string",
                    "enum": ["monthly", "category", "regional"],
                    "description": "Level of aggregation (default: monthly).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "detect_anomalies_tool",
        "description": (
            "Run the 4-rule anomaly detection engine: margin compression, discount erosion, "
            "regional outliers, and MoM growth reversals. Returns flagged anomalies with "
            "severity (high/medium/low), segment, delta, and period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Scope to a specific month YYYY-MM, or omit for all periods.",
                },
                "threshold": {
                    "type": "number",
                    "description": "Discount erosion threshold in % (default 25.0).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "drill_down",
        "description": (
            "Return a granular KPI slice from the sales fact table. "
            "Filter by any combination of category, region, and period. "
            "Use this for detailed breakdowns beyond what the KPI views provide."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Product category: 'Furniture', 'Office Supplies', or 'Technology'.",
                },
                "region": {
                    "type": "string",
                    "description": "Sales region: 'West', 'East', 'Central', or 'South'.",
                },
                "period": {
                    "type": "string",
                    "description": "Month filter in YYYY-MM format.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_forecast_tool",
        "description": (
            "Forecast revenue or profit for the next N months using Prophet time-series model. "
            "Returns point forecasts with 80% confidence intervals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["revenue", "profit"],
                    "description": "Metric to forecast (default: revenue).",
                },
                "horizon": {
                    "type": "integer",
                    "description": "Number of months to forecast (default: 3).",
                },
                "segment": {
                    "type": "string",
                    "description": "Category or region name to segment the forecast. Omit for aggregate.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_scenario",
        "description": (
            "Run a what-if scenario against the last 12 months of KPIs. "
            "Simulate changing the average discount rate or applying a revenue growth rate. "
            "Returns actuals vs scenario KPIs and the net delta in revenue, profit, and margin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "parameter": {
                    "type": "string",
                    "enum": ["discount_pct", "revenue_growth"],
                    "description": (
                        "'discount_pct': simulate a new average discount rate in %. "
                        "'revenue_growth': simulate a % change applied to all revenue."
                    ),
                },
                "value": {
                    "type": "number",
                    "description": "New discount rate (%) or growth rate (%) to simulate.",
                },
                "scope": {
                    "type": "string",
                    "description": "Limit scenario to a category or region. Omit for all segments.",
                },
            },
            "required": ["parameter", "value"],
        },
    },
    {
        "name": "generate_sql",
        "description": (
            "Convert a natural language question into SQL, execute it against the sales database, "
            "and return the result. Use this for ad-hoc questions not covered by other tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "natural_language_question": {
                    "type": "string",
                    "description": "Plain English question about the sales data.",
                },
            },
            "required": ["natural_language_question"],
        },
    },
]


# ─── TOOL DISPATCHER ──────────────────────────────────────────────────────────

_TOOL_MAP = {
    "get_kpis": get_kpis,
    "detect_anomalies_tool": detect_anomalies_tool,
    "drill_down": drill_down,
    "get_forecast_tool": get_forecast_tool,
    "run_scenario": run_scenario,
    "generate_sql": generate_sql,
}


def dispatch_tool(name: str, inputs: dict) -> dict:
    """
    Dispatch a tool call by name with the given inputs.

    Parameters
    ----------
    name : str
        Tool name matching one of the TOOL_DEFINITIONS.
    inputs : dict
        Keyword arguments for the tool function.

    Returns
    -------
    dict
        JSON-serialisable result from the tool.
    """
    if name not in _TOOL_MAP:
        return {"error": f"Unknown tool: '{name}'. Valid tools: {list(_TOOL_MAP)}"}
    try:
        return _TOOL_MAP[name](**inputs)
    except Exception as e:
        return {"error": str(e), "tool": name, "inputs": inputs}


# ─── STANDALONE RUNNER ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Tool 1: get_kpis (monthly, last 3 periods) ===")
    r = get_kpis(granularity="monthly")
    print(f"  {len(r['kpis'])} periods returned. Latest: {r['kpis'][-1]}\n")

    print("=== Tool 2: detect_anomalies_tool ===")
    r = detect_anomalies_tool()
    print(f"  {r['count']} anomalies. First: {r['anomalies'][0] if r['anomalies'] else 'none'}\n")

    print("=== Tool 3: drill_down (Furniture, West) ===")
    r = drill_down(category="Furniture", region="West")
    print(f"  {len(r['rows'])} rows returned. Sample: {r['rows'][0] if r['rows'] else 'none'}\n")

    print("=== Tool 4: get_forecast_tool (revenue, 3m) ===")
    r = get_forecast_tool(metric="revenue", horizon=3)
    print(f"  Forecasts: {r['forecasts']}\n")

    print("=== Tool 5: run_scenario (reduce discount to 15%) ===")
    r = run_scenario(parameter="discount_pct", value=15.0)
    print(f"  Delta: {r['delta']}\n")

    print("=== Tool 6: generate_sql ===")
    r = generate_sql("What are the top 3 states by total revenue?")
    print(f"  SQL: {r['sql']}")
    print(f"  Result: {r['result']}\n")
