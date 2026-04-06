# Dashboard Integration Guide

Connect Power BI or Tableau directly to the PostgreSQL KPI views for live dashboards.

---

## 1. Create a Read-Only BI User

Run this once in your PostgreSQL database before connecting any BI tool:

```sql
CREATE USER bi_reader WITH PASSWORD 'choose_a_strong_password';
GRANT CONNECT ON DATABASE sales_copilot TO bi_reader;
GRANT USAGE ON SCHEMA public TO bi_reader;
GRANT SELECT ON
    v_monthly_kpis,
    v_category_performance,
    v_regional_performance,
    v_discount_impact,
    v_growth_rates
TO bi_reader;
```

Use `bi_reader` credentials in your BI tool — never the admin user.

---

## 2. Power BI (DirectQuery)

**Requirements:** Power BI Desktop (free) or Power BI Service with a gateway.

### Steps

1. Open **Power BI Desktop**
2. Click **Get Data → Database → PostgreSQL database**
3. Enter connection details:
   - Server: `localhost` (or your host IP)
   - Database: `sales_copilot`
4. Click **OK** → enter credentials: `bi_reader` / your chosen password
5. In the Navigator, select these views:
   - `v_monthly_kpis`
   - `v_category_performance`
   - `v_regional_performance`
   - `v_discount_impact`
   - `v_growth_rates`
6. Choose **DirectQuery** mode (not Import) — this ensures charts always show live data
7. Click **Load**

### Recommended Visuals

| Visual | X-axis | Y-axis / Value | Notes |
|--------|--------|----------------|-------|
| Line chart | `v_monthly_kpis.period` | `total_revenue`, `total_profit` | Add a second Y-axis for margin_pct |
| Clustered bar | `v_category_performance.category` | `margin_pct` | Color by sub_category |
| Filled map | `v_regional_performance.state` | `total_revenue` | Requires state names (already in view) |
| Table | `v_discount_impact` | All columns | Shows discount band impact on margin |

### Power BI Gateway (for cloud deployment)

If your PostgreSQL runs on a private network and you want to publish to Power BI Service, you need an **On-premises data gateway**. Download from: [powerbi.microsoft.com/gateway](https://powerbi.microsoft.com/en-us/gateway/)

---

## 3. Tableau (Live Connection)

**Requirements:** Tableau Desktop or Tableau Public.

### Steps

1. Open **Tableau Desktop**
2. Under **Connect → To a Server**, click **PostgreSQL**
3. Enter connection details:
   - Server: `localhost`
   - Port: `5432`
   - Database: `sales_copilot`
   - Username: `bi_reader`
   - Password: your chosen password
4. Click **Sign In**
5. Under **Schema**, select `public`
6. Drag any of the 5 KPI views onto the canvas
7. Set the connection type to **Live** (top-left toggle) — not Extract

### Recommended Sheets

| Sheet | View | Chart Type |
|-------|------|------------|
| Revenue Trend | `v_monthly_kpis` | Line chart — period vs total_revenue |
| Category Margins | `v_category_performance` | Bar chart — category vs margin_pct |
| Regional Performance | `v_regional_performance` | Filled map — state coloured by margin_pct |
| Discount Impact | `v_discount_impact` | Bar chart — discount_band vs margin_pct |
| Growth Rates | `v_growth_rates` | Dual-axis line — revenue_mom_pct + profit_mom_pct |

---

## 4. Available KPI Views

| View | Key Columns | Use For |
|------|-------------|---------|
| `v_monthly_kpis` | period, total_revenue, total_profit, margin_pct, avg_discount_pct | Time-series trends |
| `v_category_performance` | period, category, sub_category, total_revenue, margin_pct | Product breakdown |
| `v_regional_performance` | period, region, state, total_revenue, margin_pct, profit_rank | Geographic analysis |
| `v_discount_impact` | category, discount_band, margin_pct | Discount strategy analysis |
| `v_growth_rates` | period, revenue_mom_pct, profit_mom_pct | MoM growth tracking |

> **Note:** `avg_discount_pct` in all views is already in percentage form (e.g. `25.0` = 25%). Do not multiply by 100 in calculated fields.
