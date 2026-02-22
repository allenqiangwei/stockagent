"""信号策略管理页面"""

import streamlit as st
from pathlib import Path

from src.data_storage.database import Database
from src.signals.rule_engine import (
    INDICATOR_GROUPS, OPERATORS, get_default_params
)


def _get_db() -> Database:
    """获取数据库实例并确保表已初始化"""
    db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
    db = Database(str(db_path))
    db.init_tables()
    db.seed_default_indicators_and_strategies()
    return db


def render_indicator_manager():
    """渲染策略管理页面"""
    st.header("📊 策略管理")

    db = _get_db()

    with st.expander("📖 策略模型说明", expanded=False):
        st.markdown("""
**每个策略由买入条件、卖出条件和风控设置构成：**

- **买入条件（AND 逻辑）**：所有条件同时满足时触发买入信号
- **卖出条件（OR 逻辑）**：任一条件满足即触发卖出信号
- **风控设置**：止损/止盈/最长持有天数（全局安全网）

**回测系统**会根据这些条件精确执行买卖操作，计算收益率。
        """)

    strategies = db.get_all_strategies()

    st.subheader(f"当前策略 ({len(strategies)} 个)")

    if not strategies:
        st.info("暂无策略配置，请点击下方创建")
    else:
        for strategy in strategies:
            _render_strategy_card(db, strategy)

    st.divider()
    st.subheader("➕ 新建策略")
    _render_add_strategy_form(db)


def _render_strategy_card(db: Database, strategy: dict):
    """渲染单个策略卡片"""
    s_id = strategy["id"]
    enabled = bool(strategy["enabled"])
    weight = strategy.get("weight", 0.5)

    col1, col2 = st.columns([5, 1])

    with col1:
        status = "🟢" if enabled else "🔴"
        st.markdown(f"**{status} {strategy['name']}** (权重 {weight:.0%})")

    with col2:
        new_enabled = st.toggle(
            "启用", value=enabled, key=f"strat_toggle_{s_id}")
        if new_enabled != enabled:
            db.update_strategy(s_id, enabled=new_enabled)
            st.rerun()

    if strategy.get("description"):
        st.caption(strategy["description"])

    buy_conds = strategy.get("buy_conditions", [])
    sell_conds = strategy.get("sell_conditions", [])
    exit_cfg = strategy.get("exit_config", {})

    # 显示买入/卖出条件详情
    if buy_conds:
        st.markdown(f"**🟢 买入条件（AND — 全部满足）：**")
        for cond in buy_conds:
            if isinstance(cond, str):
                st.text(f"    ✅ {cond}")
            else:
                label = cond.get("label", _format_condition_display(cond))
                st.text(f"    ✅ {label}")

    if sell_conds:
        st.markdown(f"**🔴 卖出条件（OR — 任一触发）：**")
        for cond in sell_conds:
            if isinstance(cond, str):
                st.text(f"    🚫 {cond}")
            else:
                label = cond.get("label", _format_condition_display(cond))
                st.text(f"    🚫 {label}")

    if exit_cfg:
        exit_parts = []
        if exit_cfg.get("stop_loss_pct"):
            exit_parts.append(f"止损 {exit_cfg['stop_loss_pct']}%")
        if exit_cfg.get("take_profit_pct"):
            exit_parts.append(f"止盈 +{exit_cfg['take_profit_pct']}%")
        if exit_cfg.get("max_hold_days"):
            exit_parts.append(f"最长持有 {exit_cfg['max_hold_days']}天")
        if exit_parts:
            st.caption(f"🛡️ 风控: {' | '.join(exit_parts)}")

    with st.expander(f"编辑 {strategy['name']}", expanded=False):
        _render_strategy_edit_form(db, strategy)


