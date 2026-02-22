# 回测挂死防护设计

**日期**: 2026-02-15
**状态**: 待实现

## 问题

AI Lab实验中，策略回测可能因以下原因挂死：
1. **信号爆炸**: 买入条件过宽，每天产生数千候选信号，回测耗时数小时
2. **单策略耗时过长**: 即使候选数不极端，3年×5000只股票也可能运行30分钟+
3. **线程不可杀**: Python daemon线程无外部kill机制
4. **串行阻塞**: 一个策略挂死导致实验内剩余策略永远pending

## 方案: 线程超时 + 增强信号检测 + 实验看门狗

### 1. 单策略超时 (5分钟硬限)

**portfolio_engine.py**:
- 新增 `BacktestTimeoutError` 异常类
- `run()` 方法新增可选参数 `cancel_event: threading.Event`
- 日循环中每天检查 `cancel_event.is_set()`，为True则抛 `BacktestTimeoutError`

**ai_lab_engine.py** `_run_single_backtest`:
- 创建 `cancel_event = threading.Event()`
- 启动 `threading.Timer(300, cancel_event.set)`
- 传给 `engine.run(..., cancel_event=cancel_event)`
- 捕获 `BacktestTimeoutError` → status=invalid, error_message含耗时

### 2. 增强信号爆炸检测

**portfolio_engine.py** 日循环:
- 保留前10天严格检查 (阈值500)
- 新增: 每50天复查 (阈值300)，用最近50天平均候选数
- 捕获"慢热型"信号爆炸

### 3. 实验级看门狗

**ai_lab_engine.py** `ExperimentRunner`:
- 记录每个实验的开始时间和策略cancel_event列表
- 看门狗线程每60秒扫描，超过60分钟的实验:
  - 设置所有cancel_event
  - 等10秒，标记实验failed
  - pending策略标记为failed (可retry)

## 影响范围

| 文件 | 改动 |
|------|------|
| `src/backtest/portfolio_engine.py` | 新增BacktestTimeoutError, cancel_event检查, 增强信号检测 |
| `api/services/ai_lab_engine.py` | Timer超时, 看门狗线程, cancel_event管理 |

## 不变部分

- 评分逻辑、数据加载、regime计算不变
- API接口不变
- 前端不变
