# src/app/streamlit_app.py
# Phase 6: Streamlit chat UI
# Run: streamlit run src/app/streamlit_app.py

import os
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# ─── STREAMLIT CLOUD SECRETS SHIM ─────────────────────────────────────────────
# Loads secrets from Streamlit Cloud dashboard if available, falls back to .env
try:
    for _key in [
        "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "ANTHROPIC_API_KEY",
        "SLACK_WEBHOOK_URL", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO", "ALERT_EMAIL_PASSWORD",
    ]:
        if _key in st.secrets:
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass

load_dotenv()

from src.agent.copilot import SalesCopilot
from src.tools.tool_layer import get_kpis, detect_anomalies_tool

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sales Analytics Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── SESSION STATE ────────────────────────────────────────────────────────────

if "copilot" not in st.session_state:
    st.session_state.copilot = SalesCopilot()
if "messages" not in st.session_state:
    st.session_state.messages = []

# ─── CHART BUILDER ────────────────────────────────────────────────────────────

def _build_charts(tool_calls: list[tuple]) -> list:
    """Convert tool call results into Plotly figures for inline display."""
    charts = []
    for tool_name, tool_input, tool_result in tool_calls:
        try:
            if tool_name == "get_kpis" and "kpis" in tool_result:
                df = pd.DataFrame(tool_result["kpis"])
                granularity = tool_input.get("granularity", "monthly")

                if granularity == "monthly" and "period" in df.columns:
                    df = df.sort_values("period")
                    fig = px.line(
                        df,
                        x="period",
                        y=["total_revenue", "total_profit"],
                        title="Monthly Revenue & Profit",
                        labels={"value": "Amount ($)", "period": "Month", "variable": "Metric"},
                        color_discrete_map={"total_revenue": "#4C9BE8", "total_profit": "#2ECC71"},
                    )
                    fig.update_layout(hovermode="x unified", legend_title_text="")
                    charts.append(fig)

                elif granularity == "category" and "category" in df.columns:
                    df_agg = df.groupby("category", as_index=False).agg(
                        total_revenue=("total_revenue", "sum"),
                        total_profit=("total_profit", "sum"),
                        margin_pct=("margin_pct", "mean"),
                    )
                    fig = px.bar(
                        df_agg,
                        x="category",
                        y=["total_revenue", "total_profit"],
                        barmode="group",
                        title="Revenue & Profit by Category",
                        labels={"value": "Amount ($)", "category": "Category", "variable": "Metric"},
                        color_discrete_map={"total_revenue": "#4C9BE8", "total_profit": "#2ECC71"},
                    )
                    charts.append(fig)

                elif granularity == "regional" and "region" in df.columns:
                    df_agg = df.groupby("region", as_index=False).agg(
                        total_revenue=("total_revenue", "sum"),
                        margin_pct=("margin_pct", "mean"),
                    )
                    fig = px.bar(
                        df_agg,
                        x="region",
                        y="total_revenue",
                        color="margin_pct",
                        title="Revenue by Region (color = margin %)",
                        labels={"total_revenue": "Total Revenue ($)", "region": "Region", "margin_pct": "Margin %"},
                        color_continuous_scale="RdYlGn",
                    )
                    charts.append(fig)

            elif tool_name == "detect_anomalies_tool" and "anomalies" in tool_result:
                anomalies = tool_result["anomalies"]
                if anomalies:
                    df = pd.DataFrame(anomalies)
                    color_map = {"high": "#E74C3C", "medium": "#F39C12", "low": "#3498DB"}
                    df["color"] = df["severity"].map(color_map)
                    fig = px.scatter(
                        df,
                        x="period",
                        y="flag",
                        color="severity",
                        size=df["delta"].abs().clip(lower=1),
                        hover_data=["segment", "delta"],
                        title="Detected Anomalies",
                        color_discrete_map={"high": "#E74C3C", "medium": "#F39C12", "low": "#3498DB"},
                        labels={"period": "Period", "flag": "Anomaly Type"},
                    )
                    charts.append(fig)

            elif tool_name == "get_forecast_tool" and "forecasts" in tool_result:
                forecasts = tool_result["forecasts"]
                metric = tool_result.get("metric", "revenue")
                df_fc = pd.DataFrame(forecasts)
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_fc["period"],
                    y=df_fc["forecast"],
                    mode="lines+markers",
                    name="Forecast",
                    line=dict(color="#4C9BE8", width=2),
                ))
                fig.add_trace(go.Scatter(
                    x=pd.concat([df_fc["period"], df_fc["period"][::-1]]),
                    y=pd.concat([df_fc["upper_80"], df_fc["lower_80"][::-1]]),
                    fill="toself",
                    fillcolor="rgba(76, 155, 232, 0.15)",
                    line=dict(color="rgba(255,255,255,0)"),
                    name="80% CI",
                ))
                fig.update_layout(
                    title=f"{metric.capitalize()} Forecast (80% Confidence Interval)",
                    xaxis_title="Period",
                    yaxis_title=f"{metric.capitalize()} ($)",
                    hovermode="x unified",
                )
                charts.append(fig)

            elif tool_name == "run_scenario" and "delta" in tool_result:
                delta = tool_result["delta"]
                scenario = tool_result["scenario"]
                actuals_df = pd.DataFrame(tool_result["actuals"])
                scenario_df = pd.DataFrame(tool_result["scenario_kpis"])
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=actuals_df["period"], y=actuals_df["total_profit"],
                    name="Actual Profit", line=dict(color="#2ECC71", dash="solid"),
                ))
                fig.add_trace(go.Scatter(
                    x=scenario_df["period"], y=scenario_df["total_profit"],
                    name="Scenario Profit", line=dict(color="#E74C3C", dash="dash"),
                ))
                fig.update_layout(
                    title=f"What-If: {scenario['parameter']} = {scenario['value']}",
                    xaxis_title="Period",
                    yaxis_title="Profit ($)",
                    hovermode="x unified",
                )
                charts.append(fig)

            elif tool_name == "drill_down" and "rows" in tool_result:
                rows = tool_result["rows"]
                if rows:
                    df = pd.DataFrame(rows)
                    df_agg = df.groupby("period", as_index=False).agg(
                        total_revenue=("total_revenue", "sum"),
                        total_profit=("total_profit", "sum"),
                    ).sort_values("period")
                    title_parts = [v for v in [
                        tool_input.get("category"),
                        tool_input.get("region"),
                        tool_input.get("period"),
                    ] if v]
                    title = "Drill-Down: " + (" / ".join(title_parts) if title_parts else "All")
                    fig = px.bar(
                        df_agg, x="period", y=["total_revenue", "total_profit"],
                        barmode="group", title=title,
                        labels={"value": "Amount ($)", "period": "Period", "variable": "Metric"},
                    )
                    charts.append(fig)

        except Exception:
            pass  # Never let chart rendering crash the app

    return charts


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 Sales Copilot")
    st.markdown("---")

    # Live KPI snapshot
    st.subheader("Live KPI Snapshot")
    try:
        kpi_data = get_kpis(granularity="monthly")
        kpis = kpi_data["kpis"]
        if kpis:
            latest = kpis[-1]
            prev = kpis[-2] if len(kpis) > 1 else latest
            rev_delta = float(latest["total_revenue"]) - float(prev["total_revenue"])
            margin_delta = float(latest["margin_pct"]) - float(prev["margin_pct"])
            st.metric("Revenue (latest month)", f"${float(latest['total_revenue']):,.0f}", f"${rev_delta:+,.0f}")
            st.metric("Profit Margin", f"{float(latest['margin_pct']):.1f}%", f"{margin_delta:+.1f}pp")
            st.metric("Period", latest["period"])
    except Exception as e:
        st.warning(f"Could not load KPIs: {e}")

    st.markdown("---")

    # Anomaly count
    st.subheader("Anomaly Status")
    try:
        anomaly_data = detect_anomalies_tool()
        count = anomaly_data["count"]
        high = sum(1 for a in anomaly_data["anomalies"] if a["severity"] == "high")
        medium = sum(1 for a in anomaly_data["anomalies"] if a["severity"] == "medium")
        if high > 0:
            st.error(f"🔴 {high} high-severity anomalies")
        if medium > 0:
            st.warning(f"🟡 {medium} medium-severity anomalies")
        if count == 0:
            st.success("✅ No anomalies detected")
        else:
            st.caption(f"{count} total anomalies detected across all periods")
    except Exception as e:
        st.warning(f"Could not load anomalies: {e}")

    st.markdown("---")

    # Suggested questions
    st.subheader("Try asking...")
    suggestions = [
        "What were the top anomalies in 2016?",
        "Forecast revenue for the next 3 months",
        "Which region has the lowest margin?",
        "What happens if we cut discounts to 15%?",
        "Show me Furniture performance in the West",
    ]
    for q in suggestions:
        if st.button(q, use_container_width=True, key=f"suggest_{q[:20]}"):
            st.session_state._pending_question = q

    st.markdown("---")

    if st.button("🔄 New Conversation", use_container_width=True):
        st.session_state.copilot.reset()
        st.session_state.messages = []
        st.rerun()

# ─── MAIN CHAT AREA ───────────────────────────────────────────────────────────

st.title("Sales Analytics Copilot")
st.caption("Ask anything about your Superstore sales data — powered by Claude")

# Render existing messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("charts"):
            for fig in msg["charts"]:
                st.plotly_chart(fig, use_container_width=True)

# Handle sidebar suggestion button clicks
pending = st.session_state.pop("_pending_question", None)

# Chat input
prompt = st.chat_input("Ask about your sales data...") or pending

if prompt:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt, "charts": []})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get copilot response
    with st.chat_message("assistant"):
        with st.spinner("Analysing..."):
            response, tool_calls = st.session_state.copilot.chat(prompt)

        if tool_calls:
            tool_names = ", ".join(tc[0] for tc in tool_calls)
            st.caption(f"Tools used: {tool_names}")

        st.markdown(response)
        charts = _build_charts(tool_calls)
        for fig in charts:
            st.plotly_chart(fig, use_container_width=True)

    st.session_state.messages.append({
        "role": "assistant",
        "content": response,
        "charts": charts,
    })
