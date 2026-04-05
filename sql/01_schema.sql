-- sql/01_schema.sql
-- Run this once to create the full star schema.
-- psql -U postgres -d sales_copilot -f sql/01_schema.sql

-- ─── CREATE DATABASE (run separately if needed) ───────────────────────────────
-- CREATE DATABASE sales_copilot;

-- ─── DIMENSION TABLES ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_date (
    date_key        DATE PRIMARY KEY,
    year            INT NOT NULL,
    quarter         INT NOT NULL,   -- 1–4
    month           INT NOT NULL,   -- 1–12
    month_name      VARCHAR(10),
    week            INT NOT NULL,   -- ISO week number
    day_of_week     INT NOT NULL,   -- 0=Mon, 6=Sun
    is_weekend      BOOLEAN
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_key     SERIAL PRIMARY KEY,
    product_id      VARCHAR(50) UNIQUE NOT NULL,
    product_name    VARCHAR(255),
    category        VARCHAR(100),
    sub_category    VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS dim_region (
    region_key      SERIAL PRIMARY KEY,
    region          VARCHAR(100),
    country         VARCHAR(100),
    state           VARCHAR(100),
    city            VARCHAR(100),
    UNIQUE (region, country, state, city)
);

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_key    SERIAL PRIMARY KEY,
    customer_id     VARCHAR(50) UNIQUE NOT NULL,
    customer_name   VARCHAR(255),
    segment         VARCHAR(100)
);

