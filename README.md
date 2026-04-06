# Automated Sales Analytics Copilot

> An end-to-end agentic analytics system that ingests multi-source sales data, computes KPIs, detects business anomalies, answers natural language questions, models what-if scenarios, and delivers automated alerts — powered by the Anthropic Claude API.

**Santhosh Narayanan Baburaman** | USC MS Analytics | Data Analyst / Business Analyst

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791.svg?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Claude API](https://img.shields.io/badge/Claude_API-claude--sonnet--4--6-D97757.svg)](https://anthropic.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Chat_UI-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Nightly_Pipeline-2088FF.svg?logo=githubactions&logoColor=white)](https://github.com/features/actions)

---

## App Preview

![Streamlit Chat UI](docs/images/app_screenshot.png)

---

## What It Does

Ask it anything about your sales data in plain English:

> *"Why did profit drop in Q3 2016?"*
> *"Which regions are underperforming and by how much?"*
> *"What happens to margin if we cut discounts to 15%?"*
> *"Forecast revenue for the next 3 months."*

The copilot reasons over a live PostgreSQL database using 6 structured tools, runs anomaly detection nightly via GitHub Actions, and renders answers as charts and natural language inside a Streamlit chat UI.

---

## Architecture

![Architecture Diagram](docs/images/architecture.png)

---

## Key Features

### Anomaly Detection — 4 Business Rules
Automatically flags data quality and business issues every night. Each anomaly includes `flag`, `severity`, `segment`, `delta`, and `period`.

| Rule | What It Catches |
|------|----------------|
| **Margin Compression** | Revenue up >2% MoM but profit drops >1% — hidden cost pressure |
| **Discount Erosion** | Category avg discount exceeds threshold (default 25%) |
| **Regional Outlier** | A region's margin falls >2σ below the period mean |
| **Growth Reversal** | Positive MoM growth flips negative for 2+ consecutive months |

### Forecasting
Prophet and ARIMA models trained on monthly KPI data. Returns point forecasts with 80% confidence intervals by metric (revenue / profit) and optional segment (category or region).

### 6 Structured Tools
The AI agent calls these tools to answer questions — the only data access layer:

| Tool | What It Does |
|------|-------------|
| `get_kpis` | Monthly / category / regional KPI summaries from SQL views |
| `detect_anomalies_tool` | Run all 4 rules, return flagged results with severity |
| `drill_down` | Granular breakdown by category, region, and/or period |
| `get_forecast_tool` | Prophet time-series forecast with confidence interval |
| `run_scenario` | What-if — simulate discount rate or revenue growth changes |
| `generate_sql` | Natural language → SQL → executed result |

### What-If Scenario Engine
Simulate business decisions against the last 12 months of KPIs — no DB writes, pure in-memory analysis. Returns actuals vs scenario KPIs side-by-side with net delta in revenue, profit, and margin.

### Nightly Automation
GitHub Actions runs the full pipeline at 06:00 UTC every day — ingests new data, detects anomalies, and dispatches Slack / email alerts for high and medium severity findings.

---

## Tech Stack

| Layer | Tools |
|-------|-------|
| Language | Python 3.11+, SQL |
| Database | PostgreSQL — star schema + 5 KPI views |
| ETL | Pandas, SQLAlchemy, PyYAML |
| Analytics | Pandas, NumPy, SciPy |
| Forecasting | Prophet, statsmodels (ARIMA) |
| AI Layer | Anthropic Claude API (`claude-sonnet-4-6`) — multi-step tool use |
| UI | Streamlit — deployable on Streamlit Cloud |
| Dashboard | Power BI DirectQuery / Tableau Live |
| Alerting | Slack Webhooks (Block Kit), SMTP email |
| Automation | GitHub Actions (nightly cron + manual trigger) |

---

## Dataset

Superstore sales dataset — 9,986 orders, ~$2.3M revenue across 4 years (2014–2017).
Categories: **Furniture / Office Supplies / Technology** across 4 US regions.

Key insight: **discounts above 30% drive significant losses — especially in Furniture**, where average margin drops to -22% in the 30–50% discount band.

---

## Project Structure

```
sales-analytics-copilot/
├── config/
│   └── sources.yaml              # Column mapping + validation thresholds
├── data/
│   └── raw/                      # Raw CSV files
├── docs/
│   ├── dashboard-setup.md        # Power BI + Tableau connection guide
│   └── images/                   # Architecture diagram + app screenshot
├── sql/
│   └── 01_schema.sql             # Star schema + 5 KPI views
├── src/
│   ├── pipeline/
│   │   ├── ingest.py             # ETL + validation pipeline
│   │   └── alerts.py             # Slack + email anomaly alerts
│   ├── analytics/
│   │   ├── anomalies.py          # 4-rule anomaly detection engine
│   │   └── forecast.py           # Prophet + ARIMA forecasting
│   ├── tools/
│   │   └── tool_layer.py         # 6 structured tools + dispatcher
│   ├── agent/
│   │   └── copilot.py            # Agentic Claude reasoning loop
│   └── app/
│       └── streamlit_app.py      # Streamlit chat UI
├── .github/
│   └── workflows/
│       └── nightly.yml           # Nightly pipeline (cron + manual trigger)
├── .env.example
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Clone and install
```bash
git clone https://github.com/Santhosh-1917/sales-analytics-copilot
cd sales-analytics-copilot
pip install -r requirements.txt
pip install prophet streamlit plotly   # install separately due to build deps
```

### 2. Configure environment
```bash
cp .env.example .env
```
Edit `.env`:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=sales_copilot
DB_USER=your_pg_user
DB_PASSWORD=your_pg_password
ANTHROPIC_API_KEY=sk-ant-...        # required for the AI agent
SLACK_WEBHOOK_URL=...               # optional — Slack anomaly alerts
ALERT_EMAIL_FROM=...                # optional — email alerts
ALERT_EMAIL_TO=...
ALERT_EMAIL_PASSWORD=...            # Gmail app password
```

### 3. Create database and schema
```bash
createdb sales_copilot
psql -U your_pg_user -d sales_copilot -f sql/01_schema.sql
```

### 4. Add data and run the pipeline
```bash
# Place Superstore.csv in data/raw/
python -m src.pipeline.ingest
```

### 5. Launch the app
```bash
streamlit run src/app/streamlit_app.py
```

---

## Database Schema

**Fact table:** `fact_sales` — order_id, order_date, ship_date, ship_mode, product_key, region_key, customer_key, revenue, quantity, discount_pct, profit, margin_pct

**Dimensions:** `dim_date`, `dim_product`, `dim_region`, `dim_customer`

**KPI Views:**

| View | Description |
|------|-------------|
| `v_monthly_kpis` | Period-level revenue, profit, margin, avg discount |
| `v_category_performance` | Breakdown by category + sub_category |
| `v_regional_performance` | Breakdown by region + state with profit rank |
| `v_discount_impact` | Revenue/profit by discount band (0%, 1–10%, 11–20%…) |
| `v_growth_rates` | MoM revenue and profit growth percentages |

---

## Build Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Multi-source ingestion + validation → PostgreSQL | ✅ |
| 2 | Star schema + 5 KPI SQL views | ✅ |
| 3 | Anomaly detection (4 rules) + Prophet/ARIMA forecasting | ✅ |
| 4 | Structured tool layer (6 tools + dispatcher) | ✅ |
| 5 | Agentic Claude reasoning loop | ✅ |
| 6 | Streamlit chat UI + inline charts | ✅ |
| 7 | GitHub Actions nightly pipeline + Slack/email alerts | ✅ |
| 8 | Power BI / Tableau live dashboard integration | ✅ |

---

*Santhosh Narayanan Baburaman | USC MS Analytics | [LinkedIn](https://linkedin.com/in/santhosh-narayanan-7b9466249)*
