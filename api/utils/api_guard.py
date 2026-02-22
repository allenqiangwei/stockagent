"""API circuit breaker — blocks flaky data sources for a cooldown period."""

import json
import time
import logging
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_STATUS_FILE = Path(__file__).parent.parent.parent / "data" / "api_guard_status.json"
DEFAULT_COOLDOWN = 2 * 60 * 60  # 2 hours


class ApiGuard:
    def __init__(self, cooldown_seconds: int = DEFAULT_COOLDOWN):
        self._cooldown = cooldown_seconds
        self._lock = Lock()
        self._status: dict = {}
        self._load()

    def _load(self):
        try:
            if _STATUS_FILE.exists():
                with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                    self._status = json.load(f)
        except Exception:
            self._status = {}

    def _save(self):
        try:
            _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save API guard status: %s", e)

    def record_failure(self, source: str, reason: str = ""):
        with self._lock:
            now = time.time()
            prev = self._status.get(source, {})
            count = prev.get("failure_count", 0) + 1
            self._status[source] = {
                "blocked_until": now + self._cooldown,
                "failure_count": count,
                "last_failure_reason": str(reason),
            }
            self._save()
            logger.warning("[ApiGuard] %s blocked (%dx): %s", source, count, reason)

    def record_success(self, source: str):
        with self._lock:
            if source in self._status:
                del self._status[source]
                self._save()

    def is_blocked(self, source: str) -> bool:
        with self._lock:
            info = self._status.get(source)
            if not info:
                return False
            if time.time() >= info.get("blocked_until", 0):
                del self._status[source]
                self._save()
                return False
            return True


_instance: Optional[ApiGuard] = None


def get_api_guard() -> ApiGuard:
    global _instance
    if _instance is None:
        _instance = ApiGuard()
    return _instance
