"""News sentiment analysis engine — calls DeepSeek to analyze financial news.

Architecture:
  1. Fetch ALL unanalyzed news (not just 100)
  2. Deduplicate by title similarity (cross-source overlap is ~30-40%)
  3. Source-proportional sampling (cap at MAX_NEWS_PER_RUN for cost control)
  4. Large batches (50 articles) with title + content snippet
  5. Final synthesis pass: merge batch results into one coherent analysis
"""

import json
import logging
import re
import time
from collections import defaultdict
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
- stock_mentions 只列出明确提到的个股(最多8个)
- sector_impacts 只列出明确受影响的行业(最多6个)"""

_SYNTHESIS_PROMPT = """你是专业的A股市场分析师。以下是对 {total_news} 条财经新闻分 {batch_count} 批分析后的结果。
请综合所有批次，输出一份最终的市场情绪分析。

注意:
- 综合考虑所有批次的情绪和事件
- 如果多批次都指向同一方向，信心应更高
- 去重重复的事件标签和个股提及
- key_summary 应是对所有批次的综合总结(2-3句话)
- stock_mentions 保留最重要的8个
- sector_impacts 保留最重要的6个

输出格式 (严格 JSON):
{{
  "market_sentiment": <-100到+100的整数>,
  "confidence": <0到100的整数>,
  "event_tags": ["标签1", "标签2"],
  "key_summary": "综合总结",
  "stock_mentions": [{{"name": "股票名", "sentiment": <int>, "reason": "原因"}}],
  "sector_impacts": [{{"sector": "行业名", "impact": <int>, "reason": "原因"}}]
}}"""

_STOCK_PROMPT = """你是专业的A股市场分析师。以下新闻与 {stock_name}({stock_code}) 相关。
分析这些新闻对该股票的影响。

