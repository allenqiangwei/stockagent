"""回测页面：选择策略和日期范围，运行回测并展示结果。"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd


def _get_db():
    """获取数据库实例"""
    from src.data_storage.database import Database
    db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(str(db_path))
    db.init_tables()
    return db


def _get_enabled_strategies():
    """获取所有已启用的策略"""
    db = _get_db()
    strategies = db.get_all_strategies()
    return [s for s in strategies if s.get("enabled")]


def _run_backtest(strategy, start_date_str, end_date_str, capital, stock_codes):
    """执行回测（在 Streamlit 脚本运行期间同步执行）"""
    from src.backtest.engine import BacktestEngine
    from src.dashboard.signal_data_service import LiveHistoricalDataAdapter

    engine = BacktestEngine(capital_per_trade=capital)
    adapter = LiveHistoricalDataAdapter()

    progress_bar = st.progress(0)
    status_text = st.empty()

    stock_data = {}
    total = len(stock_codes)

    for i, code in enumerate(stock_codes, 1):
        status_text.text(f"加载数据: {code} ({i}/{total})")
        progress_bar.progress(i / total * 0.5)  # 数据加载占 50%

        df = adapter.load_daily(code, start_date_str.replace("-", ""), end_date_str.replace("-", ""))
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df

    if not stock_data:
        progress_bar.empty()
        status_text.empty()
        st.warning("没有可用的股票数据，请检查日期范围或股票列表")
        return None

    status_text.text(f"运行回测: {len(stock_data)} 只股票...")

    def batch_progress(current, total_count, code):
        pct = 0.5 + (current / total_count * 0.5)
        progress_bar.progress(min(pct, 1.0))
        status_text.text(f"回测中: {code} ({current}/{total_count})")

    result = engine.run_batch(strategy, stock_data, progress_callback=batch_progress)

    progress_bar.progress(1.0)
    status_text.text("回测完成！")

    # 保存到数据库
    try:
        db = _get_db()
        run_id = db.save_backtest_run(strategy["id"], result)
        db.save_backtest_trades(run_id, result.trades)
    except Exception as e:
        st.warning(f"保存回测结果到数据库失败: {e}")

    progress_bar.empty()
    status_text.empty()

    return result


def _render_result(result):
    """渲染回测结果"""
    # 概览指标卡片
    st.subheader("📊 回测概览")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总交易次数", result.total_trades)
        st.metric("盈利次数", result.win_trades)
    with col2:
        win_color = "normal" if result.win_rate >= 50 else "inverse"
        st.metric("胜率", f"{result.win_rate:.1f}%", delta_color=win_color)
        st.metric("亏损次数", result.lose_trades)
    with col3:
        ret_delta = "盈利" if result.total_return_pct > 0 else "亏损"
        st.metric("累计收益率", f"{result.total_return_pct:.2f}%", delta=ret_delta)
        st.metric("平均单笔收益", f"{result.avg_pnl_pct:.2f}%")
    with col4:
        st.metric("最大回撤", f"{result.max_drawdown_pct:.2f}%")
        st.metric("平均持有天数", f"{result.avg_hold_days:.1f}")

    st.divider()

    # 卖出原因分布
    if result.sell_reason_stats:
        st.subheader("📋 卖出原因分布")
        reason_labels = {
            "stop_loss": "止损",
            "take_profit": "止盈",
            "max_hold": "持有到期",
            "strategy_exit": "策略卖出",
            "end_of_backtest": "回测结束平仓",
        }
        cols = st.columns(len(result.sell_reason_stats))
        for i, (reason, count) in enumerate(result.sell_reason_stats.items()):
            with cols[i % len(cols)]:
                label = reason_labels.get(reason, reason)
                st.metric(label, count)

    st.divider()

    # 权益曲线
    if result.equity_curve:
        st.subheader("📈 权益曲线")
        eq_df = pd.DataFrame(result.equity_curve)
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date")

        st.line_chart(eq_df["equity"])

    st.divider()

    # 交易明细表
    if result.trades:
        st.subheader("📝 交易明细")

        reason_labels = {
            "stop_loss": "止损",
            "take_profit": "止盈",
            "max_hold": "持有到期",
            "strategy_exit": "策略卖出",
            "end_of_backtest": "回测结束",
        }

        trade_rows = []
        for t in result.trades:
            trade_rows.append({
                "股票代码": t.stock_code,
                "买入日期": t.buy_date,
                "买入价": f"{t.buy_price:.2f}",
                "卖出日期": t.sell_date or "-",
                "卖出价": f"{t.sell_price:.2f}" if t.sell_price else "-",
                "收益率%": f"{t.pnl_pct:.2f}" if t.pnl_pct is not None else "-",
                "持有天数": t.hold_days,
                "卖出原因": reason_labels.get(t.sell_reason, t.sell_reason or "-"),
            })

        trade_df = pd.DataFrame(trade_rows)
        st.dataframe(trade_df, use_container_width=True, hide_index=True)


def _render_history():
    """渲染历史回测记录"""
    db = _get_db()
    runs = db.get_backtest_runs(limit=20)

    if not runs:
        st.info("暂无历史回测记录")
        return

    st.subheader("📜 历史回测记录")

    for run in runs:
        win_rate = run.get("win_rate", 0)
        total_ret = run.get("total_return_pct", 0)
        ret_emoji = "🟢" if total_ret > 0 else "🔴" if total_ret < 0 else "⚪"

        with st.expander(
            f"{ret_emoji} {run['strategy_name']} | "
            f"{run['start_date']} ~ {run['end_date']} | "
            f"收益 {total_ret:.2f}% | 胜率 {win_rate:.1f}% | "
            f"{run.get('total_trades', 0)} 笔交易 | "
            f"{run.get('created_at', '')}",
            expanded=False,
        ):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("总交易", run.get("total_trades", 0))
            with col2:
                st.metric("胜率", f"{win_rate:.1f}%")
            with col3:
                st.metric("累计收益", f"{total_ret:.2f}%")
            with col4:
                st.metric("最大回撤", f"{run.get('max_drawdown_pct', 0):.2f}%")

            # 加载交易明细
            run_id = run.get("id")
            if run_id and st.button(f"查看交易明细", key=f"trades_{run_id}"):
                trades = db.get_backtest_trades(run_id)
                if trades:
                    st.dataframe(
                        pd.DataFrame(trades),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("无交易明细")

            # 从 result_json 恢复权益曲线
            result_json = run.get("result_json")
            if result_json:
                try:
                    result_data = json.loads(result_json)
                    eq_curve = result_data.get("equity_curve", [])
                    if eq_curve:
                        eq_df = pd.DataFrame(eq_curve)
                        eq_df["date"] = pd.to_datetime(eq_df["date"])
                        eq_df = eq_df.set_index("date")
                        st.line_chart(eq_df["equity"])
                except (json.JSONDecodeError, KeyError):
                    pass


def render_backtest_page():
    """回测页面主入口"""
    st.header("🔬 策略回测")

    tab1, tab2 = st.tabs(["🚀 运行回测", "📜 历史记录"])

    with tab1:
        _render_run_tab()

    with tab2:
        _render_history()


def _render_run_tab():
    """渲染「运行回测」标签页"""
    from src.dashboard.signal_data_service import get_signal_service

    # 参数设置区
    st.subheader("参数设置")

    strategies = _get_enabled_strategies()
    if not strategies:
        st.warning("没有已启用的策略。请先在「策略管理」页面创建并启用策略。")
        return

    strategy_names = [s["name"] for s in strategies]
    col1, col2 = st.columns(2)

    with col1:
        selected_name = st.selectbox("选择策略", strategy_names, key="bt_strategy")

    with col2:
        capital = st.number_input(
            "每笔金额 (元)",
            min_value=1000,
            max_value=1000000,
            value=10000,
            step=1000,
            key="bt_capital",
        )

    # 初始化日期默认值（只在首次运行时设置）
    if "bt_start" not in st.session_state:
        st.session_state["bt_start"] = (datetime.now() - timedelta(days=180)).date()
    if "bt_end" not in st.session_state:
        st.session_state["bt_end"] = datetime.now().date()

    # 快速周期选择
    def _set_period(days):
        st.session_state["bt_start"] = (datetime.now() - timedelta(days=days)).date()

    period_cols = st.columns([1, 1, 1, 1, 2])
    with period_cols[0]:
        st.button("6个月", on_click=_set_period, args=[180], key="bp_6m", use_container_width=True)
    with period_cols[1]:
        st.button("1年", on_click=_set_period, args=[365], key="bp_1y", use_container_width=True)
    with period_cols[2]:
        st.button("2年", on_click=_set_period, args=[730], key="bp_2y", use_container_width=True)
    with period_cols[3]:
        st.button("3年", on_click=_set_period, args=[1095], key="bp_3y", use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        start_date = st.date_input(
            "开始日期",
            key="bt_start",
        )
    with col4:
        end_date = st.date_input(
            "结束日期",
            max_value=datetime.now(),
            key="bt_end",
        )

    # 股票范围选择
    scope = st.radio(
        "股票范围",
        ["样本股票 (20只热门)", "全部股票", "自定义列表"],
        horizontal=True,
        key="bt_scope",
    )

    signal_service = get_signal_service()

    if scope == "样本股票 (20只热门)":
        stock_codes = signal_service.get_sample_stock_codes(20)
        st.caption(f"将回测 {len(stock_codes)} 只热门股票")
    elif scope == "全部股票":
        all_codes = signal_service.get_all_stock_codes()
        # 过滤：只保留沪深主板(000/001/600/601/603)、中小板(002/003)、
        # 创业板(300/301)、科创板(688)，排除北交所(8/4/920)和B股(200/900)
        stock_codes = [
            c for c in all_codes
            if c[:1] in ("0", "3", "6") and not c.startswith("9")
        ]
        if stock_codes:
            st.caption(f"将回测 {len(stock_codes)} 只沪深A股（耗时较长，请耐心等待）")
        else:
            st.warning("无法获取股票列表，请检查网络连接或 TuShare 配置")
            stock_codes = []
    else:
        custom_input = st.text_area(
            "输入股票代码（逗号或换行分隔）",
            placeholder="000001, 600519, 000858",
            key="bt_custom_stocks",
        )
        stock_codes = [
            c.strip()
            for c in custom_input.replace("\n", ",").split(",")
            if c.strip()
        ]
        if stock_codes:
            st.caption(f"将回测 {len(stock_codes)} 只股票")

    # 显示策略详情
    selected_strategy = next((s for s in strategies if s["name"] == selected_name), None)
    if selected_strategy:
        exit_cfg = selected_strategy.get("exit_config", {})
        buy_count = len(selected_strategy.get("buy_conditions", []))
        sell_count = len(selected_strategy.get("sell_conditions", []))

        parts = []
        if exit_cfg.get("stop_loss_pct"):
            parts.append(f"止损 {exit_cfg['stop_loss_pct']}%")
        if exit_cfg.get("take_profit_pct"):
            parts.append(f"止盈 +{exit_cfg['take_profit_pct']}%")
        if exit_cfg.get("max_hold_days"):
            parts.append(f"最长持有 {exit_cfg['max_hold_days']} 天")

        st.info(
            f"📋 **{selected_name}**: {selected_strategy.get('description', '')} | "
            f"买入条件 {buy_count} 个 (AND) | 卖出条件 {sell_count} 个 (OR) | "
            + " | ".join(parts)
        )

    st.divider()

    # 开始回测按钮
    if st.button("🚀 开始回测", type="primary", use_container_width=True, key="bt_run"):
        if not stock_codes:
            st.error("请输入至少一只股票代码")
            return

        if start_date >= end_date:
            st.error("开始日期必须早于结束日期")
            return

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        result = _run_backtest(
            selected_strategy, start_str, end_str, capital, stock_codes
        )

        if result:
            st.session_state["backtest_result"] = result

    # 显示结果（从 session_state 恢复，支持 Streamlit rerun）
    if "backtest_result" in st.session_state and st.session_state["backtest_result"]:
        result = st.session_state["backtest_result"]
        st.divider()
        _render_result(result)
