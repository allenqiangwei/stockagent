"""Signals and positions page for dashboard."""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime


def get_signal_color(signal_type: str) -> str:
    """Get color for signal type."""
    colors = {
        "STRONG_BUY": "#28a745",
        "WEAK_BUY": "#7cb342",
        "HOLD": "#ffc107",
        "WEAK_SELL": "#ff7043",
        "STRONG_SELL": "#dc3545"
    }
    return colors.get(signal_type, "#6c757d")


def get_signal_emoji(signal_type: str) -> str:
    """Get emoji for signal type."""
    emojis = {
        "STRONG_BUY": "🟢",
        "WEAK_BUY": "🔵",
        "HOLD": "🟡",
        "WEAK_SELL": "🟠",
        "STRONG_SELL": "🔴"
    }
    return emojis.get(signal_type, "⚪")


def create_position_pnl_chart(positions: pd.DataFrame) -> go.Figure:
    """Create position P&L waterfall chart.

    Args:
        positions: DataFrame with stock names and P&L

    Returns:
        Plotly figure object
    """
    colors = ["#28a745" if x >= 0 else "#dc3545" for x in positions["pnl"]]

    fig = go.Figure(data=[
        go.Bar(
            x=positions["name"],
            y=positions["pnl"],
            marker_color=colors,
            text=[f"¥{x:+,.0f}" for x in positions["pnl"]],
            textposition="outside"
        )
    ])

    fig.update_layout(
        title="持仓盈亏分布",
        xaxis_title="",
        yaxis_title="盈亏 (¥)",
        height=300
    )

    return fig


def create_position_allocation_chart(positions: pd.DataFrame) -> go.Figure:
    """Create position allocation pie chart.

    Args:
        positions: DataFrame with stock names and values

    Returns:
        Plotly figure object
    """
    fig = go.Figure(data=[
        go.Pie(
            labels=positions["name"],
            values=positions["value"],
            hole=0.4,
            textinfo="label+percent"
        )
    ])

    fig.update_layout(
        title="仓位分配",
        height=300
    )

    return fig


