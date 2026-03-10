#!/usr/bin/env python3
"""Add new columns to existing beta/bot tables for Beta Overlay System."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from api.models.base import engine, Base
from api.models.beta_factor import BetaDailyTrack, BetaModelState

# Create new tables
Base.metadata.create_all(engine, tables=[BetaDailyTrack.__table__, BetaModelState.__table__])
print("Created new tables: beta_daily_tracks, beta_model_state")

# ALTER TABLE for new columns on existing tables
ALTER_STATEMENTS = [
    # beta_snapshots new columns
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS strategy_family VARCHAR(50)",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS final_score FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS entry_price FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS day_of_week INTEGER",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS stock_return_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS stock_volatility_20d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS volume_ratio_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS index_return_5d FLOAT",
    "ALTER TABLE beta_snapshots ADD COLUMN IF NOT EXISTS index_return_20d FLOAT",
    # beta_reviews new columns
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS max_unrealized_gain FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS max_unrealized_loss FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS regime_changed BOOLEAN",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS volume_trend_slope FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS price_path_volatility FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS sector_heat_delta FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS news_events_during_hold INTEGER DEFAULT 0",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS index_return_during_hold FLOAT",
    "ALTER TABLE beta_reviews ADD COLUMN IF NOT EXISTS is_profitable BOOLEAN",
    # bot_trade_plans new columns
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS alpha_score FLOAT",
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS beta_score FLOAT",
    "ALTER TABLE bot_trade_plans ADD COLUMN IF NOT EXISTS combined_score FLOAT",
]

with engine.connect() as conn:
    for stmt in ALTER_STATEMENTS:
        try:
            conn.execute(text(stmt))
            col_name = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0]
            print(f"  OK: {col_name}")
        except Exception as e:
            print(f"  SKIP: {e}")
    conn.commit()

print("Migration complete.")
