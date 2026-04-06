# Implementation Plan: Phases 3–8 — Automated Sales Analytics Copilot

**Date:** 2026-04-06

---

## Codebase Patterns (from Phase 1 & 2)

1. DB connection via `get_engine()` using `postgresql+psycopg2://` + `os.getenv()` after `load_dotenv()`
2. All raw SQL wrapped in `sqlalchemy.text()` — no string-interpolated queries
3. Tool layer functions return JSON-serializable `dict`
4. Error handling: try/except with logging to `run_log`/`error_log`
5. KPI view columns: `period` (YYYY-MM), `total_revenue`, `total_profit`, `margin_pct`, `avg_discount_pct`
6. Type hints + docstrings on every public function
7. Config-driven thresholds via `config/sources.yaml`

---

## Phase 3 — Analytics Engine

### 3.1 `src/analytics/anomalies.py`

**Imports:**
```python
import os, numpy as np, pandas as pd
from scipy import stats
from sqlalchemy import text
from dotenv import load_dotenv
from src.pipeline.ingest import get_engine
```

**Anomaly schema (every result):**
```python
{"flag": str, "severity": str, "segment": str, "delta": float, "period": str}
```

**Rule 1 — Margin Compression:**
- Query `v_monthly_kpis`: `period, total_revenue, total_profit, margin_pct`
- Compute MoM revenue change and MoM profit change
- Flag where revenue_mom > +2% AND profit_mom < -1%
- Severity: profit_mom < -5% → "high", -3% to -5% → "medium", else "low"
- segment="all", delta=profit_mom

**Rule 2 — Discount Erosion:**
- Query `v_category_performance`: `period, category, avg_discount_pct`
- `threshold` param (default 25.0 meaning 25%)
- Flag where `avg_discount_pct * 100 > threshold` (view stores as decimal e.g. 0.25 = 25%)
- Severity: > 40% → "high", 30–40% → "medium", else "low"
- segment=category, delta=avg_discount_pct*100 - threshold

**Rule 3 — Regional Outlier:**
- Query `v_regional_performance`: `period, region, margin_pct` for given period (or all)
- For each period group: compute mean + std of margin_pct across regions
- Flag where margin_pct < mean - 2*std
- Severity: < mean-3σ → "high", between 2σ-2.5σ → "medium", else "low"
- segment=region, delta=z-score (negative)

**Rule 4 — MoM Growth Reversal:**
- Query `v_growth_rates`: `period, revenue_mom_pct, profit_mom_pct`
- Scan for transition: prior period positive → current period negative → next period also negative (2+ consecutive negatives after positive run)
- segment="revenue" or "profit", delta=mom_pct at trigger, severity by magnitude

**Public function:**
```python
def detect_anomalies(period: str | None = None, discount_threshold: float = 25.0) -> list[dict]:
```
Calls all four rules, concatenates, returns sorted list.

Standalone runner: `if __name__ == "__main__"` prints JSON.

---

### 3.2 `src/analytics/forecast.py`

**Data helper:**
```python
def _get_monthly_series(metric: str, segment: str | None = None) -> pd.DataFrame:
```
Returns DataFrame with columns `ds` (datetime) and `y` (metric value).
Query `v_monthly_kpis` for global; `v_category_performance`/`v_regional_performance` for segments.
Convert `period` string 'YYYY-MM' → datetime by appending '-01'.

**ARIMA wrapper:**
```python
def _forecast_arima(series: pd.DataFrame, horizon: int, order: tuple = (1,1,1)) -> list[dict]:
```
Use `statsmodels.tsa.arima.model.ARIMA`. Return list of `{"period", "forecast", "lower_80", "upper_80", "model": "arima"}`.

**Prophet wrapper:**
```python
def _forecast_prophet(series: pd.DataFrame, horizon: int) -> list[dict]:
```
Use `prophet.Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)`.
Use `make_future_dataframe(periods=horizon, freq='MS')`. Return future-only rows.

**Public function:**
```python
def get_forecast(metric: str = "revenue", horizon: int = 3, segment: str | None = None, model: str = "prophet") -> dict:
```
Returns `{"metric", "segment", "horizon", "forecasts": list[dict], "model"}`.
Wrap calls in try/except; ARIMA failure falls back to Prophet with `"warning"` key.

---

## Phase 4 — Structured Tool Layer

**File:** `src/tools/tool_layer.py`

**Imports:**
```python
import json
from sqlalchemy import text
from src.pipeline.ingest import get_engine
from src.analytics.anomalies import detect_anomalies
from src.analytics.forecast import get_forecast as _get_forecast
```

Module-level `_engine = get_engine()`.

### Tool 1: `get_kpis(period, granularity)`
Route granularity to view: "monthly"→`v_monthly_kpis`, "category"→`v_category_performance`, "regional"→`v_regional_performance`.
Return `{"kpis": list[dict], "period": period, "granularity": granularity}`.

