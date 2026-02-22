"""信号定时刷新服务

后台 daemon 线程，每天在指定时间自动运行信号全量分析。
支持手动立即刷新，防止并发刷新。
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SignalScheduler:
    """信号定时刷新服务

    后台 daemon 线程，每天在指定时间自动运行信号分析。

    Usage:
        scheduler = SignalScheduler(refresh_hour=19, refresh_minute=0)
        scheduler.start()

        # 手动触发
        scheduler.refresh_now()

        # 获取状态
        status = scheduler.get_status()

        # 更新计划时间
        scheduler.update_schedule(20, 30)
    """

    def __init__(self, refresh_hour: int = 19, refresh_minute: int = 0):
        self.refresh_hour = refresh_hour
        self.refresh_minute = refresh_minute
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_run_date: Optional[str] = None
        self._next_run_time: Optional[str] = None
        self._is_refreshing = False
        self._progress = (0, 0, "")  # (current, total, stock_code)
        self._lock = threading.Lock()

    def start(self):
        """启动后台服务"""
        if self._running:
            logger.warning("信号调度服务已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            f"信号调度服务已启动，每天 {self.refresh_hour:02d}:{self.refresh_minute:02d} 自动刷新"
        )

    def stop(self):
        """停止后台服务"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("信号调度服务已停止")

    def _run_loop(self):
        """主循环：定期检查是否到达计划时间"""
        # 计算初始的下次运行时间
        self._calc_next_run_time()

        while self._running:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # 判断是否应该运行
            should_run = (
                now.hour > self.refresh_hour
                or (now.hour == self.refresh_hour and now.minute >= self.refresh_minute)
            )

            if should_run and self._last_run_date != today and not self._is_refreshing:
                logger.info(f"定时触发信号刷新: {today}")
                self._do_refresh(today)
                self._calc_next_run_time()

            # 每 30 秒检查一次
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _do_refresh(self, trade_date: str):
        """执行信号刷新"""
        with self._lock:
            if self._is_refreshing:
                logger.warning("信号刷新已在进行中，跳过")
                return
            self._is_refreshing = True

        try:
            from src.dashboard.signal_data_service import get_signal_service

            logger.info(f"开始信号刷新: {trade_date}")
            start_time = time.time()

            signal_service = get_signal_service()
            # 只清内存缓存，保留文件缓存（万一刷新失败还能用旧数据）
            signal_service._signal_cache.pop(trade_date, None)
            signal_service._adapter.clear_cache()

            def on_progress(current, total, code):
                self._progress = (current, total, code)

            signal_service.get_signals(
                trade_date, progress_callback=on_progress
            )

            elapsed = time.time() - start_time
            self._last_run_date = trade_date
            logger.info(f"信号刷新完成: {trade_date}, 耗时 {elapsed:.1f}s")

        except Exception as e:
            logger.error(f"信号刷新失败: {e}")
        finally:
            self._is_refreshing = False
            self._progress = (0, 0, "")

    def refresh_now(self, trade_date: Optional[str] = None) -> bool:
        """立即手动触发刷新（异步，在后台线程执行）

        Args:
            trade_date: 交易日期，默认今天

        Returns:
            True 表示已触发，False 表示已有刷新在进行
        """
        if self._is_refreshing:
            return False

        trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        threading.Thread(
            target=self._do_refresh, args=(trade_date,), daemon=True
        ).start()
        return True

    def _calc_next_run_time(self):
        """计算下次运行时间"""
        now = datetime.now()
        target = now.replace(
            hour=self.refresh_hour,
            minute=self.refresh_minute,
            second=0,
            microsecond=0,
        )

        # 如果今天的计划时间已过，下次是明天
        if now >= target:
            target += timedelta(days=1)

        self._next_run_time = target.strftime("%Y-%m-%d %H:%M")

    def get_status(self) -> dict:
        """获取服务状态"""
        return {
            "running": self._running,
            "is_refreshing": self._is_refreshing,
            "progress": self._progress,
            "last_run_date": self._last_run_date,
            "next_run_time": self._next_run_time,
            "refresh_hour": self.refresh_hour,
            "refresh_minute": self.refresh_minute,
        }

    def update_schedule(self, hour: int, minute: int = 0):
        """更新计划刷新时间

        Args:
            hour: 小时 (0-23)
            minute: 分钟 (0-59)
        """
        self.refresh_hour = hour
        self.refresh_minute = minute
        self._calc_next_run_time()
        logger.info(f"信号刷新时间已更新为 {hour:02d}:{minute:02d}")


# 全局单例
_signal_scheduler: Optional[SignalScheduler] = None


def get_signal_scheduler() -> SignalScheduler:
    """获取全局信号调度器实例"""
    global _signal_scheduler
    if _signal_scheduler is None:
        # 从配置文件读取刷新时间
        hour = 19
        minute = 0
        try:
            from src.utils.config import Config
            from pathlib import Path

            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                config = Config(str(config_path))
                hour = config.get("signals.auto_refresh_hour", 19)
                minute = config.get("signals.auto_refresh_minute", 0)
        except Exception:
            pass

        _signal_scheduler = SignalScheduler(refresh_hour=hour, refresh_minute=minute)
    return _signal_scheduler


def start_signal_scheduler() -> SignalScheduler:
    """启动信号调度服务"""
    svc = get_signal_scheduler()
    if not svc._running:
        svc.start()
    return svc
