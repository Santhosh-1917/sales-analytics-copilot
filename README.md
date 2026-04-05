# Automated Sales Analytics Copilot

> An agentic analytics system that ingests sales data, detects anomalies, answers business questions in plain English, models what-if scenarios, and sends automated alerts — powered by Claude.

---

## Demo
*(Add your Streamlit demo GIF here once built)*

---

## Architecture

```
Data Sources (CSV / API / DB)
        ↓
Ingestion & Validation (Phase 1)
        ↓
PostgreSQL Star Schema + KPI Views (Phase 2)
        ↓
Anomaly Detection + Forecasting (Phase 3)
        ↓
Structured Tool Layer — 6 tools (Phase 4)
        ↓
Agentic Claude Reasoning Loop (Phase 5)
   ↙        ↓        ↘
Streamlit  PDF     Power BI
Chat UI   Report  Dashboard
        ↓
GitHub Actions — nightly automation + Slack/email alerts
```

---

## Tech Stack

| Layer | Tools |
|---|---|
| Language | Python 3.11+, SQL |
| Database | PostgreSQL (star schema + KPI views) |
| ETL | Pandas, SQLAlchemy, PyYAML |
| Analytics | Pandas, SciPy (anomaly detection) |
| Forecasting | Prophet, statsmodels (ARIMA) |
| AI Layer | Claude API (tool use / function calling) |
| UI | Streamlit |
| Dashboard | Power BI DirectQuery / Tableau Live |
| Alerting | Slack Webhooks, SMTP |
| Automation | GitHub Actions |

---

## Setup

### 1. Clone and install
```bash
git clone https://github.com/Santhosh-1917/sales-analytics-copilot
cd sales-analytics-copilot
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials and Anthropic API key
```

### 3. Create the database
```bash
createdb sales_copilot
psql -U postgres -d sales_copilot -f sql/01_schema.sql
```

### 4. Add your data
Place your sales CSV in `data/raw/`. Update `config/sources.yaml` if your column names differ.

### 5. Run the pipeline
```bash
python src/pipeline/ingest.py
```

---

## Project Structure

```
sales-analytics-copilot/
├── config/
│   └── sources.yaml          # Data source configuration
├── data/
│   └── raw/                  # Place your CSV files here
├── sql/
│   └── 01_schema.sql         # Star schema + KPI views
├── src/
│   ├── pipeline/
│   │   └── ingest.py         # Phase 1: ETL + validation
│   ├── analytics/
│   │   ├── anomalies.py      # Phase 3: Anomaly detection
│   │   └── forecast.py       # Phase 3: ARIMA + Prophet
│   ├── tools/
│   │   └── tool_layer.py     # Phase 4: 6 structured tools
│   ├── agent/
│   │   └── copilot.py        # Phase 5: Agentic Claude layer
│   └── app/
│       └── streamlit_app.py  # Phase 6: Chat UI
├── .github/
│   └── workflows/
│       └── nightly.yml       # Phase 7: GitHub Actions
├── .env.example
├── requirements.txt
└── README.md
```

---

## Build Status

- [x] Phase 1: Ingestion & Validation
- [ ] Phase 2: KPI Views (run sql/01_schema.sql)
- [ ] Phase 3: Anomaly Detection + Forecasting
- [ ] Phase 4: Tool Layer
- [ ] Phase 5: Agentic Claude Layer
- [ ] Phase 6: Streamlit Chat UI
- [ ] Phase 7: GitHub Actions + Alerting
- [ ] Phase 8: Dashboard Integration

---

*Santhosh Narayanan Baburaman | USC MS Analytics | [LinkedIn](https://linkedin.com/in/santhosh-narayanan-7b9466249)*
