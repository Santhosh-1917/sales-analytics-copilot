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
- [x] Phase 3: src/analytics/anomalies.py + forecast.py
- [x] Phase 4: src/tools/tool_layer.py
- [x] Phase 5: src/agent/copilot.py
- [x] Phase 6: src/app/streamlit_app.py
- [x] Phase 7: .github/workflows/nightly.yml + src/pipeline/alerts.py
- [x] Phase 8: docs/dashboard-setup.md

## What's Already Built

### Phase 1 — `src/pipeline/ingest.py`
Full ETL pipeline: reads `data/raw/Superstore.csv` (latin-1 encoding), validates,
maps columns, deduplicates on `(order_id, product_id)`, upserts dimensions, loads
fact_sales. Run: `python -m src.pipeline.ingest` from project root.
- 9,986 rows loaded, 8 rejected (out of 9,994 raw rows)
- Fixes applied vs original: `encoding="latin-1"` on read_csv; duplicate check changed
  from `order_id` alone → `(order_id, product_id)` (orders have multiple line items)

### Phase 2 — `sql/01_schema.sql`
Star schema + 5 KPI views already applied to `sales_copilot` PostgreSQL DB.
- DB: localhost:5432, user: santhosh, DB name: sales_copilot
- Views: v_monthly_kpis, v_category_performance, v_regional_performance,
  v_discount_impact, v_growth_rates
- IMPORTANT: avg_discount_pct in all views is already multiplied by 100
  (e.g. 25.0 = 25%). Do NOT multiply by 100 again in Python code.

### Phase 3 — `src/analytics/anomalies.py` + `src/analytics/forecast.py`
Run with `python -m src.analytics.anomalies` / `python -m src.analytics.forecast`
(must use `-m` flag from project root for src.* imports to resolve).

**anomalies.py** — 4 rules, all verified working:
- Rule 1 margin_compression: revenue_mom > +2% AND profit_mom < -1%
- Rule 2 discount_erosion: avg category discount > threshold (default 25%);
  view is grouped by sub_category so must re-aggregate to category level in Pandas
- Rule 3 regional_outlier: margin_pct < mean - 2σ across regions per period;
  view has state rows so must re-aggregate to region level
- Rule 4 growth_reversal: prev_mom > 0 AND curr_mom < 0 AND next_mom < 0
- Output: 20 anomalies detected across 2014–2017 dataset

**forecast.py** — Prophet + ARIMA, both verified working:
- Prophet: Jan–Mar 2018 revenue forecast $45.7K / $32.9K / $72.1K
- ARIMA: profit ~$8.5K/month for next 3 months
- Series format: ds (datetime, first of month) + y (float)
- Convert period 'YYYY-MM' → datetime by appending '-01'

### Phase 4 — `src/tools/tool_layer.py`
Run with `python -m src.tools.tool_layer`
6 tools verified working (Tools 1–5 fully tested; Tool 6 requires ANTHROPIC_API_KEY):
1. `get_kpis(period, granularity)` — routes to KPI view, returns {"kpis", "period", "granularity"}
2. `detect_anomalies_tool(period, threshold)` — wraps anomalies.detect_anomalies()
3. `drill_down(category, region, period)` — dynamic SQL with bound params only
4. `get_forecast_tool(metric, horizon, segment)` — wraps forecast.get_forecast()
5. `run_scenario(parameter, value, scope)` — what-if on last 12 months KPIs (pure Pandas)
6. `generate_sql(question)` — calls Claude API → executes SELECT only (needs API key)
- `TOOL_DEFINITIONS` list and `dispatch_tool(name, inputs)` dispatcher exported for copilot.py

### Phase 5 — `src/agent/copilot.py`
Run with `python -m src.agent.copilot` for interactive CLI.
- `SalesCopilot` class: `chat(user_message) -> (str, list[tuple])`, `reset()`
- Multi-turn tool loop: stop_reason=="tool_use" → dispatch → feed results → loop
- tool_calls_made returned as list of (tool_name, tool_input, tool_result) for Streamlit chart rendering
- History truncation at 20 turns: keeps first + last 18
- Verified: "What was total revenue in 2017?" → correctly called generate_sql → returned $732,568.47

### Phase 6 — `src/app/streamlit_app.py`
Run with `streamlit run src/app/streamlit_app.py`
- Streamlit Cloud secrets shim at top (falls back to .env locally)
- Sidebar: live KPI snapshot (latest month revenue/margin with deltas) + anomaly count
- Sidebar: 5 suggested question buttons that pre-fill the chat input
- Charts auto-rendered based on which tools were called:
  - get_kpis monthly → px.line, category → px.bar, regional → px.bar with color scale
  - detect_anomalies_tool → px.scatter bubble chart by severity
  - get_forecast_tool → go.Figure fan chart with 80% CI shaded band
  - run_scenario → dual-line actual vs scenario profit chart
  - drill_down → grouped bar by period

### Phase 7 — `.github/workflows/nightly.yml` + `src/pipeline/alerts.py`
- nightly.yml: runs at 06:00 UTC daily + workflow_dispatch manual trigger
- Runs `python -m src.pipeline.ingest` then `python -m src.pipeline.alerts`
- alerts.py: detects anomalies, filters to high/medium, sends Slack (Block Kit) + HTML email
- Slack/email are skipped silently if env vars not set (safe for local runs)
- Updates run_log.anomalies_found after alerting

### Phase 8 — `docs/dashboard-setup.md`
- Power BI DirectQuery setup (5 KPI views, recommended visuals)
- Tableau Live connection setup (recommended sheets)
- Read-only bi_reader PostgreSQL user SQL commands
- Note on Power BI Gateway for private networks

## Known Issues / Gotchas
- All scripts must be run as modules from project root: `python -m src.x.y` not `python src/x/y.py`
- Prophet is NOT in requirements.txt — install separately: `pip install prophet`
- streamlit and plotly are NOT in requirements.txt — install separately: `pip install streamlit plotly`
- ANTHROPIC_API_KEY must be set in .env for Phase 5 (copilot), Phase 6 (UI), and Tool 6 (generate_sql)
- Streamlit app imports src.* — must be launched from project root, not from inside src/app/

## Project Complete — All 8 Phases Built
