"""News agent pipeline — orchestrates 4-agent news analysis.

Pipeline: EventClassifier → SectorAnalyst → StockHunter → DecisionSynthesizer
All agents use DeepSeek API for cost efficiency.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models.news_agent import NewsEvent, SectorHeat, NewsSignal, AgentRunLog

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_RETRIES = 2
RETRY_DELAY = 30

# ── Agent 1: Event Classifier ──────────────────────────

_EVENT_CLASSIFIER_PROMPT = """你是A股市场事件分析专家。将以下新闻分类为结构化事件。

任务:
1. 合并相同事件的多条报道（不要重复）
2. 为每个事件分类: event_type, impact_level, impact_direction
3. 识别受影响的股票代码（6位数字）和板块名称
4. 写一句话事件摘要

事件类型枚举:
- policy_positive / policy_negative — 政策利好/利空
- earnings_positive / earnings_negative — 业绩利好/利空
- capital_flow — 资金面变化（降准降息/外资流入流出）
- industry_change — 行业变化（技术突破/产能变化）
- market_sentiment — 市场情绪（机构观点/分析师评级）
- breaking_event — 突发事件
- corporate_action — 公司治理（高管变动/回购增持）
- concept_hype — 概念题材炒作

impact_level: "high" | "medium" | "low"
impact_direction: "positive" | "negative" | "neutral"

输出严格 JSON 数组:
[{
  "event_type": "policy_positive",
  "impact_level": "high",
  "impact_direction": "positive",
  "affected_codes": ["600519"],
  "affected_sectors": ["白酒", "消费"],
  "summary": "国务院发布促消费政策...",
  "source_titles": ["标题1", "标题2"]
}]

只输出 JSON，不要任何其他文字。"""

# ── Agent 2: Sector Analyst ────────────────────────────

_SECTOR_ANALYST_PROMPT = """你是A股板块轮动分析专家。基于以下事件评估板块热度。

任务:
1. 评估每个涉及板块的热度 (-100~+100)
2. 判断趋势: rising/falling/flat
3. 在热门板块中推荐龙头股（最多3只，需要给出6位股票代码）
4. 总结驱动事件

sector_type: "concept" 或 "industry"

输出严格 JSON 数组:
[{
  "sector_name": "AI概念",
  "sector_type": "concept",
  "heat_score": 75,
  "news_count": 5,
  "trend": "rising",
  "top_stocks": [{"code": "000977", "name": "浪潮信息", "reason": "AI算力龙头"}],
  "event_summary": "两会政策提及AI发展..."
}]

只输出 JSON，不要任何其他文字。"""

# ── Agent 3: Stock Hunter ──────────────────────────────

_STOCK_HUNTER_PROMPT = """你是A股个股筛选专家。基于事件和板块分析，生成新闻驱动买卖信号。

规则:
- 仅输出置信度 > 60 的信号
- buy: 重大利好事件 + 板块趋势向上 + 个股为板块龙头或直接受益
- sell: 重大利空事件 + 板块降温 + 风险因素明确
- watch: 中等利好但需要确认

signal_source 枚举:
- "news_event" — 直接受单一事件驱动
- "sector_rotation" — 板块轮动趋势驱动
- "sentiment_shift" — 情绪面转变驱动

stock_code 必须是6位数字。

输出严格 JSON 数组:
[{
  "stock_code": "000977",
  "stock_name": "浪潮信息",
  "action": "buy",
  "signal_source": "sector_rotation",
  "confidence": 78,
  "reason": "AI板块持续升温，浪潮信息作为算力龙头直接受益...",
  "sector_name": "AI概念"
}]

只输出 JSON，不要任何其他文字。"""

# ── Agent 4: Decision Synthesizer ──────────────────────

_DECISION_SYNTHESIZER_PROMPT = """你是A股投资决策合成师。审核以下 3 位分析师的输出，进行交叉验证和风险过滤。

