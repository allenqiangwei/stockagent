# 新闻驱动多智能体决策系统 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建 4-Agent 新闻情报系统，从 news_archive 提取事件、分析板块热度、生成独立新闻驱动交易信号，每日 08:00/18:00 自动运行。

**Architecture:** EventClassifier(DeepSeek) → SectorAnalyst(DeepSeek) → StockHunter(DeepSeek) → DecisionSynthesizer(Claude CLI) pipeline，结果写入 3 张新表（news_events / sector_heat / news_signals），通过独立 API 和前端展示。

**Tech Stack:** FastAPI + SQLAlchemy (SQLite/WAL) + DeepSeek API + Claude CLI + Next.js 16 + shadcn/ui + TanStack Query

---

## Phase 1: 数据基础（概念板块同步 + 新建表）

### Task 1: 创建 4 张新 ORM 模型

**Files:**
- Create: `api/models/news_agent.py`
- Modify: `api/main.py` (import 新模型)

**Step 1: 创建 news_agent.py 模型文件**

```python
"""News agent pipeline ORM models: events, sector heat, news signals, run log."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer, String, Float, Text, DateTime, Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NewsEvent(Base):
    """Structured event extracted from news articles."""
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(30))
    impact_level: Mapped[str] = mapped_column(String(10))       # high|medium|low
    impact_direction: Mapped[str] = mapped_column(String(10))   # positive|negative|neutral
    affected_codes: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    affected_sectors: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    source_titles: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_news_events_type", "event_type", "created_at"),
        Index("idx_news_events_date", "created_at"),
    )


class SectorHeat(Base):
    """Sector heat snapshot from news analysis."""
    __tablename__ = "sector_heat"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime)
    sector_name: Mapped[str] = mapped_column(String(50))
    sector_type: Mapped[str] = mapped_column(String(10))         # concept|industry
    heat_score: Mapped[float] = mapped_column(Float)              # -100 ~ +100
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String(10), default="flat")  # rising|falling|flat
    top_stocks: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    event_summary: Mapped[str] = mapped_column(Text, default="")
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_sector_heat_time", "snapshot_time"),
        Index("idx_sector_heat_name", "sector_name", "snapshot_time"),
    )


class NewsSignal(Base):
    """News-driven trading signal."""
    __tablename__ = "news_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10))
    stock_code: Mapped[str] = mapped_column(String(6))
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    action: Mapped[str] = mapped_column(String(5))                 # buy|sell|watch
    signal_source: Mapped[str] = mapped_column(String(20))         # news_event|sector_rotation|sentiment_shift
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    reason: Mapped[str] = mapped_column(Text)
    related_event_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    sector_name: Mapped[str] = mapped_column(String(50), default="")
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_news_signals_date", "trade_date"),
        Index("idx_news_signals_code", "stock_code", "trade_date"),
        UniqueConstraint("trade_date", "stock_code", "signal_source", name="uq_news_signal"),
    )


class AgentRunLog(Base):
    """Execution log for each agent run."""
    __tablename__ = "agent_run_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_time: Mapped[datetime] = mapped_column(DateTime)
    period_type: Mapped[str] = mapped_column(String(15))           # pre_market|evening
    agent_name: Mapped[str] = mapped_column(String(30))
    input_news_count: Mapped[int] = mapped_column(Integer, default=0)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="completed")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**Step 2: 在 main.py 注册模型**

在 `api/main.py` 的 `lifespan()` 函数中，`Base.metadata.create_all()` 之前添加:
```python
import api.models.news_agent  # noqa: F401 — register news agent tables
```

**Step 3: 验证表创建**

Run: 重启 FastAPI，检查日志无报错，确认 4 张新表已创建。

**Step 4: Commit**

```
feat: add ORM models for news agent pipeline (4 tables)
```

---

### Task 2: 概念板块数据同步

**Files:**
- Modify: `src/data_collector/akshare_collector.py` (添加概念板块同步方法)
- Create: `api/services/concept_sync.py` (同步服务)
- Modify: `api/main.py` (启动时同步概念板块)

**Step 1: 在 akshare_collector.py 添加概念板块采集方法**

复用现有 AkShareCollector 类，添加:
```python
def fetch_concept_board_cons(self, symbol: str) -> pd.DataFrame:
    """获取单个概念板块成分股 — akshare: stock_board_concept_cons_em"""
    import akshare as ak
    return ak.stock_board_concept_cons_em(symbol=symbol)

def fetch_concept_board_list(self) -> pd.DataFrame:
    """获取所有概念板块列表 — akshare: stock_board_concept_name_em"""
    import akshare as ak
    return ak.stock_board_concept_name_em()
```

**Step 2: 创建 concept_sync.py**

```python
"""Sync concept board data from AkShare to stock_concepts table."""

import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from api.models.stock import StockConcept, BoardSyncLog

