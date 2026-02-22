"""Stocks router — search, list, watchlist CRUD."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.stock import Stock, Watchlist, Portfolio
from api.services.data_collector import DataCollector
from api.schemas.stock import (
    StockInfo, StockListResponse, WatchlistItem, WatchlistAddRequest,
    PortfolioItem, PortfolioAddRequest,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=StockListResponse)
def list_stocks(
    keyword: str = Query("", description="Search by code or name"),
    market: str = Query("", description="Filter by market (SH/SZ)"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Search/list stocks with pagination."""
    collector = DataCollector(db)
    items, total = collector.get_stock_list(keyword, market, page, size)
    return StockListResponse(
        total=total,
        items=[
            StockInfo(
                code=s.code,
                name=s.name,
                market=s.market or "",
                industry=s.industry or "",
            )
            for s in items
        ],
    )


@router.post("/sync")
def sync_stock_list(db: Session = Depends(get_db)):
    """Sync A-share stock list from remote APIs."""
    collector = DataCollector(db)
    count = collector.sync_stock_list()
    return {"synced": count}


@router.post("/sync-boards")
def sync_boards(
    force: bool = Query(False, description="Force sync even if already done today"),
    db: Session = Depends(get_db),
):
    """Sync industry + concept boards from AkShare (once per day max)."""
    collector = DataCollector(db)
    return collector.sync_boards(force=force)


# ── Watchlist ─────────────────────────────────────────

@router.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist(db: Session = Depends(get_db)):
    """Get user's watchlist with latest price data."""
    from datetime import datetime, timedelta
    from api.models.stock import DailyPrice

    items = (
        db.query(Watchlist)
        .order_by(Watchlist.sort_order, Watchlist.created_at)
        .all()
    )
    if not items:
        return []

    # Batch query: latest 2 prices per watchlist stock for change_pct calc
    codes = [w.stock_code for w in items]
    cutoff = (datetime.now() - timedelta(days=10)).date()

    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code.in_(codes), DailyPrice.trade_date >= cutoff)
        .order_by(DailyPrice.stock_code, DailyPrice.trade_date.desc())
        .all()
    )

    # Group by stock_code, take latest 2 rows
    from collections import defaultdict
    price_map: dict[str, list] = defaultdict(list)
    for r in rows:
        if len(price_map[r.stock_code]) < 2:
            price_map[r.stock_code].append(r)

    result = []
    for w in items:
        prices = price_map.get(w.stock_code, [])
        close = None
        change_pct = None
        date_str = None
        if prices:
            latest = prices[0]
            close = float(latest.close)
            td = latest.trade_date
            date_str = td.isoformat() if hasattr(td, 'isoformat') else str(td)
            if len(prices) >= 2:
                prev_close = float(prices[1].close)
                if prev_close > 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2)
        result.append(WatchlistItem(
            stock_code=w.stock_code,
            stock_name=w.stock_name,
            sort_order=w.sort_order,
            close=close,
            change_pct=change_pct,
            date=date_str,
        ))
    return result


@router.post("/watchlist", response_model=WatchlistItem)
def add_to_watchlist(
    req: WatchlistAddRequest,
    db: Session = Depends(get_db),
):
    """Add a stock to watchlist."""
    existing = (
        db.query(Watchlist).filter(Watchlist.stock_code == req.stock_code).first()
    )
    if existing:
        raise HTTPException(409, f"{req.stock_code} already in watchlist")

    # Try to get stock name from DB
    stock_name = req.stock_name or ""
    if not stock_name:
        stock = db.query(Stock).filter(Stock.code == req.stock_code).first()
        if stock:
            stock_name = stock.name

    w = Watchlist(stock_code=req.stock_code, stock_name=stock_name)
    db.add(w)
    db.commit()
    db.refresh(w)
    return WatchlistItem(
        stock_code=w.stock_code,
        stock_name=w.stock_name,
        sort_order=w.sort_order,
    )


@router.delete("/watchlist/{code}")
def remove_from_watchlist(code: str, db: Session = Depends(get_db)):
    """Remove a stock from watchlist."""
    w = db.query(Watchlist).filter(Watchlist.stock_code == code).first()
    if not w:
        raise HTTPException(404, f"{code} not in watchlist")
    db.delete(w)
    db.commit()
    return {"removed": code}


# ── Portfolio ────────────────────────────────────────

@router.get("/portfolio", response_model=list[PortfolioItem])
def get_portfolio(db: Session = Depends(get_db)):
    """Get user's portfolio with latest price and P&L."""
    from datetime import datetime, timedelta
    from collections import defaultdict
    from api.models.stock import DailyPrice

    items = db.query(Portfolio).order_by(Portfolio.created_at).all()
    if not items:
        return []

    codes = [p.stock_code for p in items]
    cutoff = (datetime.now() - timedelta(days=10)).date()

    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_code.in_(codes), DailyPrice.trade_date >= cutoff)
        .order_by(DailyPrice.stock_code, DailyPrice.trade_date.desc())
        .all()
    )

    price_map: dict[str, list] = defaultdict(list)
    for r in rows:
        if len(price_map[r.stock_code]) < 2:
            price_map[r.stock_code].append(r)

    result = []
    for p in items:
        prices = price_map.get(p.stock_code, [])
        close = None
        change_pct = None
        pnl = None
        pnl_pct = None
        market_value = None
        if prices:
            latest = prices[0]
            close = float(latest.close)
            if len(prices) >= 2:
                prev_close = float(prices[1].close)
                if prev_close > 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2)
            if p.avg_cost > 0:
                pnl = round((close - p.avg_cost) * p.quantity, 2)
                pnl_pct = round((close - p.avg_cost) / p.avg_cost * 100, 2)
            market_value = round(close * p.quantity, 2)
        result.append(PortfolioItem(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            quantity=p.quantity,
            avg_cost=p.avg_cost,
            close=close,
            change_pct=change_pct,
            pnl=pnl,
            pnl_pct=pnl_pct,
            market_value=market_value,
        ))
    return result


@router.post("/portfolio", response_model=PortfolioItem)
def add_to_portfolio(req: PortfolioAddRequest, db: Session = Depends(get_db)):
    """Add a stock to portfolio (or update if exists)."""
    existing = db.query(Portfolio).filter(Portfolio.stock_code == req.stock_code).first()
    if existing:
        existing.quantity = req.quantity
        existing.avg_cost = req.avg_cost
        if req.stock_name:
            existing.stock_name = req.stock_name
        db.commit()
        db.refresh(existing)
        return PortfolioItem(
            stock_code=existing.stock_code,
            stock_name=existing.stock_name,
            quantity=existing.quantity,
            avg_cost=existing.avg_cost,
        )

    stock_name = req.stock_name or ""
    if not stock_name:
        stock = db.query(Stock).filter(Stock.code == req.stock_code).first()
        if stock:
            stock_name = stock.name

    p = Portfolio(
        stock_code=req.stock_code,
        stock_name=stock_name,
        quantity=req.quantity,
        avg_cost=req.avg_cost,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return PortfolioItem(
        stock_code=p.stock_code,
        stock_name=p.stock_name,
        quantity=p.quantity,
        avg_cost=p.avg_cost,
    )


@router.delete("/portfolio/{code}")
def remove_from_portfolio(code: str, db: Session = Depends(get_db)):
    """Remove a stock from portfolio."""
    p = db.query(Portfolio).filter(Portfolio.stock_code == code).first()
    if not p:
        raise HTTPException(404, f"{code} not in portfolio")
    db.delete(p)
    db.commit()
    return {"removed": code}