def render_signal_card(signal: dict):
    """Render a signal card with details."""
    emoji = get_signal_emoji(signal["signal_type"])
    color = get_signal_color(signal["signal_type"])

    st.markdown(
        f"""
        <div style="
            border: 2px solid {color};
            border-radius: 10px;
            padding: 15px;
            margin: 10px 0;
        ">
            <h4 style="margin: 0;">{emoji} {signal['code']} {signal['name']}</h4>
            <p style="margin: 5px 0;">
                <strong>信号:</strong> {signal['signal_type']} |
                <strong>得分:</strong> {signal['score']:.0f}
            </p>
            <p style="margin: 5px 0;">
                <strong>建议仓位:</strong> {signal['position_pct']*100:.1f}% |
                <strong>建议金额:</strong> ¥{signal['position_value']:,.0f}
            </p>
            <p style="margin: 5px 0; color: #6c757d;">
                {signal['reason']}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_position_row(position: dict) -> dict:
    """Format position for table display."""
    pnl_pct = position["pnl_pct"]
    pnl_color = "green" if pnl_pct >= 0 else "red"

    return {
        "代码": position["code"],
        "名称": position["name"],
        "成本": f"¥{position['entry_price']:.2f}",
        "现价": f"¥{position['current_price']:.2f}",
        "数量": position["quantity"],
        "市值": f"¥{position['value']:,.0f}",
        "盈亏": f"¥{position['pnl']:+,.0f}",
        "盈亏%": f"{pnl_pct:+.1f}%",
        "止损价": f"¥{position['stop_price']:.2f}",
        "止损类型": position["stop_type"],
        "持有天数": position["days_held"]
    }


def render_page(data_service=None):
    """Render the signals and positions page.

    Args:
        data_service: Optional DashboardDataService instance
    """
    st.header("📊 信号与持仓")

    # Tabs for signals and positions
    tab1, tab2 = st.tabs(["📥 今日信号", "💼 当前持仓"])

    with tab1:
        render_signals_tab()

    with tab2:
        render_positions_tab()


def render_signals_tab():
    """Render the signals tab."""
    # Sample signals data
    buy_signals = [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "signal_type": "STRONG_BUY",
            "score": 85.0,
            "position_pct": 0.15,
            "position_value": 15000,
            "reason": "MACD金叉 + 均线多头排列 + 资金流入"
        },
        {
            "code": "600519.SH",
            "name": "贵州茅台",
            "signal_type": "WEAK_BUY",
            "score": 68.0,
            "position_pct": 0.10,
            "position_value": 10000,
            "reason": "突破前高 + 成交量放大"
        }
    ]

    sell_signals = [
        {
            "code": "000002.SZ",
            "name": "万科A",
            "signal_type": "STRONG_SELL",
            "score": 25.0,
            "position_pct": 0.0,
            "position_value": 0,
            "reason": "触发移动止损 (从高点回落超过2*ATR)"
        }
    ]

    # Risk state warning
    st.info("📊 当前风险状态: **RISK_ON** - 信号权重正常")

    # Buy signals
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🟢 买入信号")

        if buy_signals:
            for signal in buy_signals:
                render_signal_card(signal)
        else:
            st.write("今日无买入信号")

    with col2:
        st.subheader("🔴 卖出信号")

        if sell_signals:
            for signal in sell_signals:
                render_signal_card(signal)
        else:
            st.write("今日无卖出信号")

    st.divider()

    # Signal summary table
    st.subheader("📋 信号汇总")

    all_signals = buy_signals + sell_signals
    if all_signals:
        signal_df = pd.DataFrame([
            {
                "代码": s["code"],
                "名称": s["name"],
                "信号": f"{get_signal_emoji(s['signal_type'])} {s['signal_type']}",
                "得分": f"{s['score']:.0f}",
                "建议仓位": f"{s['position_pct']*100:.1f}%",
                "建议金额": f"¥{s['position_value']:,.0f}",
                "原因": s["reason"]
            }
            for s in all_signals
        ])

        st.dataframe(
            signal_df,
            use_container_width=True,
            hide_index=True
        )


def render_positions_tab():
    """Render the positions tab."""
    # Sample positions data
    positions = [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "entry_price": 10.0,
            "current_price": 11.0,
            "quantity": 1000,
            "value": 11000,
            "pnl": 1000,
            "pnl_pct": 10.0,
            "stop_price": 10.5,
            "stop_type": "trailing",
            "days_held": 5
        },
        {
            "code": "600519.SH",
            "name": "贵州茅台",
            "entry_price": 1800.0,
            "current_price": 1850.0,
            "quantity": 10,
            "value": 18500,
            "pnl": 500,
            "pnl_pct": 2.78,
            "stop_price": 1710.0,
            "stop_type": "fixed",
            "days_held": 3
        },
        {
            "code": "000002.SZ",
            "name": "万科A",
            "entry_price": 12.0,
            "current_price": 11.5,
            "quantity": 1000,
            "value": 11500,
            "pnl": -500,
            "pnl_pct": -4.17,
            "stop_price": 11.4,
            "stop_type": "fixed",
            "days_held": 8
        }
    ]

    # Portfolio summary metrics
    total_value = sum(p["value"] for p in positions)
    total_pnl = sum(p["pnl"] for p in positions)
    winning = sum(1 for p in positions if p["pnl"] > 0)
    losing = sum(1 for p in positions if p["pnl"] < 0)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "总市值",
            f"¥{total_value:,.0f}",
            delta=f"¥{total_pnl:+,.0f}"
        )

    with col2:
        pnl_pct = (total_pnl / (total_value - total_pnl)) * 100 if total_value != total_pnl else 0
        st.metric(
            "总盈亏",
            f"¥{total_pnl:+,.0f}",
            delta=f"{pnl_pct:+.1f}%"
        )

    with col3:
        st.metric(
            "持仓数量",
            f"{len(positions)}只",
            delta=f"盈{winning}/亏{losing}"
        )

    with col4:
        portfolio_value = 100000
        invested_pct = total_value / portfolio_value * 100
        st.metric(
            "仓位比例",
            f"{invested_pct:.1f}%",
            delta="正常" if invested_pct <= 60 else "偏高"
        )

    st.divider()

    # Positions table
    st.subheader("📋 持仓明细")

    position_df = pd.DataFrame([render_position_row(p) for p in positions])

    # Style the dataframe
    def color_pnl(val):
        if "+" in str(val):
            return "color: green"
        elif "-" in str(val):
            return "color: red"
        return ""

    styled_df = position_df.style.applymap(
        color_pnl,
        subset=["盈亏", "盈亏%"]
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # Charts
    col1, col2 = st.columns(2)

    with col1:
        pos_df = pd.DataFrame({
            "name": [p["name"] for p in positions],
            "pnl": [p["pnl"] for p in positions]
        })
        fig = create_position_pnl_chart(pos_df)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        pos_df = pd.DataFrame({
            "name": [p["name"] for p in positions],
            "value": [p["value"] for p in positions]
        })
        fig = create_position_allocation_chart(pos_df)
        st.plotly_chart(fig, use_container_width=True)

    # Stop loss alerts
    st.divider()
    st.subheader("⚠️ 止损预警")

    alerts = [p for p in positions if p["current_price"] <= p["stop_price"] * 1.02]

    if alerts:
        for p in alerts:
            distance_pct = (p["current_price"] - p["stop_price"]) / p["stop_price"] * 100
            st.warning(
                f"**{p['code']} {p['name']}** - 距离止损价 {distance_pct:.1f}% "
                f"(现价 ¥{p['current_price']:.2f}, 止损价 ¥{p['stop_price']:.2f})"
            )
    else:
        st.success("✅ 所有持仓距离止损价安全")

