"""日志配置模块，基于loguru"""
import sys
from loguru import logger


# 移除默认的stderr handler
logger.remove()

_initialized = False


def setup_logger(
    log_file: str = "logs/stockagent.log",
    level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "30 days",
) -> None:
    """配置日志系统

    Args:
        log_file: 日志文件路径
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        rotation: 日志轮转大小
        retention: 日志保留时间
    """
    global _initialized

    if _initialized:
        logger.remove()

    # 控制台输出
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # 文件输出
    logger.add(
        log_file,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
    )

    _initialized = True


def get_logger(name: str):
    """获取命名logger

    Args:
        name: 模块名称

    Returns:
        绑定了模块名的logger
    """
    return logger.bind(name=name)
