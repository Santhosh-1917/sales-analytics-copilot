# src/pipeline/ingest.py
# Phase 1: Multi-source ingestion with validation
# Run: python src/pipeline/ingest.py

import os
import yaml
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ─── DB CONNECTION ─────────────────────────────────────────────────────────────

def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)

# ─── LOAD CONFIG ──────────────────────────────────────────────────────────────

def load_config(path="config/sources.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)

# ─── EXTRACT ──────────────────────────────────────────────────────────────────

def extract(source: dict) -> pd.DataFrame:
    """Read raw data from the configured source."""
    src_type = source["type"]
    print(f"  [extract] Reading from {src_type}: {source.get('path', source.get('name'))}")

    if src_type == "csv":
        df = pd.read_csv(source["path"], low_memory=False)
    elif src_type == "postgres":
        engine = get_engine()
        df = pd.read_sql(source["query"], engine)
    else:
        raise ValueError(f"Unsupported source type: {src_type}")

    print(f"  [extract] {len(df):,} rows read")
    return df

# ─── VALIDATE ─────────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame, source: dict) -> tuple[pd.DataFrame, list[dict]]:
    """
    Run validation checks. Returns (clean_df, rejected_rows).
    Rejected rows are logged with a reason — not silently dropped.
    """
    col_map = source.get("column_map", {})
    cfg = source.get("validation", {})
    required = cfg.get("required_columns", [])
    max_null_pct = cfg.get("max_null_pct", 0.05)
    max_dup_pct = cfg.get("max_duplicate_pct", 0.02)
    date_min = cfg.get("date_range", {}).get("min", "2000-01-01")
    date_max = cfg.get("date_range", {}).get("max", "2030-12-31")

    # Rename columns to standard names
    df = df.rename(columns=col_map)

    rejected = []
    clean_mask = pd.Series([True] * len(df), index=df.index)

    # 1. Required column check
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Required columns missing from source: {missing_cols}")

    # 2. Null check on required columns
    for col in required:
        null_mask = df[col].isna()
        null_pct = null_mask.mean()
        if null_pct > max_null_pct:
            print(f"  [validate] WARNING: '{col}' has {null_pct:.1%} nulls (threshold: {max_null_pct:.1%})")
        # Reject individual rows with nulls in required columns
        for idx in df[null_mask].index:
            rejected.append({
                "row_number": int(idx),
                "raw_data": str(df.loc[idx].to_dict()),
                "rejection_reason": f"null_in_required_column:{col}"
            })
        clean_mask &= ~null_mask

    # 3. Duplicate order_id check
    if "order_id" in df.columns:
        dup_mask = df.duplicated(subset=["order_id"], keep="first")
        dup_pct = dup_mask.mean()
        if dup_pct > max_dup_pct:
            print(f"  [validate] WARNING: {dup_pct:.1%} duplicate order IDs (threshold: {max_dup_pct:.1%})")
        for idx in df[dup_mask].index:
            rejected.append({
                "row_number": int(idx),
                "raw_data": str(df.loc[idx].to_dict()),
                "rejection_reason": "duplicate_order_id"
            })
        clean_mask &= ~dup_mask

    # 4. Date range check
    if "order_date" in df.columns:
        df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
        bad_date = (
            df["order_date"].isna() |
            (df["order_date"] < pd.Timestamp(date_min)) |
            (df["order_date"] > pd.Timestamp(date_max))
        )
        for idx in df[bad_date].index:
            rejected.append({
                "row_number": int(idx),
                "raw_data": str(df.loc[idx].to_dict()),
                "rejection_reason": f"date_out_of_range:{df.loc[idx, 'order_date']}"
            })
        clean_mask &= ~bad_date

    # 5. Revenue sanity check (no negative revenue)
    if "revenue" in df.columns:
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        neg_rev = df["revenue"] < 0
        for idx in df[neg_rev].index:
            rejected.append({
                "row_number": int(idx),
                "raw_data": str(df.loc[idx].to_dict()),
                "rejection_reason": f"negative_revenue:{df.loc[idx, 'revenue']}"
            })
        clean_mask &= ~neg_rev

    clean_df = df[clean_mask].copy()
    print(f"  [validate] {len(clean_df):,} rows clean | {len(rejected):,} rows rejected")
    return clean_df, rejected

# ─── TRANSFORM ────────────────────────────────────────────────────────────────

def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise types, compute derived columns, prep for star schema load."""
    # Dates
    for date_col in ["order_date", "ship_date"]:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date

    # Numerics
    for num_col in ["revenue", "profit", "quantity", "discount_pct"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

    # Margin
    if "revenue" in df.columns and "profit" in df.columns:
        df["margin_pct"] = np.where(
            df["revenue"] != 0,
            df["profit"] / df["revenue"],
            np.nan
        )

    # Strings
    for str_col in ["order_id", "product_id", "product_name", "category",
                    "sub_category", "region", "state", "city", "country",
                    "customer_id", "customer_name", "segment", "ship_mode"]:
        if str_col in df.columns:
            df[str_col] = df[str_col].astype(str).str.strip()

    return df

# ─── LOAD ─────────────────────────────────────────────────────────────────────

def load_dim_date(engine, dates: list):
    """Populate dim_date for all unique dates in the dataset."""
    rows = []
    for d in set(dates):
        if pd.isna(d):
            continue
        dt = pd.Timestamp(d)
        rows.append({
            "date_key": d,
            "year": dt.year,
            "quarter": dt.quarter,
            "month": dt.month,
            "month_name": dt.strftime("%B"),
            "week": dt.isocalendar().week,
            "day_of_week": dt.dayofweek,
            "is_weekend": dt.dayofweek >= 5
        })
    if rows:
        pd.DataFrame(rows).to_sql(
            "dim_date", engine, if_exists="append", index=False,
            method="multi",
        )
        # Deduplicate: PostgreSQL will raise on PK conflict; use ON CONFLICT DO NOTHING
        with engine.connect() as conn:
            conn.execute(text("""
                DELETE FROM dim_date a USING dim_date b
                WHERE a.ctid < b.ctid AND a.date_key = b.date_key
            """))
            conn.commit()

def upsert_dim(engine, df: pd.DataFrame, table: str, unique_col: str, cols: list) -> pd.Series:
    """Insert dimension rows, skip duplicates, return key mapping."""
    sub = df[cols].drop_duplicates(subset=[unique_col]).dropna(subset=[unique_col])
    with engine.connect() as conn:
        for _, row in sub.iterrows():
            conn.execute(text(f"""
                INSERT INTO {table} ({", ".join(cols)})
                VALUES ({", ".join([f":{c}" for c in cols])})
                ON CONFLICT ({unique_col}) DO NOTHING
            """), row.to_dict())
        conn.commit()

    key_col = table.replace("dim_", "") + "_key"
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT {unique_col}, {key_col} FROM {table}"))
        return pd.DataFrame(result.fetchall(), columns=[unique_col, key_col])

def load(df: pd.DataFrame, source_name: str, engine, run_id: int):
    """Load clean data into the star schema."""
    print(f"  [load] Loading {len(df):,} rows into star schema...")

    # dim_date
    all_dates = list(df["order_date"]) + list(df.get("ship_date", pd.Series()).dropna())
    load_dim_date(engine, all_dates)

    # dim_product
    product_map = upsert_dim(
        engine, df, "dim_product", "product_id",
        ["product_id", "product_name", "category", "sub_category"]
    )
    df = df.merge(product_map, on="product_id", how="left")

    # dim_region
    for col in ["region", "country", "state", "city"]:
        if col not in df.columns:
            df[col] = "Unknown"
    df["region_unique"] = df["region"] + "|" + df["country"] + "|" + df["state"] + "|" + df["city"]
    region_sub = df[["region", "country", "state", "city"]].drop_duplicates()
    with engine.connect() as conn:
        for _, row in region_sub.iterrows():
            conn.execute(text("""
                INSERT INTO dim_region (region, country, state, city)
                VALUES (:region, :country, :state, :city)
                ON CONFLICT (region, country, state, city) DO NOTHING
            """), row.to_dict())
        conn.commit()
        result = conn.execute(text("SELECT region, country, state, city, region_key FROM dim_region"))
        region_map = pd.DataFrame(result.fetchall(), columns=["region", "country", "state", "city", "region_key"])
    df = df.merge(region_map, on=["region", "country", "state", "city"], how="left")

    # dim_customer
    if "customer_id" in df.columns:
        customer_map = upsert_dim(
            engine, df, "dim_customer", "customer_id",
            ["customer_id", "customer_name", "segment"]
        )
        df = df.merge(customer_map, on="customer_id", how="left")
    else:
        df["customer_key"] = None

    # fact_sales
    fact_cols = [
        "order_id", "order_date", "ship_date", "ship_mode",
        "product_key", "region_key", "customer_key",
        "revenue", "quantity", "discount_pct", "profit", "margin_pct"
    ]
    fact_df = df[[c for c in fact_cols if c in df.columns]].copy()
    fact_df["source_name"] = source_name
    fact_df["loaded_at"] = datetime.now()

    fact_df.to_sql(
        "fact_sales", engine, if_exists="append",
        index=False, method="multi", chunksize=1000
    )
    print(f"  [load] Done — {len(fact_df):,} rows loaded into fact_sales")

# ─── RUN LOG ──────────────────────────────────────────────────────────────────

def start_run(engine, source_name: str) -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO run_log (source_name, started_at, status)
            VALUES (:source_name, NOW(), 'running')
            RETURNING run_id
        """), {"source_name": source_name})
        run_id = result.fetchone()[0]
        conn.commit()
    return run_id

