# News Sentiment Trading System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add DeepSeek-powered news sentiment analysis that runs twice daily (pre-market + post-close) and feeds market sentiment scores into the existing signal generation pipeline as an auxiliary factor.

**Architecture:** A new `NewsSentimentEngine` service calls DeepSeek API in batches of 10 news articles from the existing `news_archive` table, stores structured results in a new SQLAlchemy `NewsSentimentResult` table, and exposes 4 API endpoints. A background scheduler triggers analysis at 08:30 and 15:30. The existing `signal_combiner.py` already accepts `sentiment_score` but is never called with one — we wire it up. Frontend gets an AI sentiment card on the news page.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, OpenAI Python SDK (DeepSeek-compatible), Next.js + shadcn/ui, TanStack Query.

---

### Task 1: Create SQLAlchemy models for sentiment tables

**Files:**
- Create: `api/models/news_sentiment.py`

**Step 1: Create the model file with two tables**

```python
"""News sentiment analysis models."""

from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, Float, String, Text, DateTime, Boolean, Index
from sqlalchemy.types import JSON

from api.models.base import Base


class NewsSentimentResult(Base):
    """Market-level sentiment analysis result from DeepSeek."""

    __tablename__ = "news_sentiment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_time = Column(DateTime, default=datetime.now, nullable=False)
    period_type = Column(String(20), nullable=False)  # "pre_market" / "post_close" / "manual"
    news_count = Column(Integer, default=0)
    market_sentiment = Column(Float, default=0.0)  # -100 ~ +100
    confidence = Column(Float, default=0.0)  # 0 ~ 100
    event_tags = Column(JSON, default=list)
    key_summary = Column(Text, default="")
    stock_mentions = Column(JSON, default=list)
    sector_impacts = Column(JSON, default=list)
    raw_response = Column(Text, default="")

    __table_args__ = (
        Index("idx_sentiment_time", "analysis_time"),
        Index("idx_sentiment_period", "period_type", "analysis_time"),
    )


class StockNewsSentiment(Base):
    """Per-stock sentiment analysis result (on-demand)."""

    __tablename__ = "stock_news_sentiment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    analysis_time = Column(DateTime, default=datetime.now, nullable=False)
    sentiment = Column(Float, default=0.0)  # -100 ~ +100
    news_count = Column(Integer, default=0)
    summary = Column(Text, default="")
    valid_until = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_stock_sentiment_code", "stock_code", "analysis_time"),
    )

    @property
    def is_valid(self) -> bool:
        return datetime.now() < self.valid_until
```

**Step 2: Register model import in main.py so tables auto-create**

In `api/main.py`, the lifespan function calls `Base.metadata.create_all(bind=engine)` which auto-creates all tables from imported models. Ensure the new model is imported. Add this line near the top of `api/main.py` alongside other model imports:

```python
import api.models.news_sentiment  # noqa: F401  — register tables
```

Add it right after the existing model imports (near line 8-10 area, next to `import api.models.base`).

**Step 3: Verify tables are created**

Run:
```bash
source venv/bin/activate && python -c "
from api.models.base import engine, Base
import api.models.news_sentiment
Base.metadata.create_all(bind=engine)
print('Tables created:', [t for t in Base.metadata.tables if 'sentiment' in t])
"
```
Expected: `Tables created: ['news_sentiment_results', 'stock_news_sentiment']`

**Step 4: Commit**

```bash
git add api/models/news_sentiment.py api/main.py
git commit -m "feat(news): add SQLAlchemy models for sentiment analysis results"
```

---

### Task 2: Create NewsSentimentEngine service

**Files:**
- Create: `api/services/news_sentiment_engine.py`

**Step 1: Write the engine service**