logger = logging.getLogger(__name__)


def sync_concept_boards(db: Session, max_boards: int = 50) -> int:
    """Sync top concept boards and their constituent stocks.

    Respects daily limit — only syncs once per day.
    Returns number of records upserted.
    """
    # Check if already synced today
    log = db.query(BoardSyncLog).filter(BoardSyncLog.board_type == "concept").first()
    if log and log.last_synced.date() == datetime.now().date():
        logger.info("Concept boards already synced today (%d records)", log.record_count)
        return 0

    import akshare as ak
    from api.utils.network import no_proxy

    total_inserted = 0
    try:
        with no_proxy():
            boards_df = ak.stock_board_concept_name_em()

        if boards_df is None or boards_df.empty:
            logger.warning("No concept boards returned from AkShare")
            return 0

        # Take top N boards by "板块名称"
        board_names = boards_df["板块名称"].tolist()[:max_boards]
        logger.info("Syncing %d concept boards...", len(board_names))

        for board_name in board_names:
            try:
                with no_proxy():
                    cons_df = ak.stock_board_concept_cons_em(symbol=board_name)
                time.sleep(0.3)  # Rate limit

                if cons_df is None or cons_df.empty:
                    continue

                for _, row in cons_df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if not code or len(code) != 6:
                        continue

                    exists = db.query(StockConcept).filter(
                        StockConcept.stock_code == code,
                        StockConcept.concept_name == board_name,
                    ).first()
                    if not exists:
                        db.add(StockConcept(stock_code=code, concept_name=board_name))
                        total_inserted += 1

                # Batch commit every 5 boards
                if total_inserted % 500 == 0:
                    db.commit()

            except Exception as e:
                logger.warning("Failed to sync board '%s': %s", board_name, e)
                continue

        db.commit()

        # Update sync log
        if log:
            log.last_synced = datetime.now()
            log.record_count = total_inserted
        else:
            db.add(BoardSyncLog(
                board_type="concept",
                last_synced=datetime.now(),
                record_count=total_inserted,
            ))
        db.commit()

        logger.info("Concept board sync complete: %d new records from %d boards",
                     total_inserted, len(board_names))

    except Exception as e:
        logger.error("Concept board sync failed: %s", e)
        db.rollback()

    return total_inserted
```

**Step 3: 在 main.py 启动时调用同步**

在 `lifespan()` 的 `_sync_index_data()` 之后添加:
```python
# Sync concept boards (daily, idempotent)
from api.services.concept_sync import sync_concept_boards
try:
    with Session(engine) as db:
        sync_concept_boards(db, max_boards=50)
except Exception as e:
    logger.warning("Concept board sync failed (non-fatal): %s", e)
```

**Step 4: 验证**

重启 FastAPI，检查日志中有 "Concept board sync complete" 消息。用 SQLite 查询确认 `stock_concepts` 表有数据。

**Step 5: Commit**

```
feat: sync concept board data from AkShare (top 50 boards)
```

---

## Phase 2: Agent 1-3（DeepSeek 分析层）

### Task 3: Agent 1 — 事件分类师 (EventClassifier)

**Files:**
- Create: `api/services/news_agent_engine.py`

**Step 1: 创建 news_agent_engine.py 骨架 + Agent 1**

```python
"""News agent pipeline — orchestrates 4-agent news analysis.

Pipeline: EventClassifier → SectorAnalyst → StockHunter → DecisionSynthesizer
"""

import json
import logging
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

# ── Event type taxonomy ─────────────────────────────
EVENT_TYPES = [
    "policy_positive", "policy_negative",
    "earnings_positive", "earnings_negative",
    "capital_flow", "industry_change",
    "market_sentiment", "breaking_event",
    "corporate_action", "concept_hype",
]

# ── Agent 1: Event Classifier ──────────────────────