### Tool 2: `detect_anomalies_tool(period, threshold)`
Thin wrapper around `detect_anomalies()`.
Return `{"anomalies": list[dict], "count": int, "period": period}`.

### Tool 3: `drill_down(category, region, period)`
Dynamic SQL against `fact_sales` joined to dimension tables. Build WHERE clauses dynamically using `sqlalchemy.text()` with bound params (never string interpolation).
```sql
SELECT TO_CHAR(f.order_date, 'YYYY-MM') AS period,
       p.category, p.sub_category, r.region, r.state,
       SUM(f.revenue), SUM(f.profit),
       ROUND(SUM(f.profit)/NULLIF(SUM(f.revenue),0)*100, 2) AS margin_pct,
       ROUND(AVG(f.discount_pct)*100, 2) AS avg_discount_pct,
       COUNT(DISTINCT f.order_id) AS order_count
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
JOIN dim_region r ON f.region_key = r.region_key
WHERE 1=1 [AND p.category=:category] [AND r.region=:region] [AND TO_CHAR(f.order_date,'YYYY-MM')=:period]
GROUP BY ...
```
Return `{"rows": list[dict], "category", "region", "period"}`.

### Tool 4: `get_forecast_tool(metric, horizon, segment)`
Thin wrapper around `_get_forecast()`. Returns dict directly.

### Tool 5: `run_scenario(parameter, value, scope)`
Supported parameters: `"discount_pct"`, `"revenue_growth"`.
Fetch last 12 months from `v_monthly_kpis`. Apply change in Pandas (no DB write).
Return `{"scenario": {...}, "actuals": list[dict], "scenario_kpis": list[dict], "delta": {...}}`.

### Tool 6: `generate_sql(natural_language_question)`
1. Build schema context string (hardcoded table/view column summaries)
2. Call `anthropic.Anthropic().messages.create()` to generate SQL (SELECT only)
3. Guard: reject non-SELECT statements
4. Execute via `pd.read_sql(text(sql), engine)` in try/except
5. Return `{"question", "sql", "result": list[dict], "row_count"}`.

### Tool definitions & dispatcher:
```python
TOOL_DEFINITIONS: list[dict]  # Anthropic tool-use schema for all 6 tools
dispatch_tool(name: str, inputs: dict) -> dict  # maps name → function
```

Standalone runner: `if __name__ == "__main__"` calls all 6 tools and prints results.

---

## Phase 5 — Agentic Claude Reasoning Loop

**File:** `src/agent/copilot.py`

```python
import os, json
from anthropic import Anthropic
from dotenv import load_dotenv
from src.tools.tool_layer import TOOL_DEFINITIONS, dispatch_tool

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-4-6"
```

**SYSTEM_PROMPT:** Describes agent role, available tools, instructs Claude to always call tools before answering data questions, cite specific numbers, be concise.

**`SalesCopilot` class:**
```python
class SalesCopilot:
    def __init__(self):
        self.conversation_history: list[dict] = []
    
    def chat(self, user_message: str) -> tuple[str, list]:
        # Returns (text_response, tool_calls_made)
        # tool_calls_made: list of (tool_name, tool_input, tool_result)
    
    def reset(self):
        self.conversation_history = []
```

**Tool loop inside `chat()`:**
1. Append user message to history
2. Call `client.messages.create(model, tools=TOOL_DEFINITIONS, messages=history, max_tokens=4096)`
3. Append assistant response to history
4. If `stop_reason == "tool_use"`:
   - Extract all `tool_use` blocks from `response.content`
   - For each: call `dispatch_tool(block.name, block.input)` in try/except
   - Build `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": json.dumps(result)}]}` message
   - Append to history, loop back to step 2
5. If `stop_reason == "end_turn"`: extract text, return `(text, tool_calls_made)`

**History truncation:** if > 20 turns, keep first message + last 18.

**CLI runner:**
```python
def run_cli():
    copilot = SalesCopilot()
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"): break
        response, _ = copilot.chat(user_input)
        print(f"\nCopilot: {response}\n")

if __name__ == "__main__":
    run_cli()
```

---

## Phase 6 — Streamlit Chat UI

**File:** `src/app/streamlit_app.py`

**Streamlit secrets compatibility shim** (top of file):
```python
try:
    for key in ["DB_HOST","DB_PORT","DB_NAME","DB_USER","DB_PASSWORD","ANTHROPIC_API_KEY"]:
        if key in st.secrets: os.environ[key] = st.secrets[key]
except Exception: pass
load_dotenv()
```

**Page config:** `st.set_page_config(page_title="Sales Analytics Copilot", page_icon="📊", layout="wide")`