你的职责:
1. 交叉验证: 检查信号与事件逻辑是否自洽（事件确实利好/利空该股票？）
2. 风险过滤: 剔除矛盾信号或低质量推荐（如事件利空但给出buy信号）
3. 信号排序: 按置信度和事件重要性排序
4. 调整置信度: 基于你的综合判断微调每个信号的 confidence

输出严格 JSON:
{
  "verified_signals": [
    {
      "stock_code": "000977",
      "stock_name": "浪潮信息",
      "action": "buy",
      "signal_source": "sector_rotation",
      "confidence": 80,
      "reason": "审核后的综合理由...",
      "sector_name": "AI概念"
    }
  ],
  "rejected_count": 2,
  "market_brief": "2-3段总结当前新闻面形势"
}

只输出 JSON。"""


class NewsAgentEngine:
    """Orchestrates the 4-agent news analysis pipeline."""

    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self._ds_config = settings.deepseek
        self._ds_client: Optional[OpenAI] = None

    @property
    def ds_client(self) -> OpenAI:
        if self._ds_client is None:
            self._ds_client = OpenAI(
                api_key=self._ds_config.api_key,
                base_url=self._ds_config.base_url,
            )
        return self._ds_client

    # ── Public API ─────────────────────────────────────

    def run_analysis(self, period_type: str = "manual") -> dict:
        """Run full 4-agent pipeline. Returns summary dict."""
        start_time = time.time()

        # 1. Fetch news since last analysis run (no gaps, no overlaps)
        news_rows = self._fetch_news_since_last_run()
        if not news_rows:
            logger.info("No news to analyze for %s", period_type)
            return {"status": "no_news", "events": 0, "sectors": 0, "signals": 0}

        logger.info("News agent pipeline starting: %d articles, period=%s",
                     len(news_rows), period_type)

        # 2. Agent 1: Event classification
        run_log_1 = self._create_run_log(period_type, "event_classifier", len(news_rows))
        events = self._run_event_classifier(news_rows, run_log_1)
        self._finalize_run_log(run_log_1, f"{len(events)} events extracted", start_time)

        if not events:
            return {"status": "no_events", "events": 0, "sectors": 0, "signals": 0}

        event_records = self._save_events(events, run_log_1.id)

        # 3. Agent 2: Sector analysis
        t2 = time.time()
        run_log_2 = self._create_run_log(period_type, "sector_analyst", len(events))
        sectors = self._run_sector_analyst(events, run_log_2)
        self._finalize_run_log(run_log_2, f"{len(sectors)} sectors scored", t2)
        sector_records = self._save_sectors(sectors, run_log_2.id)

        # 4. Agent 3: Stock signal generation
        t3 = time.time()
        run_log_3 = self._create_run_log(period_type, "stock_hunter", len(events))
        raw_signals = self._run_stock_hunter(events, sectors, run_log_3)
        self._finalize_run_log(run_log_3, f"{len(raw_signals)} raw signals", t3)

        # 5. Agent 4: Decision synthesis
        t4 = time.time()
        run_log_4 = self._create_run_log(period_type, "decision_synthesizer", len(raw_signals))
        final_signals = self._run_decision_synthesizer(events, sectors, raw_signals, run_log_4)
        self._finalize_run_log(run_log_4, f"{len(final_signals)} final signals", t4)

        signal_records = self._save_signals(final_signals, run_log_4.id)

        total_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "News agent pipeline complete: %d events, %d sectors, %d signals (%dms)",
            len(event_records), len(sector_records), len(signal_records), total_ms,
        )

        return {
            "status": "completed",
            "events": len(event_records),
            "sectors": len(sector_records),
            "signals": len(signal_records),
            "duration_ms": total_ms,
        }

    # ── Agent 1: Event Classifier ──────────────────────

    def _run_event_classifier(self, news_rows: list[dict], run_log: AgentRunLog) -> list[dict]:
        """Batch-classify news into structured events."""
        batches = [news_rows[i:i + BATCH_SIZE] for i in range(0, len(news_rows), BATCH_SIZE)]
        all_events = []

        for i, batch in enumerate(batches):
            news_text = self._format_news_for_classifier(batch)
            result = self._call_deepseek(
                _EVENT_CLASSIFIER_PROMPT,
                f"新闻列表 (共{len(batch)}条):\n{news_text}",
            )
            if result and isinstance(result, list):
                all_events.extend(result)
            elif result and isinstance(result, dict):
                # Unwrap if wrapped in a key
                for key in ("events", "data", "items", "result"):
                    if key in result and isinstance(result[key], list):
                        all_events.extend(result[key])
                        break

            if i < len(batches) - 1:
                time.sleep(1)

        unique_events = self._deduplicate_events(all_events)
        logger.info("Event classifier: %d batches → %d raw → %d unique events",
                     len(batches), len(all_events), len(unique_events))
        return unique_events

    # ── Agent 2: Sector Analyst ────────────────────────

    def _run_sector_analyst(self, events: list[dict], run_log: AgentRunLog) -> list[dict]:
        """Analyze sector heat based on extracted events.

        Uses concept board data cached in stock_concepts table (synced from AkShare).
        If cache is empty, tries a live AkShare sync first.
        """
        concept_rows = self.db.execute(text(
            "SELECT concept_name, COUNT(*) as cnt FROM stock_concepts "
            "GROUP BY concept_name ORDER BY cnt DESC LIMIT 100"
        )).fetchall()

        # If DB cache is empty, attempt a live sync from AkShare
        if not concept_rows:
            logger.info("stock_concepts table empty, attempting AkShare sync...")
            try:
                from api.services.concept_sync import sync_concept_boards
                sync_concept_boards(self.db, max_boards=50)
                concept_rows = self.db.execute(text(
                    "SELECT concept_name, COUNT(*) as cnt FROM stock_concepts "
                    "GROUP BY concept_name ORDER BY cnt DESC LIMIT 100"
                )).fetchall()
            except Exception as e:
                logger.warning("Live AkShare sync failed: %s", e)

        concept_list = [f"{r.concept_name}({r.cnt}只)" for r in concept_rows] if concept_rows else []

        events_json = json.dumps(events, ensure_ascii=False, indent=None)
        concepts_text = ", ".join(concept_list) if concept_list else "（无概念板块数据，请基于事件自行判断板块）"

        result = self._call_deepseek(
            _SECTOR_ANALYST_PROMPT,
            f"事件列表:\n{events_json}\n\n可用概念板块:\n{concepts_text}",
        )

        sectors = self._unwrap_list(result)
        for sec in sectors:
            score = sec.get("heat_score", 0)
            sec["heat_score"] = max(-100, min(100, float(score)))

        logger.info("Sector analyst: %d sectors scored", len(sectors))
        return sectors

    # ── Agent 3: Stock Hunter ──────────────────────────

    def _run_stock_hunter(self, events: list[dict], sectors: list[dict], run_log: AgentRunLog) -> list[dict]:
        """Generate stock-level signals from events and sector analysis."""
        watchlist_rows = self.db.execute(text(
            "SELECT stock_code, stock_name FROM watchlist ORDER BY sort_order"
        )).fetchall()
        watchlist = [{"code": r.stock_code, "name": r.stock_name} for r in watchlist_rows] if watchlist_rows else []

        top_sectors = sorted(sectors, key=lambda s: abs(s.get("heat_score", 0)), reverse=True)[:10]

        events_summary = json.dumps(events[:30], ensure_ascii=False)
        sectors_json = json.dumps(top_sectors, ensure_ascii=False)
        watchlist_json = json.dumps(watchlist, ensure_ascii=False) if watchlist else "（无自选股）"

        result = self._call_deepseek(
            _STOCK_HUNTER_PROMPT,
            f"事件摘要:\n{events_summary}\n\n板块热度 TOP10:\n{sectors_json}\n\n用户自选股:\n{watchlist_json}",
        )

        signals = self._unwrap_list(result)
        filtered = [
            s for s in signals
            if s.get("confidence", 0) >= 60
            and len(str(s.get("stock_code", ""))) == 6
        ]
        logger.info("Stock hunter: %d raw → %d filtered signals", len(signals), len(filtered))
        return filtered

    # ── Agent 4: Decision Synthesizer ──────────────────

    def _run_decision_synthesizer(
        self,
        events: list[dict],
        sectors: list[dict],
        raw_signals: list[dict],
        run_log: AgentRunLog,
    ) -> list[dict]:
        """Cross-validate and filter raw signals."""
        if not raw_signals:
            return []

        input_data = {
            "events_summary": [
                {"type": e.get("event_type"), "level": e.get("impact_level"),
                 "direction": e.get("impact_direction"), "summary": e.get("summary"),
                 "sectors": e.get("affected_sectors", [])}
                for e in events[:20]
            ],
            "sector_heat_top10": [
                {"name": s.get("sector_name"), "score": s.get("heat_score"), "trend": s.get("trend")}
                for s in sorted(sectors, key=lambda x: abs(x.get("heat_score", 0)), reverse=True)[:10]
            ],
            "raw_signals": raw_signals,
        }

        result = self._call_deepseek(
            _DECISION_SYNTHESIZER_PROMPT,
            json.dumps(input_data, ensure_ascii=False),
        )

        if result and isinstance(result, dict):
            verified = result.get("verified_signals", [])
            rejected_count = result.get("rejected_count", 0)
            brief = result.get("market_brief", "")
            logger.info("Decision synthesizer: %d verified, %d rejected",
                        len(verified), rejected_count)
            run_log.output_summary = f"{len(verified)} verified, {rejected_count} rejected. {brief[:200]}"
            return verified

        # Fallback: pass through raw signals
        logger.warning("Decision synthesizer failed, passing through raw signals")
        return raw_signals

    # ── DeepSeek API ───────────────────────────────────

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> Optional[dict | list]:
        """Call DeepSeek API with retry. Returns parsed JSON."""
        from api.utils.network import no_proxy

        for attempt in range(MAX_RETRIES + 1):
            try:
                with no_proxy():
                    response = self.ds_client.chat.completions.create(
                        model=self._ds_config.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.3,
                        max_tokens=4000,
                    )
                content = response.choices[0].message.content
                if not content:
                    return None
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error("DeepSeek JSON parse error: %s", e)
                return None
            except Exception as e:
                if "Content Exists Risk" in str(e):
                    logger.warning("DeepSeek content risk, skipping")
                    return None
                logger.warning("DeepSeek call failed (attempt %d): %s", attempt + 1, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        return None

    # ── Helpers ────────────────────────────────────────

    def _fetch_news_since_last_run(self) -> list[dict]:
        """Fetch all news since the last completed analysis run.

        Uses agent_run_log to find the last event_classifier run time.
        If no previous run exists, falls back to 24 hours.
        """
        last_run = self.db.execute(text("""
            SELECT MAX(run_time) as last_time
            FROM agent_run_log
            WHERE agent_name = 'event_classifier'
              AND status = 'completed'
        """)).fetchone()

        if last_run and last_run.last_time:
            cutoff = last_run.last_time
            logger.info("Fetching news since last run: %s", cutoff)
        else:
            cutoff = datetime.now() - timedelta(hours=24)
            logger.info("No previous run found, fetching last 24h news")

        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S") if isinstance(cutoff, datetime) else str(cutoff)

        result = self.db.execute(text("""
            SELECT id, title, source, content, publish_time
            FROM news_archive
            WHERE created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT 500
        """), {"cutoff": cutoff_str})

        return [dict(row._mapping) for row in result]

    def _format_news_for_classifier(self, rows: list[dict]) -> str:
        lines = []
        for i, row in enumerate(rows, 1):
            title = row.get("title", "")
            content = (row.get("content") or "")[:100].replace("\n", " ")
            source = row.get("source", "")
            lines.append(f"{i}. [{source}] {title} — {content}")
        return "\n".join(lines)

    @staticmethod
    def _deduplicate_events(events: list[dict]) -> list[dict]:
        """Deduplicate events by summary similarity."""
        seen: set[str] = set()
        unique = []
        for evt in events:
            summary = evt.get("summary", "")
            key = re.sub(r"[\s\W]+", "", summary).lower()[:50]
            if key and key not in seen:
                seen.add(key)
                unique.append(evt)
        return unique

    @staticmethod
    def _unwrap_list(result) -> list[dict]:
        """Extract list from DeepSeek response (may be wrapped in a dict key)."""
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("events", "sectors", "signals", "items", "data", "result",
                        "verified_signals", "top_sectors"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    def _create_run_log(self, period_type: str, agent_name: str, input_count: int) -> AgentRunLog:
        log = AgentRunLog(
            run_time=datetime.now(),
            period_type=period_type,
            agent_name=agent_name,
            input_news_count=input_count,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def _finalize_run_log(self, log: AgentRunLog, summary: str, start_time: float):
        log.output_summary = summary
        log.duration_ms = int((time.time() - start_time) * 1000)
        self.db.commit()

    def _save_events(self, events: list[dict], run_id: int) -> list[NewsEvent]:
        records = []
        for evt in events:
            record = NewsEvent(
                event_type=evt.get("event_type", "breaking_event"),
                impact_level=evt.get("impact_level", "medium"),
                impact_direction=evt.get("impact_direction", "neutral"),
                affected_codes=evt.get("affected_codes", []),
                affected_sectors=evt.get("affected_sectors", []),
                summary=evt.get("summary", ""),
                source_titles=evt.get("source_titles", []),
                analysis_run_id=run_id,
            )
            self.db.add(record)
            records.append(record)
        self.db.commit()
        for r in records:
            self.db.refresh(r)
        return records

    def _save_sectors(self, sectors: list[dict], run_id: int) -> list[SectorHeat]:
        records = []
        now = datetime.now()
        for sec in sectors:
            record = SectorHeat(
                snapshot_time=now,
                sector_name=sec.get("sector_name", ""),
                sector_type=sec.get("sector_type", "concept"),
                heat_score=sec.get("heat_score", 0),
                news_count=sec.get("news_count", 0),
                trend=sec.get("trend", "flat"),
                top_stocks=sec.get("top_stocks", []),
                event_summary=sec.get("event_summary", ""),
                analysis_run_id=run_id,
            )
            self.db.add(record)
            records.append(record)
        self.db.commit()
        return records

    def _save_signals(self, signals: list[dict], run_id: int) -> list[NewsSignal]:
        records = []
        today = datetime.now().strftime("%Y-%m-%d")
        for sig in signals:
            code = str(sig.get("stock_code", ""))
            source = sig.get("signal_source", "news_event")

            existing = self.db.query(NewsSignal).filter(
                NewsSignal.trade_date == today,
                NewsSignal.stock_code == code,
                NewsSignal.signal_source == source,
            ).first()

            if existing:
                existing.action = sig.get("action", "watch")
                existing.confidence = sig.get("confidence", 0)
                existing.reason = sig.get("reason", "")
                existing.sector_name = sig.get("sector_name", "")
                existing.analysis_run_id = run_id
            else:
                record = NewsSignal(
                    trade_date=today,
                    stock_code=code,
                    stock_name=sig.get("stock_name", ""),
                    action=sig.get("action", "watch"),
                    signal_source=source,
                    confidence=sig.get("confidence", 0),
                    reason=sig.get("reason", ""),
                    related_event_ids=sig.get("related_event_ids", []),
                    sector_name=sig.get("sector_name", ""),
                    analysis_run_id=run_id,
                )
                self.db.add(record)
                records.append(record)
        self.db.commit()
        return records
