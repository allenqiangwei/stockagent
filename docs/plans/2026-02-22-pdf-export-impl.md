# AI Report PDF Export — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add server-side PDF export for AI analysis reports using reportlab.

**Architecture:** FastAPI endpoint generates PDF via reportlab, returns StreamingResponse. Frontend adds download button.

**Tech Stack:** Python reportlab, FastAPI StreamingResponse, Lucide React FileDown icon

---

### Task 1: Install reportlab dependency

**Files:**
- Modify: `requirements.txt` (or pip install directly)

**Step 1: Install reportlab**

Run: `source venv/bin/activate && pip install reportlab`

**Step 2: Verify installation**

Run: `python -c "from reportlab.lib.pagesizes import A4; print('OK', A4)"`
Expected: `OK (595.2755905511812, 841.8897637795276)`

**Step 3: Commit**

```bash
pip freeze | grep -i reportlab >> requirements.txt  # if requirements.txt exists, otherwise skip
git add -A && git commit -m "chore: install reportlab for PDF export"
```

---

### Task 2: Create PDF builder module

**Files:**
- Create: `api/services/pdf_builder.py`

This is the core module. It must:

1. Import reportlab components: `SimpleDocTemplate`, `Paragraph`, `Table`, `TableStyle`, `Spacer`, `PageBreak`, `Image`
2. Register Chinese CID font: `pdfmetrics.registerFont` with `UnicodeCIDFont('STSong-Light')`
3. Define styles: title (18pt bold), section_header (14pt bold), body (10pt), mono (9pt Courier)
4. Define colors as HexColor constants matching design doc
5. Implement `build_report_pdf(report: AIReport) -> bytes` that:
   a. Creates a `BytesIO` buffer
   b. Creates `SimpleDocTemplate` with A4, margins 60pt
   c. Builds flowables list:
      - **Cover**: Title "AI 市场分析报告", date, regime badge (colored text), confidence
      - **PageBreak**
      - **Summary section**: "摘要" header + summary paragraph in bordered frame
      - **Recommendations section**: "投资推荐" header
        - "买入推荐" sub-header + table (green rows) with columns: 股票|操作|Alpha|目标价|仓位|止损|理由
        - "卖出/减持" sub-header + table (red rows) same columns
        - "持有" sub-header if any hold recommendations
        - "暂无推荐" if empty
      - **Strategy Actions section**: "策略动态" header + list items (skip if empty)
      - **Analysis Process section**: "分析过程" header
        - Parse `thinking_process` by `## ` delimiter
        - Each `## Title` → section_header style paragraph
        - Body text → body style paragraph with preserved line breaks
   d. Calls `doc.build(flowables)`
   e. Returns `buffer.getvalue()`

6. Helper `_parse_thinking_sections(text: str) -> list[tuple[str, str]]` splits thinking_process by `## ` headers
7. Helper `_build_rec_table(recs: list, action_filter: str, color_scheme: tuple) -> list` builds recommendation table for a given action type
8. Handle None/empty fields gracefully (skip sections, show placeholder text)

**Key details for Chinese rendering:**
- Use `<font name="STSong-Light">中文文本</font>` in Paragraph XML
- Or set the default font in ParagraphStyle to STSong-Light
- For mixed Chinese+ASCII, STSong-Light handles both

**Step: Write the module**

Create `api/services/pdf_builder.py` with all the above.

**Step: Smoke test**

```python
python -c "
from api.services.pdf_builder import build_report_pdf
# Create a mock report-like dict
class MockReport:
    report_date = '2026-02-22'
    report_type = 'daily'
    market_regime = 'sideways'
    market_regime_confidence = 0.75
    summary = '今日A股市场震荡运行，上证指数小幅收跌。'
    recommendations = [
        {'stock_code': '600519', 'stock_name': '贵州茅台', 'action': 'buy', 'reason': '技术面突破', 'alpha_score': 42.5, 'target_price': 1850.0, 'position_pct': 15.0, 'stop_loss': 1780.0},
        {'stock_code': '000858', 'stock_name': '五粮液', 'action': 'sell', 'reason': '破位下行', 'alpha_score': 0, 'target_price': 165.0, 'position_pct': 100.0, 'stop_loss': 155.0},
    ]
    strategy_actions = [
        {'action': 'activate', 'strategy_id': 1, 'strategy_name': 'PSAR趋势', 'reason': '震荡市适用', 'details': ''},
    ]
    thinking_process = '## 市场环境\n今日大盘震荡运行。\n\n## 策略选择\n选择了PSAR趋势策略。\n\n## 风险提示\n注意回调风险。'
    created_at = None

pdf_bytes = build_report_pdf(MockReport())
with open('/tmp/test_report.pdf', 'wb') as f:
    f.write(pdf_bytes)
print(f'PDF generated: {len(pdf_bytes)} bytes')
"
```

