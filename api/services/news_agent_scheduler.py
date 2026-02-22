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
                if now.hour > hour or (now.hour == hour and now.minute >= minute):
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
