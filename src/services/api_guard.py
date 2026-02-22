"""API 熔断保护服务

当数据源接口（如东方财富）访问失败时，自动熔断该接口一段时间，
避免反复请求导致持续屏蔽。状态持久化到文件，重启不丢失。
"""

import json
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 状态持久化文件
_STATUS_FILE = Path(__file__).parent.parent.parent / "data" / "api_guard_status.json"

# 默认冷却时间（秒）
DEFAULT_COOLDOWN = 2 * 60 * 60  # 2小时


class ApiGuard:
    """API 熔断保护

    记录各数据源的访问状态，失败时自动熔断指定时间。
    线程安全，支持多数据源独立管理。
    """

    def __init__(self, cooldown_seconds: int = DEFAULT_COOLDOWN):
        self._cooldown = cooldown_seconds
        self._lock = Lock()
        self._status: dict = {}  # source -> {blocked_until, failure_count, last_failure_time, last_failure_reason}
        self._load()

    def _load(self):
        """从文件加载持久化状态"""
        try:
            if _STATUS_FILE.exists():
                with open(_STATUS_FILE, 'r', encoding='utf-8') as f:
                    self._status = json.load(f)
                logger.info(f"API 熔断状态已加载: {list(self._status.keys())}")
        except Exception as e:
            logger.error(f"加载 API 熔断状态失败: {e}")
            self._status = {}

    def _save(self):
        """持久化状态到文件"""
        try:
            _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 API 熔断状态失败: {e}")

    def record_failure(self, source: str, reason: str = ""):
        """记录访问失败，触发熔断

        Args:
            source: 数据源名称（如 "eastmoney"）
            reason: 失败原因
        """
        with self._lock:
            now = time.time()
            blocked_until = now + self._cooldown

            prev = self._status.get(source, {})
            failure_count = prev.get("failure_count", 0) + 1

            self._status[source] = {
                "blocked_until": blocked_until,
                "failure_count": failure_count,
                "last_failure_time": now,
                "last_failure_reason": str(reason),
            }
            self._save()

            remaining_min = self._cooldown // 60
            logger.warning(
                f"[API熔断] {source} 访问失败（第{failure_count}次），"
                f"熔断 {remaining_min} 分钟，原因: {reason}"
            )

    def record_success(self, source: str):
        """记录访问成功，清除熔断状态

        Args:
            source: 数据源名称
        """
        with self._lock:
            if source in self._status:
                del self._status[source]
                self._save()
                logger.info(f"[API熔断] {source} 访问恢复正常，熔断解除")

    def is_blocked(self, source: str) -> bool:
        """检查数据源是否被熔断

        Args:
            source: 数据源名称

        Returns:
            True 表示被熔断，应跳过该数据源
        """
        with self._lock:
            info = self._status.get(source)
            if not info:
                return False

            blocked_until = info.get("blocked_until", 0)
            if time.time() >= blocked_until:
                # 冷却期已过，自动解除
                del self._status[source]
                self._save()
                logger.info(f"[API熔断] {source} 冷却期结束，自动解除熔断")
                return False

            return True

    def get_status(self, source: str) -> dict:
        """获取数据源的熔断状态

        Args:
            source: 数据源名称

        Returns:
            状态字典，包含 blocked, remaining_seconds, failure_count 等
        """
        with self._lock:
            info = self._status.get(source)
            if not info:
                return {"blocked": False}

            blocked_until = info.get("blocked_until", 0)
            now = time.time()

            if now >= blocked_until:
                return {"blocked": False}

            return {
                "blocked": True,
                "remaining_seconds": int(blocked_until - now),
                "failure_count": info.get("failure_count", 0),
                "last_failure_reason": info.get("last_failure_reason", ""),
                "blocked_until": blocked_until,
            }

    def get_all_status(self) -> dict:
        """获取所有数据源的熔断状态"""
        sources = list(self._status.keys())
        return {s: self.get_status(s) for s in sources}


# 全局单例
_api_guard: Optional[ApiGuard] = None


def get_api_guard() -> ApiGuard:
    """获取全局 API 熔断保护实例"""
    global _api_guard
    if _api_guard is None:
        _api_guard = ApiGuard()
    return _api_guard
