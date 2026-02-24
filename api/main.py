"""FastAPI application entry point.

Run with: uvicorn api.main:app --reload --port 8050
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on sys.path (for src.* imports)
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from api.models.base import Base, engine
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst, news_signals, bot_trading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _seed_strategies():
    """Insert built-in strategies (Swing + Trend) if they don't exist yet."""
    from sqlalchemy.orm import Session
    from api.models.strategy import Strategy

    SEEDS = [
        {
            "name": "波段策略",
            "description": "基于RSI/KDJ超买超卖的波段交易策略，适合震荡市",
            "rules": [
                {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": 30, "score": 25, "label": "RSI超卖", "params": {"period": 14}},
                {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 70, "score": -25, "label": "RSI超买", "params": {"period": 14}},
                {"field": "KDJ_K", "operator": ">", "compare_type": "field", "compare_field": "KDJ_D", "score": 20, "label": "KDJ金叉", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "compare_params": {"fastk": 9, "slowk": 3, "slowd": 3}},
                {"field": "KDJ_K", "operator": "<", "compare_type": "field", "compare_field": "KDJ_D", "score": -20, "label": "KDJ死叉", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "compare_params": {"fastk": 9, "slowk": 3, "slowd": 3}},
                {"field": "MACD_hist", "operator": ">", "compare_type": "value", "compare_value": 0, "score": 15, "label": "MACD柱为正", "params": {"fast": 12, "slow": 26, "signal": 9}},
                {"field": "MACD_hist", "operator": "<", "compare_type": "value", "compare_value": 0, "score": -15, "label": "MACD柱为负", "params": {"fast": 12, "slow": 26, "signal": 9}},
            ],
            "buy_conditions": [
                {"field": "RSI", "operator": "<", "compare_type": "value", "compare_value": 30, "label": "RSI < 30", "params": {"period": 14}},
                {"field": "KDJ_K", "operator": ">", "compare_type": "field", "compare_field": "KDJ_D", "label": "KDJ_K > KDJ_D", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "compare_params": {"fastk": 9, "slowk": 3, "slowd": 3}},
            ],
            "sell_conditions": [
                {"field": "RSI", "operator": ">", "compare_type": "value", "compare_value": 70, "label": "RSI > 70", "params": {"period": 14}},
                {"field": "KDJ_K", "operator": "<", "compare_type": "field", "compare_field": "KDJ_D", "label": "KDJ_K < KDJ_D", "params": {"fastk": 9, "slowk": 3, "slowd": 3}, "compare_params": {"fastk": 9, "slowk": 3, "slowd": 3}},
            ],
            "exit_config": {"stop_loss_pct": -8, "take_profit_pct": 20, "max_hold_days": 10},
            "weight": 0.5,
        },
        {
            "name": "趋势策略",
            "description": "基于均线和ADX趋势跟踪策略，适合单边市",
            "rules": [
                {"field": "MA", "operator": ">", "compare_type": "field", "compare_field": "MA", "score": 20, "label": "MA5上穿MA20", "params": {"period": 5}, "compare_params": {"period": 20}},
                {"field": "MA", "operator": "<", "compare_type": "field", "compare_field": "MA", "score": -20, "label": "MA5下穿MA20", "params": {"period": 5}, "compare_params": {"period": 20}},
                {"field": "close", "operator": ">", "compare_type": "field", "compare_field": "EMA", "score": 15, "label": "收盘价>EMA12", "compare_params": {"period": 12}},
                {"field": "close", "operator": "<", "compare_type": "field", "compare_field": "EMA", "score": -15, "label": "收盘价<EMA12", "compare_params": {"period": 12}},
                {"field": "ADX_plus_di", "operator": ">", "compare_type": "field", "compare_field": "ADX_minus_di", "score": 20, "label": "+DI > -DI", "params": {"period": 14}, "compare_params": {"period": 14}},
                {"field": "ADX_minus_di", "operator": ">", "compare_type": "field", "compare_field": "ADX_plus_di", "score": -20, "label": "-DI > +DI", "params": {"period": 14}, "compare_params": {"period": 14}},
            ],
            "buy_conditions": [
                {"field": "MA", "operator": ">", "compare_type": "field", "compare_field": "MA", "label": "MA5 > MA20", "params": {"period": 5}, "compare_params": {"period": 20}},
                {"field": "ADX_plus_di", "operator": ">", "compare_type": "field", "compare_field": "ADX_minus_di", "label": "+DI > -DI", "params": {"period": 14}, "compare_params": {"period": 14}},
            ],
            "sell_conditions": [
                {"field": "MA", "operator": "<", "compare_type": "field", "compare_field": "MA", "label": "MA5 < MA20", "params": {"period": 5}, "compare_params": {"period": 20}},
                {"field": "ADX_minus_di", "operator": ">", "compare_type": "field", "compare_field": "ADX_plus_di", "label": "-DI > +DI", "params": {"period": 14}, "compare_params": {"period": 14}},
            ],
            "exit_config": {"stop_loss_pct": -10, "take_profit_pct": 30, "max_hold_days": 30},
            "weight": 0.5,
        },
    ]

    with Session(engine) as db:
        for seed in SEEDS:
            exists = db.query(Strategy).filter(Strategy.name == seed["name"]).first()
            if not exists:
                db.add(Strategy(**seed))
                logger.info("Seeded strategy: %s", seed["name"])
        db.commit()


def _seed_templates():
    """Insert built-in strategy templates if they don't exist yet."""
    from sqlalchemy.orm import Session
    from api.models.ai_lab import StrategyTemplate

    SEEDS = [
        # 均线类
        {"name": "均线金叉突破", "category": "均线", "description": "当MA5上穿MA20，且价格站上MA60时买入；MA5下穿MA20或价格跌破MA60时卖出。止损8%，止盈20%，最长持有20天。"},
        {"name": "EMA趋势跟踪", "category": "均线", "description": "当EMA12>EMA26且收盘价连续站上EMA12时买入；EMA12<EMA26或价格跌破EMA26时卖出。止损10%，止盈25%，最长持有30天。"},
        {"name": "多均线共振", "category": "均线", "description": "当MA5>MA10>MA20>MA60多头排列时买入；任一短周期均线下穿长周期均线时卖出。止损8%，止盈30%，最长持有30天。"},
        # 震荡类
        {"name": "RSI超卖反弹", "category": "震荡", "description": "当RSI(14)低于30后回升至35以上时买入；RSI>75或RSI再次跌破25时卖出。止损6%，止盈15%，最长持有10天。"},
        {"name": "KDJ金叉", "category": "震荡", "description": "当KDJ_J值低于20且K线上穿D线时买入；KDJ_J>80或K线下穿D线时卖出。止损7%，止盈18%，最长持有15天。"},
        {"name": "RSI+KDJ共振", "category": "震荡", "description": "当RSI<30同时KDJ_J<20时买入；RSI>70或KDJ_J>80时卖出。止损8%，止盈20%，最长持有15天。"},
        # 趋势类
        {"name": "MACD金叉", "category": "趋势", "description": "当MACD线上穿信号线，且柱状图由负转正时买入；MACD线下穿信号线或柱状图由正转负时卖出。止损8%，止盈25%，最长持有20天。"},
        {"name": "ADX强趋势", "category": "趋势", "description": "当ADX>25且+DI>-DI时买入；ADX<20或-DI>+DI时卖出。止损10%，止盈30%，最长持有30天。"},
        {"name": "MACD+ADX趋势确认", "category": "趋势", "description": "当MACD金叉同时ADX>20且+DI>-DI时买入；MACD死叉或ADX<15时卖出。止损10%，止盈30%，最长持有25天。"},
        # 量价类
        {"name": "放量突破", "category": "量价", "description": "当收盘价突破MA20且OBV创近20日新高时买入；价格跌破MA20或OBV大幅下降时卖出。止损8%，止盈20%，最长持有15天。"},
        {"name": "缩量回调", "category": "量价", "description": "当价格回踩MA20附近（距离<2%）且ATR收窄至近期低位时买入；价格跌破MA60或ATR大幅放大时卖出。止损6%，止盈15%，最长持有10天。"},
        # 组合类
        {"name": "均线+RSI", "category": "组合", "description": "当MA5>MA20且RSI在40-70区间时买入；MA5<MA20或RSI>80时卖出。止损8%，止盈20%，最长持有20天。"},
        {"name": "MACD+RSI双确认", "category": "组合", "description": "当MACD金叉且RSI>50但<70时买入；MACD死叉或RSI>80时卖出。止损8%，止盈25%，最长持有20天。"},
        {"name": "三指标共振", "category": "组合", "description": "当MA5>MA20、MACD柱状图>0且RSI>50时买入；三个条件中任意两个不满足时卖出。止损10%，止盈30%，最长持有25天。"},
        {"name": "全指标综合", "category": "组合", "description": "当MA多头排列、MACD金叉、RSI在40-60区间、KDJ金叉、ADX>20且+DI>-DI时买入（5个条件全部满足）。任一条件不满足时卖出。止损12%，止盈35%，最长持有30天。极度保守策略。"},
    ]

    with Session(engine) as db:
        for seed in SEEDS:
            exists = db.query(StrategyTemplate).filter(
                StrategyTemplate.name == seed["name"]
            ).first()
            if not exists:
                db.add(StrategyTemplate(**seed, is_builtin=True))
                logger.info("Seeded template: %s", seed["name"])
        db.commit()


def _recover_orphan_backtests():
    """Recover strategies stuck in backtesting/pending after a server restart.

    Clone experiments (source_type='clone') get re-submitted to background threads.
    Regular experiment strategies get reset to 'failed' so the retry API can handle them.
    """
    import threading
    from datetime import datetime, timedelta
    from sqlalchemy.orm import Session
    from api.models.ai_lab import Experiment, ExperimentStrategy

    with Session(engine) as db:
        orphans = (
            db.query(ExperimentStrategy)
            .filter(ExperimentStrategy.status.in_(["backtesting", "pending"]))
            .all()
        )
        if not orphans:
            return

        clone_strats = []
        reset_count = 0
        for strat in orphans:
            exp = db.query(Experiment).get(strat.experiment_id)
            if exp and exp.source_type == "clone":
                clone_strats.append((strat.id, exp.id))
            else:
                # Regular experiment strategy — mark failed so retry API can re-run
                strat.status = "failed"
                strat.error_message = "Orphaned after server restart"
                reset_count += 1

        if reset_count:
            db.commit()
            logger.info("Orphan recovery: reset %d regular strategies to 'failed'", reset_count)

        # Re-submit clone experiments in background threads
        for clone_id, exp_id in clone_strats:
            def _rerun(cid=clone_id, eid=exp_id):
                from api.models.base import SessionLocal
                from api.services.ai_lab_engine import AILabEngine, _BACKTEST_SEMAPHORE

                _BACKTEST_SEMAPHORE.acquire()
                session = SessionLocal()
                try:
                    eng = AILabEngine(session)
                    strat = session.query(ExperimentStrategy).get(cid)
                    experiment = session.query(Experiment).get(eid)
                    if not strat or not experiment:
                        return

                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

                    stock_codes = eng.collector.get_stocks_with_data(min_rows=60)
                    stock_data = {}
                    for code in stock_codes:
                        df = eng.collector.get_daily_df(code, start_date, end_date, local_only=True)
                        if df is not None and not df.empty and len(df) >= 60:
                            stock_data[code] = df

                    if not stock_data:
                        strat.status = "failed"
                        strat.error_message = "No stock data"
                        experiment.status = "failed"
                        session.commit()
                        return

                    from api.services.regime_service import ensure_regimes, get_regime_map, get_regime_summary
                    ensure_regimes(session, start_date, end_date)
                    regime_map = get_regime_map(session, start_date, end_date)
                    summary = get_regime_summary(session, start_date, end_date)
                    index_return_pct = summary.get("total_index_return_pct", 0.0)

                    eng._run_single_backtest_impl(
                        strat, stock_data, start_date, end_date,
                        experiment, regime_map, index_return_pct,
                    )
                    experiment.status = "done"
                    session.commit()
                    logger.info("Orphan recovery: S%d done (score=%.3f, ret=+%.1f%%)",
                                cid, strat.score or 0, strat.total_return_pct or 0)
                except Exception as e:
                    try:
                        strat = session.query(ExperimentStrategy).get(cid)
                        exp_obj = session.query(Experiment).get(eid)
                        if strat:
                            strat.status = "failed"
                            strat.error_message = str(e)[:500]
                        if exp_obj:
                            exp_obj.status = "failed"
                        session.commit()
                    except Exception:
                        session.rollback()
                    logger.warning("Orphan recovery: S%d failed: %s", cid, e)
                finally:
                    _BACKTEST_SEMAPHORE.release()
                    session.close()

            t = threading.Thread(target=_rerun, daemon=True)
            t.start()

        if clone_strats:
            logger.info("Orphan recovery: re-submitted %d clone backtests", len(clone_strats))


def _sync_index_data():
    """Sync major index daily data (近5年) for regime computation."""
    from datetime import date, timedelta
    from sqlalchemy.orm import Session
    from api.services.data_collector import DataCollector

    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=5 * 365)).isoformat()

    try:
        with Session(engine) as db:
            collector = DataCollector(db)
            collector.sync_all_indices(start_date, end_date)
        logger.info("Index data sync complete (%s ~ %s)", start_date, end_date)
    except Exception as e:
        logger.warning("Index data sync failed (non-fatal): %s", e)


