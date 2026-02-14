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