**Session state init:** `copilot` (SalesCopilot), `messages` (list), `tool_calls` (list).

**Sidebar KPI snapshot:** call `get_kpis()` + `detect_anomalies_tool()` directly on load. Display with `st.metric()` and delta arrows.

**Chart rendering based on tool calls:**
- `get_kpis` monthly → `px.line()` revenue/profit over time
- `get_kpis` category → `px.bar()` by category
- `get_kpis` regional → `px.choropleth()` US states
- `detect_anomalies_tool` → colored severity cards (st.container + custom HTML)
- `get_forecast_tool` → fan chart with `go.Figure()` + shaded CI band

**Chat submit handler:**
```python
if prompt := st.chat_input("Ask about your sales data..."):
    st.session_state.messages.append({"role": "user", "content": prompt, "charts": None})
    with st.spinner("Analysing..."):
        response, tool_calls = st.session_state.copilot.chat(prompt)
    charts = _build_charts(tool_calls)
    st.session_state.messages.append({"role": "assistant", "content": response, "charts": charts})
    st.rerun()
```

**`_build_charts(tool_calls)` → list of Plotly figures.**

**Reset button** in sidebar: calls `copilot.reset()` and clears messages.

---

## Phase 7 — GitHub Actions + Alerting

### `.github/workflows/nightly.yml`
```yaml
name: Nightly Analytics Pipeline
on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:
jobs:
  ingest-and-alert:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: pip install -r requirements.txt
      - name: Run ingestion
        env: {DB_HOST: ${{secrets.DB_HOST}}, ...all DB secrets}
        run: python src/pipeline/ingest.py
      - name: Run anomaly alerts
        env: {all DB secrets, SLACK_WEBHOOK_URL, ALERT_EMAIL_*}
        run: python src/pipeline/alerts.py
```

### `src/pipeline/alerts.py`

**Slack (`send_slack_alert`):** Block Kit message with severity emojis (🔴🟡🟢), segment, flag, delta, period. Uses `slack_sdk.webhook.WebhookClient`. Guard: skip if `SLACK_WEBHOOK_URL` not set.

**Email (`send_email_alert`):** HTML table of anomalies via `smtplib.SMTP_SSL("smtp.gmail.com", 465)`. Guard: skip if `ALERT_EMAIL_FROM` not set.

**Main runner (`run_alerts`):**
- Detect anomalies, filter to high/medium
- If none: print and return
- Dispatch Slack + email
- Update `run_log.anomalies_found` (column exists in schema)

Standalone: `if __name__ == "__main__": run_alerts()`

---

## Phase 8 — Dashboard Integration

**File:** `docs/dashboard-setup.md`

**Power BI DirectQuery:**
1. Get Data → PostgreSQL database
2. Enter host/port/db
3. Select the 5 KPI views (DirectQuery mode, not Import)
4. Recommended visuals: line on `v_monthly_kpis.total_revenue`, bar on `v_category_performance.margin_pct`, filled map on `v_regional_performance`

**Tableau Live Connection:**
1. Connect → PostgreSQL → Live (not Extract)
2. Drag views onto canvas

**Read-only BI user SQL:**
```sql
CREATE USER bi_reader WITH PASSWORD 'choose_a_password';
GRANT CONNECT ON DATABASE sales_copilot TO bi_reader;
GRANT USAGE ON SCHEMA public TO bi_reader;
GRANT SELECT ON v_monthly_kpis, v_category_performance,
               v_regional_performance, v_discount_impact,
               v_growth_rates TO bi_reader;
```

---

## Build Order (strict dependency chain)

```
Phase 3 (anomalies.py, forecast.py) — queries Phase 2 KPI views
  → Phase 4 (tool_layer.py) — imports Phase 3 analytics
    → Phase 5 (copilot.py) — imports Phase 4 tools
      → Phase 6 (streamlit_app.py) — imports Phase 5 agent
Phase 7 (alerts.py, nightly.yml) — imports Phase 3, Phase 1
Phase 8 (docs only)
```

## Smoke Tests Per Phase

- Phase 3: `python src/analytics/anomalies.py` → JSON anomaly list; `python src/analytics/forecast.py` → 3-month forecast
- Phase 4: `python src/tools/tool_layer.py` → all 6 tools called and printed
- Phase 5: `python src/agent/copilot.py` → interactive CLI
- Phase 6: `streamlit run src/app/streamlit_app.py`
- Phase 7: `python src/pipeline/alerts.py` → dry-run detection + alert dispatch
- Phase 8: manual Power BI / Tableau connection

## Environment Variables to Add to `.env.example`

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ALERT_EMAIL_FROM=your_alert_email@gmail.com
ALERT_EMAIL_TO=recipient@example.com
ALERT_EMAIL_PASSWORD=your_app_password_here
```
