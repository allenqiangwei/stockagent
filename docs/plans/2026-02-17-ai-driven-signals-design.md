# AI 驱动信号页面设计

## 目标

将信号系统从"规则触发+人工查看"升级为"AI自主分析+人机对话"模式。每晚7点Claude CLI自动执行市场分析→信号解读→策略复盘→自主调整的全流程，用户通过网页聊天窗口随时与AI讨论市场。

## 核心决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| AI引擎 | Claude CLI (`claude -p`) | 不依赖API key，复用订阅 |
| 运行方式 | 后端subprocess调用 | 简单可靠，无状态 |
| 对话接口 | 网页内嵌Chat + `--resume` | 用户体验好，Claude原生续会话 |
| 自主权 | 完全自主 | Claude可启停策略、调参、创建新策略 |
| 时间节奏 | 每晚7点一次全流程 | 收盘后执行，单次运行 |

## 架构

```
┌──────────────────────────────────────────────────┐
│                    Frontend                       │
│  /ai page: Report Viewer + Chat Widget            │
│  左: 日历+报告列表  中: 报告内容  右: Chat窗口     │
└────────────────────┬─────────────────────────────┘
                     │ HTTP API
┌────────────────────┴─────────────────────────────┐
│                FastAPI Backend                     │
│  /api/ai/reports — 报告CRUD                       │
│  /api/ai/chat   — Chat消息转发                    │
│  AIScheduler    — 7PM触发分析                     │
└────────────────────┬─────────────────────────────┘
                     │ subprocess
┌────────────────────┴─────────────────────────────┐
│              Claude CLI (claude -p)               │
│  读取: DB文件, 后端API (curl)                     │
│  写入: JSON报告 → stdout                         │
│  操作: curl PUT/POST → 策略API                   │
└──────────────────────────────────────────────────┘
```

## 数据模型

### ai_reports 表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增ID |
| report_date | String | 报告日期 YYYY-MM-DD |
| report_type | String | daily_analysis / weekly_review |
| market_regime | String | bull / bear / range |
| market_regime_confidence | Float | 0-1 |
| recommendations | JSON | 推荐股票列表+分析 |
| strategy_actions | JSON | 策略操作记录 |
| thinking_process | Text | 完整思考过程 |
| summary | Text | 一句话总结 |
| created_at | DateTime | 创建时间 |

### ai_chat_sessions 表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增ID |
| session_id | String UNIQUE | UUID，前端用来标识会话 |
| claude_session_id | String | Claude CLI的session ID (用于 --resume) |
| title | String | 会话标题 (自动生成) |
| messages | JSON | [{role, content, timestamp}] |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

## 每晚定时分析流程

在现有 `SignalScheduler._do_refresh()` 完成信号生成后，新增AI分析步骤:

```python
def _do_refresh(self, trade_date):
    # ... existing steps (repair, sync, generate signals) ...

    # Step 3: AI Analysis
    self._run_ai_analysis(trade_date)
```

### Claude CLI 调用方式

```python
import subprocess, json

result = subprocess.run(
    [
        "claude", "-p",
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--allowedTools", "Bash Read Glob Grep",
        "--system-prompt", SYSTEM_PROMPT,
        "--max-budget-usd", "1.0",
        prompt
    ],
    capture_output=True, text=True, timeout=300,
    env={**os.environ, "NO_PROXY": "localhost,127.0.0.1"},
)
report = json.loads(result.stdout)
```

### System Prompt 内容

```
你是A股量化交易系统的AI分析师。你的任务是每天收盘后分析市场并给出操作建议。

## 可用工具

你可以通过 Bash 工具执行 curl 命令访问后端API:
- GET  /api/signals/today — 今日信号
- GET  /api/market/index-kline/000001.SH?... — 大盘K线+regime
- GET  /api/strategies — 策略列表
- GET  /api/backtest/runs?limit=10 — 最近回测
- PUT  /api/strategies/{id} — 修改策略 (enabled, exit_config等)
- POST /api/strategies — 创建新策略
- POST /api/backtest/run/sync — 运行回测验证

你也可以直接读取项目文件:
- data/stockagent.db — SQLite数据库
- docs/lab-experiment-analysis.md — 实验分析记录

## 分析框架

1. 市场阶段判断: 读取regime数据，判断当前是牛市/熊市/震荡
2. 信号解读: 分析今日Alpha Top推荐，给出每只股票的分析理由
3. 策略复盘: 查看最近回测结果，评估策略在当前市场阶段的表现
4. 自主操作: 如果发现策略需要调整，直接调用API修改
5. 输出报告

## 输出格式 (JSON)
{输出schema...}
```

### 每日分析 Prompt

```
今天是 {date} (星期{weekday})。

请执行每日市场分析:
1. 获取今日信号和Alpha Top推荐
2. 查看大盘走势和市场阶段
3. 对推荐股票给出详细分析
4. 复盘本周策略表现，需要调整则执行
5. 输出JSON报告

如果今天是周五，额外做一次周度深度复盘。
```

## Chat 接口

### API

```
POST /api/ai/chat
Body: { message: str, session_id?: str }
Response: { response: str, session_id: str }
```

### 实现逻辑

```python
def chat(message: str, session_id: str = None):
    if session_id:
        # 查DB获取claude_session_id
        session = db.query(...).filter_by(session_id=session_id).first()
        cmd = ["claude", "-p", "--resume", session.claude_session_id, message]
    else:
        # 新会话
        session_id = str(uuid.uuid4())
        cmd = ["claude", "-p", "--system-prompt", CHAT_SYSTEM_PROMPT, message]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    # 保存会话
    ...
    return {"response": result.stdout, "session_id": session_id}
```

**Chat System Prompt**: 与定时分析类似，但更偏向对话式交流。Claude可以读取最近的分析报告和市场数据来回答问题。

### --resume 获取 session ID

`claude -p --output-format json` 的输出中包含 session ID，可以从 JSON 结构中提取或从 `~/.claude/projects/` 目录中获取最近会话。

## 前端页面 `/ai`

### 布局

```
┌──────────┬─────────────────────────┬──────────┐
│  日历    │                          │  Chat    │
│  +       │    AI 分析报告            │  窗口    │
│  报告    │    (Markdown渲染)         │          │
│  列表    │                          │          │
│          │  市场阶段 | 推荐 | 操作   │          │
│          │                          │          │
└──────────┴─────────────────────────┴──────────┘
```

### 组件

1. **ReportCalendar**: 日期选择器，高亮有报告的日期
2. **ReportViewer**: 渲染分析报告
   - MarketRegimeCard: 市场阶段判断
   - RecommendationList: 推荐股票+分析理由
   - StrategyActionsLog: 策略操作记录
   - ThinkingProcess: 可展开的思考过程
3. **ChatWidget**: 聊天窗口
   - 消息列表 (Markdown渲染)
   - 输入框+发送按钮
   - 新建会话/切换会话

## 实施分层

**P0 — 核心功能**:
1. 数据模型 (ai_reports, ai_chat_sessions)
2. Claude CLI 调度器 (AIScheduler)
3. 定时分析全流程
4. AI报告API + 前端报告页面

**P1 — Chat功能**:
5. Chat API (POST /api/ai/chat)
6. Chat 前端组件

**P2 — 增强**:
7. 策略自主操作 (启停/调参)
8. 周度深度复盘
9. 报告分享/导出
