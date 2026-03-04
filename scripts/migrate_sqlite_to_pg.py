#!/usr/bin/env python3
"""SQLite → PostgreSQL data migration script.

Usage:
    python scripts/migrate_sqlite_to_pg.py

Migrates all 42 tables (~14.8M rows, 2.2GB) from SQLite to PostgreSQL.
Uses COPY FROM with CSV intermediary for large tables (fastest method).
"""
import csv
import io
import os
import sqlite3
import sys
import time

import psycopg2
import psycopg2.extras

# ── Config ────────────────────────────────────────────
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stockagent.db")
PG_DSN = "postgresql://allenqiang@localhost:5432/stockagent"

# Tables with >100K rows — use COPY for speed
LARGE_TABLE_THRESHOLD = 50_000

# ORM tables — created by SQLAlchemy Base.metadata.create_all()
ORM_TABLES = {
    "ai_reports", "ai_chat_sessions", "strategy_templates", "experiments",
    "experiment_strategies", "exploration_rounds", "backtest_runs_v2",
    "backtest_trades_v2", "bot_portfolio", "bot_trades", "bot_trade_reviews",
    "bot_trade_plans", "market_regimes", "news_events", "sector_heat",
    "news_signals", "agent_run_log", "news_sentiment_results",
    "stock_news_sentiment", "trading_signals_v2", "action_signals_v2",
    "stocks", "daily_prices", "stock_concepts", "board_sync_log",
    "daily_basic", "trading_calendar", "index_daily", "watchlist",
    "portfolio", "strategies",
}

# Migration order: parent tables before children (FK dependencies)
MIGRATION_ORDER = [
    # Independent / parent tables first
    "stocks", "trading_calendar", "strategy_templates",
    # Stock data
    "daily_prices", "daily_basic", "index_daily", "stock_concepts",
    "board_sync_log", "watchlist", "portfolio",
    # Strategies
    "strategies",
    # Experiments (parent before child)
    "experiments", "experiment_strategies", "exploration_rounds",
    # Backtests
    "backtest_runs_v2", "backtest_trades_v2",
    # Signals
    "trading_signals_v2", "action_signals_v2",
    # AI
    "ai_reports", "ai_chat_sessions",
    # News
    "news_events", "sector_heat", "news_signals", "agent_run_log",
    "news_sentiment_results", "stock_news_sentiment",
    # Market
    "market_regimes",
    # Bot
    "bot_portfolio", "bot_trades", "bot_trade_reviews", "bot_trade_plans",
    # ── Legacy tables (not in ORM) ──
    "stock_list", "stock_daily", "data_update_log",
    "news_archive", "news_sentiment",
    "indicator_config", "signal_strategy",
    "trading_signals", "action_signals",
    "backtest_runs", "backtest_trades",
]


def get_sqlite_tables(sqlite_conn):
    """Get all non-system tables from SQLite."""
    cur = sqlite_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")
    return [row[0] for row in cur.fetchall()]


def get_sqlite_schema(sqlite_conn, table_name):
    """Get column info for a table."""
    cur = sqlite_conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return cur.fetchall()  # (cid, name, type, notnull, dflt_value, pk)


def sqlite_type_to_pg(sqlite_type, col_name, is_pk):
    """Map SQLite type to PostgreSQL type."""
    t = sqlite_type.upper()
    if is_pk and "INT" in t:
        return "SERIAL"
    if "INT" in t:
        return "INTEGER"
    if "FLOAT" in t or "REAL" in t or "DOUBLE" in t or "NUMERIC" in t:
        return "DOUBLE PRECISION"
    if "BOOL" in t:
        return "BOOLEAN"
    if "DATE" in t and "TIME" not in t:
        return "DATE"
    if "DATETIME" in t or "TIMESTAMP" in t:
        return "TIMESTAMP"
    if "TEXT" in t or "CLOB" in t:
        return "TEXT"
    if "JSON" in t:
        return "JSONB"
    if "VARCHAR" in t:
        return t.replace("VARCHAR", "VARCHAR")  # keep length
    if "CHAR" in t:
        return t
    if "BLOB" in t:
        return "BYTEA"
    return "TEXT"


def create_legacy_table(pg_conn, sqlite_conn, table_name):
    """Create a legacy table in PG based on SQLite schema."""
    schema = get_sqlite_schema(sqlite_conn, table_name)
    if not schema:
        print(f"  SKIP {table_name}: no schema")
        return False

    cols = []
    pk_cols = []
    for cid, name, col_type, notnull, dflt, pk in schema:
        # pk > 0 means part of composite PK; only use SERIAL for single-column PK
        num_pk_cols = sum(1 for c in schema if c[5] > 0)
        is_single_pk = pk > 0 and num_pk_cols == 1
        pg_type = sqlite_type_to_pg(col_type, name, is_single_pk)
        parts = [f'"{name}"', pg_type]
        if notnull and pk == 0:
            parts.append("NOT NULL")
        if pk > 0:
            pk_cols.append(f'"{name}"')
            if not is_single_pk:
                parts.append("NOT NULL")
        cols.append(" ".join(parts))

    if pk_cols:
        cols.append(f"PRIMARY KEY ({', '.join(pk_cols)})")

    ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n  ' + ",\n  ".join(cols) + "\n)"
    cur = pg_conn.cursor()
    cur.execute(ddl)
    pg_conn.commit()
    return True


