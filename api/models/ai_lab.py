"""AI Lab ORM models — experiments, experiment strategies, and strategy templates."""

from datetime import datetime

from sqlalchemy import (
    String, Float, Integer, Boolean, DateTime, Text, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class StrategyTemplate(Base):
    __tablename__ = "strategy_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    category: Mapped[str] = mapped_column(String(20), default="组合")
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20), default="template")
    source_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    strategy_count: Mapped[int] = mapped_column(Integer, default=0)
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=10)
    max_position_pct: Mapped[float] = mapped_column(Float, default=30.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    strategies: Mapped[list["ExperimentStrategy"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan",
        order_by="ExperimentStrategy.score.desc()",
    )


class ExperimentStrategy(Base):
    __tablename__ = "experiment_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiments.id"), index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    buy_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    sell_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    exit_config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str] = mapped_column(Text, default="")
    # Backtest results
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    avg_hold_days: Mapped[float] = mapped_column(Float, default=0.0)
    avg_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_run_id: Mapped[int] = mapped_column(Integer, nullable=True)
    # Market regime analysis
    regime_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Promotion
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_strategy_id: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    experiment: Mapped["Experiment"] = relationship(back_populates="strategies")

    __table_args__ = (
        Index("ix_exp_strat_experiment", "experiment_id"),
    )


class ExplorationRound(Base):
    __tablename__ = "exploration_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_number: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="semi-auto")
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    experiment_ids: Mapped[dict] = mapped_column(JSON, default=list)
    total_experiments: Mapped[int] = mapped_column(Integer, default=0)
    total_strategies: Mapped[int] = mapped_column(Integer, default=0)
    profitable_count: Mapped[int] = mapped_column(Integer, default=0)
    profitability_pct: Mapped[float] = mapped_column(Float, default=0.0)
    std_a_count: Mapped[int] = mapped_column(Integer, default=0)
    best_strategy_name: Mapped[str] = mapped_column(String(200), default="")
    best_strategy_score: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_return: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_dd: Mapped[float] = mapped_column(Float, default=0.0)
    insights: Mapped[dict] = mapped_column(JSON, default=list)
    promoted: Mapped[dict] = mapped_column(JSON, default=list)
    issues_resolved: Mapped[dict] = mapped_column(JSON, default=list)
    next_suggestions: Mapped[dict] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    memory_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    pinecone_synced: Mapped[bool] = mapped_column(Boolean, default=False)
