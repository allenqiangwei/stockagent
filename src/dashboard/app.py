"""Main Streamlit dashboard application.

Run with: streamlit run src/dashboard/app.py
"""

import sys
from pathlib import Path

# Add project root to path for absolute imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st
from datetime import datetime, timedelta

from src.dashboard.app_config import (
    get_app_config,
    get_page_config,
    init_session_state
)
from src.utils.config import Config, ConfigError
from src.dashboard.live_data_service import get_live_data_service, reload_live_data_service
from src.dashboard.signal_data_service import get_signal_service
from src.dashboard.indicator_manager import render_indicator_manager
from src.dashboard.backtest_page import render_backtest_page
from src.data_collector.news_crawler import NewsCrawler, NewsItem
from src.services.news_service import NewsService, get_news_service, start_news_service
from src.services.api_guard import get_api_guard


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
    """Render market overview page with live data."""
    st.header("🏠 市场概览")

    # 获取实时数据服务
    live_service = get_live_data_service()

    # 显示数据源状态
    sources = live_service.get_all_sources()
    with st.expander("📡 数据源状态", expanded=False):
        cols = st.columns(3)
        source_names = {"akshare": "🆓 AkShare", "tushare": "🔐 TuShare"}
        category_names = {
            "realtime_quotes": "实时行情",
            "index_data": "指数数据",
            "sector_data": "行业板块",
        }
        for i, (key, name) in enumerate(category_names.items()):
            with cols[i % 3]:
                st.caption(f"{name}: {source_names.get(sources.get(key, 'akshare'), 'AkShare')}")

        # 东方财富 API 熔断状态
        guard = get_api_guard()
        em_status = guard.get_status("eastmoney")
        if em_status.get("blocked"):
            remaining = em_status.get("remaining_seconds", 0)
            remaining_min = remaining // 60
            reason = em_status.get("last_failure_reason", "未知")
            fail_count = em_status.get("failure_count", 0)
            st.warning(
                f"⚠️ 东方财富接口已熔断（第{fail_count}次失败），"
                f"剩余冷却 {remaining_min} 分钟 | 原因: {reason}"
            )
        else:
            st.caption("东方财富接口: ✅ 正常")

    # 获取指数行情
    index_quote = live_service.get_index_quote("sh000001")
    market_breadth = live_service.get_market_breadth()

    # Risk state indicator
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # TODO: 从风控系统获取真实状态
        st.metric(
            "风险状态",
            "RISK_ON",
            delta="稳定",
            delta_color="normal"
        )

    with col2:
        if index_quote:
            delta_str = f"{index_quote.change_pct:+.2f}%"
            delta_color = "normal" if index_quote.change_pct >= 0 else "inverse"
            st.metric(
                index_quote.name,
                f"{index_quote.current:,.2f}",
                delta=delta_str,
                delta_color=delta_color
            )
        else:
            st.metric("上证指数", "数据获取中...", delta="--")

    with col3:
        if market_breadth:
            breadth_pct = f"{market_breadth.breadth_ratio * 100:.0f}%"
            if market_breadth.breadth_ratio > 0.5:
                delta_text = f"涨{market_breadth.advance_count} 跌{market_breadth.decline_count}"
            else:
                delta_text = f"跌{market_breadth.decline_count} 涨{market_breadth.advance_count}"
            st.metric(
                "市场宽度",
                breadth_pct,
                delta=delta_text
            )
        else:
            st.metric("市场宽度", "数据获取中...", delta="--")

    with col4:
        # TODO: 从持仓系统获取真实数据
        st.metric(
            "持仓数量",
            "0只",
            delta="可新增"
        )

    st.divider()

    # 指数走势图
    st.subheader("📈 指数走势")
    index_history = live_service.get_index_history("sh000001", days=60)
    if index_history is not None and not index_history.empty:
        import plotly.graph_objects as go

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=index_history['date'],
            open=index_history['open'],
            high=index_history['high'],
            low=index_history['low'],
            close=index_history['close'],
            name='上证指数'
        ))
        fig.update_layout(
            height=400,
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📊 正在获取指数数据...")

    # 行业热力图
    st.subheader("🔥 行业板块涨跌")
    sector_data = live_service.get_sector_performance()
    if sector_data is not None and not sector_data.empty:
        # 创建涨跌排序视图
        col1, col2 = st.columns(2)

        with col1:
            st.write("**🔴 领涨板块**")
            top_sectors = sector_data.nlargest(10, 'change_pct')
            for _, row in top_sectors.iterrows():
                pct = row['change_pct']
                color = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
                st.write(f"{color} {row['name']}: {pct:+.2f}% ({row['leader']})")

        with col2:
            st.write("**🟢 领跌板块**")
            bottom_sectors = sector_data.nsmallest(10, 'change_pct')
            for _, row in bottom_sectors.iterrows():
                pct = row['change_pct']
                color = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
                st.write(f"{color} {row['name']}: {pct:+.2f}% ({row['leader']})")
    else:
        st.info("📊 正在获取行业数据...")

    # 数据更新时间
    if index_quote:
        st.caption(f"数据更新时间: {index_quote.update_time}")


def render_signals_positions():
    """Render signals and positions page with real trading signals."""
    st.header("📊 信号与持仓")

    tab1, tab2, tab3 = st.tabs(["📥 今日信号", "💼 当前持仓", "📊 历史信号"])

    with tab1:
        # 获取信号服务和调度器
        signal_service = get_signal_service()
        from src.services.signal_scheduler import get_signal_scheduler
        scheduler = get_signal_scheduler()
        sched_status = scheduler.get_status()

        # 确定默认日期：使用最新可用信号日期，而非当天
        today_str = datetime.now().strftime("%Y-%m-%d")
        latest_date = signal_service.get_latest_available_date()
        default_date = datetime.strptime(latest_date, "%Y-%m-%d") if latest_date else datetime.now()

        # 日期选择和刷新按钮
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            trade_date = st.date_input(
                "交易日期",
                value=default_date,
                max_value=datetime.now()
            ).strftime("%Y-%m-%d")
        # 提示：当显示的不是今天的信号时，给出说明
        if latest_date and latest_date != today_str and trade_date == latest_date:
            st.caption(f"显示最近一次信号刷新结果 ({latest_date})")
        with col2:
            refresh_info = st.empty()
        with col3:
            if st.button("🔄 刷新信号"):
                if sched_status["is_refreshing"]:
                    st.toast("信号正在刷新中，请稍候")
                else:
                    scheduler.refresh_now(trade_date)
                    st.toast("已触发后台信号刷新")
                    st.rerun()

        # 根据缓存状态决定显示内容
        has_cache = signal_service._is_cache_valid(trade_date)

        if has_cache:
            # 有缓存，直接显示
            signals_data = signal_service.get_signals(trade_date)
        elif sched_status["is_refreshing"]:
            # 后台正在刷新，显示实时进度
            current, total, code = sched_status["progress"]
            if total > 0:
                st.progress(current / total, text=f"正在分析: {code} ({current}/{total})")
            else:
                st.progress(0, text="信号刷新正在启动...")
            st.caption("页面每 3 秒自动刷新进度")
            if sched_status["next_run_time"]:
                refresh_info.caption(f"下次自动刷新: {sched_status['next_run_time']}")
            # 自动刷新页面以更新进度
            import time
            time.sleep(3)
            st.rerun()
            return
        else:
            # 无缓存且未在刷新
            st.warning("暂无信号数据")
            next_time = sched_status.get("next_run_time", "--")
            st.caption(f"下次自动刷新: {next_time}，或点击上方「刷新信号」立即生成")
            if sched_status["next_run_time"]:
                refresh_info.caption(f"下次自动刷新: {sched_status['next_run_time']}")
            return

        # 显示刷新时间信息
        last_refresh = signals_data.get('last_refresh_time')
        next_run = sched_status.get("next_run_time", "")
        info_parts = []
        if last_refresh:
            info_parts.append(f"最后刷新: {last_refresh}")
        if next_run:
            info_parts.append(f"下次: {next_run}")
        refresh_info.caption(" | ".join(info_parts) if info_parts else "最后刷新: --")

        # 显示错误信息
        if 'error' in signals_data:
            st.error(f"❌ 获取信号失败: {signals_data['error']}")

        # 信号汇总
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("分析股票数", signals_data['total'])
        with col2:
            st.metric("买入信号", len(signals_data['buy_signals']), delta="📈" if signals_data['buy_signals'] else None)
        with col3:
            st.metric("卖出信号", len(signals_data['sell_signals']), delta="📉" if signals_data['sell_signals'] else None)
        with col4:
            st.metric("持有/观望", len(signals_data['hold_signals']))
        with col5:
            sentiment = signals_data.get('market_sentiment')
            if sentiment is not None:
                sentiment_label = "偏多" if sentiment > 55 else "偏空" if sentiment < 45 else "中性"
                st.metric("市场情绪", f"{sentiment:.0f}", delta=sentiment_label)
            else:
                st.metric("市场情绪", "--", delta="未获取")

        # 市场状态和自适应权重
        regime = signals_data.get('market_regime')
        if regime:
            regime_icons = {
                "trending_bull": "📈", "trending_bear": "📉",
                "ranging": "📊", "volatile": "⚡"
            }
            icon = regime_icons.get(regime['regime'], "📊")
            st.info(
                f"{icon} **市场状态: {regime['regime_label']}** | "
                f"趋势强度 {regime['trend_strength']:.0%} | "
                f"波动率 {regime['volatility']:.0%} | "
                f"策略权重: 波段 {regime['swing_weight']:.0%} / 趋势 {regime['trend_weight']:.0%}"
            )

        st.divider()

        # 信号级别映射
        signal_level_names = {
            5: "强烈买入",
            4: "建议买入",
            3: "持有观望",
            2: "建议卖出",
            1: "强烈卖出"
        }

        # 买入信号
        st.subheader("🟢 买入信号")
        buy_signals = signals_data['buy_signals']
        if buy_signals:
            for signal in buy_signals[:10]:
                level_name = signal_level_names.get(signal.signal_level.value, "未知")
                display_name = f"{signal.stock_code} {signal.stock_name}" if signal.stock_name else signal.stock_code
                with st.expander(f"**{display_name}** | 综合得分: {signal.final_score:.1f} | {level_name}", expanded=False):
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("综合得分", f"{signal.final_score:.1f}")
                    with col2:
                        st.metric("波段得分", f"{signal.swing_score:.1f}")
                    with col3:
                        st.metric("趋势得分", f"{signal.trend_score:.1f}")
                    with col4:
                        if signal.sentiment_score is not None:
                            st.metric("情绪得分", f"{signal.sentiment_score:.1f}")
                        else:
                            st.metric("情绪得分", "--")

                    if signal.reasons:
                        st.write("**信号原因:**")
                        for reason in signal.reasons:
                            st.write(f"• {reason}")
        else:
            st.info("📭 今日暂无买入信号")

        st.divider()

        # 卖出信号
        st.subheader("🔴 卖出/止损信号")
        sell_signals = signals_data['sell_signals']
        if sell_signals:
            for signal in sell_signals[:10]:
                level_name = signal_level_names.get(signal.signal_level.value, "未知")
                display_name = f"{signal.stock_code} {signal.stock_name}" if signal.stock_name else signal.stock_code
                with st.expander(f"**{display_name}** | 综合得分: {signal.final_score:.1f} | {level_name}", expanded=False):
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("综合得分", f"{signal.final_score:.1f}")
                    with col2:
                        st.metric("波段得分", f"{signal.swing_score:.1f}")
                    with col3:
                        st.metric("趋势得分", f"{signal.trend_score:.1f}")
                    with col4:
                        if signal.sentiment_score is not None:
                            st.metric("情绪得分", f"{signal.sentiment_score:.1f}")
                        else:
                            st.metric("情绪得分", "--")

                    if signal.reasons:
                        st.write("**信号原因:**")
                        for reason in signal.reasons:
                            st.write(f"• {reason}")
        else:
            st.info("📭 今日暂无卖出信号")

        # ── 动作信号（明确买卖指令） ──
        action_buy = signals_data.get('action_buy_signals', [])
        action_sell = signals_data.get('action_sell_signals', [])

        if action_buy or action_sell:
            st.divider()
            st.subheader("🎯 动作信号（回测执行指令）")

            col_ab, col_as = st.columns(2)

            with col_ab:
                st.write(f"**BUY 信号 ({len(action_buy)})**")
                if action_buy:
                    for a in action_buy[:20]:
                        name = f"{a.stock_code} {a.stock_name}" if a.stock_name else a.stock_code
                        exit_info = ""
                        if a.exit_config:
                            parts = []
                            if a.exit_config.stop_loss_pct:
                                parts.append(f"止损{a.exit_config.stop_loss_pct}%")
                            if a.exit_config.take_profit_pct:
                                parts.append(f"止盈+{a.exit_config.take_profit_pct}%")
                            if a.exit_config.max_hold_days:
                                parts.append(f"持仓≤{a.exit_config.max_hold_days}天")
                            exit_info = " | " + ", ".join(parts)
                        st.text(f"  🟢 {name} [{a.strategy_name}] ({a.confidence_score:.0f}分){exit_info}")
                        if a.trigger_rules:
                            for r in a.trigger_rules:
                                st.caption(f"    ✓ {r}")
                else:
                    st.caption("无")

            with col_as:
                st.write(f"**SELL 信号 ({len(action_sell)})**")
                if action_sell:
                    for a in action_sell[:20]:
                        name = f"{a.stock_code} {a.stock_name}" if a.stock_name else a.stock_code
                        reason_tag = f" ({a.sell_reason.value})" if a.sell_reason else ""
                        st.text(f"  🔴 {name} [{a.strategy_name}]{reason_tag}")
                        if a.trigger_rules:
                            for r in a.trigger_rules:
                                st.caption(f"    ✓ {r}")
                else:
                    st.caption("无")

    with tab2:
        st.subheader("持仓明细")
        st.info("持仓管理功能开发中...")

        st.subheader("组合指标")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总市值", "¥0", delta="未持仓")
        with col2:
            st.metric("仓位比例", "0%", delta="空仓")
        with col3:
            st.metric("盈亏比", "--", delta="无数据")

    with tab3:
        _render_signal_history()


def _render_signal_history():
    """渲染历史信号查询页面"""
    from src.data_storage.database import Database
    db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
    if not db_path.exists():
        st.info("暂无历史信号数据")
        return

    db = Database(str(db_path))
    db.init_tables()

    # 统计概览
    total_count = db.get_signal_count()
    st.metric("数据库信号总数", f"{total_count:,}")

    # 查询条件
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input(
            "开始日期",
            value=datetime.now() - timedelta(days=7),
            key="hist_start"
        ).strftime("%Y-%m-%d")
    with col2:
        end_date = st.date_input(
            "结束日期",
            value=datetime.now(),
            key="hist_end"
        ).strftime("%Y-%m-%d")
    with col3:
        stock_filter = st.text_input("股票代码 (可选)", key="hist_stock", placeholder="如 000001")

    # 统计信息
    stats = db.get_signal_stats(start_date=start_date, end_date=end_date)
    if stats and stats.get('total', 0) > 0:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("期间信号总数", stats.get('total', 0))
        with col2:
            st.metric("买入信号", stats.get('buy_count', 0))
        with col3:
            st.metric("卖出信号", stats.get('sell_count', 0))
        with col4:
            avg_score = stats.get('avg_score')
            st.metric("平均得分", f"{avg_score:.1f}" if avg_score else "--")

        # 每日趋势
        by_date = stats.get('by_date', [])
        if by_date:
            st.subheader("每日信号统计")
            import pandas as _pd
            df_stats = _pd.DataFrame(by_date)
            if not df_stats.empty and 'trade_date' in df_stats.columns:
                df_stats = df_stats.sort_values('trade_date')
                st.dataframe(
                    df_stats[['trade_date', 'total', 'buy_count', 'sell_count', 'avg_score']].rename(columns={
                        'trade_date': '日期', 'total': '总数',
                        'buy_count': '买入', 'sell_count': '卖出', 'avg_score': '平均分'
                    }),
                    use_container_width=True,
                    hide_index=True
                )
    else:
        st.info("所选日期范围内暂无信号数据")

    # 股票历史查询
    if stock_filter:
        st.subheader(f"股票 {stock_filter} 信号历史")
        history = db.get_signal_history(stock_filter, start_date=start_date, end_date=end_date)
        if history:
            signal_level_names = {
                5: "强烈买入", 4: "建议买入", 3: "持有观望",
                2: "建议卖出", 1: "强烈卖出"
            }
            for sig in history[:20]:
                level_name = signal_level_names.get(sig.get('signal_level', 3), "未知")
                regime = sig.get('market_regime', '')
                st.write(
                    f"**{sig['trade_date']}** | "
                    f"得分 {sig['final_score']:.1f} | {level_name} | "
                    f"波段 {sig.get('swing_score', 0):.1f} / 趋势 {sig.get('trend_score', 0):.1f}"
                    + (f" | 市场: {regime}" if regime else "")
                )
        else:
            st.info(f"未找到 {stock_filter} 的历史信号")


def fetch_news_data() -> dict:
    """从后台服务缓存读取新闻数据（只读）

    前端仅负责展示，所有抓取由后台 NewsService 独立完成。

    Returns:
        包含新闻列表和统计信息的字典
    """
    # 从缓存读取（只读）
    cached = NewsService.get_cached_news()
    if cached and cached.get("news_list"):
        news_list = [
            NewsItem(
                title=n["title"],
                source=n["source"],
                sentiment_score=n["sentiment_score"],
                keywords=n.get("keywords", ""),
                url=n.get("url", ""),
                publish_time=n.get("publish_time", ""),
                content=n.get("content", "")
            )
            for n in cached.get("news_list", [])
        ]

        by_source = {"cls": [], "eastmoney": [], "sina": []}
        for news in news_list:
            if news.source in by_source:
                by_source[news.source].append(news)

        return {
            "all_news": news_list,
            "by_source": by_source,
            "overall_sentiment": cached.get("overall_sentiment", 50),
            "positive_news": [n for n in news_list if n.sentiment_score > 58],
            "negative_news": [n for n in news_list if n.sentiment_score < 42],
            "neutral_news": [n for n in news_list if 42 <= n.sentiment_score <= 58],
            "keyword_counts": cached.get("keyword_counts", []),
            "fetch_time": cached.get("fetch_time", "未知"),
            "from_cache": True
        }

    # 缓存为空，返回空数据（等待后台服务首次获取完成）
    return {
        "all_news": [],
        "by_source": {"cls": [], "eastmoney": [], "sina": []},
        "overall_sentiment": 50,
        "positive_news": [],
        "negative_news": [],
        "neutral_news": [],
        "keyword_counts": [],
        "fetch_time": "等待后台服务获取...",
        "from_cache": False
    }


def render_news_page():
    """渲染财经新闻页面"""
    st.header("📰 财经新闻")

    # 初始化分页状态
    if "news_page" not in st.session_state:
        st.session_state.news_page = 0
    if "news_filter_key" not in st.session_state:
        st.session_state.news_filter_key = ""

    # 数据库新闻总数 + 下次获取时间
    col1, col2 = st.columns(2)

    with col1:
        try:
            news_service = get_news_service()
            total_archived = news_service.get_total_news_count()
            st.metric("数据库新闻总数", f"{total_archived} 条")
        except Exception:
            st.metric("数据库新闻总数", "获取失败")
            total_archived = 0

    with col2:
        import time as _time
        cached_meta = NewsService.get_cached_news()
        fetch_ts = cached_meta.get("fetch_timestamp", 0) if cached_meta else 0

        if fetch_ts > 0:
            # 用 fetch_timestamp + 默认间隔(600秒) 计算下次获取时间
            interval = cached_meta.get("interval_seconds", 600)
            next_ts = fetch_ts + interval
            remaining = next_ts - _time.time()

            if remaining > 0:
                mins, secs = divmod(int(remaining), 60)
                next_time_str = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
                st.metric("下次自动获取", next_time_str, delta=f"剩余 {mins}分{secs}秒")
            else:
                # 已经过了预计时间，显示上次获取的时间
                last_time_str = cached_meta.get("fetch_time", "未知")
                st.metric("上次获取", last_time_str, delta="等待下次自动刷新")
        else:
            st.metric("下次自动获取", "等待首次获取", delta="服务启动中...")

    # 获取新闻数据
    news_data = fetch_news_data()

    # 市场情绪总览
    st.subheader("📊 市场情绪总览")

    col1, col2, col3, col4 = st.columns(4)

    overall = news_data["overall_sentiment"]
    sentiment_label = "偏多" if overall > 55 else "偏空" if overall < 45 else "中性"
    sentiment_color = "🟢" if overall > 55 else "🔴" if overall < 45 else "🟡"

    with col1:
        st.metric(
            "整体情绪",
            f"{overall:.1f}",
            delta=f"{sentiment_color} {sentiment_label}"
        )

    with col2:
        st.metric(
            "正面新闻",
            len(news_data["positive_news"]),
            delta="📈 利好"
        )

    with col3:
        st.metric(
            "负面新闻",
            len(news_data["negative_news"]),
            delta="📉 利空"
        )

    with col4:
        st.metric(
            "中性新闻",
            len(news_data["neutral_news"]),
            delta="➖ 观望"
        )

    cache_source = "📦 缓存" if news_data.get("from_cache") else "🌐 实时获取"
    st.caption(f"数据更新时间: {news_data['fetch_time']} ({cache_source}) | 本次获取: {len(news_data['all_news'])} 条")

    st.divider()

    # 热门关键词
    st.subheader("🔥 热门关键词")
    keywords = news_data["keyword_counts"]
    if keywords:
        keyword_html = " ".join([
            f'<span style="background-color: {"#ffcccc" if kw in NewsCrawler.NEGATIVE_KEYWORDS else "#ccffcc"}; '
            f'padding: 4px 8px; margin: 2px; border-radius: 4px; display: inline-block;">'
            f'{kw} ({count})</span>'
            for kw, count in keywords
        ])
        st.markdown(keyword_html, unsafe_allow_html=True)
    else:
        st.info("暂无热门关键词")

    st.divider()

    # 新闻列表
    st.subheader("📋 新闻列表")

    # 筛选器 + 分页设置
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        source_filter = st.selectbox(
            "数据源",
            ["全部", "财联社", "东方财富", "新浪财经"],
            index=0,
            key="news_source_filter"
        )

    with col2:
        sentiment_filter = st.selectbox(
            "情绪筛选",
            ["全部", "正面 (>58)", "负面 (<42)", "中性 (42-58)"],
            index=0,
            key="news_sentiment_filter"
        )

    with col3:
        sort_order = st.selectbox(
            "排序方式",
            ["时间倒序", "情绪高→低", "情绪低→高"],
            index=0,
            key="news_sort_order"
        )

    with col4:
        page_size = st.selectbox(
            "每页条数",
            [10, 20, 50, 100],
            index=1,
            key="news_page_size"
        )

    # 来源映射
    source_map = {
        "全部": None,
        "财联社": "cls",
        "东方财富": "eastmoney",
        "新浪财经": "sina"
    }

    source_names = {
        "cls": "财联社",
        "eastmoney": "东方财富",
        "sina": "新浪财经"
    }

    # 过滤新闻
    filtered_news = news_data["all_news"]

    if source_filter != "全部":
        source_key = source_map[source_filter]
        filtered_news = [n for n in filtered_news if n.source == source_key]

    if sentiment_filter == "正面 (>58)":
        filtered_news = [n for n in filtered_news if n.sentiment_score > 58]
    elif sentiment_filter == "负面 (<42)":
        filtered_news = [n for n in filtered_news if n.sentiment_score < 42]
    elif sentiment_filter == "中性 (42-58)":
        filtered_news = [n for n in filtered_news if 42 <= n.sentiment_score <= 58]

    # 排序
    def _parse_publish_time(news_item):
        """解析发布时间用于排序，无法解析的排到最后"""
        t = news_item.publish_time or ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                     "%Y-%m-%d", "%H:%M:%S", "%m-%d %H:%M"):
            try:
                return datetime.strptime(t, fmt)
            except ValueError:
                continue
        return datetime.min

    if sort_order == "时间倒序":
        filtered_news = sorted(filtered_news, key=_parse_publish_time, reverse=True)
    elif sort_order == "情绪高→低":
        filtered_news = sorted(filtered_news, key=lambda x: x.sentiment_score, reverse=True)
    elif sort_order == "情绪低→高":
        filtered_news = sorted(filtered_news, key=lambda x: x.sentiment_score)

    # 筛选条件变化时重置页码
    current_filter_key = f"{source_filter}|{sentiment_filter}|{sort_order}|{page_size}"
    if current_filter_key != st.session_state.news_filter_key:
        st.session_state.news_filter_key = current_filter_key
        st.session_state.news_page = 0

    # 分页计算
    total_count = len(filtered_news)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = min(st.session_state.news_page, total_pages - 1)
    start_idx = current_page * page_size
    end_idx = min(start_idx + page_size, total_count)
    page_news = filtered_news[start_idx:end_idx]

    # 分页导航回调
    def _go_page(page):
        st.session_state.news_page = page

    # 分页信息和导航
    st.caption(f"共 {total_count} 条新闻 | 第 {current_page + 1}/{total_pages} 页 | 显示第 {start_idx + 1}-{end_idx} 条")

    # 分页按钮
    if total_pages > 1:
        nav_cols = st.columns([1, 1, 2, 1, 1])

        with nav_cols[0]:
            st.button("⏮ 首页", disabled=(current_page == 0),
                      key="news_first", on_click=_go_page, args=[0])

        with nav_cols[1]:
            st.button("◀ 上一页", disabled=(current_page == 0),
                      key="news_prev", on_click=_go_page, args=[current_page - 1])

        with nav_cols[2]:
            st.caption(f"第 {current_page + 1} / {total_pages} 页")

        with nav_cols[3]:
            st.button("下一页 ▶", disabled=(current_page >= total_pages - 1),
                      key="news_next", on_click=_go_page, args=[current_page + 1])

        with nav_cols[4]:
            st.button("末页 ⏭", disabled=(current_page >= total_pages - 1),
                      key="news_last", on_click=_go_page, args=[total_pages - 1])

    # 显示当前页新闻列表
    if page_news:
        for news in page_news:
            if news.sentiment_score > 58:
                sentiment_emoji = "🟢"
            elif news.sentiment_score < 42:
                sentiment_emoji = "🔴"
            else:
                sentiment_emoji = "🟡"

            source_name = source_names.get(news.source, news.source)

            with st.container():
                col1, col2, col3 = st.columns([5, 1, 1])

                with col1:
                    st.markdown(f"**{news.title}**")

                with col2:
                    st.caption(f"📍 {source_name}")

                with col3:
                    st.caption(f"{sentiment_emoji} {news.sentiment_score:.0f}")

                with st.expander("查看详情", expanded=False):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        if news.content:
                            st.write(news.content)
                        else:
                            st.write("暂无详细内容")

                    with col2:
                        st.metric("情绪分数", f"{news.sentiment_score:.1f}")
                        if news.publish_time:
                            st.caption(f"📅 {news.publish_time}")
                        if news.keywords:
                            st.caption(f"🏷️ {news.keywords}")
                        if news.url:
                            st.link_button("🔗 原文链接", news.url)

                st.divider()
    else:
        st.info("没有符合条件的新闻")

    # 数据源统计（本次获取）
    fetch_time_str = news_data.get("fetch_time", "未知")
    st.subheader(f"📈 本次获取统计（{fetch_time_str}）")
    total_fetched = len(news_data["all_news"])
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("本次获取总数", f"{total_fetched} 条")

    with col2:
        cls_count = len(news_data["by_source"]["cls"])
        cls_avg = sum(n.sentiment_score for n in news_data["by_source"]["cls"]) / cls_count if cls_count else 50
        st.metric("财联社", f"{cls_count} 条", delta=f"情绪 {cls_avg:.1f}")

    with col3:
        em_count = len(news_data["by_source"]["eastmoney"])
        em_avg = sum(n.sentiment_score for n in news_data["by_source"]["eastmoney"]) / em_count if em_count else 50
        st.metric("东方财富", f"{em_count} 条", delta=f"情绪 {em_avg:.1f}")

    with col4:
        sina_count = len(news_data["by_source"]["sina"])
        sina_avg = sum(n.sentiment_score for n in news_data["by_source"]["sina"]) / sina_count if sina_count else 50
        st.metric("新浪财经", f"{sina_count} 条", delta=f"情绪 {sina_avg:.1f}")

    st.divider()

    # 数据库存档统计
    st.subheader("🗄️ 数据库历史存档")

    try:
        news_service = get_news_service()
        total_archived = news_service.get_total_news_count()
        db_stats = news_service.get_news_statistics()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("存档总数", f"{total_archived} 条")

        with col2:
            avg_sent = db_stats.get("avg_sentiment", 50)
            st.metric("历史平均情绪", f"{avg_sent:.1f}")

        with col3:
            dist = db_stats.get("sentiment_distribution", {})
            positive = dist.get("positive", 0)
            st.metric("历史正面新闻", f"{positive} 条")

        with col4:
            negative = dist.get("negative", 0)
            st.metric("历史负面新闻", f"{negative} 条")

        # 历史趋势
        if db_stats.get("by_date"):
            with st.expander("📅 每日新闻统计", expanded=False):
                for day_stat in db_stats["by_date"][:7]:
                    date = day_stat.get("fetch_date", "")
                    count = day_stat.get("count", 0)
                    avg = day_stat.get("avg_sentiment", 50)
                    emoji = "🟢" if avg > 55 else "🔴" if avg < 45 else "🟡"
                    st.write(f"{emoji} {date}: {count} 条新闻, 平均情绪 {avg:.1f}")

    except Exception as e:
        st.warning(f"获取存档统计失败: {e}")