_EVENT_CLASSIFIER_PROMPT = """你是A股市场事件分析专家。将以下新闻分类为结构化事件。

任务:
1. 合并相同事件的多条报道（不要重复）
2. 为每个事件分类: event_type, impact_level, impact_direction
3. 识别受影响的股票代码（6位数字）和板块名称
4. 写一句话事件摘要

事件类型枚举:
- policy_positive / policy_negative — 政策利好/利空
- earnings_positive / earnings_negative — 业绩利好/利空
- capital_flow — 资金面变化
- industry_change — 行业变化
- market_sentiment — 市场情绪
- breaking_event — 突发事件
- corporate_action — 公司治理
- concept_hype — 概念题材

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

    # ── Public API ─────────────────────────────────

    def run_analysis(self, period_type: str = "manual") -> dict:
        """Run full 4-agent pipeline.

        Returns summary dict with counts and status.
        """
        start_time = time.time()

        # Determine time window
        if period_type == "pre_market":
            hours_back = 16.5
        elif period_type == "evening":
            hours_back = 10.0
        else:
            hours_back = 24.0

        # 1. Fetch unanalyzed news
        news_rows = self._fetch_recent_news(hours_back)
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

        # Save events to DB
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

        # 5. Agent 4: Decision synthesis (Claude CLI)
        t4 = time.time()
        run_log_4 = self._create_run_log(period_type, "decision_synthesizer", len(raw_signals))
        final_signals = self._run_decision_synthesizer(events, sectors, raw_signals, run_log_4)
        self._finalize_run_log(run_log_4, f"{len(final_signals)} final signals", t4)

        # Save final signals
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

    # ── Agent 1: Event Classifier ──────────────────

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
            elif result and isinstance(result, dict) and "events" in result:
                all_events.extend(result["events"])

            if i < len(batches) - 1:
                time.sleep(1)

        # Deduplicate events by summary similarity
        unique_events = self._deduplicate_events(all_events)
        logger.info("Event classifier: %d batches → %d raw → %d unique events",
                     len(batches), len(all_events), len(unique_events))
        return unique_events

    # ── Internal helpers ───────────────────────────

    def _fetch_recent_news(self, hours_back: float) -> list[dict]:
        """Fetch recent news from news_archive."""
        cutoff = datetime.now() - timedelta(hours=hours_back)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

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

    def _deduplicate_events(self, events: list[dict]) -> list[dict]:
        """Deduplicate events by summary similarity."""
        import re
        seen = set()
        unique = []
        for evt in events:
            summary = evt.get("summary", "")
            key = re.sub(r"[\s\W]+", "", summary).lower()[:50]
            if key and key not in seen:
                seen.add(key)
                unique.append(evt)
        return unique

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
                parsed = json.loads(content)
                # DeepSeek may wrap array in {"events": [...]} etc.
                if isinstance(parsed, dict):
                    for key in ("events", "sectors", "signals", "items", "data", "result"):
                        if key in parsed and isinstance(parsed[key], list):
                            return parsed[key]
                return parsed
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
            code = sig.get("stock_code", "")
            source = sig.get("signal_source", "news_event")
            # Upsert: skip if duplicate (same date+code+source)
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
```

**Step 2: 验证 — 模块可导入**

```bash
cd /Users/allenqiang/stockagent && venv/bin/python3 -c "from api.services.news_agent_engine import NewsAgentEngine; print('OK')"
```

**Step 3: Commit**

```
feat: add NewsAgentEngine with Agent 1 (event classifier)
```

---

### Task 4: Agent 2 — 板块分析师 (SectorAnalyst)

**Files:**
- Modify: `api/services/news_agent_engine.py`

**Step 1: 添加板块分析师 prompt + 方法**

在 `NewsAgentEngine` 类中，在 `_run_event_classifier` 方法之后添加:

```python
# ── Agent 2 prompt ──
_SECTOR_ANALYST_PROMPT = """你是A股板块轮动分析专家。基于以下事件评估板块热度。

任务:
1. 评估每个涉及板块的热度 (-100~+100)
2. 判断趋势: rising/falling/flat
3. 在热门板块中推荐龙头股 (最多3只)
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
```

```python
def _run_sector_analyst(self, events: list[dict], run_log: AgentRunLog) -> list[dict]:
    """Analyze sector heat based on extracted events."""
    # Gather available concept names from DB
    concept_rows = self.db.execute(text(
        "SELECT DISTINCT concept_name, COUNT(*) as cnt FROM stock_concepts GROUP BY concept_name ORDER BY cnt DESC LIMIT 100"
    )).fetchall()
    concept_list = [f"{r.concept_name}({r.cnt}只)" for r in concept_rows] if concept_rows else []

    events_json = json.dumps(events, ensure_ascii=False, indent=None)
    concepts_text = ", ".join(concept_list) if concept_list else "（无概念板块数据）"

    result = self._call_deepseek(
        _SECTOR_ANALYST_PROMPT,
        f"事件列表:\n{events_json}\n\n可用概念板块:\n{concepts_text}",
    )

    if result and isinstance(result, list):
        # Validate and cap heat_score
        for sec in result:
            score = sec.get("heat_score", 0)
            sec["heat_score"] = max(-100, min(100, float(score)))
        logger.info("Sector analyst: %d sectors scored", len(result))
        return result

    logger.warning("Sector analyst returned no results")
    return []
