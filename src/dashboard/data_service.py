"""Dashboard data service for aggregating display data."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class MarketOverview:
    """Market overview data for dashboard display.

    Attributes:
        date: Current date
        risk_state: Current risk state (RISK_ON, NEUTRAL, RISK_OFF)
        risk_score: Composite risk score (0-100)
        index_name: Main index name
        index_value: Current index value
        index_change_pct: Index change percentage
        advance_count: Number of advancing stocks
        decline_count: Number of declining stocks
        market_breadth: Advance/Total ratio
    """
    date: str
    risk_state: str
    risk_score: float
    index_name: str
    index_value: float
    index_change_pct: float
    advance_count: int
    decline_count: int
    market_breadth: float


@dataclass
class SignalSummary:
    """Signal summary for dashboard display.

    Attributes:
        stock_code: Stock identifier
        stock_name: Stock name
        signal_type: Signal type (STRONG_BUY, WEAK_BUY, etc.)
        signal_score: Signal score (0-100)
        recommended_position_pct: Recommended position percentage
        recommended_value: Recommended position value
        atr_pct: ATR as percentage
        reason: Signal reason
    """
    stock_code: str
    stock_name: str
    signal_type: str
    signal_score: float
    recommended_position_pct: float
    recommended_value: float
    atr_pct: float
    reason: str


@dataclass
class PositionSummary:
    """Position summary for dashboard display.

    Attributes:
        stock_code: Stock identifier
        stock_name: Stock name
        entry_price: Entry price
        current_price: Current price
        quantity: Number of shares
        position_value: Current position value
        pnl_value: Profit/Loss in currency
        pnl_pct: Profit/Loss percentage
        stop_price: Current stop price
        stop_type: Stop type (fixed, trailing, profit_lock)
        days_held: Number of days held
    """
    stock_code: str
    stock_name: str
    entry_price: float
    current_price: float
    quantity: int
    position_value: float
    pnl_value: float
    pnl_pct: float
    stop_price: float
    stop_type: str
    days_held: int


@dataclass
class RiskStatusSummary:
    """Risk status summary for dashboard display.

    Attributes:
        current_state: Current risk state
        state_since: Date when state started
        days_in_state: Number of days in current state
        composite_score: Overall risk score
        index_trend_score: Index trend component
        sentiment_score: Sentiment component
        money_flow_score: Money flow component
        volatility_score: Volatility component
        position_multiplier: Position size multiplier
        allows_new_positions: Whether new positions are allowed
    """
    current_state: str
    state_since: str
    days_in_state: int
    composite_score: float
    index_trend_score: float
    sentiment_score: float
    money_flow_score: float
    volatility_score: float
    position_multiplier: float
    allows_new_positions: bool


class DashboardDataService:
    """Service for aggregating and formatting dashboard data.

    This service acts as an intermediary between the trading system
    components and the dashboard UI, transforming domain objects into
    display-friendly formats.

    Usage:
        service = DashboardDataService()
        overview = service.get_market_overview(index_data, risk_state, ...)
        signals = service.get_signal_summaries(raw_signals)
    """

    def get_market_overview(
        self,
        index_data: pd.DataFrame,
        risk_state: str,
        risk_score: float,
        advance_count: int,
        decline_count: int,
        index_name: str = "上证指数"
    ) -> MarketOverview:
        """Create market overview from raw data.

        Args:
            index_data: DataFrame with trade_date, close, pct_chg
            risk_state: Current risk state string
            risk_score: Composite risk score
            advance_count: Number of advancing stocks
            decline_count: Number of declining stocks
            index_name: Name of main index

        Returns:
            MarketOverview with formatted data
        """
        # Get latest data
        latest = index_data.iloc[0]
        date = latest["trade_date"]
        if len(date) == 8:  # YYYYMMDD format
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

        total_stocks = advance_count + decline_count
        market_breadth = advance_count / total_stocks if total_stocks > 0 else 0.5

        return MarketOverview(
            date=date,
            risk_state=risk_state,
            risk_score=risk_score,
            index_name=index_name,
            index_value=float(latest["close"]),
            index_change_pct=float(latest["pct_chg"]),
            advance_count=advance_count,
            decline_count=decline_count,
            market_breadth=market_breadth
        )

    def get_signal_summaries(
        self,
        signals: list[dict]
    ) -> list[SignalSummary]:
        """Convert raw signals to display summaries.

        Args:
            signals: List of signal dicts with stock_code, signal_type, etc.

        Returns:
            List of SignalSummary objects
        """
        summaries = []
        for sig in signals:
            summary = SignalSummary(
                stock_code=sig["stock_code"],
                stock_name=sig.get("stock_name", ""),
                signal_type=sig["signal_type"],
                signal_score=sig["signal_score"],
                recommended_position_pct=sig.get("position_pct", 0.0),
                recommended_value=sig.get("position_value", 0.0),
                atr_pct=sig.get("atr_pct", 0.0),
                reason=sig.get("reason", "")
            )
            summaries.append(summary)
        return summaries

    def get_position_summaries(
        self,
        positions: list[dict],
        stop_results: list[dict],
        current_date: str
    ) -> list[PositionSummary]:
        """Convert raw positions to display summaries.

        Args:
            positions: List of position dicts
            stop_results: List of stop loss results
            current_date: Current date string (YYYY-MM-DD)

        Returns:
            List of PositionSummary objects
        """
        # Build stop info lookup
        stop_lookup = {
            r["stock_code"]: r for r in stop_results
        }

        summaries = []
        for pos in positions:
            stock_code = pos["stock_code"]
            entry_price = pos["entry_price"]
            current_price = pos["current_price"]
            quantity = pos["quantity"]

            # Calculate P&L
            pnl_value = (current_price - entry_price) * quantity
            pnl_pct = (current_price - entry_price) / entry_price * 100

            # Get stop info
            stop_info = stop_lookup.get(stock_code, {})
            stop_price = stop_info.get("stop_price", entry_price * 0.95)
            stop_type = stop_info.get("stop_type", "fixed")

            # Calculate days held
            entry_date = pos["entry_date"]
            days_held = self._calculate_days_between(entry_date, current_date)

            summary = PositionSummary(
                stock_code=stock_code,
                stock_name=pos.get("stock_name", ""),
                entry_price=entry_price,
                current_price=current_price,
                quantity=quantity,
                position_value=current_price * quantity,
                pnl_value=pnl_value,
                pnl_pct=pnl_pct,
                stop_price=stop_price,
                stop_type=stop_type,
                days_held=days_held
            )
            summaries.append(summary)

        return summaries

    def get_risk_status_summary(
        self,
        risk_state: str,
        market_condition: dict,
        state_history: list[dict],
        current_date: str
    ) -> RiskStatusSummary:
        """Create risk status summary.

        Args:
            risk_state: Current risk state
            market_condition: Dict with score components
            state_history: List of {date, state} dicts
            current_date: Current date string

        Returns:
            RiskStatusSummary with formatted data
        """
        # Find when current state started
        state_since = current_date
        for record in state_history:
            if record["state"] == risk_state:
                state_since = record["date"]
            else:
                break

        days_in_state = self._calculate_days_between(state_since, current_date)

        # Determine position multiplier and allows_new based on state
        if risk_state == "RISK_ON":
            position_multiplier = 1.0
            allows_new = True
        elif risk_state == "NEUTRAL":
            position_multiplier = 0.5
            allows_new = True
        else:  # RISK_OFF
            position_multiplier = 0.0
            allows_new = False

        return RiskStatusSummary(
            current_state=risk_state,
            state_since=state_since,
            days_in_state=days_in_state,
            composite_score=market_condition.get("composite_score", 50.0),
            index_trend_score=market_condition.get("index_trend_score", 50.0),
            sentiment_score=market_condition.get("sentiment_score", 50.0),
            money_flow_score=market_condition.get("money_flow_score", 50.0),
            volatility_score=market_condition.get("volatility_score", 50.0),
            position_multiplier=position_multiplier,
            allows_new_positions=allows_new
        )

    def format_signals_for_table(
        self,
        signals: list[SignalSummary]
    ) -> pd.DataFrame:
        """Format signals for display in a table.

        Args:
            signals: List of SignalSummary objects

        Returns:
            DataFrame formatted for display
        """
        if not signals:
            return pd.DataFrame()

        data = []
        for sig in signals:
            data.append({
                "代码": sig.stock_code,
                "名称": sig.stock_name,
                "信号": sig.signal_type,
                "得分": f"{sig.signal_score:.0f}",
                "建议仓位": f"{sig.recommended_position_pct*100:.1f}%",
                "建议金额": f"¥{sig.recommended_value:,.0f}",
                "ATR%": f"{sig.atr_pct:.1f}%",
                "原因": sig.reason
            })

        return pd.DataFrame(data)

    def format_positions_for_table(
        self,
        positions: list[PositionSummary]
    ) -> pd.DataFrame:
        """Format positions for display in a table.

        Args:
            positions: List of PositionSummary objects

        Returns:
            DataFrame formatted for display
        """
        if not positions:
            return pd.DataFrame()

        data = []
        for pos in positions:
            pnl_display = f"+{pos.pnl_pct:.1f}%" if pos.pnl_pct >= 0 else f"{pos.pnl_pct:.1f}%"
            data.append({
                "代码": pos.stock_code,
                "名称": pos.stock_name,
                "成本": f"¥{pos.entry_price:.2f}",
                "现价": f"¥{pos.current_price:.2f}",
                "数量": pos.quantity,
                "市值": f"¥{pos.position_value:,.0f}",
                "盈亏": f"¥{pos.pnl_value:+,.0f}",
                "盈亏%": pnl_display,
                "止损价": f"¥{pos.stop_price:.2f}",
                "止损类型": pos.stop_type,
                "持有天数": pos.days_held
            })

        return pd.DataFrame(data)

    def calculate_portfolio_metrics(
        self,
        positions: list[PositionSummary],
        total_portfolio_value: float
    ) -> dict:
        """Calculate portfolio-level metrics.

        Args:
            positions: List of position summaries
            total_portfolio_value: Total portfolio value

        Returns:
            Dict with portfolio metrics
        """
        if not positions:
            return {
                "total_invested": 0.0,
                "total_pnl": 0.0,
                "invested_pct": 0.0,
                "position_count": 0,
                "winning_count": 0,
                "losing_count": 0
            }

        total_invested = sum(p.position_value for p in positions)
        total_pnl = sum(p.pnl_value for p in positions)
        winning = sum(1 for p in positions if p.pnl_value > 0)
        losing = sum(1 for p in positions if p.pnl_value < 0)

        return {
            "total_invested": total_invested,
            "total_pnl": total_pnl,
            "invested_pct": total_invested / total_portfolio_value if total_portfolio_value > 0 else 0.0,
            "position_count": len(positions),
            "winning_count": winning,
            "losing_count": losing
        }

    def _calculate_days_between(self, start_date: str, end_date: str) -> int:
        """Calculate days between two date strings.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Number of days between dates
        """
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            return (end - start).days
        except ValueError:
            return 0