This is the core service. It reads news from the legacy `news_archive` table (raw SQL since it's not ORM-managed), sends batches to DeepSeek, and stores results in the new ORM table.

```python
"""News sentiment analysis engine — calls DeepSeek to analyze financial news."""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models.news_sentiment import NewsSentimentResult, StockNewsSentiment

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是专业的A股市场分析师。分析以下财经新闻，输出结构化 JSON。

输出格式 (严格 JSON，不要输出其他内容):
{
  "market_sentiment": <-100到+100的整数, 负=悲观, 正=乐观>,
  "confidence": <0到100的整数, 对本次判断的信心>,
  "event_tags": ["标签1", "标签2"],
  "key_summary": "一句话总结当前市场情绪和主要事件",
  "stock_mentions": [
    {"name": "股票名", "sentiment": <-100到+100>, "reason": "简短原因"}
  ],
  "sector_impacts": [
    {"sector": "行业名", "impact": <-100到+100>, "reason": "简短原因"}
  ]
}

分析规则:
- 重大政策(降准/降息/监管)权重最高
- 多条同方向新闻叠加增强信心
- 标题党/重复内容降权
- 无明确方向时 sentiment 接近 0
- stock_mentions 只列出明确提到的个股
- sector_impacts 只列出明确受影响的行业"""

_STOCK_PROMPT = """你是专业的A股市场分析师。以下新闻与 {stock_name}({stock_code}) 相关。
分析这些新闻对该股票的影响。

输出格式 (严格 JSON):
{{
  "sentiment": <-100到+100的整数>,
  "summary": "2-3句话分析新闻对该股票的具体影响",
  "key_events": ["事件1", "事件2"]
}}"""

BATCH_SIZE = 10
MAX_RETRIES = 2
RETRY_DELAY = 30


class NewsSentimentEngine:
    """Analyzes financial news sentiment using DeepSeek API."""

    def __init__(self):
        settings = get_settings()
        self._config = settings.deepseek
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
            )
        return self._client

    # ── Market-level analysis ─────────────────────────────

    def analyze_market(
        self,
        db: Session,
        period_type: str = "manual",
        hours_back: float = 12,
    ) -> Optional[NewsSentimentResult]:
        """Analyze recent news for overall market sentiment.

        Args:
            db: SQLAlchemy session
            period_type: "pre_market", "post_close", or "manual"
            hours_back: how many hours of news to analyze

        Returns:
            NewsSentimentResult or None if no news found
        """
        news_rows = self._fetch_unanalyzed_news(db, hours_back)
        if not news_rows:
            logger.info("No unanalyzed news found for %s (last %.0f hours)", period_type, hours_back)
            return None

        logger.info("Analyzing %d news articles for %s sentiment", len(news_rows), period_type)

        # Split into batches of BATCH_SIZE
        batches = [news_rows[i:i + BATCH_SIZE] for i in range(0, len(news_rows), BATCH_SIZE)]
        batch_results = []

        for i, batch in enumerate(batches):
            result = self._analyze_batch(batch)
            if result:
                batch_results.append(result)
            if i < len(batches) - 1:
                time.sleep(1)  # Rate limit between batches

        if not batch_results:
            logger.warning("All batches failed for %s", period_type)
            return None

        # Merge batch results (confidence-weighted average)
        merged = self._merge_results(batch_results)

        # Persist
        record = NewsSentimentResult(
            period_type=period_type,
            news_count=len(news_rows),
            market_sentiment=merged["market_sentiment"],
            confidence=merged["confidence"],
            event_tags=merged["event_tags"],
            key_summary=merged["key_summary"],
            stock_mentions=merged["stock_mentions"],
            sector_impacts=merged["sector_impacts"],
            raw_response=json.dumps(batch_results, ensure_ascii=False),
        )
        db.add(record)

        # Mark news as analyzed
        ids = [r["id"] for r in news_rows]
        self._mark_analyzed(db, ids)

        db.commit()
        db.refresh(record)

        logger.info(
            "Sentiment analysis complete: %s, sentiment=%.0f, confidence=%.0f, news=%d",
            period_type, record.market_sentiment, record.confidence, record.news_count,
        )
        return record

    # ── Stock-level analysis (on-demand) ──────────────────

    def analyze_stock(
        self,
        db: Session,
        stock_code: str,
        stock_name: str = "",
    ) -> Optional[StockNewsSentiment]:
        """Analyze news related to a specific stock.

        Checks cache first (valid_until). If expired or missing, runs fresh analysis.
        """
        # Check cache
        cached = (
            db.query(StockNewsSentiment)
            .filter(
                StockNewsSentiment.stock_code == stock_code,
                StockNewsSentiment.valid_until > datetime.now(),
            )
            .order_by(StockNewsSentiment.analysis_time.desc())
            .first()
        )
        if cached:
            return cached

        # Fetch related news (reuse the matching logic from news router)
        related_news = self._fetch_related_news(db, stock_code, stock_name)
        if not related_news:
            return None

        prompt = _STOCK_PROMPT.format(stock_name=stock_name, stock_code=stock_code)
        news_text = self._format_news_list(related_news)
        result = self._call_deepseek(prompt, news_text)
        if not result:
            return None

        record = StockNewsSentiment(
            stock_code=stock_code,
            stock_name=stock_name,
            sentiment=result.get("sentiment", 0),
            news_count=len(related_news),
            summary=result.get("summary", ""),
            valid_until=datetime.now() + timedelta(hours=24),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    # ── Internal helpers ──────────────────────────────────

    def _fetch_unanalyzed_news(self, db: Session, hours_back: float) -> list[dict]:
        """Fetch recent unanalyzed news from news_archive (legacy raw SQL table)."""
        from sqlalchemy import text

        cutoff = datetime.now() - timedelta(hours=hours_back)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        result = db.execute(text("""
            SELECT id, title, source, sentiment_score, content, publish_time
            FROM news_archive
            WHERE created_at >= :cutoff
              AND (sentiment_analyzed IS NULL OR sentiment_analyzed = 0)
            ORDER BY created_at DESC
            LIMIT 100
        """), {"cutoff": cutoff_str})

        return [dict(row._mapping) for row in result]

    def _mark_analyzed(self, db: Session, ids: list[int]):
        """Mark news_archive rows as analyzed."""
        from sqlalchemy import text

        if not ids:
            return
        placeholders = ",".join(str(i) for i in ids)
        db.execute(text(f"UPDATE news_archive SET sentiment_analyzed = 1 WHERE id IN ({placeholders})"))

    def _fetch_related_news(self, db: Session, stock_code: str, stock_name: str) -> list[dict]:
        """Fetch news related to a stock from news_archive."""
        from sqlalchemy import text

        terms = [stock_name] if stock_name else []
        if not terms:
            return []

        # Build LIKE clauses for stock name
        where_parts = []
        params = {}
        for i, term in enumerate(terms):
            key = f"term_{i}"
            where_parts.append(f"(title LIKE :{key} OR content LIKE :{key})")
            params[key] = f"%{term}%"

        where = " OR ".join(where_parts)
        result = db.execute(text(f"""
            SELECT id, title, source, sentiment_score, content, publish_time
            FROM news_archive
            WHERE ({where})
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT 30
        """), {**params, "cutoff": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")})

        return [dict(row._mapping) for row in result]

    def _format_news_list(self, news_rows: list[dict]) -> str:
        """Format news rows into numbered text for the prompt."""
        lines = []
        for i, row in enumerate(news_rows, 1):
            title = row.get("title", "")
            source = row.get("source", "")
            ptime = row.get("publish_time", "")
            lines.append(f"{i}. [{title}] [{source}] [{ptime}]")
        return "\n".join(lines)

    def _analyze_batch(self, batch: list[dict]) -> Optional[dict]:
        """Send a batch of news to DeepSeek and parse the response."""
        news_text = self._format_news_list(batch)
        return self._call_deepseek(_SYSTEM_PROMPT, f"新闻列表:\n{news_text}")

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        """Call DeepSeek API with retry logic."""
        from api.utils.network import no_proxy

        for attempt in range(MAX_RETRIES + 1):
            try:
                with no_proxy():
                    response = self.client.chat.completions.create(
                        model=self._config.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.3,
                        max_tokens=2000,
                    )
                content = response.choices[0].message.content
                if not content:
                    logger.warning("DeepSeek returned empty content")
                    return None
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse DeepSeek JSON: %s", e)
                return None
            except Exception as e:
                logger.warning("DeepSeek API call failed (attempt %d): %s", attempt + 1, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        return None

    def _merge_results(self, results: list[dict]) -> dict:
        """Merge multiple batch results using confidence-weighted average."""
        if len(results) == 1:
            return results[0]

        total_weight = 0.0
        weighted_sentiment = 0.0
        all_tags = []
        all_stocks = []
        all_sectors = []
        summaries = []

        for r in results:
            conf = r.get("confidence", 50)
            sent = r.get("market_sentiment", 0)
            weighted_sentiment += sent * conf
            total_weight += conf
            all_tags.extend(r.get("event_tags", []))
            all_stocks.extend(r.get("stock_mentions", []))
            all_sectors.extend(r.get("sector_impacts", []))
            summaries.append(r.get("key_summary", ""))

        avg_sentiment = weighted_sentiment / total_weight if total_weight > 0 else 0
        avg_confidence = total_weight / len(results) if results else 0

        # Deduplicate tags
        unique_tags = list(dict.fromkeys(all_tags))

        return {
            "market_sentiment": round(avg_sentiment, 1),
            "confidence": round(avg_confidence, 1),
            "event_tags": unique_tags[:10],
            "key_summary": summaries[0] if summaries else "",
            "stock_mentions": all_stocks,
            "sector_impacts": all_sectors,
        }


# ── Module-level helpers ──────────────────────────────

def get_latest_sentiment(db: Session) -> Optional[NewsSentimentResult]:
    """Get the most recent sentiment analysis result."""
    return (
        db.query(NewsSentimentResult)
        .order_by(NewsSentimentResult.analysis_time.desc())
        .first()
    )


def get_sentiment_score_for_signal(db: Session) -> Optional[float]:
    """Get sentiment score mapped to 0-100 range for signal_combiner.

    The combiner expects 0-100 (50=neutral), but our sentiment is -100 to +100.
    Mapping: score = (market_sentiment + 100) / 2
    """
    latest = get_latest_sentiment(db)
    if not latest:
        return None
    # Only use if analysis is within last 24 hours
    if (datetime.now() - latest.analysis_time).total_seconds() > 86400:
        return None
    return (latest.market_sentiment + 100) / 2
```

**Step 2: Add the `sentiment_analyzed` column to news_archive**

The legacy `news_archive` table needs a new column. We'll add it via ALTER TABLE in the database init. Add to `src/data_storage/database.py` in the `_init_tables()` method, after the existing CREATE TABLE/INDEX statements:

Find the line after `CREATE INDEX IF NOT EXISTS idx_news_archive_sentiment` and add:

```python
            # Add sentiment_analyzed column if missing (migration)
            try:
                cursor.execute("""
                    ALTER TABLE news_archive ADD COLUMN sentiment_analyzed INTEGER DEFAULT 0
                """)
            except Exception:
                pass  # Column already exists
```

**Step 3: Verify the engine can be instantiated**

```bash
source venv/bin/activate && python -c "
from api.services.news_sentiment_engine import NewsSentimentEngine
engine = NewsSentimentEngine()
print('Engine created, model:', engine._config.model)
"
```
Expected: `Engine created, model: deepseek-chat`

**Step 4: Commit**

```bash
git add api/services/news_sentiment_engine.py src/data_storage/database.py
git commit -m "feat(news): add NewsSentimentEngine service with DeepSeek integration"
```

---

### Task 3: Create the news sentiment scheduler

**Files:**
- Create: `api/services/news_sentiment_scheduler.py`

**Step 1: Write the scheduler**

Follow the pattern of `api/services/signal_scheduler.py` — daemon thread, check every 30 seconds.

```python
"""News sentiment scheduler — runs analysis at pre-market and post-close.

Schedule:
  08:30  pre_market   (analyzes news from previous evening to morning)
  15:30  post_close   (analyzes news from morning to close)
"""

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from api.models.base import SessionLocal
from api.services.news_sentiment_engine import NewsSentimentEngine

logger = logging.getLogger(__name__)


class NewsSentimentScheduler:
    """Background scheduler for news sentiment analysis."""

    # (hour, minute, period_type, hours_back)
    SCHEDULE = [
        (8, 30, "pre_market", 15.5),   # 17:00 yesterday → 08:30 today
        (15, 30, "post_close", 7.0),    # 08:30 → 15:30
    ]

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._today_completed: set[str] = set()
        self._engine = NewsSentimentEngine()
        self._is_analyzing = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("News sentiment scheduler started (08:30 pre_market, 15:30 post_close)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("News sentiment scheduler stopped")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "is_analyzing": self._is_analyzing,
            "today_completed": list(self._today_completed),
        }

    def _run_loop(self):
        while self._running:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Reset completed set at midnight
            if self._today_completed and not any(
                c.startswith(today_str) for c in self._today_completed
            ):
                self._today_completed.clear()

            for hour, minute, period_type, hours_back in self.SCHEDULE:
                key = f"{today_str}_{period_type}"
                if key in self._today_completed:
                    continue

                should_run = (
                    now.hour > hour
                    or (now.hour == hour and now.minute >= minute)
                )
                if should_run and not self._is_analyzing:
                    self._do_analysis(period_type, hours_back, key)

            # Check every 30 seconds
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _do_analysis(self, period_type: str, hours_back: float, key: str):
        self._is_analyzing = True
        try:
            db = SessionLocal()
            try:
                result = self._engine.analyze_market(db, period_type, hours_back)
                if result:
                    logger.info(
                        "Scheduled %s analysis done: sentiment=%.0f, confidence=%.0f",
                        period_type, result.market_sentiment, result.confidence,
                    )
                else:
                    logger.info("Scheduled %s analysis: no news to analyze", period_type)
                self._today_completed.add(key)
            finally:
                db.close()
        except Exception as e:
            logger.error("Scheduled %s analysis failed: %s", period_type, e)
            self._today_completed.add(key)  # Don't retry on same day
        finally:
            self._is_analyzing = False


# ── Global singleton ──────────────────────────────

_scheduler: Optional[NewsSentimentScheduler] = None


def get_news_sentiment_scheduler() -> NewsSentimentScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = NewsSentimentScheduler()
    return _scheduler


def start_news_sentiment_scheduler() -> NewsSentimentScheduler:
    svc = get_news_sentiment_scheduler()
    if not svc._running:
        svc.start()
    return svc


def stop_news_sentiment_scheduler():
    global _scheduler
    if _scheduler and _scheduler._running:
        _scheduler.stop()
```

**Step 2: Register scheduler in main.py lifespan**

In `api/main.py`, inside the lifespan function, after `start_news_service()` and `start_signal_scheduler()`, add:

```python
from api.services.news_sentiment_scheduler import start_news_sentiment_scheduler, stop_news_sentiment_scheduler

start_news_sentiment_scheduler()
```

And in the shutdown section (after `yield`), add:

```python
stop_news_sentiment_scheduler()
```

**Step 3: Verify scheduler starts**

```bash
source venv/bin/activate && python -c "
from api.services.news_sentiment_scheduler import NewsSentimentScheduler
s = NewsSentimentScheduler()
print('Schedule:', [(h,m,p) for h,m,p,_ in s.SCHEDULE])
print('Status:', s.get_status())
"
```
Expected: `Schedule: [(8, 30, 'pre_market'), (15, 30, 'post_close')]`

**Step 4: Commit**

```bash
git add api/services/news_sentiment_scheduler.py api/main.py
git commit -m "feat(news): add sentiment analysis scheduler (08:30 + 15:30 daily)"
```

---

### Task 4: Add API endpoints for sentiment

**Files:**
- Modify: `api/routers/news.py`

**Step 1: Add 4 new endpoints to the existing news router**

Append these endpoints to the end of `api/routers/news.py` (after the existing `/api/news/related/{stock_code}` endpoint):

```python
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
```

Also add `Query` to the import line at the top of the file (if not already there):

```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

**Step 2: Verify endpoints appear in OpenAPI**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/openapi.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
paths=[p for p in spec['paths'] if 'sentiment' in p]
print('Sentiment endpoints:', paths)
"
```
Expected: 4 paths containing "sentiment"

**Step 3: Commit**

```bash
git add api/routers/news.py
git commit -m "feat(news): add 4 sentiment API endpoints (latest, history, analyze, stock)"
```

---

### Task 5: Wire sentiment into signal generation

**Files:**
- Modify: `api/services/signal_engine.py:186-271` (_evaluate_stock method area)

**Step 1: Add sentiment score to the signal output**

The current `SignalEngine` doesn't use `signal_combiner.py` at all — it directly evaluates buy/sell conditions via `evaluate_conditions()`. The sentiment score should be included in the signal output as metadata so the frontend can display it, and it should influence signal ordering.

In `api/services/signal_engine.py`, modify the `generate_signals_stream` method. Add a sentiment lookup at the start of generation (before the stock loop), then include it in the signal output.

At the top of `generate_signals_stream()` method (after loading strategies, around line 109), add:

```python
        # Load latest market sentiment for signal weighting
        from api.services.news_sentiment_engine import get_sentiment_score_for_signal
        sentiment_score = get_sentiment_score_for_signal(self.db)
```

Then in `_evaluate_stock()` (around line 265, where the return dict is built), add the sentiment to the output:

```python
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "action": action,
            "reasons": reasons,
            "sentiment_score": sentiment_score,  # Add this line
        }
```

But `_evaluate_stock` doesn't have access to `sentiment_score`. Pass it through: add `sentiment_score: Optional[float] = None` parameter to `_evaluate_stock`, and pass it from the callers.

In `generate_signals_stream` loop (line 127):
```python
                signal = self._evaluate_stock(
                    code, trade_date, strategies,
                    stock_name=stock_name,
                    is_held=code in held_codes,
                    sentiment_score=sentiment_score,
                )
```

Same for `generate_signals` (line 68):
```python
                signal = self._evaluate_stock(
                    code, trade_date, strategies,
                    stock_name=name_map.get(code, ""),
                    is_held=code in held_codes,
                    sentiment_score=sentiment_score,
                )
```

And add the sentiment lookup in `generate_signals` too (before the loop, line 65):
```python
        from api.services.news_sentiment_engine import get_sentiment_score_for_signal
        sentiment_score = get_sentiment_score_for_signal(self.db)
```

**Step 2: Use sentiment to influence signal filtering**

In `_evaluate_stock`, after determining the action (line 248-254), add sentiment-aware filtering:

```python
        # Sentiment influence: if strongly bearish, suppress weak buy signals
        if sentiment_score is not None:
            if action == "buy" and sentiment_score < 30:
                # Strong bearish sentiment: only keep buy signals with multiple strategies
                if len(buy_strategies) < 2:
                    return None
```

This is a conservative approach — only suppress single-strategy buys during strong bearish sentiment.

**Step 3: Verify signal generation still works**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/signals/meta
```
Expected: Normal response with signal metadata

**Step 4: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "feat(signals): wire market sentiment into signal generation pipeline"
```

---

### Task 6: Add frontend sentiment card and API hooks

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/hooks/use-queries.ts`
- Modify: `web/src/types/index.ts`
- Modify: `web/src/app/news/page.tsx`

**Step 1: Add TypeScript types**

Add to `web/src/types/index.ts` (after `NewsStatsResponse`):

```typescript
export interface SentimentLatestResponse {
  has_data: boolean;
  market_sentiment: number;
  confidence: number;
  event_tags: string[];
  key_summary: string;
  stock_mentions: { name: string; sentiment: number; reason: string }[];
  sector_impacts: { sector: string; impact: number; reason: string }[];
  analysis_time: string | null;
  period_type: string | null;
  news_count: number;
}

export interface SentimentHistoryItem {
  id: number;
  analysis_time: string | null;
  period_type: string;
  market_sentiment: number;
  confidence: number;
  event_tags: string[];
  key_summary: string;
  news_count: number;
}

export interface SentimentHistoryResponse {
  days: number;
  count: number;
  items: SentimentHistoryItem[];
}
```

**Step 2: Add API functions**

In `web/src/lib/api.ts`, extend the `news` object:

```typescript
export const news = {
  latest: () => request<NewsLatestResponse>("/news/latest"),
  stats: () => request<NewsStatsResponse>("/news/stats"),
  related: (code: string) => request<RelatedNewsResponse>(`/news/related/${code}`),
  sentimentLatest: () => request<SentimentLatestResponse>("/news/sentiment/latest"),
  sentimentHistory: (days = 30) =>
    request<SentimentHistoryResponse>(`/news/sentiment/history?days=${days}`),
  triggerAnalysis: () => post<{ message: string; result: unknown }>("/news/sentiment/analyze", {}),
};
```

Add the new types to the import block at the top of `api.ts`.

**Step 3: Add TanStack Query hooks**

In `web/src/hooks/use-queries.ts`, add after the existing news hooks:

```typescript
export function useSentimentLatest() {
  return useQuery({
    queryKey: ["news", "sentiment", "latest"],
    queryFn: () => news.sentimentLatest(),
    refetchInterval: 5 * 60 * 1000,
  });
}

export function useSentimentHistory(days = 30) {
  return useQuery({
    queryKey: ["news", "sentiment", "history", days],
    queryFn: () => news.sentimentHistory(days),
    staleTime: 10 * 60 * 1000,
  });
}

export function useTriggerSentimentAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => news.triggerAnalysis(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news", "sentiment"] });
    },
  });
}
```

**Step 4: Add AI Sentiment Card to the news page**

In `web/src/app/news/page.tsx`, add a new card component at the top of the page content (before the existing sentiment overview cards). Insert after the imports:

```typescript
import { useSentimentLatest, useTriggerSentimentAnalysis } from "@/hooks/use-queries";
import { Brain, RefreshCw } from "lucide-react";
```

Then add this component before the main `NewsPage` function or inline it. Insert the card JSX right after the page header div and before the existing "数据总览" info bar:

```tsx
{/* AI Sentiment Card */}
{(() => {
  const { data: sentiment } = useSentimentLatest();
  const triggerMutation = useTriggerSentimentAnalysis();

  if (!sentiment) return null;

  const s = sentiment.market_sentiment;
  const color = s > 30 ? "text-green-400" : s < -30 ? "text-red-400" : "text-yellow-400";
  const bgColor = s > 30 ? "bg-green-600/10" : s < -30 ? "bg-red-600/10" : "bg-yellow-600/10";
  const label = s > 60 ? "强烈乐观" : s > 30 ? "偏乐观" : s < -60 ? "强烈悲观" : s < -30 ? "偏悲观" : "中性";

  return (
    <Card className={`${bgColor} border-0 mb-4`}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-purple-400" />
            <span className="text-sm font-medium text-muted-foreground">AI 市场情绪分析</span>
          </div>
          <div className="flex items-center gap-2">
            {sentiment.analysis_time && (
              <span className="text-xs text-muted-foreground">
                {sentiment.period_type === "pre_market" ? "盘前" : sentiment.period_type === "post_close" ? "收盘后" : "手动"} · {sentiment.analysis_time}
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={() => triggerMutation.mutate()}
              disabled={triggerMutation.isPending}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${triggerMutation.isPending ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {sentiment.has_data ? (
          <div className="space-y-3">
            <div className="flex items-baseline gap-3">
              <span className={`text-3xl font-bold ${color}`}>
                {s > 0 ? "+" : ""}{s.toFixed(0)}
              </span>
              <span className={`text-sm ${color}`}>{label}</span>
              <span className="text-xs text-muted-foreground">
                信心 {sentiment.confidence.toFixed(0)}% · {sentiment.news_count} 条新闻
              </span>
            </div>

            {sentiment.key_summary && (
              <p className="text-sm text-muted-foreground">{sentiment.key_summary}</p>
            )}

            {sentiment.event_tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {sentiment.event_tags.map((tag, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">{tag}</Badge>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">暂无分析数据，点击刷新按钮手动触发</p>
        )}
      </CardContent>
    </Card>
  );
})()}
```

Note: The `useSentimentLatest` and `useTriggerSentimentAnalysis` hooks must be called inside a component, not conditionally. If the news page uses a flat function component, place the hooks at the top of the function alongside the existing `useNewsLatest()` call.

**Step 5: Verify the page renders**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:3050/news | head -c 200
```
Expected: HTML response (page renders without errors)

**Step 6: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts web/src/app/news/page.tsx
git commit -m "feat(web): add AI sentiment card to news page with trigger analysis button"
```

---

### Task 7: End-to-end verification

**Step 1: Restart backend to pick up all changes**

```bash
kill $(lsof -ti:8050) 2>/dev/null; sleep 2
source venv/bin/activate
NO_PROXY=localhost,127.0.0.1 nohup uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/stockagent-api.log 2>&1 &
sleep 5
```

**Step 2: Verify tables exist**

```bash
source venv/bin/activate && python -c "
import sqlite3
conn = sqlite3.connect('data/stockagent.db')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%sentiment%'\").fetchall()]
print('Sentiment tables:', tables)
# Check news_archive has new column
cols = [r[1] for r in conn.execute('PRAGMA table_info(news_archive)').fetchall()]
print('sentiment_analyzed column:', 'sentiment_analyzed' in cols)
conn.close()
"
```
Expected: Tables and column present

**Step 3: Test manual sentiment analysis**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/news/sentiment/analyze | python3 -m json.tool
```
Expected: JSON with `market_sentiment`, `event_tags`, `key_summary`, etc. (or "无最新新闻可分析" if news_archive is empty)

**Step 4: Test sentiment latest endpoint**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/news/sentiment/latest | python3 -m json.tool
```
Expected: JSON response with sentiment data (or `has_data: false`)

**Step 5: Test sentiment history endpoint**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s "http://127.0.0.1:8050/api/news/sentiment/history?days=7" | python3 -m json.tool
```
Expected: JSON with `items` array

**Step 6: Test frontend renders**

Open `http://localhost:3050/news` in browser. Verify the AI sentiment card appears at the top.

**Step 7: Final commit if any remaining changes**

```bash
git status
# If any uncommitted changes:
git add -A && git commit -m "chore: news sentiment system end-to-end verification"
```
