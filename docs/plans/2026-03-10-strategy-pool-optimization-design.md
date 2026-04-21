# Strategy Pool Optimization — 信号签名 + 家族管理

**日期**: 2026-03-10
**状态**: Approved
**问题**: 6,119 个策略中大量冗余 (同一 buy/sell 条件, 仅 SL/TP/MHD 不同), 导致信号生成 ~3000 万次评估/天, 且信号高度重复

## 核心概念

### Signal Fingerprint

```
signal_fingerprint = SHA256(canonical(buy_conditions) + "|" + canonical(sell_conditions))
```

- 条件 canonical 化: 按 `(field, params, operator, compare_type)` 排序后序列化
- 相同 fingerprint = 买卖信号完全相同, 仅退出参数不同
- 当前 6,119 策略 → ~33 个 unique fingerprint

### Strategy Family

同一 fingerprint 下的所有策略构成一个 Family:
- 每个 Family 最多 **15 个活跃成员**
- 超出的按 score 排序归档
- 归档 = 软删除 (archived_at 非空), 可恢复

## 数据模型

### Strategy 表新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_fingerprint` | String(64), indexed | buy+sell 条件的 SHA256 哈希 |
| `family_rank` | Integer, nullable | 家族内排名 (1=champion) |
| `family_role` | String(20), nullable | `champion` / `active` / `archive` |
| `archived_at` | DateTime, nullable | 归档时间, 非 null = 不参与信号生成 |

### 规则
- `enabled=True AND archived_at IS NULL` → 参与信号生成
- `archived_at IS NOT NULL` → 保留数据但不生成信号
- 归档不影响已有持仓的退出监控

## StrategyPoolManager 服务

### `rebalance_pool(max_per_family=15, dry_run=False)`

探索后自动调用:

1. 计算所有策略的 signal_fingerprint (未计算的)
2. 按 fingerprint 分组
3. 每个家族内:
   - 按 score 降序排列
   - 选 top 15, 优先保留 SL/TP/MHD 参数差异大的组合
   - rank 1 = champion, rank 2-15 = active, 其余 = archive
   - 完全相同的 SL/TP/MHD 只保留 score 最高的
4. 跨家族覆盖检查:
   - 牛/熊/震荡各至少 3 个家族有 champion
   - 不足时从 archive 拉回最佳 regime 策略
5. 输出变更报告

### `daily_health_check()`

每日信号生成前 (19:00) 自动运行:

1. 补算缺失的 fingerprint
2. 检查家族超限 → 归档多余
3. 检查市场阶段覆盖 → 告警
4. 耗时 <1s (纯 DB 查询)

## 信号生成优化

修改 `signal_engine.py` 核心循环:

```python
# Before: 6119 evaluations per stock
for strategy in all_enabled_strategies:
    evaluate(strategy.buy_conditions, ...)

# After: ~33 evaluations per stock (by fingerprint group)
families = group_by_fingerprint(all_enabled_strategies)
for fingerprint, members in families.items():
    representative = members[0]  # 任一成员, buy/sell 条件相同
    triggered = evaluate(representative.buy_conditions, ...)
    if triggered:
        for member in members:
            create_signal(member, ...)  # 各自的退出参数
```

信号评估从 ~6119 → ~33 次/stock, **提速 ~180x**

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/strategies/pool/rebalance` | 触发重平衡, 支持 dry_run |
| `GET` | `/api/strategies/pool/status` | 池状态: 家族数、活跃/归档数、覆盖度 |
| `GET` | `/api/strategies/families` | 按家族分组列表 |
| `GET` | `/api/strategies/families/{fingerprint}` | 单家族全部成员 |
| `POST` | `/api/strategies/{id}/unarchive` | 从归档恢复 |

## Pool Status 响应

```json
{
  "total_strategies": 6119,
  "active_strategies": 420,
  "archived_strategies": 5699,
  "family_count": 33,
  "families_summary": [...],
  "regime_coverage": {
    "bull": {"families": 28, "strategies": 380},
    "bear": {"families": 25, "strategies": 310},
    "sideways": {"families": 30, "strategies": 400}
  },
  "last_rebalance_at": "2026-03-10T15:00:00",
  "signal_eval_reduction": "6119 → 33 unique evaluations per stock"
}
```

## 前端变更

策略管理页新增:
- **家族视图**: 按 fingerprint 分组, 折叠/展开成员
- **池状态卡片**: 活跃数、家族数、上次 rebalance
- **归档标签**: archived 策略灰色显示, 可一键恢复

## `/explore-strategies` 集成

Step 7 (Auto-Promote) 之后增加 Step 7b:
```
Step 7b: 策略池 Rebalance
  → POST /api/strategies/pool/rebalance
  → 输出: "归档 X 个冗余策略, 当前池: Y 活跃 / Z 家族"
```

## 边界情况

1. **新家族**: 直接加入活跃池, 不受 15 个限制
2. **家族超限**: rebalance 自动归档多余, 保留 score 最高 + 参数差异最大的
3. **归档策略被持仓引用**: 归档只影响新信号生成, 不影响已有持仓的 exit monitoring
4. **条件排序不同但语义相同**: canonical 化后 hash, 保证一致
5. **市场阶段覆盖不足**: 每日检查只告警, rebalance 时自动从 archive 拉回

## 安全机制

- rebalance 只做 archive (软删除), 不做物理删除
- 任何归档策略可通过 unarchive 恢复
- 首次 rebalance 默认 dry_run=True
- 变更写入审计日志

## 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `api/models/strategy.py` | 修改 | 新增 fingerprint/family_rank/family_role/archived_at |
| `api/services/strategy_pool.py` | 新建 | StrategyPoolManager |
| `api/schemas/strategy.py` | 修改 | family 相关响应模型 |
| `api/routers/strategies.py` | 修改 | pool/rebalance、families 端点 |
| `api/services/signal_engine.py` | 修改 | fingerprint 分组优化 |
| `api/services/signal_scheduler.py` | 修改 | 插入 daily_health_check |
| `.claude/skills/explore-strategies/SKILL.md` | 修改 | Step 7b |
| `web/src/app/strategies/page.tsx` | 修改 | 家族视图 |

**总计**: 1 新建, 7 修改