```

**Step 2: Commit**

```
feat: add Agent 2 — sector analyst to news pipeline
```

---

### Task 5: Agent 3 — 个股猎手 (StockHunter)

**Files:**
- Modify: `api/services/news_agent_engine.py`

**Step 1: 添加个股猎手 prompt + 方法**

```python
# ── Agent 3 prompt ──
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
```

```python
def _run_stock_hunter(self, events: list[dict], sectors: list[dict], run_log: AgentRunLog) -> list[dict]:
    """Generate stock-level signals from events and sector analysis."""
    # Get watchlist for priority
    watchlist_rows = self.db.execute(text(
        "SELECT stock_code, stock_name FROM watchlist ORDER BY sort_order"
    )).fetchall()
    watchlist = [{"code": r.stock_code, "name": r.stock_name} for r in watchlist_rows] if watchlist_rows else []

    # Top 10 sectors
    top_sectors = sorted(sectors, key=lambda s: abs(s.get("heat_score", 0)), reverse=True)[:10]

    events_summary = json.dumps(events[:30], ensure_ascii=False)  # Cap for token limit
    sectors_json = json.dumps(top_sectors, ensure_ascii=False)
    watchlist_json = json.dumps(watchlist, ensure_ascii=False) if watchlist else "（无自选股）"

    result = self._call_deepseek(
        _STOCK_HUNTER_PROMPT,
        f"事件摘要:\n{events_summary}\n\n板块热度 TOP10:\n{sectors_json}\n\n用户自选股:\n{watchlist_json}",
    )

    if result and isinstance(result, list):
        # Filter: only confidence > 60, valid stock codes
        filtered = [
            s for s in result
            if s.get("confidence", 0) >= 60
            and len(str(s.get("stock_code", ""))) == 6
        ]
        logger.info("Stock hunter: %d raw → %d filtered signals", len(result), len(filtered))
        return filtered

    logger.warning("Stock hunter returned no results")
    return []
```

**Step 2: Commit**

```
feat: add Agent 3 — stock hunter to news pipeline
```

---

### Task 6: Agent 4 — 决策合成师 (DecisionSynthesizer)

**Files:**
- Modify: `api/services/news_agent_engine.py`

**说明:** Agent 4 使用 DeepSeek 而非 Claude CLI（简化实现，避免 subprocess 依赖）。后续可升级为 Claude。

**Step 1: 添加决策合成师 prompt + 方法**

```python
# ── Agent 4 prompt ──
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
  "rejected_signals": [
    {"stock_code": "...", "reason": "剔除原因"}
  ],
  "market_brief": "2-3段总结当前新闻面形势"
}

