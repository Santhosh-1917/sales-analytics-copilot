# Automated Sales Analytics Copilot

## Project Overview
An agentic analytics system that ingests multi-source sales data, computes KPIs,
detects business anomalies, answers natural language questions via text-to-SQL,
models what-if scenarios, and sends automated alerts — powered by the Claude API.

Built by Santhosh Narayanan Baburaman (USC MS Analytics) as a portfolio project
targeting Data Analyst / Business Analyst roles.

## Architecture (8 Phases)
1. Multi-source ingestion + validation → PostgreSQL
2. Star schema + KPI SQL views
3. Anomaly detection (4 rules) + ARIMA/Prophet forecasting
4. Structured tool layer (6 tools exposed to Claude)
5. Agentic Claude reasoning loop (multi-step tool calling)
6. Streamlit chat UI (deployed on Streamlit Cloud)
7. GitHub Actions automation + Slack/email alerting
8. Power BI / Tableau live dashboard integration

## Project Structure
```
project/
├── config/
│   └── sources.yaml          # Data source config (column mapping, thresholds)
├── data/
│   └── raw/                  # Raw CSV files go here
├── sql/
│   └── 01_schema.sql         # Star schema + all KPI views
├── src/
│   ├── pipeline/
│   │   └── ingest.py         # ETL + validation pipeline
│   ├── analytics/
│   │   ├── anomalies.py      # 4-rule anomaly detection engine
│   │   └── forecast.py       # ARIMA + Prophet forecasting
│   ├── tools/
│   │   └── tool_layer.py     # 6 structured tools for Claude
│   ├── agent/
│   │   └── copilot.py        # Agentic Claude reasoning loop
│   └── app/
│       └── streamlit_app.py  # Chat UI
├── .github/
│   └── workflows/
│       └── nightly.yml       # Scheduled GitHub Actions pipeline
├── .env                      # Local only — never commit
├── .env.example              # Committed version without secrets
├── requirements.txt
├── README.md
└── CLAUDE.md                 # This file
```

## Database Schema (PostgreSQL)
**Fact table:** `fact_sales` (order_id, order_date, ship_date, ship_mode,
product_key, region_key, customer_key, revenue, quantity, discount_pct,
profit, margin_pct, source_name, loaded_at)

**Dimension tables:** `dim_date`, `dim_product`, `dim_region`, `dim_customer`

**KPI Views:** `v_monthly_kpis`, `v_category_performance`, `v_regional_performance`,
`v_discount_impact`, `v_growth_rates`

**Tracking tables:** `run_log`, `error_log`

## The 6 Tools (Phase 4)
1. `get_kpis(period, granularity)` → revenue, profit, margin, growth as JSON
2. `detect_anomalies(period, threshold)` → flagged anomalies with severity + delta
3. `drill_down(category, region, period)` → granular KPI slice
4. `get_forecast(metric, horizon, segment)` → point forecast + confidence intervals
5. `run_scenario(parameter, value, scope)` → what-if recalculated KPIs vs actuals
6. `generate_sql(natural_language_question)` → executes dynamic SQL, returns result

## Anomaly Detection Rules
1. **Margin compression** — revenue up >2% but profit down >1%
2. **Discount erosion** — avg discount in a category exceeded threshold (default 25%)
3. **Regional outlier** — a region's margin >2σ below the mean
4. **MoM growth reversal** — positive growth trend flips negative for 2+ periods

Each anomaly outputs: flag, severity (low/medium/high), segment, delta, period.

## Key Environment Variables
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — PostgreSQL connection
- `ANTHROPIC_API_KEY` — Claude API for the agentic layer
- `SLACK_WEBHOOK_URL` — for anomaly alerts (optional)
- `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, `ALERT_EMAIL_PASSWORD` — email alerts (optional)

## Tech Stack
- **Language:** Python 3.11+, SQL
- **Database:** PostgreSQL (SQLAlchemy + psycopg2)
- **ETL:** Pandas, PyYAML
- **Analytics:** Pandas, NumPy, SciPy
- **Forecasting:** Prophet, statsmodels (ARIMA)
- **AI Layer:** Anthropic Python SDK (claude-sonnet-4-6, tool use)
- **UI:** Streamlit
- **Automation:** GitHub Actions
- **Alerting:** Slack SDK, smtplib

## Dataset
Using the Superstore sales dataset (similar to the Tableau dashboard project).
~25,000 orders, $12.6M revenue, categories: Furniture / Office Supplies / Technology.
Known insight: discounts above 30% drive significant losses — especially in Furniture.

## Coding Conventions
- All DB interactions via SQLAlchemy (never raw psycopg2 string queries)
- All secrets via python-dotenv (.env file, never hardcoded)
- Each tool function returns clean JSON — no unstructured text
- Anomaly output always includes: flag, severity, segment, delta, period
- SQL views preferred over in-memory Pandas aggregations for KPIs
- Type hints on all functions
- Docstrings on all public functions

## Current Build Status
- [x] Phase 1: src/pipeline/ingest.py (ETL + validation)
- [x] Phase 2: sql/01_schema.sql (star schema + KPI views)
- [ ] Phase 3: src/analytics/anomalies.py + forecast.py
- [ ] Phase 4: src/tools/tool_layer.py
- [ ] Phase 5: src/agent/copilot.py
- [ ] Phase 6: src/app/streamlit_app.py
- [ ] Phase 7: .github/workflows/nightly.yml
- [ ] Phase 8: Dashboard integration

## What's Already Built
- `src/pipeline/ingest.py` — full ETL pipeline with 5 validation checks,
  dimension upserts, fact table loading, run_log and error_log tracking
- `sql/01_schema.sql` — complete star schema + 5 KPI views
- `config/sources.yaml` — configurable column mapping and validation thresholds
- `requirements.txt` — all dependencies pinned

## Next Up
Build Phase 3: anomaly detection engine in src/analytics/anomalies.py
