# AI 模拟交易系统 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在分析报告保存后自动执行模拟买卖，记录每步思考过程，清仓后自动复盘并写入记忆库，前端新增 AI交易 Tab 展示交易时间线和复盘。

**Architecture:** 后端新增 3 张表（bot_portfolio / bot_trades / bot_trade_reviews）+ 交易执行引擎 + 复盘 Claude 任务。reports/save 端点保存后自动触发交易。前端 AI 页面增加 Tab 切换。

**Tech Stack:** Python (FastAPI + SQLAlchemy), TypeScript (Next.js 16 + React Query + shadcn/ui), Claude CLI

---

### Task 1: 后端模型 — BotPortfolio, BotTrade, BotTradeReview

**Files:**
- Create: `api/models/bot_trading.py`

**Step 1: 创建 ORM 模型文件**

```python
"""Bot Trading ORM models — simulated portfolio, trades, and reviews."""

from datetime import datetime

from sqlalchemy import Integer, String, Float, DateTime, Text, Index, Boolean
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BotPortfolio(Base):
    """Robot simulated portfolio — separate from user's real portfolio."""

    __tablename__ = "bot_portfolio"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_invested: Mapped[float] = mapped_column(Float, default=0.0)
    first_buy_date: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class BotTrade(Base):
    """Individual trade record with thinking process."""

    __tablename__ = "bot_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    action: Mapped[str] = mapped_column(String(10))  # buy|sell|reduce|hold
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    thinking: Mapped[str] = mapped_column(Text, default="")
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_bot_trade_code_date", "stock_code", "trade_date"),
    )


class BotTradeReview(Base):
    """Post-mortem review after fully exiting a position."""

    __tablename__ = "bot_trade_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    total_buy_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_sell_amount: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    first_buy_date: Mapped[str] = mapped_column(String(10), default="")
    last_sell_date: Mapped[str] = mapped_column(String(10), default="")
    holding_days: Mapped[int] = mapped_column(Integer, default=0)
    review_thinking: Mapped[str] = mapped_column(Text, default="")
    memory_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_note_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trades: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**Step 2: 在 api/main.py 中注册模型以确保建表**

在 `api/main.py:360` 的 `import api.models.ai_analyst` 行之后添加：

```python
    import api.models.bot_trading  # noqa: F401 — register bot trading tables