def _run_migrations():
    """Add new nullable columns to existing tables (idempotent)."""
    from sqlalchemy import text, inspect as sa_inspect

    with engine.connect() as conn:
        inspector = sa_inspect(engine)

        def _add_col_if_missing(table: str, column: str, col_type: str):
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                logger.info("Migration: added %s.%s", table, column)

        # Strategy: rank_config, portfolio_config
        _add_col_if_missing("strategies", "rank_config", "TEXT")
        _add_col_if_missing("strategies", "portfolio_config", "TEXT")

        # BacktestRun: portfolio mode columns
        _add_col_if_missing("backtest_runs_v2", "backtest_mode", "VARCHAR(20)")
        _add_col_if_missing("backtest_runs_v2", "initial_capital", "FLOAT")
        _add_col_if_missing("backtest_runs_v2", "max_positions", "INTEGER")
        _add_col_if_missing("backtest_runs_v2", "cagr_pct", "FLOAT")
        _add_col_if_missing("backtest_runs_v2", "sharpe_ratio", "FLOAT")
        _add_col_if_missing("backtest_runs_v2", "calmar_ratio", "FLOAT")
        _add_col_if_missing("backtest_runs_v2", "profit_loss_ratio", "FLOAT")

        # Experiment: portfolio config columns
        _add_col_if_missing("experiments", "initial_capital", "FLOAT")
        _add_col_if_missing("experiments", "max_positions", "INTEGER")
        _add_col_if_missing("experiments", "max_position_pct", "FLOAT")

        # Market regime stats
        _add_col_if_missing("experiment_strategies", "regime_stats", "TEXT")
        _add_col_if_missing("backtest_runs_v2", "regime_stats", "TEXT")
        _add_col_if_missing("backtest_runs_v2", "index_return_pct", "FLOAT")

        # Strategy: category tags + backtest summary
        _add_col_if_missing("strategies", "category", "VARCHAR(20)")
        _add_col_if_missing("strategies", "backtest_summary", "TEXT")
        _add_col_if_missing("strategies", "source_experiment_id", "INTEGER")

        conn.commit()