**Step: Commit**

```bash
git add api/services/pdf_builder.py
git commit -m "feat: add PDF builder for AI analysis reports"
```

---

### Task 3: Add PDF download API endpoint

**Files:**
- Modify: `api/routers/ai_analyst.py` — add endpoint between `get_report` (line 132) and `delete_report` (line 141)

**Step: Add the endpoint**

Insert after the `get_report` endpoint (after line 138):

```python
@router.get("/reports/{report_id}/pdf")
def download_report_pdf(report_id: int, db: Session = Depends(get_db)):
    """Download an AI report as a professionally formatted PDF."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from api.services.pdf_builder import build_report_pdf

    report = db.query(AIReport).get(report_id)
    if not report:
        raise HTTPException(404, "Report not found")

    pdf_bytes = build_report_pdf(report)
    filename = f"AI分析报告_{report.report_date}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
```

**IMPORTANT**: This endpoint MUST be placed BEFORE the `get_report` endpoint (`/reports/{report_id}`) in the router, because FastAPI matches routes in order and `/reports/{report_id}/pdf` must not be captured by `/reports/{report_id}` first. Actually, FastAPI handles this correctly since `/pdf` is a literal suffix, but to be safe place it before.

**Step: Test the endpoint**

```bash
# First find a valid report ID
curl -s http://localhost:8050/api/ai/reports?limit=1 | python -m json.tool | head -5

# Then download the PDF (replace 10 with actual ID)
curl -s -o /tmp/test_api_report.pdf http://localhost:8050/api/ai/reports/10/pdf
ls -la /tmp/test_api_report.pdf
```

**Step: Commit**

```bash
git add api/routers/ai_analyst.py
git commit -m "feat: add PDF download endpoint for AI reports"
```

---

### Task 4: Add download button to frontend ReportViewer

**Files:**
- Modify: `web/src/app/ai/page.tsx`

**Step 1: Add FileDown to lucide-react imports**

In the import block (lines 9-30), add `FileDown` to the import list:

```typescript
import {
  Sparkles,
  Calendar,
  // ... existing imports ...
  CircleX,
  FileDown,  // ← add this
} from "lucide-react";
```

**Step 2: Add download button to ReportViewer header**

In the ReportViewer component, find the header `<div>` (around line 115) that contains the date and regime badge. Add a download button between the title and regime badge:

Current structure:
```tsx
<div className="flex items-start justify-between">
  <div>
    <div className="text-xs ...">AI 市场分析</div>
    <h1 className="text-xl ...">{ report.report_date }</h1>
  </div>
  <div className={`flex items-center gap-2.5 ...`}>
    {/* regime badge */}
  </div>
</div>
```

New structure — add a button group between title and regime:
```tsx
<div className="flex items-start justify-between">
  <div>
    <div className="text-xs ...">AI 市场分析</div>
    <h1 className="text-xl ...">{ report.report_date }</h1>
  </div>
  <div className="flex items-center gap-2">
    <Button
      variant="outline"
      size="sm"
      onClick={() => window.open(`/api/ai/reports/${report.id}/pdf`, '_blank')}
      title="导出PDF报告"
    >
      <FileDown className="h-4 w-4 mr-1.5" />
      导出PDF
    </Button>
    <div className={`flex items-center gap-2.5 ...`}>
      {/* regime badge - unchanged */}
    </div>
  </div>
</div>
```

**Step: Verify in browser**

Open http://localhost:3000/ai, select a report, verify the "导出PDF" button appears in the header and clicking it downloads a PDF file.

**Step: Commit**

```bash
git add web/src/app/ai/page.tsx
git commit -m "feat: add PDF export button to AI report viewer"
```

---

### Task 5: Final integration test & polish

**Step 1: End-to-end test**

1. Open http://localhost:3000/ai
2. Select the most recent report
3. Click "导出PDF" button
4. Verify PDF downloads with correct filename
5. Open PDF and verify all sections render correctly:
   - Cover page with date and regime
   - Summary section
   - Buy/sell recommendation tables with colors
   - Strategy actions list
   - Analysis process with section headers

**Step 2: Test edge cases**

- Test with a report that has no recommendations
- Test with a report that has no strategy_actions
- Test with a report that has empty thinking_process

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete AI report PDF export feature"
```
