# AI Analysis Report PDF Export — Design Document

**Date**: 2026-02-22
**Status**: Approved

## Goal

Add PDF export functionality to AI analysis reports. Users click a button in the report viewer to download a professionally formatted PDF containing the full analysis: cover page, summary, buy/sell recommendations table, strategy actions, and the complete thinking process.

## Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Generation side | Server-side (FastAPI) | User preference; keeps client lightweight |
| PDF library | reportlab | Pure Python, zero system deps, industry standard, built-in Chinese CID fonts |
| Language | All Chinese | Matches A-share investment advisor report style |
| Content scope | Full report (all sections) | Cover + summary + recommendations + strategy actions + thinking_process |
| Entry point | Button in report viewer header | Right side of report title row |

## Architecture

```
User clicks "导出PDF"
  → Frontend: window.open(`/api/ai/reports/${id}/pdf`)
  → Next.js rewrites → FastAPI
  → GET /api/ai/reports/{report_id}/pdf
  → Query AIReport from DB
  → pdf_builder.build_report_pdf(report) → bytes
  → StreamingResponse(application/pdf)
  → Browser downloads file
```

### Files

| File | Action | Purpose |
|------|--------|---------|
| `api/services/pdf_builder.py` | Create | Core PDF generation module using reportlab |
| `api/routers/ai_analyst.py` | Modify | Add `GET /api/ai/reports/{id}/pdf` endpoint |
| `web/src/app/ai/page.tsx` | Modify | Add download button to ReportViewer header |

No new database tables or models needed.

## PDF Page Structure (A4 Portrait)

### Page 1: Cover
- Title: "AI 市场分析报告"
- Report date (large, centered)
- Market regime badge: bull/bear/sideways/transition with color
- Confidence percentage
- Footer: "StockAgent 量化交易系统 — AI 分析引擎"

### Page 2: Executive Summary
- Section header: "摘要"
- `summary` field rendered as bordered paragraph
- Page break after

### Page 3+: Recommendations
- Section header: "投资推荐"
- Sub-header: "买入推荐" (green theme)
- Table columns: 股票 | 操作 | Alpha | 目标价 | 仓位 | 止损 | 理由
- Sub-header: "卖出/减持" (red theme)
- Same table structure
- Sub-header: "持有" (if any)
- If no recommendations: "暂无推荐"

### Page 4+: Strategy Actions
- Section header: "策略动态"
- List items: strategy_name + action badge + reason
- If empty: skip section

### Page 5+: Analysis Process
- Section header: "分析过程"
- Parse `thinking_process` by `## ` headers
- Each `##` header → 14pt bold paragraph with 12pt top spacing
- Body text → 10pt, 1.4x line height, 6pt paragraph spacing
- Automatic pagination by reportlab

## Visual Design

### Fonts
- Titles: STSong-Light (reportlab built-in CID font), bold via `<b>` tag
- Body: STSong-Light, 10pt
- Numbers/codes: Courier, 9pt

### Colors
- Buy rows: background `#ecfdf5`, text `#065f46`
- Sell rows: background `#fef2f2`, text `#991b1b`
- Bull regime: `#059669` (emerald)
- Bear regime: `#dc2626` (red)
- Sideways regime: `#d97706` (amber)
- Transition regime: `#2563eb` (blue)
- Headings: `#1f2937`
- Body text: `#374151`

### Table Design
- Alternating row shading for readability
- Color-coded action column (buy=green, sell=red, hold=gray)
- Reason column wraps text (max width ~200pt)

## API Endpoint

```
GET /api/ai/reports/{report_id}/pdf

Response:
  Content-Type: application/pdf
  Content-Disposition: attachment; filename="AI分析报告_2026-02-22.pdf"
  Body: PDF bytes
```

Error cases:
- Report not found → 404
- PDF generation failure → 500 with error message

## Frontend Integration

Button placement: ReportViewer header row, right side.

```
[AI 市场分析报告 2026-02-22]  [市场状态标签]  [📥 导出PDF]
```

Icon: Lucide React `FileDown`
Click handler: `window.open(\`/api/ai/reports/${report.id}/pdf\`, '_blank')`

## Edge Cases

- No recommendations → Show "暂无推荐" text in that section
- No strategy actions → Skip section entirely
- Empty thinking_process → Skip section
- Very long thinking_process → reportlab handles auto-pagination
- Special characters in text → reportlab Paragraph handles HTML escaping
- `## ` headers in thinking_process → Split and render as styled sections