def create_orm_tables():
    """Create all ORM tables using SQLAlchemy metadata."""
    # Temporarily point config to PG
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from api.models.base import engine, Base
    # Import all models to register them
    import api.models.stock
    import api.models.signal
    import api.models.strategy
    import api.models.ai_lab
    import api.models.backtest
    import api.models.ai_analyst
    import api.models.news_agent
    import api.models.news_sentiment
    import api.models.market_regime
    import api.models.bot_trading
    Base.metadata.create_all(engine)
    print(f"  Created {len(Base.metadata.tables)} ORM tables via SQLAlchemy")


def migrate_table_copy(sqlite_conn, pg_conn, table_name, columns):
    """Migrate a table using PostgreSQL COPY FROM (fastest for large tables)."""
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    col_names = [c[1] for c in columns]
    col_list = ", ".join(f'"{c}"' for c in col_names)

    # Check if the table has SERIAL column — if so, we need to include id in COPY
    # and reset the sequence after
    has_serial = any(c[5] == 1 and "INT" in c[2].upper() for c in columns)

    # Detect boolean columns in PG for int→bool casting
    bool_cols = get_pg_bool_columns(pg_conn, table_name)
    bool_indices = {i for i, name in enumerate(col_names) if name in bool_cols}

    # Read from SQLite into CSV buffer
    sqlite_cur.execute(f'SELECT {col_list} FROM "{table_name}"')

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    row_count = 0
    for row in sqlite_cur:
        clean_row = []
        for i, val in enumerate(row):
            if val is None:
                clean_row.append("")
            elif i in bool_indices:
                # SQLite stores booleans as 0/1 integers
                clean_row.append("t" if val else "f")
            elif isinstance(val, bool):
                clean_row.append("t" if val else "f")
            else:
                s = str(val)
                if "\x00" in s:
                    s = s.replace("\x00", "")
                clean_row.append(s)
        writer.writerow(clean_row)
        row_count += 1

    if row_count == 0:
        return 0

    buf.seek(0)

    # COPY into PG
    copy_sql = f"""COPY "{table_name}" ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '')"""
    pg_cur.copy_expert(copy_sql, buf)
    pg_conn.commit()

    return row_count