def _migrate_strategy_metadata():
    """Back-fill category + backtest_summary on promoted strategies (idempotent)."""
    import json as _json
    import re
    from sqlalchemy.orm import Session
    from api.models.strategy import Strategy
    from api.models.ai_lab import ExperimentStrategy

    LABEL_MAP = {
        "[AI]": "全能",
        "[AI-牛市]": "牛市",
        "[AI-熊市]": "熊市",
        "[AI-震荡]": "震荡",
    }

    with Session(engine) as db:
        strats = db.query(Strategy).all()
        updated = 0
        for s in strats:
            changed = False

            # 1) Parse category from name prefix if category is NULL
            if s.category is None:
                for prefix, cat in LABEL_MAP.items():
                    if s.name.startswith(prefix):
                        s.category = cat
                        changed = True
                        break

            # 2) Back-fill backtest_summary + source_experiment_id from ExperimentStrategy
            if s.backtest_summary is None:
                exp_strat = (
                    db.query(ExperimentStrategy)
                    .filter(ExperimentStrategy.promoted_strategy_id == s.id)
                    .first()
                )
                if exp_strat:
                    s.backtest_summary = {
                        "score": exp_strat.score,
                        "total_return_pct": exp_strat.total_return_pct,
                        "max_drawdown_pct": exp_strat.max_drawdown_pct,
                        "win_rate": exp_strat.win_rate,
                        "total_trades": exp_strat.total_trades,
                        "avg_hold_days": exp_strat.avg_hold_days,
                        "avg_pnl_pct": exp_strat.avg_pnl_pct,
                        "regime_stats": exp_strat.regime_stats,
                    }
                    s.source_experiment_id = exp_strat.id
                    changed = True

            if changed:
                updated += 1

        if updated:
            db.commit()
            logger.info("Backfill: updated %d strategies with category/backtest_summary", updated)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, start background services."""
    logger.info("Creating database tables...")
    import api.models.ai_lab  # noqa: F401 — ensure AI Lab tables are registered
    import api.models.market_regime  # noqa: F401 — ensure market_regimes table is registered
    import api.models.news_sentiment  # noqa: F401 — register sentiment tables
    import api.models.ai_analyst  # noqa: F401 — register AI analyst tables
    import api.models.news_agent  # noqa: F401 — register news agent tables
    import api.models.bot_trading  # noqa: F401 — register bot trading tables
    Base.metadata.create_all(bind=engine)

    # Run lightweight ALTER TABLE migrations for new nullable columns
    _run_migrations()

    # Back-fill category + backtest metrics for promoted strategies
    _migrate_strategy_metadata()

    # Note: _seed_strategies() removed — built-in strategies kept resurrecting
    # after user deletion. Users can create strategies manually or via AI Lab.
    _seed_templates()

    # Sync index data (上证/深成指/创业板) for regime computation
    _sync_index_data()

    # Sync concept boards (daily, idempotent)
    try:
        from sqlalchemy.orm import Session as _Session
        from api.services.concept_sync import sync_concept_boards
        with _Session(engine) as _db:
            sync_concept_boards(_db, max_boards=50)
    except Exception as e:
        logger.warning("Concept board sync failed (non-fatal): %s", e)

    # Register extended indicators into rule engine
    from api.services.indicator_registry import register_extended_indicators
    register_extended_indicators()

    logger.info("Database ready.")

    # Recover orphaned backtests from previous server crash
    _recover_orphan_backtests()

    # Start background services
    from src.services.news_service import start_news_service, stop_news_service
    from api.services.news_sentiment_scheduler import start_news_sentiment_scheduler, stop_news_sentiment_scheduler

    start_news_service()
    logger.info("News service started.")

    start_news_sentiment_scheduler()

    from api.services.news_agent_scheduler import start_news_agent_scheduler, stop_news_agent_scheduler
    start_news_agent_scheduler()
    logger.info("News agent scheduler started (08:00 pre_market, 18:00 evening)")

    from api.services.signal_scheduler import start_signal_scheduler, stop_signal_scheduler
    start_signal_scheduler()
    logger.info("Data sync scheduler started (19:00 daily).")

    yield

    stop_signal_scheduler()
    stop_news_agent_scheduler()

    stop_news_sentiment_scheduler()
    stop_news_service()
    logger.info("Shutting down.")


app = FastAPI(
    title="StockAgent API",
    description="A-share trading signal and backtest API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(market.router)
app.include_router(stocks.router)
app.include_router(strategies.router)
app.include_router(signals.router)
app.include_router(backtest.router)
app.include_router(news.router)
app.include_router(config.router)
app.include_router(ai_lab.router)
app.include_router(ai_analyst.router)
app.include_router(news_signals.router)
app.include_router(bot_trading.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