输出格式 (严格 JSON):
{{
  "sentiment": <-100到+100的整数>,
  "summary": "2-3句话分析新闻对该股票的具体影响",
  "key_events": ["事件1", "事件2"]
}}"""

BATCH_SIZE = 50  # DeepSeek handles 50 titles+snippets easily
MAX_NEWS_PER_RUN = 500  # Cost control: cap after dedup + sampling
MAX_RETRIES = 2
RETRY_DELAY = 30
CONTENT_SNIPPET_LEN = 80  # First N chars of content per article


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

        Pipeline:
          1. Fetch ALL unanalyzed news (no hard limit)
          2. Deduplicate by title similarity
          3. Source-proportional sampling (cap at MAX_NEWS_PER_RUN)
          4. Batch analyze (BATCH_SIZE=50) with title + content snippet
          5. Final synthesis pass if multiple batches
        """
        raw_rows = self._fetch_unanalyzed_news(db, hours_back)
        if not raw_rows:
            logger.info("No unanalyzed news found for %s (last %.0f hours)", period_type, hours_back)
            return None

        # Dedup + sample
        unique_rows = self._deduplicate(raw_rows)
        sampled_rows = self._source_proportional_sample(unique_rows, MAX_NEWS_PER_RUN)

        logger.info(
            "Analyzing %d news for %s sentiment (raw=%d, dedup=%d, sampled=%d)",
            len(sampled_rows), period_type, len(raw_rows), len(unique_rows), len(sampled_rows),
        )

        # Split into batches of BATCH_SIZE
        batches = [sampled_rows[i:i + BATCH_SIZE] for i in range(0, len(sampled_rows), BATCH_SIZE)]
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

        # Final synthesis: if multiple batches, ask DeepSeek for a coherent summary
        if len(batch_results) >= 2:
            merged = self._synthesize_results(batch_results, len(sampled_rows))
        else:
            merged = batch_results[0]

        # Persist
        record = NewsSentimentResult(
            period_type=period_type,
            news_count=len(sampled_rows),
            market_sentiment=merged["market_sentiment"],
            confidence=merged["confidence"],
            event_tags=merged["event_tags"],
            key_summary=merged["key_summary"],
            stock_mentions=merged["stock_mentions"],
            sector_impacts=merged["sector_impacts"],
            raw_response=json.dumps(batch_results, ensure_ascii=False),
        )
        db.add(record)

        # Mark ALL raw rows as analyzed (including duplicates)
        ids = [r["id"] for r in raw_rows]
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
        """Fetch ALL recent unanalyzed news from news_archive (no hard limit)."""
        from sqlalchemy import text

        cutoff = datetime.now() - timedelta(hours=hours_back)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        result = db.execute(text("""
            SELECT id, title, source, sentiment_score, content, publish_time
            FROM news_archive
            WHERE created_at >= :cutoff
              AND (sentiment_analyzed IS NULL OR sentiment_analyzed = 0)
            ORDER BY created_at DESC
        """), {"cutoff": cutoff_str})

        return [dict(row._mapping) for row in result]

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for dedup: strip punctuation, whitespace, common prefixes."""
        if not title:
            return ""
        # Remove common source prefixes like 【财联社】
        t = re.sub(r"^[【\[].*?[】\]]", "", title)
        # Remove all punctuation and whitespace
        t = re.sub(r"[\s\W]+", "", t)
        return t.lower()

    def _deduplicate(self, rows: list[dict]) -> list[dict]:
        """Remove near-duplicate articles by normalized title.

        Keeps the first occurrence (most recent due to DESC order).
        """
        seen: dict[str, bool] = {}
        unique = []
        for row in rows:
            key = self._normalize_title(row.get("title", ""))
            if not key or key in seen:
                continue
            seen[key] = True
            unique.append(row)
        removed = len(rows) - len(unique)
        if removed > 0:
            logger.info("Dedup removed %d/%d duplicate articles", removed, len(rows))
        return unique

    @staticmethod
    def _source_proportional_sample(rows: list[dict], max_count: int) -> list[dict]:
        """Sample proportionally from each source to ensure balanced representation."""
        if len(rows) <= max_count:
            return rows

        by_source: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_source[row.get("source", "unknown")].append(row)

        # Allocate slots proportionally
        total = len(rows)
        sampled = []
        for source, source_rows in by_source.items():
            n = max(1, round(len(source_rows) / total * max_count))
            sampled.extend(source_rows[:n])

        # Trim if over max due to rounding
        sampled = sampled[:max_count]
        logger.info(
            "Source sampling: %s → %d articles",
            {s: len(r) for s, r in by_source.items()},
            len(sampled),
        )
        return sampled

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

    def _format_news_list(self, news_rows: list[dict], include_content: bool = True) -> str:
        """Format news rows into numbered text for the prompt.

        With include_content=True, appends first CONTENT_SNIPPET_LEN chars of content
        for richer context (titles alone miss key details).
        """
        lines = []
        for i, row in enumerate(news_rows, 1):
            title = row.get("title", "")
            source = row.get("source", "")
            ptime = row.get("publish_time", "")
            line = f"{i}. [{source}] {title}"
            if include_content:
                content = (row.get("content") or "").strip()
                if content and content != title:
                    snippet = content[:CONTENT_SNIPPET_LEN].replace("\n", " ")
                    line += f" — {snippet}"
            lines.append(line)
        return "\n".join(lines)

    def _analyze_batch(self, batch: list[dict]) -> Optional[dict]:
        """Send a batch of news to DeepSeek and parse the response.

        If "Content Exists Risk" error occurs, splits the batch in half and
        retries each half separately (binary search to isolate bad content).
        """
        news_text = self._format_news_list(batch)
        result = self._call_deepseek(_SYSTEM_PROMPT, f"新闻列表:\n{news_text}")

        if result is not None:
            return result

        # If batch failed and has >1 article, try splitting
        if self._last_error_is_content_risk and len(batch) > 1:
            logger.info("Content risk in batch of %d, splitting in half", len(batch))
            mid = len(batch) // 2
            left = self._analyze_batch(batch[:mid])
            right = self._analyze_batch(batch[mid:])
            parts = [r for r in [left, right] if r is not None]
            if parts:
                return self._merge_results_simple(parts) if len(parts) > 1 else parts[0]

        return None

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        """Call DeepSeek API with retry logic.

        Sets self._last_error_is_content_risk for content-safety errors
        (no point retrying those — caller should split the batch instead).
        """
        from api.utils.network import no_proxy

        self._last_error_is_content_risk = False

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
                err_str = str(e)
                # Content safety filter — don't retry, let caller split batch
                if "Content Exists Risk" in err_str:
                    logger.warning("DeepSeek content risk filter triggered, skipping retries")
                    self._last_error_is_content_risk = True
                    return None
                logger.warning("DeepSeek API call failed (attempt %d): %s", attempt + 1, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        return None

    def _synthesize_results(self, results: list[dict], total_news: int) -> dict:
        """Use DeepSeek to synthesize multiple batch results into one coherent analysis.

        This produces a much more coherent summary than simple weighted-average merging.
        Falls back to _merge_results_simple() if the synthesis API call fails.
        """
        # Format batch results as input for synthesis
        batch_summaries = []
        for i, r in enumerate(results, 1):
            batch_summaries.append(json.dumps(r, ensure_ascii=False, indent=None))

        prompt = _SYNTHESIS_PROMPT.format(total_news=total_news, batch_count=len(results))
        user_input = "各批次分析结果:\n" + "\n---\n".join(batch_summaries)

        synthesized = self._call_deepseek(prompt, user_input)
        if synthesized:
            logger.info("Synthesis pass complete for %d batches", len(results))
            # Ensure stock_mentions and sector_impacts are present
            # (DeepSeek sometimes omits them in synthesis; backfill from batch results)
            if not synthesized.get("stock_mentions"):
                synthesized["stock_mentions"] = self._collect_top_mentions(results, "stock_mentions", 8)
            if not synthesized.get("sector_impacts"):
                synthesized["sector_impacts"] = self._collect_top_mentions(results, "sector_impacts", 6)
            return synthesized

        logger.warning("Synthesis pass failed, falling back to simple merge")
        return self._merge_results_simple(results)

    @staticmethod
    def _collect_top_mentions(results: list[dict], key: str, top_n: int) -> list[dict]:
        """Collect and deduplicate mentions from batch results, keep top N by abs(sentiment/impact)."""
        all_items = []
        for r in results:
            all_items.extend(r.get(key, []))

        # Deduplicate by name/sector
        name_key = "name" if key == "stock_mentions" else "sector"
        score_key = "sentiment" if key == "stock_mentions" else "impact"
        seen: dict[str, dict] = {}
        for item in all_items:
            n = item.get(name_key, "")
            if not n:
                continue
            # Keep the one with higher absolute score
            if n not in seen or abs(item.get(score_key, 0)) > abs(seen[n].get(score_key, 0)):
                seen[n] = item

        # Sort by abs score descending, take top N
        sorted_items = sorted(seen.values(), key=lambda x: abs(x.get(score_key, 0)), reverse=True)
        return sorted_items[:top_n]

    @staticmethod
    def _merge_results_simple(results: list[dict]) -> dict:
        """Simple confidence-weighted merge as fallback."""
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
            "stock_mentions": all_stocks[:8],
            "sector_impacts": all_sectors[:6],
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
