"""StockAgent主入口"""
import argparse
import os
import sys
from datetime import date, datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import Config
from src.utils.logger import setup_logger, get_logger
from src.data_storage.database import Database
from src.data_storage.parquet_storage import ParquetStorage
from src.data_collector.collector_manager import create_collector_manager
from src.data_pipeline.daily_updater import DailyUpdater


def init_system(config_path: str = "config/config.yaml"):
    """初始化系统组件

    Args:
        config_path: 配置文件路径

    Returns:
        (config, collector, storage, database, updater)
    """
    # 加载配置
    config = Config(config_path)

    # 设置日志
    setup_logger(
        log_file=config.get("logging.file", "logs/stockagent.log"),
        level=config.get("logging.level", "INFO"),
    )
    logger = get_logger(__name__)
    logger.info("系统初始化中...")

    # 初始化存储
    storage = ParquetStorage(config.get("storage.parquet_dir", "data/market_data"))

    # 初始化数据库
    db_path = config.get("storage.sqlite_db", "data/business.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    database = Database(db_path)
    database.init_tables()

    # 初始化采集器
    collector = create_collector_manager(config)

    # 初始化更新器
    updater = DailyUpdater(
        collector=collector,
        storage=storage,
        database=database,
    )

    logger.info("系统初始化完成")
    return config, collector, storage, database, updater


def cmd_update(args):
    """执行数据更新命令"""
    config, collector, storage, database, updater = init_system(args.config)
    logger = get_logger(__name__)

    trade_date = args.date or datetime.now().strftime("%Y%m%d")

    if args.type == "all":
        results = updater.run_full_update(trade_date, force=args.force)
        for data_type, result in results.items():
            status = "成功" if result.get("success") or result.get("skipped") else "失败"
            logger.info(f"  {data_type}: {status}")
    elif args.type == "daily":
        updater.update_daily(trade_date, force=args.force)
    elif args.type == "index":
        updater.update_index(trade_date, force=args.force)
    elif args.type == "money_flow":
        updater.update_money_flow(trade_date, force=args.force)
    elif args.type == "news":
        updater.update_news(trade_date)
    elif args.type == "stock_list":
        updater.update_stock_list()


def cmd_init(args):
    """初始化系统"""
    config, collector, storage, database, updater = init_system(args.config)
    logger = get_logger(__name__)

    logger.info("正在初始化股票列表...")
    updater.update_stock_list()

    logger.info("系统初始化完成！")
    logger.info("下一步: 运行 'python src/main.py update --date YYYYMMDD' 更新数据")


def main():
    parser = argparse.ArgumentParser(description="StockAgent - A股量化交易系统")
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="配置文件路径"
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init命令
    init_parser = subparsers.add_parser("init", help="初始化系统")
    init_parser.set_defaults(func=cmd_init)

    # update命令
    update_parser = subparsers.add_parser("update", help="更新数据")
    update_parser.add_argument(
        "--type",
        choices=["all", "daily", "index", "money_flow", "news", "stock_list"],
        default="all",
        help="更新类型"
    )
    update_parser.add_argument(
        "--date",
        help="交易日期 (YYYYMMDD), 默认为今天"
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        help="强制更新（忽略已更新检查）"
    )
    update_parser.set_defaults(func=cmd_update)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
