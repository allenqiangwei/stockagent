# AI 记忆系统设计: Zettelkasten 原子笔记 + Pinecone 语义检索

> 日期: 2026-02-17 | 状态: 已批准

## 问题

当前记忆系统是单一 MEMORY.md 文件（98 行），混合了架构、库笔记、实验洞察、配置等所有信息。MEMORY.md 前 200 行注入系统提示，无法扩展。核心痛点:

1. **决策复盘缺失**: 实验结论散落在对话中，新会话不知道哪些方向已探索过
2. **跨会话断裂**: 每次新会话需重新建立上下文
3. **知识检索困难**: 200 行摘要无法承载 300+ 实验的知识量

## 架构: 三层记忆系统

```
消费端          Claude Code (系统提示) + ChatWidget (API 调用)
                         │
检索层          Pinecone 语义搜索 + Grep/Glob 标签检索
                         │
存储层          memory/ 目录 (Markdown 原子笔记 + YAML frontmatter)
```

### 目录结构

```
memory/
├── MEMORY.md              ← 精简导航索引 (<80行)
├── semantic/              ← 事实型知识 (长期稳定)
│   ├── architecture.md    系统架构概览
│   ├── api-patterns.md    后端 API 模式与约定
│   ├── library-gotchas.md 第三方库踩坑笔记
│   ├── strategy-knowledge.md 策略族知识 (哪些有效/无效)
│   ├── design-docs.md     设计文档索引
│   └── environment.md     环境配置
├── episodic/              ← 事件型记忆 (持续积累)
│   ├── experiments/       每轮实验一个文件
│   │   ├── R01-kdj-exploration.md
│   │   ├── R16-grid-search-breakthrough.md
│   │   └── ...
│   ├── decisions/         架构决策记录 (ADR)
│   │   ├── 001-fire-and-forget-chat.md
│   │   └── ...
│   └── bugs/              踩坑与修复
│       ├── data-gap-2026-02-10.md
│       └── ...
├── procedural/            ← 操作流程 (按需更新)
│   ├── grid-search-workflow.md
│   ├── backtest-pipeline.md
│   └── experiment-analysis.md
└── meta/
    └── index.json         全量索引 (id→file, tags, type 映射)
```

## 原子笔记格式

每条记忆是独立 Markdown 文件，带 YAML frontmatter:

```yaml
---
id: exp-r16-grid-search
type: episodic/experiment
tags: [grid-search, PSAR+MACD+KDJ, exit-config, breakthrough]
created: 2026-02-14
relevance: high
related: [exp-r15-clone-param, strategy-psar-macd-kdj]
---
```

### Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一标识，用于 related 引用和 Pinecone _id |
| `type` | enum | `semantic/{topic}`, `episodic/{experiment,decision,bug}`, `procedural/{workflow}` |
| `tags` | string[] | 自由标签，Grep 检索 + Pinecone metadata filter |
| `created` | date | 创建日期 |
| `relevance` | enum | `high` / `medium` / `low` / `outdated` |
| `related` | string[] | 关联笔记 ID，形成知识网络 |

### 记忆衰减

- 新记忆默认 `relevance: high`
- 定期审查时降级过时记忆为 `outdated`
- `outdated` 不删除（保留历史），检索时低优先级
- MEMORY.md 索引只包含 `high` + `medium` 摘要

## Pinecone 集成

### Index 配置

```
Index name: stockagent-memory
Cloud: aws (us-east-1)
Embed model: multilingual-e5-large
Field map: text → 笔记全文
```

### Record schema

```json
{
  "_id": "exp-r16-grid-search",
  "text": "R16: Grid Search 突破性成果\n绕过 DeepSeek...",
  "type": "episodic",
  "subtype": "experiment",
  "tags": "grid-search,PSAR+MACD+KDJ,exit-config",
  "relevance": "high",
  "created": "2026-02-14",
  "file_path": "episodic/experiments/R16-grid-search.md"
}
```

### 检索流程

**Claude Code:**
1. 会话开始 → MEMORY.md 注入系统提示（导航索引 + 检索指南）
2. 需要详细知识 → Pinecone `search-records` 语义搜索
3. 找到笔记 → Read 文件获取完整内容
4. 会话结束前 → 新发现写入笔记 + upsert Pinecone

**ChatWidget:**
1. Claude CLI 系统提示包含 Pinecone 检索指令
2. Claude 通过工具调用检索相关记忆
3. 记忆增强回答质量

### 同步脚本

`scripts/sync-memory.py`:
- 扫描 `memory/` 下所有 `.md` 文件
- 解析 frontmatter + 正文
- Upsert 到 Pinecone
- 支持 `--full`（全量重建）和 `--incremental`（增量）
- 更新 `meta/index.json`

## 写入触发点

| 触发场景 | 记忆类型 | 模式 |
|----------|----------|------|
| AI Lab 实验完成 | episodic/experiment | 半自动 |
| 架构决策 | episodic/decision | 自动 |
| Bug 修复 | episodic/bug | 半自动 |
| 库 API 踩坑 | semantic/library | 自动 |
| 策略知识更新 | semantic/strategy | 半自动 |
| 工作流变更 | procedural/workflow | 手动 |

## 迁移计划

从现有 MEMORY.md (98行) + lab-experiment-analysis.md (50条洞察) 拆分:

1. 架构描述 → `semantic/architecture.md`
2. 库 API 笔记 → `semantic/library-gotchas.md`
3. 信号/策略系统 → `semantic/strategy-knowledge.md`
4. 数据完整性系统 → `episodic/bugs/data-gap-2026-02-10.md`
5. AI Lab 40 条洞察 → `episodic/experiments/` 下按轮次拆为 ~10 个文件
6. 设计文档索引 → `semantic/design-docs.md`
7. 环境配置 → `semantic/environment.md`
8. 重写 MEMORY.md 为精简导航索引

## MEMORY.md 新格式 (模板)

```markdown
# StockAgent Memory Index

## Project
A股量化交易系统: Next.js + FastAPI + SQLAlchemy + AkShare/TuShare

## How to Use This Memory
- 架构/API/库: 查 `semantic/`
- 实验/决策/Bug: 查 `episodic/`
- 操作流程: 查 `procedural/`
- 语义搜索: 用 Pinecone search-records (index: stockagent-memory)
- 全量索引: 读 `meta/index.json`

## Recent Highlights (auto-updated)
- [high] PSAR+MACD+KDJ 是最强组合 (score 0.825, +90.5%)
- [high] Grid search 成功率 >90%, DeepSeek 已失效
- [high] TP14 是通用黄金止盈点
- [high] fire-and-forget chat 架构已上线

## Key Constraints
- DeepSeek 不使用新 compare_type, 需 few-shot 模板
- 回测串行执行 (Semaphore=1)
- Google Fonts 被代理阻断, 用系统字体
```

## 参考

- [A-Mem: Agentic Memory for LLM Agents (NeurIPS 2025)](https://arxiv.org/abs/2502.12110)
- [Claude Code Memory Best Practices](https://github.com/shanraisshan/claude-code-best-practice/blob/main/reports/claude-agent-memory.md)
- [Project Memory Skill](https://github.com/SpillwaveSolutions/project-memory)
- [Claude Memory Bank](https://github.com/russbeye/claude-memory-bank)
- [Memory in the Age of AI Agents Survey](https://arxiv.org/abs/2512.13564)