```

**Step 3: 验证**

运行: `cd /Users/allenqiang/stockagent && source venv/bin/activate && python -c "from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview; print('OK')"`

预期: `OK`

**Step 4: 提交**

```bash
git add api/models/bot_trading.py api/main.py
git commit -m "feat(bot): add BotPortfolio, BotTrade, BotTradeReview models"
```

---

### Task 2: 后端 Schema — 请求/响应模型

**Files:**
- Create: `api/schemas/bot_trading.py`

**Step 1: 创建 Pydantic schema**

```python
"""Bot Trading Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class BotPortfolioItem(BaseModel):
    stock_code: str
    stock_name: str = ""
    quantity: int = 0
    avg_cost: float = 0.0
    total_invested: float = 0.0
    first_buy_date: str = ""
    # Computed at query time
    close: Optional[float] = None
    change_pct: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    market_value: Optional[float] = None


class BotTradeItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    action: str
    quantity: int = 0
    price: float = 0.0
    amount: float = 0.0
    thinking: str = ""
    report_id: Optional[int] = None
    trade_date: str = ""
    created_at: str = ""

    model_config = {"from_attributes": True}


class BotTradeReviewItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    first_buy_date: str = ""
    last_sell_date: str = ""
    holding_days: int = 0
    review_thinking: str = ""
    memory_synced: bool = False
    memory_note_id: Optional[str] = None
    trades: Optional[list] = None
    created_at: str = ""

    model_config = {"from_attributes": True}


class BotSummary(BaseModel):
    total_invested: float = 0.0
    current_market_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    active_positions: int = 0
    completed_trades: int = 0
    reviews_count: int = 0
    win_count: int = 0
    loss_count: int = 0


class BotStockTimeline(BaseModel):
    """Full timeline for a single stock: all trades + optional review."""
    stock_code: str
    stock_name: str = ""
    status: str = ""  # "holding" | "closed"
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    first_buy_date: str = ""
    last_trade_date: str = ""
    holding_days: int = 0
    current_quantity: int = 0
    current_price: Optional[float] = None
    current_market_value: Optional[float] = None
    trades: list[BotTradeItem] = []
    review: Optional[BotTradeReviewItem] = None
```

**Step 2: 验证**

运行: `python -c "from api.schemas.bot_trading import BotPortfolioItem, BotSummary, BotStockTimeline; print('OK')"`

预期: `OK`

**Step 3: 提交**

```bash
git add api/schemas/bot_trading.py
git commit -m "feat(bot): add bot trading Pydantic schemas"
```

---

### Task 3: 交易执行引擎

**Files:**
- Create: `api/services/bot_trading_engine.py`

**Step 1: 创建交易执行引擎**

```python
"""Bot Trading Engine — executes simulated trades from AI report recommendations."""

import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview

logger = logging.getLogger(__name__)

BUY_AMOUNT = 100_000  # ¥100,000 per buy


def execute_bot_trades(db: Session, report_id: int, report_date: str, recommendations: list[dict]) -> list[dict]:
    """Execute simulated trades based on AI report recommendations.

    Returns list of executed trade summaries.
    """
    if not recommendations:
        return []

    executed = []

    for rec in recommendations:
        action = rec.get("action", "")
        stock_code = rec.get("stock_code", "")
        stock_name = rec.get("stock_name", "")
        target_price = rec.get("target_price")
        position_pct = rec.get("position_pct", 0)
        reason = rec.get("reason", "")

        if not stock_code or not action:
            continue

        if action == "buy":
            result = _execute_buy(db, stock_code, stock_name, target_price, reason, report_id, report_date)
        elif action == "sell":
            result = _execute_sell(db, stock_code, stock_name, target_price, 100.0, reason, report_id, report_date)
        elif action == "reduce":
            result = _execute_sell(db, stock_code, stock_name, target_price, position_pct, reason, report_id, report_date)
        elif action == "hold":
            result = _execute_hold(db, stock_code, stock_name, target_price, reason, report_id, report_date)
        else:
            continue

        if result:
            executed.append(result)

    db.commit()
    return executed


def _execute_buy(db: Session, code: str, name: str, price: float | None, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Buy ~¥100,000 worth of stock."""
    if not price or price <= 0:
        logger.warning("Bot buy skipped: no valid target_price for %s", code)
        return None

    quantity = math.floor(BUY_AMOUNT / price / 100) * 100  # Round to lots of 100
    if quantity <= 0:
        quantity = 100  # Minimum 1 lot

    amount = quantity * price

    # Update or create portfolio entry
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if holding:
        # Average up: recalculate avg_cost
        total_cost = holding.avg_cost * holding.quantity + amount
        holding.quantity += quantity
        holding.avg_cost = total_cost / holding.quantity
        holding.total_invested += amount
    else:
        holding = BotPortfolio(
            stock_code=code,
            stock_name=name,
            quantity=quantity,
            avg_cost=price,
            total_invested=amount,
            first_buy_date=trade_date,
        )
        db.add(holding)

    # Record trade
    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action="buy",
        quantity=quantity,
        price=price,
        amount=amount,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    logger.info("Bot BUY: %s %s × %d @ ¥%.2f = ¥%.0f", code, name, quantity, price, amount)
    return {"action": "buy", "stock_code": code, "quantity": quantity, "price": price, "amount": amount}