只输出 JSON。"""
```

```python
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
        rejected = result.get("rejected_signals", [])
        brief = result.get("market_brief", "")
        logger.info(
            "Decision synthesizer: %d verified, %d rejected",
            len(verified), len(rejected),
        )
        run_log.output_summary = f"{len(verified)} verified, {len(rejected)} rejected. {brief[:100]}"
        return verified

    # Fallback: pass through raw signals if synthesizer fails
    logger.warning("Decision synthesizer failed, passing through raw signals")
    return raw_signals
```

**Step 2: Commit**

```
feat: add Agent 4 — decision synthesizer to news pipeline
```

---

## Phase 3: 调度器 + API 端点

### Task 7: 新闻智能体调度器

**Files:**
- Create: `api/services/news_agent_scheduler.py`
- Modify: `api/main.py` (启动调度器)

**Step 1: 创建调度器**

复用 `news_sentiment_scheduler.py` 的 daemon thread + 30s polling 模式:

```python
"""News agent scheduler — runs pipeline at 08:00 and 18:00 daily."""

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from api.models.base import SessionLocal
from api.services.news_agent_engine import NewsAgentEngine

logger = logging.getLogger(__name__)


class NewsAgentScheduler:
    """Background scheduler for news agent pipeline."""

    SCHEDULE = [
        (8, 0, "pre_market"),
        (18, 0, "evening"),
    ]

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._today_completed: set[str] = set()
        self._is_running_pipeline = False

    @property
    def is_busy(self) -> bool:
        return self._is_running_pipeline

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("News agent scheduler started (08:00 pre_market, 18:00 evening)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "is_busy": self._is_running_pipeline,
            "today_completed": list(self._today_completed),
        }

    def _run_loop(self):
        while self._running:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            if self._today_completed and not any(
                c.startswith(today_str) for c in self._today_completed
            ):
                self._today_completed.clear()

            for hour, minute, period_type in self.SCHEDULE:
                key = f"{today_str}_{period_type}"
                if key in self._today_completed:
                    continue
                if (now.hour > hour or (now.hour == hour and now.minute >= minute)):
                    if not self._is_running_pipeline:
                        self._do_pipeline(period_type, key)

            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _do_pipeline(self, period_type: str, key: str):
        self._is_running_pipeline = True
        try:
            db = SessionLocal()
            try:
                engine = NewsAgentEngine(db)
                result = engine.run_analysis(period_type)
                logger.info("News agent %s done: %s", period_type, result)
                self._today_completed.add(key)
            finally:
                db.close()
        except Exception as e:
            logger.error("News agent %s failed: %s", period_type, e)
            self._today_completed.add(key)
        finally:
            self._is_running_pipeline = False


# ── Singleton ──

_scheduler: Optional[NewsAgentScheduler] = None


def get_news_agent_scheduler() -> NewsAgentScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = NewsAgentScheduler()
    return _scheduler


def start_news_agent_scheduler() -> NewsAgentScheduler:
    svc = get_news_agent_scheduler()
    if not svc._running:
        svc.start()
    return svc


def stop_news_agent_scheduler():
    global _scheduler
    if _scheduler and _scheduler._running:
        _scheduler.stop()
```

**Step 2: 在 main.py 注册调度器**

在 `lifespan()` 中，`start_news_sentiment_scheduler()` 之后添加:

```python
from api.services.news_agent_scheduler import start_news_agent_scheduler, stop_news_agent_scheduler
start_news_agent_scheduler()
logger.info("News agent scheduler started (08:00 pre_market, 18:00 evening)")
```

在 yield 之后的 shutdown 中添加:
```python
stop_news_agent_scheduler()
```

**Step 3: Commit**

```
feat: add news agent scheduler (08:00 + 18:00 daily)
```

---

### Task 8: API 端点

**Files:**
- Create: `api/routers/news_signals.py`
- Modify: `api/main.py` (注册 router)

**Step 1: 创建 news_signals router**

```python
"""News signals router — news-driven signals, events, sector heat."""

import logging
import threading
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.models.base import get_db, SessionLocal
from api.models.news_agent import NewsEvent, SectorHeat, NewsSignal, AgentRunLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news-signals", tags=["news-signals"])

# In-memory job tracking for manual analysis
_analysis_jobs: dict[str, dict] = {}


@router.get("/today")
def get_today_signals(
    date_str: str = Query("", alias="date"),
    db: Session = Depends(get_db),
):
    """Get news-driven signals for a date (default today)."""
    target = date_str or date.today().isoformat()
    rows = (
        db.query(NewsSignal)
        .filter(NewsSignal.trade_date == target)
        .order_by(NewsSignal.confidence.desc())
        .all()
    )
    return {
        "date": target,
        "count": len(rows),
        "signals": [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "action": r.action,
                "signal_source": r.signal_source,
                "confidence": r.confidence,
                "reason": r.reason,
                "sector_name": r.sector_name,
                "created_at": r.created_at.strftime("%H:%M") if r.created_at else "",
            }
            for r in rows
        ],
    }


@router.get("/history")
def get_signal_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    action: str = Query(""),
    db: Session = Depends(get_db),
):
    """Paginated news signal history."""
    q = db.query(NewsSignal).order_by(NewsSignal.created_at.desc())
    if action:
        q = q.filter(NewsSignal.action == action)
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return {
        "page": page,
        "size": size,
        "total": total,
        "items": [
            {
                "id": r.id,
                "trade_date": r.trade_date,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "action": r.action,
                "signal_source": r.signal_source,
                "confidence": r.confidence,
                "reason": r.reason,
                "sector_name": r.sector_name,
            }
            for r in rows
        ],
    }


@router.get("/sectors")
def get_sector_heat(
    date_str: str = Query("", alias="date"),
    db: Session = Depends(get_db),
):
    """Get latest sector heat rankings."""
    if date_str:
        cutoff = datetime.strptime(date_str, "%Y-%m-%d")
        end = cutoff + timedelta(days=1)
    else:
        end = datetime.now()
        cutoff = end - timedelta(hours=24)

    rows = (
        db.query(SectorHeat)
        .filter(SectorHeat.snapshot_time >= cutoff, SectorHeat.snapshot_time < end)
        .order_by(SectorHeat.heat_score.desc())
        .all()
    )
    return {
        "count": len(rows),
        "sectors": [
            {
                "id": r.id,
                "sector_name": r.sector_name,
                "sector_type": r.sector_type,
                "heat_score": r.heat_score,
                "trend": r.trend,
                "news_count": r.news_count,
                "top_stocks": r.top_stocks or [],
                "event_summary": r.event_summary,
                "snapshot_time": r.snapshot_time.strftime("%Y-%m-%d %H:%M") if r.snapshot_time else "",
            }
            for r in rows
        ],
    }


@router.get("/events")
def get_events(
    date_str: str = Query("", alias="date"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get recent news events."""
    q = db.query(NewsEvent).order_by(NewsEvent.created_at.desc())
    if date_str:
        q = q.filter(NewsEvent.created_at >= date_str)
    rows = q.limit(limit).all()
    return {
        "count": len(rows),
        "events": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "impact_level": r.impact_level,
                "impact_direction": r.impact_direction,
                "affected_codes": r.affected_codes or [],
                "affected_sectors": r.affected_sectors or [],
                "summary": r.summary,
                "source_titles": r.source_titles or [],
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            }
            for r in rows
        ],
    }


