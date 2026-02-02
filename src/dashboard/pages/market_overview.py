"""Market overview page for dashboard."""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def render_risk_state_indicator(risk_state: str, risk_score: float):
    """Render the risk state indicator with color coding."""
    colors = {
        "RISK_ON": "#28a745",   # Green
        "NEUTRAL": "#ffc107",   # Yellow
        "RISK_OFF": "#dc3545"   # Red
    }
    labels = {
        "RISK_ON": "风险开启 - 可正常交易",
        "NEUTRAL": "中性状态 - 减半仓位",
        "RISK_OFF": "风险关闭 - 暂停开仓"
    }

    color = colors.get(risk_state, "#6c757d")
    label = labels.get(risk_state, "未知状态")

    st.markdown(
        f"""
        <div style="
            background-color: {color};
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        ">
            <h2 style="margin: 0;">{risk_state}</h2>
            <p style="margin: 5px 0 0 0;">{label}</p>
            <p style="margin: 5px 0 0 0;">综合得分: {risk_score:.1f}</p>
        </div>
        """,
        unsafe_allow_html=True
    )


def create_index_chart(data: pd.DataFrame) -> go.Figure:
    """Create candlestick chart for index data.

    Args:
        data: DataFrame with date, open, high, low, close columns

    Returns:
        Plotly figure object
    """
    fig = go.Figure(data=[
        go.Candlestick(
            x=data["date"],
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name="指数"
        )
    ])

    # Add moving averages
    if len(data) >= 5:
        data["MA5"] = data["close"].rolling(5).mean()
        fig.add_trace(go.Scatter(
            x=data["date"],
            y=data["MA5"],
            mode="lines",
            name="MA5",
            line=dict(color="orange", width=1)
        ))

    if len(data) >= 20:
        data["MA20"] = data["close"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=data["date"],
            y=data["MA20"],
            mode="lines",
            name="MA20",
            line=dict(color="blue", width=1)
        ))

    fig.update_layout(
        title="上证指数走势",
        xaxis_title="日期",
        yaxis_title="点位",
        xaxis_rangeslider_visible=False,
        height=400
    )

    return fig


def create_market_breadth_chart(advance: int, decline: int, unchanged: int) -> go.Figure:
    """Create market breadth pie chart.

    Args:
        advance: Number of advancing stocks
        decline: Number of declining stocks
        unchanged: Number of unchanged stocks

    Returns:
        Plotly figure object
    """
    fig = go.Figure(data=[
        go.Pie(
            labels=["上涨", "下跌", "平盘"],
            values=[advance, decline, unchanged],
            marker_colors=["#28a745", "#dc3545", "#6c757d"],
            hole=0.4
        )
    ])

    fig.update_layout(
        title="市场宽度",
        height=300
    )

    return fig


def create_sector_heatmap(sector_data: pd.DataFrame) -> go.Figure:
    """Create sector performance heatmap.

    Args:
        sector_data: DataFrame with sector, change_pct columns

    Returns:
        Plotly figure object
    """
    # Sort by change percentage
    sector_data = sector_data.sort_values("change_pct", ascending=False)

    # Create color scale
    colors = [
        "#dc3545" if x < -2 else
        "#fd7e14" if x < -1 else
        "#ffc107" if x < 0 else
        "#28a745" if x < 1 else
        "#20c997" if x < 2 else
        "#17a2b8"
        for x in sector_data["change_pct"]
    ]

    fig = go.Figure(data=[
        go.Bar(
            x=sector_data["sector"],
            y=sector_data["change_pct"],
            marker_color=colors,
            text=[f"{x:+.2f}%" for x in sector_data["change_pct"]],
            textposition="outside"
        )
    ])

    fig.update_layout(
        title="行业板块涨跌",
        xaxis_title="",
        yaxis_title="涨跌幅 (%)",
        height=350,
        xaxis_tickangle=-45
    )

    return fig


def create_risk_gauge(score: float) -> go.Figure:
    """Create risk score gauge chart.

    Args:
        score: Risk score (0-100)

    Returns:
        Plotly figure object
    """
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "风险评分"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "darkblue"},
            "steps": [
                {"range": [0, 40], "color": "#dc3545"},
                {"range": [40, 60], "color": "#ffc107"},
                {"range": [60, 100], "color": "#28a745"}
            ],
            "threshold": {
                "line": {"color": "black", "width": 4},
                "thickness": 0.75,
                "value": score
            }
        }
    ))

    fig.update_layout(height=250)

    return fig


def render_page(data_service=None):
    """Render the market overview page.

    Args:
        data_service: Optional DashboardDataService instance
    """
    st.header("🏠 市场概览")

    # For demo, use sample data
    # In production, this would come from data_service

    # Row 1: Key metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "上证指数",
            "3,150.25",
            delta="+39.12 (+1.25%)"
        )

    with col2:
        st.metric(
            "成交额",
            "8,532亿",
            delta="+15%"
        )

    with col3:
        st.metric(
            "涨跌比",
            "2,500 / 1,800",
            delta="上涨占优"
        )

    with col4:
        st.metric(
            "涨停/跌停",
            "45 / 12",
            delta="多头氛围"
        )

    st.divider()

    # Row 2: Risk state and gauge
    col1, col2 = st.columns([2, 1])

    with col1:
        render_risk_state_indicator("RISK_ON", 72.5)

    with col2:
        fig = create_risk_gauge(72.5)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Row 3: Index chart and market breadth
    col1, col2 = st.columns([3, 1])

    with col1:
        # Sample index data
        dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
        np.random.seed(42)
        closes = 3000 + np.cumsum(np.random.randn(60) * 20)
        opens = closes + np.random.randn(60) * 10
        highs = np.maximum(opens, closes) + np.abs(np.random.randn(60) * 15)
        lows = np.minimum(opens, closes) - np.abs(np.random.randn(60) * 15)

        index_data = pd.DataFrame({
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes
        })

        fig = create_index_chart(index_data)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = create_market_breadth_chart(2500, 1800, 200)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Row 4: Sector heatmap
    st.subheader("🔥 行业板块")

    sectors = [
        "银行", "保险", "券商", "房地产", "医药",
        "新能源", "半导体", "消费", "军工", "有色"
    ]
    changes = [2.35, 1.82, 1.45, 0.92, 0.56, -0.23, -0.78, -1.12, -1.56, -2.01]

    sector_data = pd.DataFrame({
        "sector": sectors,
        "change_pct": changes
    })

    fig = create_sector_heatmap(sector_data)
    st.plotly_chart(fig, use_container_width=True)

    # Row 5: Risk components
    st.subheader("📊 风险指标分解")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("指数趋势", "75.0", help="基于均线和趋势判断")

    with col2:
        st.metric("市场情绪", "68.0", help="基于新闻和舆情分析")

    with col3:
        st.metric("资金流向", "70.0", help="主力资金净流入/流出")

    with col4:
        st.metric("波动率", "35.0", help="市场波动程度 (越低越好)")