def _execute_sell(db: Session, code: str, name: str, price: float | None, sell_pct: float, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Sell a percentage of holdings. sell_pct=100 means full exit."""
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if not holding or holding.quantity <= 0:
        logger.warning("Bot sell skipped: no holding for %s", code)
        return None

    if not price or price <= 0:
        price = holding.avg_cost  # Fallback to cost if no target_price

    sell_qty = math.floor(holding.quantity * sell_pct / 100 / 100) * 100  # Round to lots
    if sell_qty <= 0:
        sell_qty = min(100, holding.quantity)
    if sell_qty > holding.quantity:
        sell_qty = holding.quantity

    amount = sell_qty * price
    action = "sell" if sell_qty >= holding.quantity else "reduce"

    # Record trade
    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action=action,
        quantity=sell_qty,
        price=price,
        amount=amount,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    # Update holding
    holding.quantity -= sell_qty
    fully_exited = holding.quantity <= 0

    logger.info("Bot %s: %s %s × %d @ ¥%.2f = ¥%.0f", action.upper(), code, name, sell_qty, price, amount)

    if fully_exited:
        # Trigger review (sync for now, async later)
        _create_review(db, code, name, trade_date)
        db.delete(holding)

    return {"action": action, "stock_code": code, "quantity": sell_qty, "price": price, "amount": amount, "fully_exited": fully_exited}


def _execute_hold(db: Session, code: str, name: str, price: float | None, reason: str, report_id: int, trade_date: str) -> dict | None:
    """Record a hold decision with thinking."""
    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == code).first()
    if not holding:
        return None

    trade = BotTrade(
        stock_code=code,
        stock_name=name,
        action="hold",
        quantity=0,
        price=price or 0,
        amount=0,
        thinking=reason,
        report_id=report_id,
        trade_date=trade_date,
    )
    db.add(trade)

    logger.info("Bot HOLD: %s %s", code, name)
    return {"action": "hold", "stock_code": code}


def _create_review(db: Session, code: str, name: str, last_sell_date: str):
    """Create a trade review record after fully exiting a position."""
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == code)
        .order_by(BotTrade.trade_date, BotTrade.id)
        .all()
    )
    if not trades:
        return

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))
    pnl = sell_amount - buy_amount
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 else 0.0

    first_buy = next((t for t in trades if t.action == "buy"), None)
    first_buy_date = first_buy.trade_date if first_buy else ""

    holding_days = 0
    if first_buy_date and last_sell_date:
        try:
            from datetime import date
            d1 = date.fromisoformat(first_buy_date)
            d2 = date.fromisoformat(last_sell_date)
            holding_days = (d2 - d1).days
        except ValueError:
            pass

    trades_snapshot = [
        {
            "id": t.id,
            "action": t.action,
            "quantity": t.quantity,
            "price": t.price,
            "amount": t.amount,
            "thinking": t.thinking,
            "trade_date": t.trade_date,
        }
        for t in trades
    ]

    review = BotTradeReview(
        stock_code=code,
        stock_name=name,
        total_buy_amount=buy_amount,
        total_sell_amount=sell_amount,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        first_buy_date=first_buy_date,
        last_sell_date=last_sell_date,
        holding_days=holding_days,
        review_thinking="",  # Will be filled by Claude review job
        memory_synced=False,
        trades=trades_snapshot,
    )
    db.add(review)
    logger.info("Bot review created: %s %s, PnL=¥%.2f (%.1f%%)", code, name, pnl, pnl_pct)
```

**Step 2: 验证**

运行: `python -c "from api.services.bot_trading_engine import execute_bot_trades; print('OK')"`

预期: `OK`

**Step 3: 提交**

```bash
git add api/services/bot_trading_engine.py
git commit -m "feat(bot): add trade execution engine with buy/sell/hold/review"
```

---

### Task 4: 后端 API 端点

**Files:**
- Create: `api/routers/bot_trading.py`
- Modify: `api/main.py:20` (add import) and `api/main.py:446` (register router)

**Step 1: 创建 bot_trading router**

```python
"""Bot Trading router — simulated portfolio, trades, and reviews."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.bot_trading import BotPortfolio, BotTrade, BotTradeReview
from api.models.stock import DailyPrice
from api.schemas.bot_trading import (
    BotPortfolioItem, BotTradeItem, BotTradeReviewItem,
    BotSummary, BotStockTimeline,
)

router = APIRouter(prefix="/api/bot", tags=["bot-trading"])


def _latest_close(db: Session, code: str) -> tuple[float | None, float | None]:
    """Get latest close price and change_pct for a stock."""
    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code == code)
        .order_by(DailyPrice.trade_date.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return None, None
    close = float(rows[0].close)
    change_pct = None
    if len(rows) >= 2:
        prev = float(rows[1].close)
        if prev > 0:
            change_pct = round((close - prev) / prev * 100, 2)
    return close, change_pct


@router.get("/portfolio", response_model=list[BotPortfolioItem])
def get_bot_portfolio(db: Session = Depends(get_db)):
    """List all bot portfolio holdings with current price and P&L."""
    holdings = db.query(BotPortfolio).order_by(BotPortfolio.first_buy_date.desc()).all()
    result = []
    for h in holdings:
        close, change_pct = _latest_close(db, h.stock_code)
        pnl = None
        pnl_pct = None
        market_value = None
        if close is not None and h.quantity > 0:
            market_value = round(close * h.quantity, 2)
            pnl = round((close - h.avg_cost) * h.quantity, 2)
            if h.avg_cost > 0:
                pnl_pct = round((close - h.avg_cost) / h.avg_cost * 100, 2)
        result.append(BotPortfolioItem(
            stock_code=h.stock_code,
            stock_name=h.stock_name,
            quantity=h.quantity,
            avg_cost=h.avg_cost,
            total_invested=h.total_invested,
            first_buy_date=h.first_buy_date,
            close=close,
            change_pct=change_pct,
            pnl=pnl,
            pnl_pct=pnl_pct,
            market_value=market_value,
        ))
    return result


@router.get("/trades", response_model=list[BotTradeItem])
def list_trades(
    stock_code: str = Query("", description="Filter by stock code"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List bot trades, optionally filtered by stock."""
    q = db.query(BotTrade)
    if stock_code:
        q = q.filter(BotTrade.stock_code == stock_code)
    rows = q.order_by(BotTrade.trade_date.desc(), BotTrade.id.desc()).limit(limit).all()
    return [
        BotTradeItem(
            id=t.id,
            stock_code=t.stock_code,
            stock_name=t.stock_name,
            action=t.action,
            quantity=t.quantity,
            price=t.price,
            amount=t.amount,
            thinking=t.thinking,
            report_id=t.report_id,
            trade_date=t.trade_date,
            created_at=t.created_at.isoformat() if t.created_at else "",
        )
        for t in rows
    ]


@router.get("/trades/{stock_code}/timeline", response_model=BotStockTimeline)
def get_stock_timeline(stock_code: str, db: Session = Depends(get_db)):
    """Get full trade timeline for a single stock (all trades + review if exists)."""
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.stock_code == stock_code)
        .order_by(BotTrade.trade_date, BotTrade.id)
        .all()
    )
    if not trades:
        raise HTTPException(404, f"No trades found for {stock_code}")

    holding = db.query(BotPortfolio).filter(BotPortfolio.stock_code == stock_code).first()
    review = (
        db.query(BotTradeReview)
        .filter(BotTradeReview.stock_code == stock_code)
        .order_by(BotTradeReview.created_at.desc())
        .first()
    )

    buy_amount = sum(t.amount for t in trades if t.action == "buy")
    sell_amount = sum(t.amount for t in trades if t.action in ("sell", "reduce"))

    status = "holding" if holding and holding.quantity > 0 else "closed"
    pnl = sell_amount - buy_amount if status == "closed" else 0.0
    pnl_pct = (pnl / buy_amount * 100) if buy_amount > 0 and status == "closed" else 0.0

    first_buy = next((t for t in trades if t.action == "buy"), None)
    last_trade = trades[-1] if trades else None

    close, _ = _latest_close(db, stock_code) if holding else (None, None)

    return BotStockTimeline(
        stock_code=stock_code,
        stock_name=trades[0].stock_name if trades else "",
        status=status,
        total_buy_amount=buy_amount,
        total_sell_amount=sell_amount,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        first_buy_date=first_buy.trade_date if first_buy else "",
        last_trade_date=last_trade.trade_date if last_trade else "",
        holding_days=0,  # Simplified
        current_quantity=holding.quantity if holding else 0,
        current_price=close,
        current_market_value=round(close * holding.quantity, 2) if close and holding else None,
        trades=[
            BotTradeItem(
                id=t.id, stock_code=t.stock_code, stock_name=t.stock_name,
                action=t.action, quantity=t.quantity, price=t.price,
                amount=t.amount, thinking=t.thinking, report_id=t.report_id,
                trade_date=t.trade_date,
                created_at=t.created_at.isoformat() if t.created_at else "",
            )
            for t in trades
        ],
        review=BotTradeReviewItem(
            id=review.id, stock_code=review.stock_code, stock_name=review.stock_name,
            total_buy_amount=review.total_buy_amount, total_sell_amount=review.total_sell_amount,
            pnl=review.pnl, pnl_pct=review.pnl_pct,
            first_buy_date=review.first_buy_date, last_sell_date=review.last_sell_date,
            holding_days=review.holding_days, review_thinking=review.review_thinking,
            memory_synced=review.memory_synced, memory_note_id=review.memory_note_id,
            trades=review.trades,
            created_at=review.created_at.isoformat() if review.created_at else "",
        ) if review else None,
    )


@router.get("/reviews", response_model=list[BotTradeReviewItem])
def list_reviews(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List trade reviews (post-mortems)."""
    rows = (
        db.query(BotTradeReview)
        .order_by(BotTradeReview.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        BotTradeReviewItem(
            id=r.id, stock_code=r.stock_code, stock_name=r.stock_name,
            total_buy_amount=r.total_buy_amount, total_sell_amount=r.total_sell_amount,
            pnl=r.pnl, pnl_pct=r.pnl_pct,
            first_buy_date=r.first_buy_date, last_sell_date=r.last_sell_date,
            holding_days=r.holding_days, review_thinking=r.review_thinking,
            memory_synced=r.memory_synced, memory_note_id=r.memory_note_id,
            trades=r.trades,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.get("/summary", response_model=BotSummary)
def get_bot_summary(db: Session = Depends(get_db)):
    """Get aggregate bot trading statistics."""
    holdings = db.query(BotPortfolio).all()
    reviews = db.query(BotTradeReview).all()

    total_invested = 0.0
    current_mv = 0.0
    for h in holdings:
        total_invested += h.total_invested
        close, _ = _latest_close(db, h.stock_code)
        if close:
            current_mv += close * h.quantity

    # P&L from closed positions
    closed_pnl = sum(r.pnl for r in reviews)
    # Unrealized P&L from open positions
    open_pnl = current_mv - sum(h.avg_cost * h.quantity for h in holdings)
    total_pnl = closed_pnl + open_pnl
    all_invested = total_invested + sum(r.total_buy_amount for r in reviews)
    total_pnl_pct = (total_pnl / all_invested * 100) if all_invested > 0 else 0.0

    return BotSummary(
        total_invested=round(all_invested, 2),
        current_market_value=round(current_mv, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        active_positions=len(holdings),
        completed_trades=len(reviews),
        reviews_count=len(reviews),
        win_count=sum(1 for r in reviews if r.pnl > 0),
        loss_count=sum(1 for r in reviews if r.pnl <= 0),
    )
```

**Step 2: 注册 router**

在 `api/main.py` 第 20 行的 import 列表末尾添加 `, bot_trading`:

```python
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst, news_signals, bot_trading
```

在 `api/main.py` 第 446 行 `app.include_router(news_signals.router)` 后添加:

```python
app.include_router(bot_trading.router)
```

**Step 3: 验证**

运行: `NO_PROXY=localhost,127.0.0.1 curl -s http://localhost:8050/api/bot/portfolio | python3 -c "import json,sys; print(json.load(sys.stdin))"`

预期: `[]` (空列表)

**Step 4: 提交**

```bash
git add api/routers/bot_trading.py api/main.py
git commit -m "feat(bot): add /api/bot/* endpoints — portfolio, trades, reviews, summary"
```

---

### Task 5: reports/save 触发自动交易

**Files:**
- Modify: `api/routers/ai_analyst.py:76-92` (save_report 函数)

**Step 1: 在 save_report 中添加交易执行调用**

将 `save_report` 函数（第 76-92 行）替换为：

```python
@router.post("/reports/save")
def save_report(body: AIReportSaveRequest, db: Session = Depends(get_db)):
    """Save an AI analysis report and auto-execute bot trades."""
    report = AIReport(
        report_date=body.report_date,
        report_type=body.report_type,
        market_regime=body.market_regime,
        market_regime_confidence=body.market_regime_confidence,
        recommendations=body.recommendations,
        strategy_actions=body.strategy_actions,
        thinking_process=body.thinking_process,
        summary=body.summary,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Auto-execute bot trades from recommendations
    bot_trades_result = []
    if body.recommendations:
        from api.services.bot_trading_engine import execute_bot_trades
        try:
            bot_trades_result = execute_bot_trades(
                db, report.id, body.report_date, body.recommendations
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Bot trade execution failed: %s", e)

    return {
        "id": report.id,
        "report_date": report.report_date,
        "summary": report.summary,
        "bot_trades": bot_trades_result,
    }
```

**Step 2: 验证**

运行: `grep -n "bot_trades" api/routers/ai_analyst.py`

预期: 匹配到 `execute_bot_trades` 和 `bot_trades_result` 相关行

**Step 3: 提交**

```bash
git add api/routers/ai_analyst.py
git commit -m "feat(bot): auto-execute bot trades on report save"
```

---

### Task 6: ANALYSIS_SYSTEM_PROMPT — 加入 bot_portfolio

**Files:**
- Modify: `web/src/lib/claude-worker.ts` (ANALYSIS_SYSTEM_PROMPT Step 7 和 API reference)

**Step 1: 修改 Step 7 — 加入机器人持仓**

找到 Step 7 部分（大约第 404-410 行），将其替换为：

```
STEP 7: 检查持仓 — Check portfolio holdings (user + bot)
  - GET /api/stocks/portfolio → User's real portfolio (highest priority)
  - GET /api/bot/portfolio → Robot simulated portfolio (auto-traded by AI)
  Both portfolios need diagnosis. Sell/reduce recommendations apply to BOTH.
  The response includes: stock_code, stock_name, quantity, avg_cost, close, change_pct, pnl, pnl_pct, market_value.
  - For each holding (from both portfolios), fetch recent kline:
    GET /api/market/kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
  - Check if any holdings have triggered signals from Step 6.
  - In recommendations, use "source": "user" or "source": "bot" to indicate which portfolio.
```

**Step 2: 修改 Step 9 JSON recommendations 注释**

在 recommendations 注释区域添加:

```
      // Use "source": "user"|"bot" to indicate which portfolio a sell/hold/reduce applies to.
```

**Step 3: 在 API reference 中添加 bot API**

在 API reference 列表末尾（`GET /api/news-signals/events` 之后）添加：

```
  GET  /api/bot/portfolio  (robot simulated portfolio — same format as /api/stocks/portfolio)
```

**Step 4: 修改 thinking_process 的持仓诊断部分**

将「持仓诊断」section 更新为：

```
  ## 持仓诊断
  分两部分诊断：
  **用户持仓**: 逐一分析每只持仓股的当前状况...
  **机器人持仓**: 逐一分析 AI 模拟交易的持仓...
```

**Step 5: 构建验证**

运行: `cd /Users/allenqiang/stockagent/web && npx next build 2>&1 | tail -5`

预期: 构建成功

**Step 6: 提交**

```bash
git add -f web/src/lib/claude-worker.ts
git commit -m "feat(bot): add bot portfolio to analysis workflow Step 7"
```

---

### Task 7: 前端类型 + API + Hooks

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/hooks/use-queries.ts`

**Step 1: 添加 TypeScript 类型**

在 `web/src/types/index.ts` 末尾（AnalysisPollResponse 之后，大约第 475 行）添加：

```typescript
// ── Bot Trading ──
export interface BotPortfolioItem {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_cost: number;
  total_invested: number;
  first_buy_date: string;
  close: number | null;
  change_pct: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  market_value: number | null;
}

export interface BotTradeItem {
  id: number;
  stock_code: string;
  stock_name: string;
  action: string;
  quantity: number;
  price: number;
  amount: number;
  thinking: string;
  report_id: number | null;
  trade_date: string;
  created_at: string;
}

export interface BotTradeReviewItem {
  id: number;
  stock_code: string;
  stock_name: string;
  total_buy_amount: number;
  total_sell_amount: number;
  pnl: number;
  pnl_pct: number;
  first_buy_date: string;
  last_sell_date: string;
  holding_days: number;
  review_thinking: string;
  memory_synced: boolean;
  memory_note_id: string | null;
  trades: BotTradeItem[] | null;
  created_at: string;
}

export interface BotSummary {
  total_invested: number;
  current_market_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  active_positions: number;
  completed_trades: number;
  reviews_count: number;
  win_count: number;
  loss_count: number;
}

export interface BotStockTimeline {
  stock_code: string;
  stock_name: string;
  status: string;
  total_buy_amount: number;
  total_sell_amount: number;
  pnl: number;
  pnl_pct: number;
  first_buy_date: string;
  last_trade_date: string;
  holding_days: number;
  current_quantity: number;
  current_price: number | null;
  current_market_value: number | null;
  trades: BotTradeItem[];
  review: BotTradeReviewItem | null;
}
```

**Step 2: 添加 API 函数**

在 `web/src/lib/api.ts` 的 import 区域（第 57 行附近）添加类型引入：

```typescript
  BotPortfolioItem,
  BotTradeItem,
  BotTradeReviewItem,
  BotSummary,
  BotStockTimeline,
```

在 `ai` export 对象后面（第 253 行 `};` 之后），添加:

```typescript
// ── Bot Trading ──────────────────────────────────────
export const bot = {
  portfolio: () => request<BotPortfolioItem[]>("/bot/portfolio"),
  trades: (stockCode = "", limit = 100) =>
    request<BotTradeItem[]>(
      `/bot/trades?stock_code=${stockCode}&limit=${limit}`
    ),
  timeline: (stockCode: string) =>
    request<BotStockTimeline>(`/bot/trades/${stockCode}/timeline`),
  reviews: (limit = 50) =>
    request<BotTradeReviewItem[]>(`/bot/reviews?limit=${limit}`),
  summary: () => request<BotSummary>("/bot/summary"),
};
```

**Step 3: 添加 React Query hooks**

在 `web/src/hooks/use-queries.ts` 末尾添加:

```typescript
// ── Bot Trading ──────────────────────────────────────
import { bot } from "@/lib/api";
import type { BotPortfolioItem, BotSummary, BotStockTimeline, BotTradeReviewItem } from "@/types";

export function useBotPortfolio() {
  return useQuery({
    queryKey: ["bot-portfolio"],
    queryFn: () => bot.portfolio(),
  });
}

export function useBotSummary() {
  return useQuery({
    queryKey: ["bot-summary"],
    queryFn: () => bot.summary(),
  });
}

export function useBotTimeline(stockCode: string) {
  return useQuery({
    queryKey: ["bot-timeline", stockCode],
    queryFn: () => bot.timeline(stockCode),
    enabled: !!stockCode,
  });
}

export function useBotReviews(limit = 50) {
  return useQuery({
    queryKey: ["bot-reviews", limit],
    queryFn: () => bot.reviews(limit),
  });
}
```

**Step 4: 构建验证**

运行: `cd /Users/allenqiang/stockagent/web && npx next build 2>&1 | tail -5`

预期: 构建成功

**Step 5: 提交**

```bash
git add -f web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts
git commit -m "feat(bot): add frontend types, API client, and React Query hooks"
```

---

### Task 8: 前端 — AI交易 Tab UI

**Files:**
- Modify: `web/src/app/ai/page.tsx` (添加 Tab 切换和 BotTradingPanel)

**Step 1: 在 ai/page.tsx 顶部添加 imports**

在现有 import 区域添加:

```typescript
import { useBotPortfolio, useBotSummary, useBotReviews, useBotTimeline } from "@/hooks/use-queries";
import type { BotStockTimeline, BotTradeItem, BotTradeReviewItem } from "@/types";
```

**Step 2: 创建 BotTradingPanel 组件**

在 `page.tsx` 的 `ReportViewer` 组件之前，添加 `BotTradingPanel` 组件。这是一个完整的组件，包含：

- 顶部汇总卡片（总投入/市值/盈亏/持仓数）
- [当前持仓 | 已完结] 子 Tab
- 每只股票可展开的交易时间线
- 复盘内容和记忆同步标签

关键 UI 结构:

```tsx
function BotTradingPanel() {
  const { data: summary } = useBotSummary();
  const { data: portfolio } = useBotPortfolio();
  const { data: reviews } = useBotReviews();
  const [subTab, setSubTab] = useState<"holding" | "closed">("holding");
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="p-5 space-y-5 max-w-3xl mx-auto">
      {/* Summary cards */}
      {/* Sub-tabs: 当前持仓 | 已完结 */}
      {/* Stock cards with expandable trade timeline */}
    </div>
  );
}
```

**Step 3: 在主页面组件中添加 Tab 切换**

在页面的主内容区域（center panel），将 `ReportViewer` 包裹在一个 Tab 切换中：

```tsx
const [mainTab, setMainTab] = useState<"analysis" | "trading">("analysis");

{/* Tab 头 */}
<div className="flex border-b">
  <button onClick={() => setMainTab("analysis")} className={...}>
    市场分析
  </button>
  <button onClick={() => setMainTab("trading")} className={...}>
    AI交易
  </button>
</div>

{/* Tab 内容 */}
{mainTab === "analysis" ? <ReportViewer ... /> : <BotTradingPanel />}
```

**Step 4: 构建验证**

运行: `cd /Users/allenqiang/stockagent/web && npx next build 2>&1 | tail -5`

预期: 构建成功

**Step 5: 提交**

```bash
git add -f web/src/app/ai/page.tsx
git commit -m "feat(bot): add AI Trading tab with portfolio, timeline, and reviews"
```

---

### Task 9: 复盘 Claude 任务（异步）

**Files:**
- Modify: `web/src/lib/claude-worker.ts` (添加 startReviewJob)
- Create: `web/src/app/api/bot/review/route.ts` (触发复盘的 Next.js route)

**Step 1: 在 claude-worker.ts 中添加复盘系统提示和任务函数**

在 `ANALYSIS_SYSTEM_PROMPT` 之后添加：

```typescript
const REVIEW_SYSTEM_PROMPT = `\
You are an expert A-share investment analyst conducting a post-mortem review of a completed trade.
You MUST analyze the entire buy-sell cycle and extract lessons learned.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...
API base: http://localhost:8050

Your analysis should cover:
1. 买入时机评估: Was the entry timing good? What signals were correct/missed?
2. 持有期间分析: How did the stock perform during holding? Were there warning signs?
3. 卖出时机评估: Was the exit timing optimal? Should it have been earlier/later?
4. 新闻/事件影响: What news events impacted the trade?
5. 策略有效性: Did the strategy that generated the signal perform as expected?
6. 关键教训: What should be remembered for future similar situations?

Read the memory base at: /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
Check semantic/strategy-knowledge.md for strategy performance data to cross-reference.

Output ONLY a JSON object:
{
  "review_thinking": "详细的复盘分析（中文，投资顾问风格，500-1000字）",
  "lessons_learned": "1-3句话总结关键教训",
  "memory_note": {
    "id": "trade-review-{stock_code}-{date}",
    "tags": ["trade-review", "{stock_code}", "profit|loss", "{strategy-name}"],
    "content": "一段精炼的记忆笔记（100-200字），包含：股票代码、持有天数、盈亏、关键教训"
  }
}

Answer in Chinese. Be thorough and honest about mistakes.`;
```

并添加 `startReviewJob` 函数（复用 fire-and-forget + 轮询模式）。

**Step 2: 创建复盘触发 route**

创建 `web/src/app/api/bot/review/route.ts`：

```typescript
import { NextResponse } from "next/server";
import { startReviewJob } from "@/lib/claude-worker";

export async function POST(req: Request) {
  const { reviewId, stockCode, stockName, trades, pnl, pnlPct } = await req.json();
  // ... trigger review job
}
```

**Step 3: 在交易引擎清仓后触发复盘**

修改 `api/routers/ai_analyst.py` 的 `save_report` 或 `api/services/bot_trading_engine.py`：当 `fully_exited=true` 时，调用 Next.js 的 `/api/bot/review` 端点触发复盘。

**Step 4: 复盘完成后写入记忆**

复盘 Claude 输出 JSON 后：
- 更新 `bot_trade_reviews.review_thinking`
- 创建记忆文件 `episodic/trades/trade-review-{code}-{date}.md`
- 更新 `meta/index.json`
- 运行 `python scripts/sync-memory.py`
- 更新 `memory_synced = true`

**Step 5: 提交**

```bash
git add -f web/src/lib/claude-worker.ts web/src/app/api/bot/review/route.ts
git commit -m "feat(bot): add Claude review job with memory sync"
```

---

### Task 10: 端到端验证

**Step 1: 重启服务**

```bash
lsof -ti:8050 -ti:3050 | xargs kill -9; sleep 1
source venv/bin/activate && NO_PROXY=localhost,127.0.0.1 nohup python -m uvicorn api.main:app --host 0.0.0.0 --port 8050 --reload > /tmp/stockagent-api.log 2>&1 &
cd web && rm -f .next/dev/lock && nohup npx next dev -p 3050 > /tmp/stockagent-web.log 2>&1 &
```

**Step 2: 验证 API**

```bash
# Bot portfolio (should be empty)
NO_PROXY=localhost,127.0.0.1 curl -s http://localhost:8050/api/bot/portfolio
# Bot summary (should show zeros)
NO_PROXY=localhost,127.0.0.1 curl -s http://localhost:8050/api/bot/summary
```

**Step 3: 验证前端**

打开 `http://localhost:3050/ai`，确认：
- 顶部出现 [市场分析 | AI交易] Tab
- 点击 AI交易 显示空状态
- 触发一次分析报告，确认报告保存后 bot_trades 表有数据

**Step 4: 提交**

```bash
git add -A
git commit -m "feat(bot): complete AI simulated trading system — end-to-end verified"
```
