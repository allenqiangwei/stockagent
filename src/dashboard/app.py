"""Main Streamlit dashboard application.

Run with: streamlit run src/dashboard/app.py
"""

import streamlit as st
from datetime import datetime

from .app_config import (
    get_app_config,
    get_page_config,
    init_session_state
)


def setup_page():
    """Configure page settings."""
    config = get_app_config()
    st.set_page_config(
        page_title=config.app_title,
        page_icon=config.page_icon,
        layout=config.layout,
        initial_sidebar_state=config.initial_sidebar_state
    )


def setup_session_state():
    """Initialize session state with defaults."""
    defaults = init_session_state()
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar():
    """Render navigation sidebar."""
    with st.sidebar:
        st.title("📈 A股量化系统")
        st.divider()

        # User info
        if st.session_state.authenticated:
            st.write(f"👤 {st.session_state.username}")
            st.write(f"🔑 {st.session_state.user_role}")
            st.divider()

        # Navigation
        pages = get_page_config()
        for page in pages:
            # Check role access
            if st.session_state.authenticated:
                if st.session_state.user_role not in page.allowed_roles:
                    continue

            if st.button(
                f"{page.icon} {page.name}",
                key=f"nav_{page.name}",
                use_container_width=True
            ):
                st.session_state.current_page = page.name
                st.rerun()

        st.divider()

        # Logout button
        if st.session_state.authenticated:
            if st.button("🚪 退出登录", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.user_role = None
                st.session_state.username = None
                st.rerun()

        # Last refresh time
        st.caption(f"最后刷新: {datetime.now().strftime('%H:%M:%S')}")


def render_login_page():
    """Render login page for unauthenticated users."""
    st.title("🔐 登录")
    st.write("请输入用户名和密码登录系统")

    with st.form("login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录", use_container_width=True)

        if submitted:
            # Simple authentication (replace with real auth in production)
            if authenticate_user(username, password):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.user_role = get_user_role(username)
                st.success("登录成功！")
                st.rerun()
            else:
                st.error("用户名或密码错误")


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate user credentials.

    Args:
        username: Username to check
        password: Password to verify

    Returns:
        True if credentials are valid
    """
    # Simple hardcoded auth for development
    # In production, use proper password hashing and database
    users = {
        "admin": "admin123",
        "viewer": "viewer123"
    }
    return users.get(username) == password


def get_user_role(username: str) -> str:
    """Get role for authenticated user.

    Args:
        username: Username to lookup

    Returns:
        Role string (admin or readonly)
    """
    roles = {
        "admin": "admin",
        "viewer": "readonly"
    }
    return roles.get(username, "readonly")


def render_market_overview():
    """Render market overview page."""
    st.header("🏠 市场概览")

    # Risk state indicator
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "风险状态",
            "RISK_ON",
            delta="稳定",
            delta_color="normal"
        )

    with col2:
        st.metric(
            "上证指数",
            "3,150.25",
            delta="+1.25%",
            delta_color="normal"
        )

    with col3:
        st.metric(
            "市场宽度",
            "58%",
            delta="上涨占优"
        )

    with col4:
        st.metric(
            "持仓数量",
            "3只",
            delta="可新增"
        )

    st.divider()

    # Placeholder charts
    st.subheader("📈 指数走势")
    st.info("指数走势图表将在这里显示")

    st.subheader("🔥 行业热力图")
    st.info("行业热力图将在这里显示")


def render_signals_positions():
    """Render signals and positions page."""
    st.header("📊 信号与持仓")

    tab1, tab2 = st.tabs(["📥 今日信号", "💼 当前持仓"])

    with tab1:
        st.subheader("买入信号")
        st.info("今日买入信号将在这里显示")

        st.subheader("卖出信号")
        st.info("止损/止盈信号将在这里显示")

    with tab2:
        st.subheader("持仓明细")
        st.info("当前持仓列表将在这里显示")

        st.subheader("组合指标")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总市值", "¥60,000", delta="+¥2,500")
        with col2:
            st.metric("仓位比例", "60%", delta="正常")
        with col3:
            st.metric("盈亏比", "2:1", delta="良好")


def render_risk_status():
    """Render risk status page."""
    st.header("⚠️ 风险状态")

    # Current state
    st.subheader("当前状态")
    col1, col2 = st.columns(2)

    with col1:
        st.metric("风险状态", "RISK_ON")
        st.metric("状态持续", "5天")
        st.metric("综合得分", "72.5")

    with col2:
        st.metric("指数趋势", "75.0")
        st.metric("市场情绪", "68.0")
        st.metric("资金流向", "70.0")

    st.divider()

    st.subheader("状态历史")
    st.info("风险状态历史图表将在这里显示")


def render_settings():
    """Render settings page (admin only)."""
    st.header("⚙️ 系统设置")

    if st.session_state.user_role != "admin":
        st.error("您没有权限访问此页面")
        return

    st.subheader("组合参数")
    col1, col2 = st.columns(2)

    with col1:
        st.number_input("总资金 (¥)", value=100000, step=10000)
        st.slider("目标仓位", 0.0, 1.0, 0.6, 0.05)

    with col2:
        st.number_input("最大单股仓位 (%)", value=25, step=5)
        st.number_input("最大持股数", value=10, step=1)

    st.divider()

    st.subheader("止损参数")
    col1, col2 = st.columns(2)

    with col1:
        st.slider("固定止损 (%)", 1.0, 10.0, 5.0, 0.5)

    with col2:
        st.slider("ATR倍数", 1.0, 4.0, 2.0, 0.5)


def render_current_page():
    """Render the current page based on session state."""
    page = st.session_state.current_page

    if page == "市场概览":
        render_market_overview()
    elif page == "信号与持仓":
        render_signals_positions()
    elif page == "风险状态":
        render_risk_status()
    elif page == "系统设置":
        render_settings()
    else:
        render_market_overview()


def main():
    """Main application entry point."""
    setup_page()
    setup_session_state()

    if not st.session_state.authenticated:
        render_login_page()
    else:
        render_sidebar()
        render_current_page()


if __name__ == "__main__":
    main()