@router.post("/analyze")
def trigger_analysis():
    """Manually trigger news agent pipeline (fire-and-forget)."""
    from api.services.news_agent_scheduler import get_news_agent_scheduler

    scheduler = get_news_agent_scheduler()
    if scheduler.is_busy:
        raise HTTPException(409, "Analysis already in progress")

    job_id = str(uuid.uuid4())[:8]
    _analysis_jobs[job_id] = {"status": "processing", "result": None, "error": None}

    def _run():
        try:
            db = SessionLocal()
            try:
                engine_mod = __import__("api.services.news_agent_engine", fromlist=["NewsAgentEngine"])
                engine = engine_mod.NewsAgentEngine(db)
                result = engine.run_analysis("manual")
                _analysis_jobs[job_id] = {"status": "completed", "result": result, "error": None}
            finally:
                db.close()
        except Exception as e:
            logger.error("Manual analysis failed: %s", e)
            _analysis_jobs[job_id] = {"status": "error", "result": None, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "processing"}


@router.get("/analyze/poll")
def poll_analysis(job_id: str = Query(...)):
    """Poll analysis progress."""
    job = _analysis_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/runs")
def get_run_logs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get recent agent run logs."""
    rows = (
        db.query(AgentRunLog)
        .order_by(AgentRunLog.run_time.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "runs": [
            {
                "id": r.id,
                "run_time": r.run_time.strftime("%Y-%m-%d %H:%M") if r.run_time else "",
                "period_type": r.period_type,
                "agent_name": r.agent_name,
                "input_news_count": r.input_news_count,
                "output_summary": r.output_summary,
                "duration_ms": r.duration_ms,
                "status": r.status,
            }
            for r in rows
        ],
    }
```

**Step 2: 在 main.py 注册 router**

```python
from api.routers import news_signals
app.include_router(news_signals.router)
```

**Step 3: 验证**

重启 FastAPI，测试:
- `GET /api/news-signals/today` → 返回空列表
- `POST /api/news-signals/analyze` → 返回 job_id
- `GET /api/news-signals/analyze/poll?job_id=xxx` → 轮询状态

**Step 4: Commit**

```
feat: add news-signals API endpoints (7 routes)
```

---

## Phase 4: 前端展示

### Task 9: 前端类型 + API 方法

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/hooks/use-queries.ts`

**Step 1: 添加 TypeScript 类型**

在 `web/src/types/index.ts` 末尾添加:

```typescript
// ── News Signals ─────────────────────────────────
export interface NewsSignalItem {
  id: number;
  stock_code: string;
  stock_name: string;
  action: "buy" | "sell" | "watch";
  signal_source: string;
  confidence: number;
  reason: string;
  sector_name: string;
  created_at: string;
  trade_date?: string;
}

export interface SectorHeatItem {
  id: number;
  sector_name: string;
  sector_type: string;
  heat_score: number;
  trend: "rising" | "falling" | "flat";
  news_count: number;
  top_stocks: { code: string; name: string; reason: string }[];
  event_summary: string;
  snapshot_time: string;
}

export interface NewsEventItem {
  id: number;
  event_type: string;
  impact_level: string;
  impact_direction: string;
  affected_codes: string[];
  affected_sectors: string[];
  summary: string;
  source_titles: string[];
  created_at: string;
}
```

**Step 2: 添加 API 方法**

在 `web/src/lib/api.ts` 添加 `newsSignals` namespace:

```typescript
export const newsSignals = {
  today: (date?: string) =>
    request<{ date: string; count: number; signals: NewsSignalItem[] }>(
      `/news-signals/today${date ? `?date=${date}` : ""}`
    ),
  history: (page = 1, size = 20, action = "") =>
    request<{ page: number; total: number; items: NewsSignalItem[] }>(
      `/news-signals/history?page=${page}&size=${size}${action ? `&action=${action}` : ""}`
    ),
  sectors: (date?: string) =>
    request<{ count: number; sectors: SectorHeatItem[] }>(
      `/news-signals/sectors${date ? `?date=${date}` : ""}`
    ),
  events: (date?: string) =>
    request<{ count: number; events: NewsEventItem[] }>(
      `/news-signals/events${date ? `?date=${date}` : ""}`
    ),
  triggerAnalysis: () =>
    post<{ job_id: string; status: string }>("/news-signals/analyze", {}),
  pollAnalysis: (jobId: string) =>
    request<{ status: string; result: any; error: string | null }>(
      `/news-signals/analyze/poll?job_id=${jobId}`
    ),
};
```

**Step 3: 添加 React Query hooks**

在 `web/src/hooks/use-queries.ts` 添加:

```typescript
export function useNewsSignalsToday(date?: string) {
  return useQuery({
    queryKey: ["news-signals-today", date],
    queryFn: () => newsSignals.today(date),
  });
}

export function useSectorHeat(date?: string) {
  return useQuery({
    queryKey: ["sector-heat", date],
    queryFn: () => newsSignals.sectors(date),
  });
}

export function useNewsEvents(date?: string) {
  return useQuery({
    queryKey: ["news-events", date],
    queryFn: () => newsSignals.events(date),
  });
}

export function useTriggerNewsAnalysis() {
  return useMutation({
    mutationFn: () => newsSignals.triggerAnalysis(),
  });
}

export function useNewsAnalysisPoll(jobId: string | null) {
  return useQuery({
    queryKey: ["news-analysis-poll", jobId],
    queryFn: () => newsSignals.pollAnalysis(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "error") return false;
      return 3000;
    },
  });
}
```

**Step 4: Commit**

```
feat: add news signals frontend types, API, and hooks
```

---

### Task 10: 信号页面 — 新增 "新闻驱动" Tab

**Files:**
- Modify: `web/src/app/signals/page.tsx`

**Step 1: 在信号页面添加"新闻驱动"标签页**

在现有 Tabs 组件中新增 `TabsTrigger` + `TabsContent`:

- Tab label: "新闻驱动"
- 内容: 使用 `useNewsSignalsToday` hook
- 信号卡片复用 `SignalCard` 或新建简化版
- 每张卡片: 股票名+代码, action badge, 置信度 bar, 原因文本, 来源板块 badge
- 底部: "手动触发分析" 按钮（fire-and-forget + polling）

**具体修改:**

1. import 新 hooks:
```typescript
import { useNewsSignalsToday, useTriggerNewsAnalysis, useNewsAnalysisPoll } from "@/hooks/use-queries";
```

2. 在组件中添加 state:
```typescript
const [newsAnalysisJobId, setNewsAnalysisJobId] = useState<string | null>(null);
const newsSignals = useNewsSignalsToday();
const triggerNews = useTriggerNewsAnalysis();
const newsPoll = useNewsAnalysisPoll(newsAnalysisJobId);
```

3. 在 TabsList 中添加:
```tsx
<TabsTrigger value="news">新闻驱动</TabsTrigger>
```

4. 添加 TabsContent:
```tsx
<TabsContent value="news">
  {/* 触发按钮 */}
  <div className="flex items-center gap-2 mb-4">
    <Button
      size="sm"
      onClick={() => {
        triggerNews.mutate(undefined, {
          onSuccess: (data) => setNewsAnalysisJobId(data.job_id),
        });
      }}
      disabled={triggerNews.isPending || newsPoll?.data?.status === "processing"}
    >
      {newsPoll?.data?.status === "processing" ? (
        <><Loader2 className="h-4 w-4 animate-spin mr-1" />分析中...</>
      ) : (
        <><Zap className="h-4 w-4 mr-1" />触发新闻分析</>
      )}
    </Button>
  </div>

  {/* 信号列表 */}
  <div className="grid gap-3">
    {newsSignals.data?.signals?.map((sig) => (
      <Card key={sig.id} className="bg-zinc-900 border-zinc-800">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-bold">{sig.stock_name}</span>
              <span className="text-zinc-500 ml-2">{sig.stock_code}</span>
            </div>
            <div className="flex items-center gap-2">
              {actionBadge(sig.action)}
              <Badge variant="outline">{sig.confidence}%</Badge>
            </div>
          </div>
          <p className="text-sm text-zinc-400 mt-2">{sig.reason}</p>
          <div className="flex gap-2 mt-2">
            <Badge variant="secondary" className="text-xs">{sig.sector_name}</Badge>
            <Badge variant="outline" className="text-xs">{sig.signal_source}</Badge>
          </div>
        </CardContent>
      </Card>
    ))}
    {newsSignals.data?.signals?.length === 0 && (
      <p className="text-zinc-500 text-center py-8">暂无新闻驱动信号，点击上方按钮触发分析</p>
    )}
  </div>
</TabsContent>
```

**Step 2: Commit**

```
feat: add news-driven signals tab to signals page
```

---

### Task 11: 板块热度页面

**Files:**
- Create: `web/src/app/sectors/page.tsx`

**Step 1: 创建板块热度页面**

```tsx
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useSectorHeat, useNewsEvents } from "@/hooks/use-queries";
import { TrendingUp, TrendingDown, Minus, Flame, BarChart3 } from "lucide-react";

const TREND_ICON = {
  rising: <TrendingUp className="h-4 w-4 text-emerald-500" />,
  falling: <TrendingDown className="h-4 w-4 text-red-500" />,
  flat: <Minus className="h-4 w-4 text-zinc-500" />,
};

export default function SectorsPage() {
  const sectors = useSectorHeat();
  const events = useNewsEvents();

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-2">
        <Flame className="h-6 w-6 text-orange-500" />
        <h1 className="text-2xl font-bold">板块热度</h1>
      </div>

      {/* Sector heat bars */}
      <div className="grid gap-3">
        {sectors.data?.sectors?.map((sec) => (
          <Card key={sec.id} className="bg-zinc-900 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {TREND_ICON[sec.trend] || TREND_ICON.flat}
                  <span className="font-bold">{sec.sector_name}</span>
                  <Badge variant="outline" className="text-xs">{sec.sector_type}</Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-lg font-bold ${
                    sec.heat_score > 0 ? "text-emerald-500" : sec.heat_score < 0 ? "text-red-500" : "text-zinc-400"
                  }`}>
                    {sec.heat_score > 0 ? "+" : ""}{sec.heat_score}
                  </span>
                </div>
              </div>

              {/* Heat bar */}
              <div className="h-2 bg-zinc-800 rounded-full overflow-hidden mb-2">
                <div
                  className={`h-full rounded-full ${
                    sec.heat_score > 0 ? "bg-emerald-600" : "bg-red-600"
                  }`}
                  style={{ width: `${Math.abs(sec.heat_score)}%`, marginLeft: sec.heat_score < 0 ? "auto" : 0 }}
                />
              </div>

              <p className="text-sm text-zinc-400">{sec.event_summary}</p>

              {/* Top stocks */}
              {sec.top_stocks?.length > 0 && (
                <div className="flex gap-2 mt-2 flex-wrap">
                  {sec.top_stocks.map((s) => (
                    <Badge key={s.code} variant="secondary" className="text-xs">
                      {s.name} ({s.code})
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent events */}
      <div>
        <h2 className="text-xl font-bold mb-3 flex items-center gap-2">
          <BarChart3 className="h-5 w-5" />
          最近事件
        </h2>
        <div className="grid gap-2">
          {events.data?.events?.map((evt) => (
            <Card key={evt.id} className="bg-zinc-900 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Badge
                    className={`text-xs ${
                      evt.impact_direction === "positive"
                        ? "bg-emerald-900 text-emerald-300"
                        : evt.impact_direction === "negative"
                        ? "bg-red-900 text-red-300"
                        : "bg-zinc-800 text-zinc-400"
                    }`}
                  >
                    {evt.event_type}
                  </Badge>
                  <Badge variant="outline" className="text-xs">{evt.impact_level}</Badge>
                  <span className="text-xs text-zinc-500 ml-auto">{evt.created_at}</span>
                </div>
                <p className="text-sm">{evt.summary}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: 在导航中添加 "板块" 链接**

在主导航组件中添加 `/sectors` 路由。

**Step 3: Commit**

```
feat: add sectors page with heat rankings and events
```

---

## Phase 5: 集成测试 + 收尾

### Task 12: 端到端测试

**Step 1: 重启两个服务**

```bash
# FastAPI
cd /Users/allenqiang/stockagent && venv/bin/python3 -m uvicorn api.main:app --reload --port 8050

# Next.js
cd /Users/allenqiang/stockagent/web && npm run dev -- --port 3050 --hostname 0.0.0.0
```

**Step 2: 测试 API**

```bash
# 概念板块数据
curl http://localhost:8050/api/news-signals/sectors

# 手动触发分析
curl -X POST http://localhost:8050/api/news-signals/analyze

# 轮询
curl http://localhost:8050/api/news-signals/analyze/poll?job_id=xxx

# 查看结果
curl http://localhost:8050/api/news-signals/today
curl http://localhost:8050/api/news-signals/events
```

**Step 3: 测试前端**

1. 访问 http://192.168.7.125:3050/signals → 确认 "新闻驱动" Tab 存在
2. 点击 "触发新闻分析" → 确认按钮变为 loading
3. 等待完成 → 确认信号列表展示
4. 访问 http://192.168.7.125:3050/sectors → 确认板块热度页面

**Step 4: Final commit**

```
feat: news agent multi-agent system — complete pipeline
```

---

## 关键文件总览

| 文件 | 操作 | 说明 |
|------|------|------|
| `api/models/news_agent.py` | 新建 | 4 张表 ORM 模型 |
| `api/services/concept_sync.py` | 新建 | 概念板块数据同步 |
| `api/services/news_agent_engine.py` | 新建 | 4-Agent Pipeline 核心 |
| `api/services/news_agent_scheduler.py` | 新建 | 08:00/18:00 调度 |
| `api/routers/news_signals.py` | 新建 | 7 个 API 端点 |
| `api/main.py` | 修改 | 注册模型+调度器+路由 |
| `web/src/types/index.ts` | 修改 | 新类型定义 |
| `web/src/lib/api.ts` | 修改 | 新 API 方法 |
| `web/src/hooks/use-queries.ts` | 修改 | 新 hooks |
| `web/src/app/signals/page.tsx` | 修改 | 新增 "新闻驱动" Tab |
| `web/src/app/sectors/page.tsx` | 新建 | 板块热度页面 |
