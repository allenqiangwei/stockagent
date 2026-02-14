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
