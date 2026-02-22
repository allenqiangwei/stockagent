"""动作信号模型 — 回测系统的精确买卖指令

与打分系统（CombinedSignal）共存：
- CombinedSignal: 0-100 分数，用于排序和筛选
- ActionSignal: 明确的 BUY/SELL 指令，用于回测执行
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalAction(str, Enum):
    """买卖动作类型"""
    BUY = "BUY"
    SELL = "SELL"


class SellReason(str, Enum):
    """卖出原因分类（回测时区分卖出类型）"""
    STRATEGY_EXIT = "strategy_exit"   # 策略指标条件触发卖出
    STOP_LOSS = "stop_loss"           # 止损
    TAKE_PROFIT = "take_profit"       # 止盈
    MAX_HOLD = "max_hold"             # 最长持有天数到期


@dataclass
class ExitConfig:
    """策略的风控/退出配置"""
    stop_loss_pct: Optional[float] = None    # 止损比例（如 -8.0 表示 -8%）
    take_profit_pct: Optional[float] = None  # 止盈比例（如 20.0 表示 +20%）
    max_hold_days: Optional[int] = None      # 最长持有天数


@dataclass
class ActionSignal:
    """动作信号 — 回测系统的执行单元

    Attributes:
        stock_code: 股票代码
        trade_date: 信号日期 (YYYY-MM-DD)
        action: BUY 或 SELL
        strategy_name: 产生该信号的策略名称
        confidence_score: 打分系统的分数（0-100），用于同方向信号排序
        sell_reason: 卖出原因分类（仅 SELL 信号有值）
        exit_config: 风控配置（仅 BUY 信号携带，回测系统用于跟踪仓位）
        trigger_rules: 触发的具体条件描述列表
        reasons: 人类可读的信号理由
        stock_name: 股票名称
    """
    stock_code: str
    trade_date: str
    action: SignalAction
    strategy_name: str
    confidence_score: float = 50.0

    # 卖出专属
    sell_reason: Optional[SellReason] = None

    # 买入专属：携带退出配置供回测使用
    exit_config: Optional[ExitConfig] = None

    # 触发信息
    trigger_rules: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    # 元数据
    stock_name: str = ""
