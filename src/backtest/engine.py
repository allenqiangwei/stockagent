"""回测引擎：基于历史数据模拟策略交易，统计收益指标。

复用现有的 rule_engine.evaluate_conditions() 和 ExitConfig 机制，
逐日遍历历史数据模拟交易，计算胜率/收益率/最大回撤等统计指标。
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import pandas as pd

from src.signals.rule_engine import (
    evaluate_conditions,
    collect_indicator_params,
)
from src.indicators.indicator_calculator import (
    IndicatorCalculator,
    IndicatorConfig,
)


# ── 涨跌停工具函数 ──

def get_price_limit_pct(stock_code: str) -> float:
    """根据股票代码返回涨跌停幅度百分比。

    主板(0xx/6xx): ±10%, 创业板(300/301): ±20%,
    科创板(688): ±20%, 北交所(8xx/4xx): ±30%
    """
    if stock_code.startswith(('300', '301')):
        return 20.0
    if stock_code.startswith('688'):
        return 20.0
    if stock_code.startswith(('8', '4')):
        return 30.0
    return 10.0


def calc_limit_prices(stock_code: str, prev_close: float) -> tuple:
    """计算涨停价和跌停价。返回 (limit_up, limit_down)。"""
    pct = get_price_limit_pct(stock_code)
    limit_up = round(prev_close * (1 + pct / 100), 2)
    limit_down = round(prev_close * (1 - pct / 100), 2)
    return limit_up, limit_down


@dataclass
class Trade:
    """单笔交易记录"""
    stock_code: str
    strategy_name: str
    buy_date: str
    buy_price: float
    sell_date: Optional[str] = None
    sell_price: Optional[float] = None
    sell_reason: Optional[str] = None  # strategy_exit | stop_loss | take_profit | max_hold
    pnl_pct: Optional[float] = None   # 收益率 %
    hold_days: int = 0
    regime: str = ""  # market regime at buy time (trending_bull/bear/ranging/volatile)


@dataclass
class BacktestResult:
    """回测结果汇总"""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float          # 胜率 %
    total_return_pct: float  # 累计收益率 %
    max_drawdown_pct: float  # 最大回撤 %
    avg_hold_days: float
    avg_pnl_pct: float       # 平均单笔收益率
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)  # [{date, equity}]
    sell_reason_stats: dict = field(default_factory=dict)    # {reason: count}


class BacktestEngine:
    """回测引擎

    对单只或多只股票运行策略回测，逐日遍历历史数据模拟交易。

    Usage:
        engine = BacktestEngine(capital_per_trade=10000)
        result = engine.run_single(strategy_dict, df, "000001")
    """

    def __init__(self, capital_per_trade: float = 10000.0, slippage_pct: float = 0.1):
        self.capital_per_trade = capital_per_trade
        self.slippage_pct = slippage_pct

    def run_single(
        self,
        strategy: Dict[str, Any],
        df: pd.DataFrame,
        stock_code: str,
    ) -> BacktestResult:
        """对单只股票运行单个策略的回测

        Args:
            strategy: 策略字典（从 DB 加载），包含 buy_conditions、
                      sell_conditions、exit_config、rules 等字段
            df: 原始日线数据 (date, open, high, low, close, volume)
            stock_code: 股票代码

        Returns:
            BacktestResult
        """
        strategy_name = strategy.get("name", "未知策略")
        buy_conditions = strategy.get("buy_conditions", [])
        sell_conditions = strategy.get("sell_conditions", [])
        exit_config = strategy.get("exit_config", {})

        stop_loss_pct = exit_config.get("stop_loss_pct")      # e.g. -8.0
        take_profit_pct = exit_config.get("take_profit_pct")   # e.g. 20.0
        max_hold_days = exit_config.get("max_hold_days")       # e.g. 30

        # 收集买入+卖出条件的指标参数
        all_rules = buy_conditions + sell_conditions
        collected_params = collect_indicator_params(all_rules)
        config = IndicatorConfig.from_collected_params(collected_params)
        calculator = IndicatorCalculator(config)

        # 计算指标（一次性计算全量，效率最高）
        if df.empty or len(df) < 2:
            return self._empty_result(strategy_name, df)

        indicators = calculator.calculate_all(df)
        df_full = pd.concat([df.reset_index(drop=True), indicators.reset_index(drop=True)], axis=1)

        # 日期列处理
        if "date" in df_full.columns:
            df_full["date"] = pd.to_datetime(df_full["date"])
            dates = df_full["date"].dt.strftime("%Y-%m-%d").tolist()
        else:
            dates = [str(i) for i in range(len(df_full))]

        # ── T+1 逐日模拟 ──
        # 信号在 Day T 生成，Day T+1 以开盘价执行。
        # SL/TP 日内触发但跌停时转 pending。买入日不可卖出（T+1 结算）。
        # hold_days 语义: 买入日=0, 完整持有一天后=1。
        trades: List[Trade] = []
        current_trade: Optional[Trade] = None
        equity = self.capital_per_trade
        equity_curve = []
        pending_buy = False
        pending_sell = False
        pending_sell_reason: Optional[str] = None
        slippage = self.slippage_pct
        just_bought = False  # T+1: 买入日标记，当天禁止卖出

        for i in range(1, len(df_full)):
            row = df_full.iloc[i]
            open_p = float(row["open"])
            close = float(row["close"])
            low = float(row.get("low", close))
            high = float(row.get("high", close))
            current_date = dates[i]

            # 上一日收盘价 → 计算涨跌停价
            prev_close = float(df_full.iloc[i - 1]["close"])
            limit_up, limit_down = calc_limit_prices(stock_code, prev_close)

            # ── Step 1: 执行昨日 pending_sell (开盘价) ──
            if pending_sell and current_trade is not None:
                if open_p >= limit_down:  # Fix#4: >= 允许跌停价成交
                    sell_price = max(open_p * (1 - slippage / 100), limit_down)
                    current_trade.hold_days += 1  # Fix#3: pending执行日计入
                    current_trade.sell_date = current_date
                    current_trade.sell_price = sell_price
                    current_trade.sell_reason = pending_sell_reason
                    current_trade.pnl_pct = (
                        (sell_price - current_trade.buy_price)
                        / current_trade.buy_price * 100
                    )
                    trades.append(current_trade)
                    current_trade = None
                    pending_sell = False
                    pending_sell_reason = None
                else:
                    # 跌停无法卖出，下一个交易日重试
                    current_trade.hold_days += 1

            # ── Step 2: 执行昨日 pending_buy (开盘价) ──
            if pending_buy and current_trade is None:
                if open_p <= limit_up:  # Fix#4: <= 允许涨停价成交
                    buy_price = min(open_p * (1 + slippage / 100), limit_up)
                    current_trade = Trade(
                        stock_code=stock_code,
                        strategy_name=strategy_name,
                        buy_date=current_date,
                        buy_price=buy_price,
                    )
                    just_bought = True  # Fix#1: 买入日标记
                # 无论是否成交，信号过期
                pending_buy = False

            # ── Step 3: 持仓检查（买入日跳过，T+1 结算） ──
            if current_trade is not None and not pending_sell and not just_bought:
                current_trade.hold_days += 1  # Fix#2: 先 +1 再检查，hold_days=1 表示已持有1天
                sell_reason = None
                exec_price = None

                # 3a) 止损 — 日内触发，跳空处理，跌停则 pending
                if stop_loss_pct is not None:
                    loss_threshold = current_trade.buy_price * (1 + stop_loss_pct / 100)
                    if open_p <= loss_threshold:
                        # 跳空低开
                        sl_price = max(open_p * (1 - slippage / 100), limit_down)
                        if open_p >= limit_down:  # Fix#6: 跌停检查
                            sell_reason = "stop_loss"
                            exec_price = sl_price
                        else:
                            # 跌停无法成交，转 pending
                            pending_sell = True
                            pending_sell_reason = "stop_loss"
                    elif low <= loss_threshold:
                        # 日内触发
                        sl_price = max(loss_threshold * (1 - slippage / 100), limit_down)
                        sell_reason = "stop_loss"
                        exec_price = sl_price

                # 3b) 止盈 — 日内触发，跳空处理
                if sell_reason is None and not pending_sell and take_profit_pct is not None:
                    profit_threshold = current_trade.buy_price * (1 + take_profit_pct / 100)
                    if open_p >= profit_threshold:
                        # 跳空高开
                        sell_reason = "take_profit"
                        exec_price = max(open_p * (1 - slippage / 100), limit_down)  # Fix#5: 不低于跌停
                    elif high >= profit_threshold:
                        # 日内触发
                        sell_reason = "take_profit"
                        exec_price = max(profit_threshold * (1 - slippage / 100), limit_down)  # Fix#5

                # SL/TP 执行
                if sell_reason and exec_price is not None:
                    current_trade.sell_date = current_date
                    current_trade.sell_price = exec_price
                    current_trade.sell_reason = sell_reason
                    current_trade.pnl_pct = (
                        (exec_price - current_trade.buy_price)
                        / current_trade.buy_price * 100
                    )
                    trades.append(current_trade)
                    current_trade = None
                elif not pending_sell:
                    # 3c) 最长持有天数 → pending sell
                    if max_hold_days is not None and current_trade.hold_days >= max_hold_days:
                        pending_sell = True
                        pending_sell_reason = "max_hold"

                    # 3d) 策略卖出条件 → pending sell (Fix#7: 统一用 pending)
                    if not pending_sell and sell_conditions:
                        df_slice = df_full.iloc[: i + 1]
                        triggered, _ = evaluate_conditions(
                            sell_conditions, df_slice, mode="OR"
                        )
                        if triggered:
                            pending_sell = True
                            pending_sell_reason = "strategy_exit"

            # 重置买入日标记
            just_bought = False

            # ── Step 4: 买入信号 → pending buy ──
            if current_trade is None and not pending_buy and buy_conditions:
                df_slice = df_full.iloc[: i + 1]
                triggered, _ = evaluate_conditions(
                    buy_conditions, df_slice, mode="AND"
                )
                if triggered:
                    pending_buy = True

            # ── Fix#8: Equity 包含浮动盈亏 ──
            if current_trade is not None:
                unrealized_pnl = (close - current_trade.buy_price) / current_trade.buy_price
                cur_equity = self.capital_per_trade * (1 + unrealized_pnl)
            else:
                cur_equity = equity
            equity_curve.append({"date": current_date, "equity": round(cur_equity, 2)})

        # ── 回测结束处理 ──
        # pending_buy → 丢弃（没有下一天执行）
        # pending_sell 或持仓 → 以最后一天收盘价平仓
        if current_trade is not None:
            last_close = float(df_full.iloc[-1]["close"])
            last_date = dates[-1]
            current_trade.sell_date = last_date
            current_trade.sell_price = last_close
            current_trade.sell_reason = pending_sell_reason or "end_of_backtest"
            current_trade.pnl_pct = (
                (last_close - current_trade.buy_price) / current_trade.buy_price * 100
            )
            equity = self.capital_per_trade * (1 + current_trade.pnl_pct / 100)
            trades.append(current_trade)
            if equity_curve:
                equity_curve[-1]["equity"] = round(equity, 2)

        return self._build_result(
            strategy_name=strategy_name,
            trades=trades,
            equity_curve=equity_curve,
            start_date=dates[0] if dates else "",
            end_date=dates[-1] if dates else "",
        )

    def run_batch(
        self,
        strategy: Dict[str, Any],
        stock_data: Dict[str, pd.DataFrame],
        progress_callback=None,
    ) -> BacktestResult:
        """批量回测：对多只股票运行策略，合并交易结果

        Args:
            strategy: 策略字典
            stock_data: {stock_code: DataFrame} 映射
            progress_callback: 进度回调 (current, total, stock_code) -> None

        Returns:
            合并后的 BacktestResult
        """
        all_trades: List[Trade] = []
        all_equity_points: List[dict] = []
        strategy_name = strategy.get("name", "未知策略")
        total = len(stock_data)
        start_date = ""
        end_date = ""

        for idx, (code, df) in enumerate(stock_data.items(), 1):
            if progress_callback:
                progress_callback(idx, total, code)

            if df is None or df.empty or len(df) < 60:
                continue

            result = self.run_single(strategy, df, code)
            all_trades.extend(result.trades)
            all_equity_points.extend(result.equity_curve)

            # 跟踪全局日期范围
            if result.start_date and (not start_date or result.start_date < start_date):
                start_date = result.start_date
            if result.end_date and (not end_date or result.end_date > end_date):
                end_date = result.end_date

        # 按日期聚合 equity_curve（多只股票的累计权益）
        merged_equity = self._merge_equity_curves(all_equity_points)

        return self._build_result(
            strategy_name=strategy_name,
            trades=all_trades,
            equity_curve=merged_equity,
            start_date=start_date,
            end_date=end_date,
        )

    def _merge_equity_curves(self, equity_points: List[dict]) -> List[dict]:
        """将多只股票的 equity 按日期聚合"""
        if not equity_points:
            return []

        # 按日期分组，累加各股票在同一天的损益
        date_equity: Dict[str, float] = {}
        for point in equity_points:
            d = point["date"]
            # 损益 = equity - initial_capital
            pnl = point["equity"] - self.capital_per_trade
            date_equity[d] = date_equity.get(d, 0) + pnl

        # 转为累计权益曲线
        base = self.capital_per_trade
        result = []
        cumulative = base
        for d in sorted(date_equity.keys()):
            cumulative = base + date_equity[d]
            result.append({"date": d, "equity": round(cumulative, 2)})

        return result

    def _build_result(
        self,
        strategy_name: str,
        trades: List[Trade],
        equity_curve: List[dict],
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """从交易列表构建统计结果"""
        total_trades = len(trades)

        if total_trades == 0:
            return BacktestResult(
                strategy_name=strategy_name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.capital_per_trade,
                total_trades=0,
                win_trades=0,
                lose_trades=0,
                win_rate=0.0,
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                avg_hold_days=0.0,
                avg_pnl_pct=0.0,
                trades=trades,
                equity_curve=equity_curve,
                sell_reason_stats={},
            )

        win_trades = sum(1 for t in trades if t.pnl_pct is not None and t.pnl_pct > 0)
        lose_trades = total_trades - win_trades
        win_rate = (win_trades / total_trades) * 100

        pnl_values = [t.pnl_pct for t in trades if t.pnl_pct is not None]
        total_return_pct = sum(pnl_values) if pnl_values else 0.0
        avg_pnl_pct = total_return_pct / total_trades if total_trades else 0.0

        hold_days_list = [t.hold_days for t in trades]
        avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0.0

        # 最大回撤（基于 equity_curve）
        max_drawdown_pct = self._calc_max_drawdown(equity_curve)

        # 卖出原因统计
        sell_reason_stats: Dict[str, int] = {}
        for t in trades:
            reason = t.sell_reason or "unknown"
            sell_reason_stats[reason] = sell_reason_stats.get(reason, 0) + 1

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.capital_per_trade,
            total_trades=total_trades,
            win_trades=win_trades,
            lose_trades=lose_trades,
            win_rate=round(win_rate, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            avg_hold_days=round(avg_hold_days, 1),
            avg_pnl_pct=round(avg_pnl_pct, 2),
            trades=trades,
            equity_curve=equity_curve,
            sell_reason_stats=sell_reason_stats,
        )

    @staticmethod
    def _calc_max_drawdown(equity_curve: List[dict]) -> float:
        """计算最大回撤百分比"""
        if not equity_curve:
            return 0.0

        peak = equity_curve[0]["equity"]
        max_dd = 0.0

        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def _empty_result(self, strategy_name: str, df: pd.DataFrame) -> BacktestResult:
        """数据不足时返回空结果"""
        return BacktestResult(
            strategy_name=strategy_name,
            start_date="",
            end_date="",
            initial_capital=self.capital_per_trade,
            total_trades=0,
            win_trades=0,
            lose_trades=0,
            win_rate=0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            avg_hold_days=0.0,
            avg_pnl_pct=0.0,
        )
