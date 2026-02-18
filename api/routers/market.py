"""Market data router — kline, indicators, quote."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.stock import Stock, INDEX_CODES
from api.models.market_regime import MarketRegimeLabel
from api.services.data_collector import DataCollector
from api.services.indicator_engine import IndicatorEngine
from api.services.regime_service import ensure_regimes
from api.schemas.market import (
    KlineResponse, KlineBar, IndicatorResponse, QuoteResponse,
    IndexKlineResponse, RegimeWeek,
)
from src.indicators.indicator_calculator import IndicatorConfig

router = APIRouter(prefix="/api/market", tags=["market"])


def _parse_indicator_query(query: str) -> tuple[list[str], IndicatorConfig]:
    """Parse pipe-separated indicator query into (indicator_names, config).

    Format: "MA:5,10,20,60|MACD:12,26,9|RSI:14|OBV"
    Each segment is NAME or NAME:param1,param2,...
    """
    config = IndicatorConfig(
        ma_periods=[], ema_periods=[], rsi_periods=[],
        macd_params_list=[], kdj_params_list=[],
        adx_periods=[], atr_periods=[], calc_obv=False,
    )
    ind_list: list[str] = []

    for segment in query.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        if ":" in segment:
            name, params_str = segment.split(":", 1)
            params = [p.strip() for p in params_str.split(",") if p.strip()]
        else:
            name = segment
            params = []

        name_lower = name.strip().lower()
        ind_list.append(name_lower)

        if name_lower == "ma":
            config.ma_periods = [int(p) for p in params] if params else [5, 10, 20, 60]
        elif name_lower == "ema":
            config.ema_periods = [int(p) for p in params] if params else [12, 26]
        elif name_lower == "rsi":
            config.rsi_periods = [int(p) for p in params] if params else [14]
        elif name_lower == "macd":
            if len(params) == 3:
                config.macd_params_list = [(int(params[0]), int(params[1]), int(params[2]))]
            else:
                config.macd_params_list = [(12, 26, 9)]
        elif name_lower == "kdj":
            if len(params) == 3:
                config.kdj_params_list = [(int(params[0]), int(params[1]), int(params[2]))]
            else:
                config.kdj_params_list = [(9, 3, 3)]
        elif name_lower == "adx":
            config.adx_periods = [int(params[0])] if params else [14]
        elif name_lower == "atr":
            config.atr_periods = [int(params[0])] if params else [14]
        elif name_lower == "obv":
            config.calc_obv = True

    return ind_list, config


@router.get("/kline/{code}", response_model=KlineResponse)
def get_kline(
    code: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    start: str = Query("", description="YYYY-MM-DD"),
    end: str = Query("", description="YYYY-MM-DD"),
    signals: bool = Query(False, description="Include buy/sell signals"),
    db: Session = Depends(get_db),
):
    """Get K-line data for a stock."""
    from datetime import datetime, timedelta

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")
    if not start:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    collector = DataCollector(db)
    df = collector.get_daily_df(code, start, end)
    if df is None or df.empty:
        raise HTTPException(404, f"No data for {code}")

    # Weekly/monthly aggregation
    if period in ("weekly", "monthly"):
        import pandas as pd
        df["date"] = pd.to_datetime(df["date"])
        freq = "W" if period == "weekly" else "ME"
        df = df.set_index("date").resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna().reset_index()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    bars = [
        KlineBar(
            date=str(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
        )
        for _, row in df.iterrows()
    ]

    stock = db.query(Stock).filter(Stock.code == code).first()
    stock_name = stock.name if stock else code

    return KlineResponse(
        stock_code=code,
        stock_name=stock_name,
        period=period,
        bars=bars,
    )


@router.get("/indicators/{code}", response_model=IndicatorResponse)
def get_indicators(
    code: str,
    indicators: str = Query("RSI:14|MACD:12,26,9", description="Pipe-separated indicators with params, e.g. MA:5,10,20|RSI:14|MACD:12,26,9"),
    start: str = Query("", description="YYYY-MM-DD"),
    end: str = Query("", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """Get computed indicator values for a stock."""
    from datetime import datetime, timedelta

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")
    if not start:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    collector = DataCollector(db)
    df = collector.get_daily_df(code, start, end)
    if df is None or df.empty:
        raise HTTPException(404, f"No data for {code}")

    ind_list, config = _parse_indicator_query(indicators)
    engine = IndicatorEngine()
    data = engine.compute_for_api(df, ind_list, config=config)

    return IndicatorResponse(
        stock_code=code,
        indicators=ind_list,
        data=data,
    )


@router.get("/quote/{code}", response_model=QuoteResponse)
def get_quote(
    code: str,
    db: Session = Depends(get_db),
):
    """Get the latest quote for a stock."""
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    collector = DataCollector(db)
    df = collector.get_daily_df(code, start, end)
    if df is None or df.empty:
        raise HTTPException(404, f"No data for {code}")

    latest = df.iloc[-1]
    change_pct = None
    if len(df) >= 2:
        prev_close = float(df.iloc[-2]["close"])
        if prev_close > 0:
            change_pct = round(
                (float(latest["close"]) - prev_close) / prev_close * 100, 2
            )

    stock = db.query(Stock).filter(Stock.code == code).first()
    stock_name = stock.name if stock else code

    return QuoteResponse(
        stock_code=code,
        stock_name=stock_name,
        date=str(latest["date"]),
        open=float(latest["open"]),
        high=float(latest["high"]),
        low=float(latest["low"]),
        close=float(latest["close"]),
        volume=float(latest.get("volume", 0)),
        change_pct=change_pct,
    )


@router.get("/index-list")
def get_index_list():
    """Return available index codes and names."""
    return {code: {"name": info["name"]} for code, info in INDEX_CODES.items()}


@router.get("/index-kline/{code}", response_model=IndexKlineResponse)
def get_index_kline(
    code: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    start: str = Query("", description="YYYY-MM-DD"),
    end: str = Query("", description="YYYY-MM-DD"),
    refresh: bool = Query(False, description="Force re-fetch data and recompute regimes"),
    db: Session = Depends(get_db),
):
    """Get index K-line data with weekly regime labels."""
    from datetime import datetime, timedelta

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")
    if not start:
        start = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

    info = INDEX_CODES.get(code)
    if not info:
        raise HTTPException(404, f"Unknown index code: {code}")

    collector = DataCollector(db)
    df = collector.get_index_daily_df(code, start, end, force_refresh=refresh)
    if df is None or df.empty:
        raise HTTPException(404, f"No data for index {code}")

    # Weekly/monthly aggregation
    if period in ("weekly", "monthly"):
        import pandas as pd
        df["date"] = pd.to_datetime(df["date"])
        freq = "W" if period == "weekly" else "ME"
        df = df.set_index("date").resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna().reset_index()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    bars = [
        KlineBar(
            date=str(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
        )
        for _, row in df.iterrows()
    ]

    # Regime data: on refresh, delete existing and recompute
    from datetime import date as date_type
    req_start = date_type.fromisoformat(start)
    req_end = date_type.fromisoformat(end)

    try:
        if refresh:
            db.query(MarketRegimeLabel).filter(
                MarketRegimeLabel.week_start >= req_start,
                MarketRegimeLabel.week_end <= req_end,
            ).delete()
            db.commit()
        ensure_regimes(db, start, end)
    except Exception:
        pass  # Non-critical — chart still works without regime bands
    regime_rows = (
        db.query(MarketRegimeLabel)
        .filter(
            MarketRegimeLabel.week_start >= req_start,
            MarketRegimeLabel.week_end <= req_end,
        )
        .order_by(MarketRegimeLabel.week_start)
        .all()
    )
    regimes = [
        RegimeWeek(
            week_start=r.week_start.isoformat() if hasattr(r.week_start, "isoformat") else str(r.week_start),
            week_end=r.week_end.isoformat() if hasattr(r.week_end, "isoformat") else str(r.week_end),
            regime=r.regime,
            confidence=r.confidence,
            trend_strength=r.trend_strength,
            volatility=r.volatility,
            index_return_pct=r.index_return_pct,
        )
        for r in regime_rows
    ]

    return IndexKlineResponse(
        index_code=code,
        index_name=info["name"],
        period=period,
        bars=bars,
        regimes=regimes,
    )


@router.get("/trading-day")
def get_trading_day_info(
    date: str = Query("", description="YYYY-MM-DD, defaults to today"),
    db: Session = Depends(get_db),
):
    """Check if a date is a trading day and return prev/next trading days."""
    from datetime import date as date_type, timedelta

    target = date_type.fromisoformat(date) if date else date_type.today()
    collector = DataCollector(db)

    # Fetch a window around the target date to find prev/next
    window_start = (target - timedelta(days=15)).isoformat()
    window_end = (target + timedelta(days=15)).isoformat()
    trading_dates = collector.get_trading_dates(window_start, window_end)

    is_trading_day = target.isoformat() in trading_dates

    prev_trading_day = None
    next_trading_day = None
    for td in trading_dates:
        d = date_type.fromisoformat(td)
        if d < target:
            prev_trading_day = td
        if d > target and next_trading_day is None:
            next_trading_day = td

    return {
        "date": target.isoformat(),
        "is_trading_day": is_trading_day,
        "prev_trading_day": prev_trading_day,
        "next_trading_day": next_trading_day,
    }