def finish_run(engine, run_id: int, rows_read: int, rows_loaded: int,
               rows_rejected: int, status: str, notes: str = ""):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE run_log SET
                finished_at = NOW(),
                status = :status,
                rows_read = :rows_read,
                rows_loaded = :rows_loaded,
                rows_rejected = :rows_rejected,
                notes = :notes
            WHERE run_id = :run_id
        """), {
            "run_id": run_id, "status": status, "rows_read": rows_read,
            "rows_loaded": rows_loaded, "rows_rejected": rows_rejected, "notes": notes
        })
        conn.commit()

def log_errors(engine, run_id: int, source_name: str, rejected: list):
    if not rejected:
        return
    rows = [{"run_id": run_id, "source_name": source_name, **r} for r in rejected]
    pd.DataFrame(rows).to_sql("error_log", engine, if_exists="append", index=False)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run_pipeline():
    config = load_config()
    engine = get_engine()

    for source in config["sources"]:
        if not source.get("enabled", True):
            print(f"Skipping {source['name']} (disabled)")
            continue

        print(f"\n{'='*50}")
        print(f"Processing: {source['name']}")
        print(f"{'='*50}")

        run_id = start_run(engine, source["name"])
        rows_read = 0

        try:
            raw_df = extract(source)
            rows_read = len(raw_df)

            clean_df, rejected = validate(raw_df, source)
            clean_df = transform(clean_df)

            load(clean_df, source["name"], engine, run_id)

            log_errors(engine, run_id, source["name"], rejected)
            finish_run(engine, run_id, rows_read, len(clean_df), len(rejected), "success")

            print(f"\n✓ {source['name']} complete: {len(clean_df):,} loaded, {len(rejected):,} rejected")

        except Exception as e:
            finish_run(engine, run_id, rows_read, 0, 0, "failed", notes=str(e))
            print(f"\n✗ {source['name']} failed: {e}")
            raise

if __name__ == "__main__":
    run_pipeline()
