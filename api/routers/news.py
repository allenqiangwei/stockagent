"""News router — cached latest news, DB statistics, and related news."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.stock import Stock, StockConcept
from src.services.news_service import NewsService, get_news_service

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/latest")
def get_latest_news():
    """Return cached news list + sentiment overview.

    Reads from the JSON file written by the background NewsService.
    Returns an empty structure when no cache exists yet.
    """
    data = NewsService.get_cached_news()
    if data is None:
        return {
            "fetch_time": "",
            "fetch_timestamp": 0,
            "next_fetch_timestamp": 0,
            "interval_seconds": 600,
            "total_count": 0,
            "overall_sentiment": 50,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "keyword_counts": [],
            "source_stats": {},
            "news_list": [],
        }
    return data


@router.get("/stats")
def get_news_stats():
    """Return DB-level statistics (total archived, per-source breakdown)."""
    service = get_news_service()
    stats = service.get_news_statistics()
    total = service.get_total_news_count()
    return {
        "total_archived": total,
        **stats,
    }


@router.get("/related/{stock_code}")
def get_related_news(stock_code: str, limit: int = 20, db: Session = Depends(get_db)):
    """Return news related to a stock (matched by name, industry, and concepts)."""
    stock = db.query(Stock).filter(Stock.code == stock_code).first()
    if not stock:
        return {
            "stock_code": stock_code, "stock_name": "", "industry": "",
            "concepts": [], "news": [],
        }

    # Get concepts for this stock
    concept_rows = db.query(StockConcept.concept_name).filter(
        StockConcept.stock_code == stock_code
    ).all()
    concepts = [r[0] for r in concept_rows]

    # Build LIKE conditions: stock name + industry + concepts
    conditions = []
    params: dict = {}

    if stock.name:
        conditions.append("(title LIKE :name_pat OR content LIKE :name_pat)")
        params["name_pat"] = f"%{stock.name}%"
    if stock.industry:
        conditions.append("(title LIKE :ind_pat OR content LIKE :ind_pat)")
        params["ind_pat"] = f"%{stock.industry}%"
    for i, concept in enumerate(concepts):
        key = f"con_{i}"
        conditions.append(f"(title LIKE :{key} OR content LIKE :{key})")
        params[key] = f"%{concept}%"

    if not conditions:
        return {
            "stock_code": stock_code, "stock_name": stock.name,
            "industry": stock.industry, "concepts": concepts, "news": [],
        }

    where = " OR ".join(conditions)
    params["lim"] = limit
    rows = db.execute(
        text(
            f"SELECT DISTINCT title, source, sentiment_score, keywords, url, "
            f"publish_time, content "
            f"FROM news_archive WHERE {where} "
            f"ORDER BY publish_time DESC LIMIT :lim"
        ),
        params,
    ).fetchall()

    news_list = [
        {
            "title": r.title,
            "source": r.source,
            "sentiment_score": r.sentiment_score,
            "keywords": r.keywords or "",
            "url": r.url or "",
            "publish_time": r.publish_time or "",
            "content": r.content or "",
        }
        for r in rows
    ]

    return {
        "stock_code": stock_code,
        "stock_name": stock.name,
        "industry": stock.industry,
        "concepts": concepts,
        "news": news_list,
    }


# ── Sentiment Analysis ──────────────────────────────────

@router.get("/sentiment/latest")
def get_sentiment_latest(db: Session = Depends(get_db)):
    """Get the most recent market sentiment analysis."""
    from api.models.news_sentiment import NewsSentimentResult

    result = (
        db.query(NewsSentimentResult)
        .order_by(NewsSentimentResult.analysis_time.desc())
        .first()
    )
    if not result:
        return {
            "has_data": False,
            "market_sentiment": 0,
            "confidence": 0,
            "event_tags": [],
            "key_summary": "暂无分析数据",
            "stock_mentions": [],
            "sector_impacts": [],
            "analysis_time": None,
            "period_type": None,
            "news_count": 0,
        }

    return {
        "has_data": True,
        "market_sentiment": result.market_sentiment,
        "confidence": result.confidence,
        "event_tags": result.event_tags or [],
        "key_summary": result.key_summary or "",
        "stock_mentions": result.stock_mentions or [],
        "sector_impacts": result.sector_impacts or [],
        "analysis_time": result.analysis_time.strftime("%Y-%m-%d %H:%M") if result.analysis_time else None,
        "period_type": result.period_type,
        "news_count": result.news_count,
    }


@router.get("/sentiment/history")
def get_sentiment_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Get sentiment analysis history for the given number of days."""
    from datetime import datetime, timedelta
    from api.models.news_sentiment import NewsSentimentResult

    cutoff = datetime.now() - timedelta(days=days)
    rows = (
        db.query(NewsSentimentResult)
        .filter(NewsSentimentResult.analysis_time >= cutoff)
        .order_by(NewsSentimentResult.analysis_time.desc())
        .all()
    )

    return {
        "days": days,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "analysis_time": r.analysis_time.strftime("%Y-%m-%d %H:%M") if r.analysis_time else None,
                "period_type": r.period_type,
                "market_sentiment": r.market_sentiment,
                "confidence": r.confidence,
                "event_tags": r.event_tags or [],
                "key_summary": r.key_summary or "",
                "news_count": r.news_count,
            }
            for r in rows
        ],
    }


@router.post("/sentiment/analyze")
def trigger_sentiment_analysis(db: Session = Depends(get_db)):
    """Manually trigger a market sentiment analysis."""
    from api.services.news_sentiment_engine import NewsSentimentEngine

    engine = NewsSentimentEngine()
    result = engine.analyze_market(db, period_type="manual", hours_back=24)

    if not result:
        return {"message": "无最新新闻可分析", "result": None}

    return {
        "message": "分析完成",
        "result": {
            "market_sentiment": result.market_sentiment,
            "confidence": result.confidence,
            "event_tags": result.event_tags or [],
            "key_summary": result.key_summary or "",
            "news_count": result.news_count,
        },
    }


@router.post("/sentiment/stock/{stock_code}")
def analyze_stock_sentiment(
    stock_code: str,
    db: Session = Depends(get_db),
):
    """Analyze news sentiment for a specific stock (cached 24h)."""
    from api.models.stock import Stock
    from api.services.news_sentiment_engine import NewsSentimentEngine

    stock = db.query(Stock).filter(Stock.code == stock_code).first()
    stock_name = stock.name if stock else ""

    engine = NewsSentimentEngine()
    result = engine.analyze_stock(db, stock_code, stock_name)

    if not result:
        return {"has_data": False, "message": f"无 {stock_name or stock_code} 相关新闻"}

    return {
        "has_data": True,
        "stock_code": result.stock_code,
        "stock_name": result.stock_name,
        "sentiment": result.sentiment,
        "news_count": result.news_count,
        "summary": result.summary,
        "analysis_time": result.analysis_time.strftime("%Y-%m-%d %H:%M") if result.analysis_time else None,
        "valid_until": result.valid_until.strftime("%Y-%m-%d %H:%M") if result.valid_until else None,
    }