def get_pg_bool_columns(pg_conn, table_name):
    """Get set of column names that are BOOLEAN in PG."""
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND data_type = 'boolean'
    """, (table_name,))
    return {row[0] for row in cur.fetchall()}


def cast_row_for_pg(row, col_names, bool_cols):
    """Cast SQLite row values for PG compatibility (int→bool, strip NUL bytes)."""
    result = list(row)
    for i, (val, name) in enumerate(zip(result, col_names)):
        if name in bool_cols and val is not None:
            result[i] = bool(val)
        elif isinstance(val, str) and "\x00" in val:
            result[i] = val.replace("\x00", "")
    return tuple(result)


def migrate_table_insert(sqlite_conn, pg_conn, table_name, columns):
    """Migrate a table using batch INSERT (for small tables)."""
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    col_names = [c[1] for c in columns]
    col_list = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(["%s"] * len(col_names))

    # Detect boolean columns in PG for casting
    bool_cols = get_pg_bool_columns(pg_conn, table_name)

    sqlite_cur.execute(f'SELECT {col_list} FROM "{table_name}"')
    rows = sqlite_cur.fetchall()

    if not rows:
        return 0

    # Cast rows: int→bool, strip NUL bytes from strings
    rows = [cast_row_for_pg(r, col_names, bool_cols) for r in rows]

    insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'

    # Batch insert
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        psycopg2.extras.execute_batch(pg_cur, insert_sql, batch, page_size=batch_size)

    pg_conn.commit()
    return len(rows)


def reset_sequences(pg_conn):
    """Reset all SERIAL sequences to max(id) + 1."""
    cur = pg_conn.cursor()
    # Find all sequences in public schema
    cur.execute("""
        SELECT t.relname AS table_name, a.attname AS column_name,
               s.relname AS seq_name
        FROM pg_class s
        JOIN pg_depend d ON d.objid = s.oid
        JOIN pg_class t ON d.refobjid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE s.relkind = 'S'
          AND n.nspname = 'public'
    """)
    sequences = cur.fetchall()

    for table_name, col_name, seq_name in sequences:
        try:
            cur.execute(f'SELECT COALESCE(MAX("{col_name}"), 0) FROM "{table_name}"')
            max_val = cur.fetchone()[0]
            if max_val and max_val > 0:
                cur.execute(f"SELECT setval('{seq_name}', {max_val})")
                print(f"  {seq_name} → {max_val}")
        except Exception as e:
            print(f"  WARN: {seq_name}: {e}")
            pg_conn.rollback()

    pg_conn.commit()


def verify_migration(sqlite_conn, pg_conn, tables):
    """Verify row counts match between SQLite and PG."""
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    mismatches = []
    for table in tables:
        try:
            sqlite_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            sqlite_count = sqlite_cur.fetchone()[0]
        except Exception:
            sqlite_count = -1

        try:
            pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            pg_count = pg_cur.fetchone()[0]
        except Exception:
            pg_count = -1

        status = "OK" if sqlite_count == pg_count else "MISMATCH"
        if status == "MISMATCH":
            mismatches.append((table, sqlite_count, pg_count))
        if sqlite_count > 0 or pg_count > 0:
            print(f"  {table}: SQLite={sqlite_count:,} PG={pg_count:,} [{status}]")

    return mismatches


def main():
    print("=" * 60)
    print("SQLite → PostgreSQL Migration")
    print("=" * 60)

    # Connect to SQLite
    sqlite_path = os.path.abspath(SQLITE_PATH)
    print(f"\nSQLite: {sqlite_path}")
    print(f"PostgreSQL: {PG_DSN}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    pg_conn = psycopg2.connect(PG_DSN)

    all_sqlite_tables = get_sqlite_tables(sqlite_conn)
    print(f"\nSQLite tables: {len(all_sqlite_tables)}")

    # Step 1: Create ORM tables via SQLAlchemy
    print("\n── Step 1: Create ORM tables ──")
    create_orm_tables()

    # Step 2: Create legacy tables
    print("\n── Step 2: Create legacy tables ──")
    legacy_tables = [t for t in all_sqlite_tables if t not in ORM_TABLES]
    for table in legacy_tables:
        ok = create_legacy_table(pg_conn, sqlite_conn, table)
        if ok:
            print(f"  Created legacy table: {table}")

    # Step 3: Migrate data
    print("\n── Step 3: Migrate data ──")
    total_rows = 0
    total_time = 0

    # Build migration order (tables in MIGRATION_ORDER first, then any remaining)
    ordered_tables = []
    for t in MIGRATION_ORDER:
        if t in all_sqlite_tables:
            ordered_tables.append(t)
    # Add any tables not in explicit order
    for t in all_sqlite_tables:
        if t not in ordered_tables:
            ordered_tables.append(t)

    for table in ordered_tables:
        columns = get_sqlite_schema(sqlite_conn, table)
        if not columns:
            continue

        # Check if PG table exists
        pg_cur = pg_conn.cursor()
        pg_cur.execute(f"SELECT COUNT(*) FROM \"{table}\"")
        existing_count = pg_cur.fetchone()[0]
        if existing_count > 0:
            print(f"  SKIP {table}: already has {existing_count:,} rows")
            continue

        # Count rows
        sqlite_cur = sqlite_conn.cursor()
        sqlite_cur.execute(f"SELECT COUNT(*) FROM \"{table}\"")
        row_count = sqlite_cur.fetchone()[0]

        if row_count == 0:
            print(f"  SKIP {table}: empty")
            continue

        t0 = time.time()
        if row_count >= LARGE_TABLE_THRESHOLD:
            print(f"  COPY {table} ({row_count:,} rows)...", end="", flush=True)
            migrated = migrate_table_copy(sqlite_conn, pg_conn, table, columns)
        else:
            print(f"  INSERT {table} ({row_count:,} rows)...", end="", flush=True)
            migrated = migrate_table_insert(sqlite_conn, pg_conn, table, columns)

        elapsed = time.time() - t0
        total_rows += migrated
        total_time += elapsed
        rate = migrated / elapsed if elapsed > 0 else 0
        print(f" done ({elapsed:.1f}s, {rate:,.0f} rows/s)")

    # Step 4: Reset sequences
    print("\n── Step 4: Reset sequences ──")
    reset_sequences(pg_conn)

    # Step 5: Verify
    print("\n── Step 5: Verify row counts ──")
    mismatches = verify_migration(sqlite_conn, pg_conn, ordered_tables)

    # Summary
    print("\n" + "=" * 60)
    print(f"Migration complete: {total_rows:,} rows in {total_time:.1f}s")
    if mismatches:
        print(f"WARNING: {len(mismatches)} table(s) have row count mismatches!")
        for table, sc, pc in mismatches:
            print(f"  {table}: SQLite={sc:,} PG={pc:,}")
    else:
        print("All tables verified: row counts match!")
    print("=" * 60)

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