def _render_strategy_edit_form(db: Database, strategy: dict):
    """渲染策略编辑表单"""
    s_id = strategy["id"]

    new_name = st.text_input("策略名称", value=strategy["name"],
                             key=f"strat_name_{s_id}")
    new_desc = st.text_area("策略描述", value=strategy.get("description", ""),
                            key=f"strat_desc_{s_id}")
    new_weight = st.slider("策略权重", 0.0, 1.0,
                           value=float(strategy.get("weight", 0.5)),
                           step=0.05, key=f"strat_weight_{s_id}",
                           help="多策略组合时此策略的权重占比")

    # ── 买入触发条件 ──
    st.divider()
    st.write("**买入触发条件（AND 逻辑 — 全部满足才买入）：**")
    buy_conds = list(strategy.get("buy_conditions", []))
    _render_condition_list(db, s_id, buy_conds, "buy")

    st.write("添加买入条件：")
    _render_add_condition_form(db, s_id, buy_conds, "buy")

    # ── 卖出触发条件 ──
    st.divider()
    st.write("**卖出触发条件（OR 逻辑 — 任一满足就卖出）：**")
    sell_conds = list(strategy.get("sell_conditions", []))
    _render_condition_list(db, s_id, sell_conds, "sell")

    st.write("添加卖出条件：")
    _render_add_condition_form(db, s_id, sell_conds, "sell")

    # ── 风控设置 ──
    st.divider()
    st.write("**风控设置（全局安全网）：**")
    exit_cfg = strategy.get("exit_config", {})
    col_sl, col_tp, col_mh = st.columns(3)
    with col_sl:
        new_stop_loss = st.number_input(
            "止损 %", value=float(exit_cfg.get("stop_loss_pct", -8.0)),
            step=1.0, max_value=0.0, key=f"exit_sl_{s_id}",
            help="负数，如 -8.0 表示亏损 8% 时止损")
    with col_tp:
        new_take_profit = st.number_input(
            "止盈 %", value=float(exit_cfg.get("take_profit_pct", 20.0)),
            step=1.0, min_value=0.0, key=f"exit_tp_{s_id}",
            help="正数，如 20.0 表示盈利 20% 时止盈")
    with col_mh:
        new_max_hold = st.number_input(
            "最长持有天数", value=int(exit_cfg.get("max_hold_days", 30)),
            step=1, min_value=1, key=f"exit_mh_{s_id}",
            help="超过此天数强制卖出")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存策略信息", key=f"strat_save_{s_id}"):
            new_exit_config = {
                "stop_loss_pct": new_stop_loss,
                "take_profit_pct": new_take_profit,
                "max_hold_days": new_max_hold,
            }
            db.update_strategy(s_id, name=new_name, description=new_desc,
                               weight=new_weight, exit_config=new_exit_config)
            st.success(f"策略 {new_name} 已更新")
            st.rerun()
    with col2:
        if st.button("🗑️ 删除策略", key=f"strat_del_{s_id}", type="secondary"):
            db.delete_strategy(s_id)
            st.success("策略已删除")
            st.rerun()


# ── 条件列表 & 添加表单（买入/卖出触发条件）───────────────

def _format_condition_display(cond) -> str:
    """格式化条件为可读字符串（不带 score）"""
    if isinstance(cond, str):
        return cond
    field = cond.get("field", "?")
    operator = cond.get("operator", "?")
    compare_type = cond.get("compare_type", "value")
    params = cond.get("params")

    from src.signals.rule_engine import _format_field_with_params
    field_label = _format_field_with_params(field, params)

    if compare_type == "field":
        compare_field = cond.get("compare_field", "?")
        compare_params = cond.get("compare_params")
        compare_label = _format_field_with_params(compare_field, compare_params)
        return f"{field_label} {operator} {compare_label}"
    else:
        return f"{field_label} {operator} {cond.get('compare_value', 0)}"


def _render_condition_list(db: Database, strategy_id: int, conditions: list, cond_type: str):
    """渲染条件列表（带删除按钮）"""
    if not conditions:
        st.caption("暂无条件")
        return

    conds_to_keep = []
    for i, cond in enumerate(conditions):
        col1, col2 = st.columns([6, 1])
        with col1:
            if isinstance(cond, str):
                label = cond
            else:
                label = cond.get("label", _format_condition_display(cond))
            st.text(f"  {'🟢' if cond_type == 'buy' else '🔴'} {label}")
        with col2:
            if st.button("❌", key=f"del_{cond_type}_cond_{strategy_id}_{i}"):
                continue
        conds_to_keep.append(cond)

    if len(conds_to_keep) < len(conditions):
        if cond_type == "buy":
            db.update_strategy(strategy_id, buy_conditions=conds_to_keep)
        else:
            db.update_strategy(strategy_id, sell_conditions=conds_to_keep)
        st.rerun()