def load_config() -> Config | None:
    """Load configuration file.

    Returns:
        Config instance or None if load fails
    """
    try:
        config_path = project_root / "config" / "config.yaml"
        return Config(str(config_path))
    except ConfigError:
        return None


def save_tushare_token(token: str) -> bool:
    """Save TuShare token to config file.

    Args:
        token: TuShare API token

    Returns:
        True if save successful, False otherwise
    """
    try:
        config_path = project_root / "config" / "config.yaml"
        config = Config(str(config_path))
        config.set("data_sources.tushare.token", token)
        config.save()
        return True
    except Exception:
        return False


def save_data_source(primary: str, fallback_enabled: bool) -> bool:
    """Save data source configuration (legacy, single primary).

    Args:
        primary: Primary data source ('tushare' or 'akshare')
        fallback_enabled: Whether to enable fallback to other source

    Returns:
        True if save successful, False otherwise
    """
    try:
        config_path = project_root / "config" / "config.yaml"
        config = Config(str(config_path))
        config.set("data_sources.primary", primary)
        config.set("data_sources.fallback_enabled", fallback_enabled)
        config.save()
        return True
    except Exception:
        return False


def save_data_sources(sources: dict, fallback_enabled: bool) -> bool:
    """Save per-category data source configuration.

    Args:
        sources: Dict mapping category to data source ('tushare' or 'akshare')
        fallback_enabled: Whether to enable fallback to other source

    Returns:
        True if save successful, False otherwise
    """
    try:
        config_path = project_root / "config" / "config.yaml"
        config = Config(str(config_path))

        for category, source in sources.items():
            config.set(f"data_sources.{category}", source)

        config.set("data_sources.fallback_enabled", fallback_enabled)
        config.save()
        return True
    except Exception:
        return False


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

    # 数据源配置
    st.subheader("🔑 数据源配置")

    # 加载当前配置
    config = load_config()
    current_token = ""
    current_fallback = True

    # 数据分类配置
    data_categories = {
        "realtime_quotes": {"name": "📊 实时行情", "desc": "股票实时价格、涨跌幅"},
        "historical_daily": {"name": "📈 历史日线", "desc": "K线数据、历史行情"},
        "index_data": {"name": "📉 指数数据", "desc": "上证、深证、创业板指数"},
        "sector_data": {"name": "🏭 行业板块", "desc": "行业涨跌排行、板块数据"},
        "money_flow": {"name": "💰 资金流向", "desc": "主力资金、大单小单流向"},
        "stock_list": {"name": "📋 股票列表", "desc": "A股股票代码、名称"},
    }

    # 当前各分类的数据源
    current_sources = {}
    if config:
        current_token = config.get("data_sources.tushare.token", "")
        current_fallback = config.get("data_sources.fallback_enabled", True)
        for key in data_categories:
            current_sources[key] = config.get(f"data_sources.{key}", "akshare")

    # 数据源对比说明
    with st.expander("📖 数据源对比说明", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **🆓 AkShare**
            - ✅ 完全免费，无需注册
            - ✅ 实时行情数据全面
            - ✅ 行业板块数据丰富
            - ⚠️ 资金流向数据有限
            - ⚠️ 部分接口不稳定
            """)
        with col2:
            st.markdown("""
            **🔐 TuShare Pro**
            - ✅ 数据更全面准确
            - ✅ 资金流向详细
            - ✅ 历史数据完整
            - ❌ 需要Token
            - ❌ 部分接口需积分
            """)

    st.write("**为每个数据分类选择数据源：**")

    # 创建表格式的选择界面
    selected_sources = {}

    for key, info in data_categories.items():
        col1, col2, col3 = st.columns([2, 3, 2])

        with col1:
            st.write(info["name"])

        with col2:
            st.caption(info["desc"])

        with col3:
            current_val = current_sources.get(key, "akshare")
            selected_sources[key] = st.selectbox(
                f"数据源-{key}",
                options=["akshare", "tushare"],
                index=0 if current_val == "akshare" else 1,
                format_func=lambda x: "🆓 AkShare" if x == "akshare" else "🔐 TuShare",
                label_visibility="collapsed",
                key=f"source_{key}"
            )

    st.divider()

    # 备用数据源开关
    fallback_enabled = st.checkbox(
        "🔄 启用备用数据源（主数据源失败时自动切换到另一个）",
        value=current_fallback
    )

    # 一键设置按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🆓 全部使用 AkShare", use_container_width=True):
            for key in data_categories:
                st.session_state[f"source_{key}"] = "akshare"
            st.rerun()
    with col2:
        if st.button("🔐 全部使用 TuShare", use_container_width=True):
            for key in data_categories:
                st.session_state[f"source_{key}"] = "tushare"
            st.rerun()
    with col3:
        if st.button("⚡ 推荐配置", use_container_width=True, help="AkShare实时+TuShare资金流向"):
            st.session_state["source_realtime_quotes"] = "akshare"
            st.session_state["source_historical_daily"] = "akshare"
            st.session_state["source_index_data"] = "akshare"
            st.session_state["source_sector_data"] = "akshare"
            st.session_state["source_money_flow"] = "tushare"
            st.session_state["source_stock_list"] = "akshare"
            st.rerun()

    # 保存数据源设置
    if st.button("💾 保存数据源设置", type="primary", use_container_width=True):
        if save_data_sources(selected_sources, fallback_enabled):
            reload_live_data_service()
            st.success("✅ 数据源设置已保存！")
            st.rerun()
        else:
            st.error("❌ 保存失败")

    st.divider()

    # TuShare Token 配置
    needs_tushare = any(v == "tushare" for v in selected_sources.values()) or fallback_enabled

    if needs_tushare:
        st.subheader("🎫 TuShare Token")

        if current_token and current_token != "YOUR_TUSHARE_TOKEN":
            masked_token = current_token[:8] + "*" * (len(current_token) - 12) + current_token[-4:]
            st.success(f"✅ Token 已配置: {masked_token}")
        else:
            tushare_categories = [info["name"] for key, info in data_categories.items()
                                  if selected_sources.get(key) == "tushare"]
            if tushare_categories:
                st.error(f"⚠️ 以下分类使用 TuShare，请配置 Token: {', '.join(tushare_categories)}")
            else:
                st.warning("💡 配置 TuShare Token 可在 AkShare 失败时自动切换")

        with st.form("tushare_token_form"):
            new_token = st.text_input(
                "TuShare Token",
                type="password",
                placeholder="请输入您的TuShare Token",
                help="从 https://tushare.pro 获取您的Token"
            )
            submitted = st.form_submit_button("💾 保存Token", use_container_width=True)

            if submitted:
                if new_token:
                    if save_tushare_token(new_token):
                        st.success("✅ Token已保存！")
                        st.rerun()
                    else:
                        st.error("❌ 保存失败")
                else:
                    st.warning("请输入Token")

        # TuShare 接口限速配置
        st.subheader("⏱️ TuShare 接口限速")
        current_rate_limit = config.get("data_sources.tushare.rate_limit", 450) if config else 450
        new_rate_limit = st.number_input(
            "每分钟最大请求数",
            min_value=50, max_value=2000, value=int(current_rate_limit), step=50,
            help="TuShare 免费用户限制 500次/分钟，建议设置 450 留安全余量。高级用户可根据权限调大。",
            key="tushare_rate_limit"
        )
        if st.button("💾 保存限速设置", key="save_tushare_rate"):
            if config:
                config.set("data_sources.tushare.rate_limit", int(new_rate_limit))
                config.save()
                st.success(f"✅ TuShare 限速已设为 {int(new_rate_limit)} 次/分钟")
                st.rerun()
            else:
                st.error("❌ 配置文件加载失败")

        st.divider()

    # 信号自动刷新配置
    st.subheader("🕐 信号自动刷新")

    current_refresh_hour = config.get("signals.auto_refresh_hour", 19) if config else 19
    current_refresh_minute = config.get("signals.auto_refresh_minute", 0) if config else 0

    col1, col2 = st.columns(2)
    with col1:
        new_refresh_hour = st.number_input(
            "刷新时间（时）", min_value=0, max_value=23,
            value=current_refresh_hour, key="signal_refresh_hour"
        )
    with col2:
        new_refresh_minute = st.number_input(
            "刷新时间（分）", min_value=0, max_value=59,
            value=current_refresh_minute, step=5, key="signal_refresh_min"
        )

    # 显示服务状态
    from src.services.signal_scheduler import get_signal_scheduler
    scheduler = get_signal_scheduler()
    sched_status = scheduler.get_status()

    if sched_status["running"]:
        st.success(
            f"✅ 信号自动刷新服务运行中 | "
            f"每天 {sched_status['refresh_hour']:02d}:{sched_status['refresh_minute']:02d} 刷新"
        )
        col_a, col_b = st.columns(2)
        with col_a:
            last_run = sched_status.get("last_run_date")
            st.caption(f"上次运行: {last_run or '尚未运行'}")
        with col_b:
            next_run = sched_status.get("next_run_time")
            st.caption(f"下次运行: {next_run or '--'}")

        if sched_status["is_refreshing"]:
            current, total, code = sched_status["progress"]
            if total > 0:
                st.progress(current / total)
                st.caption(f"正在刷新: {code} ({current}/{total})")
            else:
                st.caption("正在启动刷新...")
    else:
        st.warning("⚠️ 信号自动刷新服务未运行")

    if st.button("💾 保存刷新时间设置", key="save_signal_refresh"):
        if config:
            config.set("signals.auto_refresh_hour", int(new_refresh_hour))
            config.set("signals.auto_refresh_minute", int(new_refresh_minute))
            config.save()
            scheduler.update_schedule(int(new_refresh_hour), int(new_refresh_minute))
            st.success(f"✅ 信号刷新时间已更新为 {int(new_refresh_hour):02d}:{int(new_refresh_minute):02d}")
            st.rerun()
        else:
            st.error("❌ 配置文件加载失败")

    st.divider()

    st.subheader("💼 组合参数")
    col1, col2 = st.columns(2)

    with col1:
        st.number_input("总资金 (¥)", value=100000, step=10000)
        st.slider("目标仓位", 0.0, 1.0, 0.6, 0.05)

    with col2:
        st.number_input("最大单股仓位 (%)", value=25, step=5)
        st.number_input("最大持股数", value=10, step=1)

    st.divider()

    st.subheader("🛡️ 止损参数")
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
    elif page == "财经新闻":
        render_news_page()
    elif page == "策略回测":
        render_backtest_page()
    elif page == "策略管理":
        render_indicator_manager()
    elif page == "系统设置":
        render_settings()
    else:
        render_market_overview()


def main():
    """Main application entry point."""
    setup_page()
    setup_session_state()

    # 确保新闻后台服务正在运行（模块热重载后全局实例会丢失）
    svc = get_news_service()
    if not svc._running:
        svc.start()

    # 确保信号自动刷新服务正在运行
    from src.services.signal_scheduler import start_signal_scheduler
    start_signal_scheduler()

    if not st.session_state.authenticated:
        render_login_page()
    else:
        render_sidebar()
        render_current_page()


if __name__ == "__main__":
    main()