-- ─── FACT TABLE ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id         SERIAL PRIMARY KEY,
    order_id        VARCHAR(50) NOT NULL,
    order_date      DATE NOT NULL REFERENCES dim_date(date_key),
    ship_date       DATE REFERENCES dim_date(date_key),
    ship_mode       VARCHAR(100),
    product_key     INT REFERENCES dim_product(product_key),
    region_key      INT REFERENCES dim_region(region_key),
    customer_key    INT REFERENCES dim_customer(customer_key),
    revenue         NUMERIC(12, 2) NOT NULL,
    quantity        INT,
    discount_pct    NUMERIC(5, 4),   -- e.g. 0.2000 = 20%
    profit          NUMERIC(12, 2),
    margin_pct      NUMERIC(7, 4),   -- computed: profit / revenue
    source_name     VARCHAR(100),    -- which source file this came from
    loaded_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_order_date ON fact_sales(order_date);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product_key ON fact_sales(product_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_region_key ON fact_sales(region_key);

-- ─── PIPELINE TRACKING TABLES ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS run_log (
    run_id          SERIAL PRIMARY KEY,
    source_name     VARCHAR(100),
    started_at      TIMESTAMP DEFAULT NOW(),
    finished_at     TIMESTAMP,
    status          VARCHAR(20),     -- success | failed | partial
    rows_read       INT,
    rows_loaded     INT,
    rows_rejected   INT,
    anomalies_found INT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS error_log (
    error_id        SERIAL PRIMARY KEY,
    run_id          INT REFERENCES run_log(run_id),
    source_name     VARCHAR(100),
    row_number      INT,
    raw_data        TEXT,
    rejection_reason VARCHAR(255),
    logged_at       TIMESTAMP DEFAULT NOW()
);

-- ─── KPI VIEWS ────────────────────────────────────────────────────────────────
-- These are what the tool layer reads. Modify thresholds here, not in Python.

-- Monthly KPIs across all dimensions
CREATE OR REPLACE VIEW v_monthly_kpis AS
SELECT
    d.year,
    d.month,
    d.month_name,
    TO_CHAR(f.order_date, 'YYYY-MM') AS period,
    COUNT(DISTINCT f.order_id)        AS order_count,
    SUM(f.revenue)                    AS total_revenue,
    SUM(f.profit)                     AS total_profit,
    ROUND(SUM(f.profit) / NULLIF(SUM(f.revenue), 0) * 100, 2) AS margin_pct,
    ROUND(AVG(f.discount_pct) * 100, 2) AS avg_discount_pct,
    SUM(f.quantity)                   AS total_units
FROM fact_sales f
JOIN dim_date d ON f.order_date = d.date_key
GROUP BY d.year, d.month, d.month_name, TO_CHAR(f.order_date, 'YYYY-MM')
ORDER BY period;

-- KPIs by category and period
CREATE OR REPLACE VIEW v_category_performance AS
SELECT
    TO_CHAR(f.order_date, 'YYYY-MM') AS period,
    p.category,
    p.sub_category,
    COUNT(DISTINCT f.order_id)        AS order_count,
    SUM(f.revenue)                    AS total_revenue,
    SUM(f.profit)                     AS total_profit,
    ROUND(SUM(f.profit) / NULLIF(SUM(f.revenue), 0) * 100, 2) AS margin_pct,
    ROUND(AVG(f.discount_pct) * 100, 2) AS avg_discount_pct
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY TO_CHAR(f.order_date, 'YYYY-MM'), p.category, p.sub_category
ORDER BY period, category;

-- KPIs by region and period
CREATE OR REPLACE VIEW v_regional_performance AS
SELECT
    TO_CHAR(f.order_date, 'YYYY-MM') AS period,
    r.region,
    r.state,
    SUM(f.revenue)                    AS total_revenue,
    SUM(f.profit)                     AS total_profit,
    ROUND(SUM(f.profit) / NULLIF(SUM(f.revenue), 0) * 100, 2) AS margin_pct,
    ROUND(AVG(f.discount_pct) * 100, 2) AS avg_discount_pct,
    RANK() OVER (
        PARTITION BY TO_CHAR(f.order_date, 'YYYY-MM')
        ORDER BY SUM(f.profit) DESC
    ) AS profit_rank
FROM fact_sales f
JOIN dim_region r ON f.region_key = r.region_key
GROUP BY TO_CHAR(f.order_date, 'YYYY-MM'), r.region, r.state
ORDER BY period, profit_rank;

-- Discount impact: how discount bands affect margin
CREATE OR REPLACE VIEW v_discount_impact AS
SELECT
    p.category,
    CASE
        WHEN f.discount_pct = 0             THEN '0% (no discount)'
        WHEN f.discount_pct <= 0.10         THEN '1–10%'
        WHEN f.discount_pct <= 0.20         THEN '11–20%'
        WHEN f.discount_pct <= 0.30         THEN '21–30%'
        WHEN f.discount_pct <= 0.50         THEN '31–50%'
        ELSE '50%+'
    END AS discount_band,
    COUNT(*)                                AS order_count,
    SUM(f.revenue)                          AS total_revenue,
    SUM(f.profit)                           AS total_profit,
    ROUND(SUM(f.profit) / NULLIF(SUM(f.revenue), 0) * 100, 2) AS margin_pct
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY p.category, discount_band
ORDER BY category, discount_band;

-- MoM growth rates
CREATE OR REPLACE VIEW v_growth_rates AS
WITH monthly AS (
    SELECT
        TO_CHAR(order_date, 'YYYY-MM') AS period,
        SUM(revenue)                    AS revenue,
        SUM(profit)                     AS profit
    FROM fact_sales
    GROUP BY TO_CHAR(order_date, 'YYYY-MM')
)
SELECT
    period,
    revenue,
    profit,
    ROUND((revenue - LAG(revenue) OVER (ORDER BY period))
        / NULLIF(LAG(revenue) OVER (ORDER BY period), 0) * 100, 2) AS revenue_mom_pct,
    ROUND((profit - LAG(profit) OVER (ORDER BY period))
        / NULLIF(LAG(profit) OVER (ORDER BY period), 0) * 100, 2)  AS profit_mom_pct
FROM monthly
ORDER BY period;

-- ─── DONE ─────────────────────────────────────────────────────────────────────
-- Run next: python src/pipeline/ingest.py