def _render_add_condition_form(db: Database, strategy_id: int, current_conds: list, cond_type: str):
    """渲染添加条件的表单（买入或卖出）"""
    field_display, field_codes, field_groups = _build_field_options()
    operator_options = [f"{op} ({label})" for op, label in OPERATORS]
    operator_codes = [op[0] for op in OPERATORS]
    prefix = f"add_{cond_type}_cond_{strategy_id}"

    col1, col2 = st.columns([3, 1])
    with col1:
        field_sel = st.selectbox("指标", field_display, key=f"{prefix}_field")
        idx = field_display.index(field_sel)
        selected_field = field_codes[idx]
        selected_group = field_groups[idx]
    with col2:
        op_sel = st.selectbox("运算符", operator_options, key=f"{prefix}_op")
        selected_op = operator_codes[operator_options.index(op_sel)]

    params = _render_params_input(selected_group, key_prefix=f"{prefix}_p")

    compare_type = st.radio(
        "比较对象", ["固定数值", "另一个指标"],
        key=f"{prefix}_ctype", horizontal=True)

    compare_field = None
    compare_params = None
    compare_value = 0.0

    if compare_type == "固定数值":
        compare_value = st.number_input(
            "比较值", value=0.0, step=1.0,
            key=f"{prefix}_val", format="%.2f")
    else:
        cf_sel = st.selectbox("比较字段", field_display, key=f"{prefix}_cf")
        cf_idx = field_display.index(cf_sel)
        compare_field = field_codes[cf_idx]
        cf_group = field_groups[cf_idx]
        compare_params = _render_params_input(cf_group, key_prefix=f"{prefix}_cp")

    label = st.text_input("条件说明", placeholder="如：RSI超卖(<30)",
                          key=f"{prefix}_label")

    btn_text = "➕ 添加买入条件" if cond_type == "buy" else "➕ 添加卖出条件"
    if st.button(btn_text, key=f"{prefix}_btn"):
        new_cond = {
            "field": selected_field,
            "operator": selected_op,
            "label": label or _format_condition_display({
                "field": selected_field, "operator": selected_op,
                "compare_type": "value" if compare_type == "固定数值" else "field",
                "compare_value": compare_value, "compare_field": compare_field,
            }),
        }

        if params:
            defaults = get_default_params(selected_field)
            if params != defaults:
                new_cond["params"] = params

        if compare_type == "固定数值":
            new_cond["compare_type"] = "value"
            new_cond["compare_value"] = float(compare_value)
        else:
            new_cond["compare_type"] = "field"
            new_cond["compare_field"] = compare_field
            if compare_params:
                cf_defaults = get_default_params(compare_field)
                if compare_params != cf_defaults:
                    new_cond["compare_params"] = compare_params

        updated = current_conds + [new_cond]
        if cond_type == "buy":
            db.update_strategy(strategy_id, buy_conditions=updated)
        else:
            db.update_strategy(strategy_id, sell_conditions=updated)
        st.success(f"条件已添加")
        st.rerun()


# ── 构建字段选择列表 ──────────────────────────────────────

def _build_field_options():
    """构建分组的字段选择列表

    Returns:
        (display_list, field_code_list, group_list)
        display_list: ["[RSI] RSI", "[MACD] MACD线", ...]
        field_code_list: ["RSI", "MACD", ...]
        group_list: ["RSI", "MACD", ...]
    """
    display = []
    codes = []
    groups = []
    for group_name, group_def in INDICATOR_GROUPS.items():
        for sub_field, sub_label in group_def["sub_fields"]:
            display.append(f"[{group_def['label']}] {sub_label}")
            codes.append(sub_field)
            groups.append(group_name)
    return display, codes, groups


def _render_params_input(group_name: str, key_prefix: str) -> dict:
    """渲染指标参数输入框，返回用户设置的参数

    Args:
        group_name: 指标分组名（如 "RSI", "MACD"）
        key_prefix: Streamlit widget key 前缀

    Returns:
        参数字典（如 {"period": 7}），无参数时返回空字典
    """
    group_def = INDICATOR_GROUPS.get(group_name)
    if not group_def or not group_def["params"]:
        return {}

    params = {}
    param_defs = group_def["params"]
    cols = st.columns(len(param_defs))

    for i, (param_key, param_info) in enumerate(param_defs.items()):
        with cols[i]:
            default_val = param_info["default"]
            params[param_key] = st.number_input(
                param_info["label"],
                value=default_val,
                step=1,
                min_value=1,
                key=f"{key_prefix}_{param_key}"
            )

    return params


def _render_add_strategy_form(db: Database):
    """渲染新建策略表单"""
    name = st.text_input("策略名称", placeholder="如：我的自定义策略",
                         key="add_strat_name")
    desc = st.text_area("策略描述", placeholder="描述策略的适用场景",
                        key="add_strat_desc")
    weight = st.slider("策略权重", 0.0, 1.0, 0.5, 0.05,
                       key="add_strat_weight",
                       help="多策略组合时此策略的权重占比")

    st.caption("创建后可在编辑页面添加买卖条件和风控设置")

    if st.button("✅ 创建策略", type="primary", key="add_strat_submit"):
        if not name:
            st.error("请输入策略名称")
        else:
            existing = db.get_all_strategies()
            if name in [s["name"] for s in existing]:
                st.error(f"策略名称 '{name}' 已存在")
            else:
                db.save_strategy(name, desc, rules=[], weight=weight)
                st.success(f"策略 {name} 已创建，请展开编辑添加买卖条件")
                st.rerun()
