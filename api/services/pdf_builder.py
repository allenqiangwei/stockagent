"""PDF generator for AI analysis reports.

Uses reportlab with the built-in STSong-Light CID font to render
Chinese text in A4 pages.  The single public entry point is
``build_report_pdf(report) -> bytes`` which accepts an AIReport ORM
object and returns the raw PDF bytes ready for streaming.
"""

from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm  # noqa: F401 – pt is just 1 in reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)

if TYPE_CHECKING:
    from api.models.ai_analyst import AIReport

# ---------------------------------------------------------------------------
# Font registration
# ---------------------------------------------------------------------------
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

_FONT = "STSong-Light"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
_CLR_HEADING = HexColor("#1f2937")
_CLR_BODY = HexColor("#374151")

_CLR_BULL = HexColor("#059669")
_CLR_BEAR = HexColor("#dc2626")
_CLR_SIDEWAYS = HexColor("#d97706")
_CLR_TRANSITION = HexColor("#2563eb")

_CLR_BUY_BG = HexColor("#ecfdf5")
_CLR_BUY_TEXT = HexColor("#065f46")
_CLR_SELL_BG = HexColor("#fef2f2")
_CLR_SELL_TEXT = HexColor("#991b1b")

_CLR_TABLE_HEADER_BG = HexColor("#f3f4f6")
_CLR_TABLE_BORDER = HexColor("#d1d5db")

# ---------------------------------------------------------------------------
# Page geometry
# ---------------------------------------------------------------------------
_PAGE_W, _PAGE_H = A4
_MARGIN = 60  # 60 points

# Available width inside margins (both sides)
_CONTENT_W = _PAGE_W - 2 * _MARGIN

# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------
_STYLE_TITLE = ParagraphStyle(
    "title",
    fontName=_FONT,
    fontSize=24,
    leading=30,
    alignment=TA_CENTER,
    textColor=_CLR_HEADING,
    spaceAfter=12,
)

_STYLE_SUBTITLE = ParagraphStyle(
    "subtitle",
    fontName=_FONT,
    fontSize=18,
    leading=24,
    alignment=TA_CENTER,
    textColor=_CLR_BODY,
    spaceAfter=8,
)

_STYLE_SECTION = ParagraphStyle(
    "section",
    fontName=_FONT,
    fontSize=16,
    leading=22,
    textColor=_CLR_HEADING,
    spaceBefore=18,
    spaceAfter=10,
    borderPadding=(0, 0, 4, 0),
)

_STYLE_SUBSECTION = ParagraphStyle(
    "subsection",
    fontName=_FONT,
    fontSize=13,
    leading=18,
    textColor=_CLR_HEADING,
    spaceBefore=12,
    spaceAfter=6,
)

_STYLE_BODY = ParagraphStyle(
    "body",
    fontName=_FONT,
    fontSize=10,
    leading=14,
    textColor=_CLR_BODY,
    spaceAfter=6,
)

_STYLE_BODY_CENTER = ParagraphStyle(
    "body_center",
    parent=_STYLE_BODY,
    alignment=TA_CENTER,
)

_STYLE_FOOTER = ParagraphStyle(
    "footer",
    fontName=_FONT,
    fontSize=9,
    leading=12,
    alignment=TA_CENTER,
    textColor=HexColor("#9ca3af"),
    spaceBefore=30,
)

_STYLE_TABLE_HEADER = ParagraphStyle(
    "table_header",
    fontName=_FONT,
    fontSize=9,
    leading=12,
    textColor=_CLR_HEADING,
    alignment=TA_CENTER,
)

_STYLE_TABLE_CELL = ParagraphStyle(
    "table_cell",
    fontName=_FONT,
    fontSize=9,
    leading=12,
    textColor=_CLR_BODY,
)

_STYLE_TABLE_CELL_CENTER = ParagraphStyle(
    "table_cell_center",
    parent=_STYLE_TABLE_CELL,
    alignment=TA_CENTER,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _safe(val, fmt: str = "{}", default: str = "-") -> str:
    """Safely format a value that might be *None*."""
    if val is None:
        return default
    try:
        return fmt.format(val)
    except (ValueError, TypeError):
        return default


def _esc(text: str | None) -> str:
    """Escape text for safe embedding inside reportlab Paragraph XML."""
    if not text:
        return ""
    return escape(str(text))


def _regime_label(regime: str | None) -> str:
    """Map English regime string to Chinese label."""
    mapping = {
        "bull": "牛市",
        "bear": "熊市",
        "sideways": "震荡",
        "transition": "转换",
    }
    if regime is None:
        return "未知"
    return mapping.get(regime.lower(), "未知")


def _regime_color(regime: str | None) -> HexColor:
    """Return the themed colour for a market regime."""
    mapping = {
        "bull": _CLR_BULL,
        "bear": _CLR_BEAR,
        "sideways": _CLR_SIDEWAYS,
        "transition": _CLR_TRANSITION,
    }
    if regime is None:
        return _CLR_BODY
    return mapping.get(regime.lower(), _CLR_BODY)


def _action_label(action: str | None) -> str:
    """Translate recommendation action to Chinese."""
    mapping = {
        "buy": "买入",
        "sell": "卖出",
        "hold": "持有",
        "reduce": "减持",
    }
    if action is None:
        return "-"
    return mapping.get(action.lower(), action)


def _parse_thinking_sections(text: str) -> list[tuple[str, str]]:
    """Split *thinking_process* by ``## `` markdown headers.

    Returns a list of ``(title, body)`` tuples.  Text before the first
    ``## `` header is returned with an empty-string title.
    """
    if not text:
        return []

    sections: list[tuple[str, str]] = []
    # Split on lines that start with "## "
    parts = re.split(r"(?m)^## ", text)

    for i, part in enumerate(parts):
        if i == 0:
            # Content before the first ## header (if any)
            stripped = part.strip()
            if stripped:
                sections.append(("", stripped))
        else:
            # First line is the header title, rest is body
            lines = part.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            sections.append((title, body))

    return sections


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------

# Column widths — proportional to _CONTENT_W
_COL_STOCK = 90
_COL_ACTION = 40
_COL_ALPHA = 40
_COL_PRICE = 50
_COL_PCT = 40
_COL_STOP = 50
_COL_REASON_MIN = 0  # computed as remainder

_FIXED_COLS = _COL_STOCK + _COL_ACTION + _COL_ALPHA + _COL_PRICE + _COL_PCT + _COL_STOP


def _build_rec_table(
    recs: list[dict],
    bg_color: HexColor,
    text_color: HexColor,
) -> Table:
    """Build a styled ``Table`` for a group of recommendations."""

    reason_w = max(_CONTENT_W - _FIXED_COLS, 60)
    col_widths = [
        _COL_STOCK, _COL_ACTION, _COL_ALPHA,
        _COL_PRICE, _COL_PCT, _COL_STOP, reason_w,
    ]

    # ---------- header row ----------
    headers = ["股票", "操作", "Alpha", "目标价", "仓位%", "止损", "理由"]
    header_row = [Paragraph(_esc(h), _STYLE_TABLE_HEADER) for h in headers]
    data = [header_row]

    # ---------- reason cell style (inherits text_color) ----------
    reason_style = ParagraphStyle(
        "reason",
        parent=_STYLE_TABLE_CELL,
        textColor=text_color,
    )
    cell_center_colored = ParagraphStyle(
        "cell_center_colored",
        parent=_STYLE_TABLE_CELL_CENTER,
        textColor=text_color,
    )

    for rec in recs:
        stock = f"{_esc(_safe(rec.get('stock_name')))}<br/>{_esc(_safe(rec.get('stock_code')))}"
        row = [
            Paragraph(stock, ParagraphStyle("stock_cell", parent=_STYLE_TABLE_CELL, textColor=text_color)),
            Paragraph(_esc(_action_label(rec.get("action"))), cell_center_colored),
            Paragraph(_esc(_safe(rec.get("alpha_score"), "{:.2f}")), cell_center_colored),
            Paragraph(_esc(_safe(rec.get("target_price"), "{:.2f}")), cell_center_colored),
            Paragraph(_esc(_safe(rec.get("position_pct"), "{}%")), cell_center_colored),
            Paragraph(_esc(_safe(rec.get("stop_loss"), "{:.2f}")), cell_center_colored),
            Paragraph(_esc(_safe(rec.get("reason"))), reason_style),
        ]
        data.append(row)

    table = Table(data, colWidths=col_widths, repeatRows=1)

    # ---------- table style ----------
    n_rows = len(data)
    style_cmds: list = [
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), _CLR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _CLR_HEADING),
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        # Grid
        ("GRID", (0, 0), (-1, -1), 0.5, _CLR_TABLE_BORDER),
        # Padding
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        # Vertical alignment
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    # Apply background colour to data rows
    if n_rows > 1:
        style_cmds.append(("BACKGROUND", (0, 1), (-1, -1), bg_color))

    table.setStyle(TableStyle(style_cmds))
    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_report_pdf(report: "AIReport") -> bytes:
    """Render an ``AIReport`` ORM object to PDF and return raw bytes.

    The returned bytes can be streamed directly as an HTTP response
    with ``Content-Type: application/pdf``.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title="AI 市场分析报告",
        author="StockAgent",
    )

    story: list = []

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------
    story.append(Spacer(1, 80))
    story.append(Paragraph(_esc("AI 市场分析报告"), _STYLE_TITLE))
    story.append(Spacer(1, 20))

    # Report date
    report_date = getattr(report, "report_date", None) or "-"
    report_type_label = {"daily": "日报", "weekly": "周报"}.get(
        (getattr(report, "report_type", None) or "").lower(), "报告",
    )
    story.append(
        Paragraph(
            _esc(f"{report_date}  {report_type_label}"),
            _STYLE_SUBTITLE,
        ),
    )
    story.append(Spacer(1, 24))

    # Market regime
    regime = getattr(report, "market_regime", None)
    regime_lbl = _regime_label(regime)
    regime_clr = _regime_color(regime)
    regime_style = ParagraphStyle(
        "regime",
        parent=_STYLE_SUBTITLE,
        fontSize=20,
        textColor=regime_clr,
    )
    story.append(Paragraph(_esc(f"市场状态: {regime_lbl}"), regime_style))
    story.append(Spacer(1, 8))

    # Confidence
    confidence = getattr(report, "market_regime_confidence", None)
    if confidence is not None:
        pct_text = f"置信度: {confidence * 100:.1f}%"
        story.append(Paragraph(_esc(pct_text), _STYLE_BODY_CENTER))
    story.append(Spacer(1, 60))

    # Footer
    story.append(Paragraph(_esc("StockAgent 量化交易系统"), _STYLE_FOOTER))

    # Created timestamp
    created_at = getattr(report, "created_at", None)
    if created_at is not None:
        ts_text = f"生成时间: {created_at.strftime('%Y-%m-%d %H:%M')}"
        story.append(Paragraph(_esc(ts_text), _STYLE_FOOTER))

    story.append(PageBreak())

    # ------------------------------------------------------------------
    # Summary section
    # ------------------------------------------------------------------
    story.append(Paragraph(_esc("摘要"), _STYLE_SECTION))
    summary = getattr(report, "summary", None) or ""
    if summary:
        # Preserve line breaks by converting to <br/>
        for para in summary.split("\n\n"):
            para = para.strip()
            if para:
                text = _esc(para).replace("\n", "<br/>")
                story.append(Paragraph(text, _STYLE_BODY))
    else:
        story.append(Paragraph(_esc("暂无摘要"), _STYLE_BODY))
    story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # Recommendations section
    # ------------------------------------------------------------------
    story.append(Paragraph(_esc("投资推荐"), _STYLE_SECTION))

    recs = getattr(report, "recommendations", None) or []
    if recs:
        buy_recs = [r for r in recs if (r.get("action") or "").lower() == "buy"]
        sell_reduce_recs = [
            r for r in recs
            if (r.get("action") or "").lower() in ("sell", "reduce")
        ]
        hold_recs = [r for r in recs if (r.get("action") or "").lower() == "hold"]

        # --- Buy recommendations ---
        if buy_recs:
            buy_header_style = ParagraphStyle(
                "buy_header",
                parent=_STYLE_SUBSECTION,
                textColor=_CLR_BUY_TEXT,
            )
            story.append(Paragraph(_esc("买入推荐"), buy_header_style))
            table = _build_rec_table(buy_recs, _CLR_BUY_BG, _CLR_BUY_TEXT)
            story.append(KeepTogether([table]))
            story.append(Spacer(1, 10))

        # --- Sell / Reduce recommendations ---
        if sell_reduce_recs:
            sell_header_style = ParagraphStyle(
                "sell_header",
                parent=_STYLE_SUBSECTION,
                textColor=_CLR_SELL_TEXT,
            )
            story.append(Paragraph(_esc("卖出/减持"), sell_header_style))
            table = _build_rec_table(sell_reduce_recs, _CLR_SELL_BG, _CLR_SELL_TEXT)
            story.append(KeepTogether([table]))
            story.append(Spacer(1, 10))

        # --- Hold recommendations ---
        if hold_recs:
            story.append(Paragraph(_esc("持有"), _STYLE_SUBSECTION))
            table = _build_rec_table(hold_recs, colors.white, _CLR_BODY)
            story.append(KeepTogether([table]))
            story.append(Spacer(1, 10))
    else:
        story.append(Paragraph(_esc("暂无推荐"), _STYLE_BODY))

    story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # Strategy Actions section
    # ------------------------------------------------------------------
    strategy_actions = getattr(report, "strategy_actions", None) or []
    if strategy_actions:
        story.append(Paragraph(_esc("策略动态"), _STYLE_SECTION))

        for sa in strategy_actions:
            name = _safe(sa.get("strategy_name"))
            action = _safe(sa.get("action"))
            reason = _safe(sa.get("reason"))
            details = _safe(sa.get("details"), default="")

            header_text = f"<b>{_esc(name)}</b>  [{_esc(action)}]"
            header_style = ParagraphStyle(
                "sa_header",
                parent=_STYLE_BODY,
                fontSize=11,
                leading=15,
                textColor=_CLR_HEADING,
                spaceBefore=6,
            )
            story.append(Paragraph(header_text, header_style))

            if reason and reason != "-":
                story.append(Paragraph(_esc(reason), _STYLE_BODY))
            if details and details != "-":
                detail_style = ParagraphStyle(
                    "sa_detail",
                    parent=_STYLE_BODY,
                    fontSize=9,
                    textColor=HexColor("#6b7280"),
                )
                story.append(Paragraph(_esc(details), detail_style))

            story.append(Spacer(1, 4))

        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # Analysis Process section (thinking_process)
    # ------------------------------------------------------------------
    thinking = getattr(report, "thinking_process", None) or ""
    if thinking.strip():
        story.append(Paragraph(_esc("分析过程"), _STYLE_SECTION))

        sections = _parse_thinking_sections(thinking)
        for title, body in sections:
            if title:
                story.append(Paragraph(_esc(title), _STYLE_SUBSECTION))
            if body:
                # Split body by double newlines into paragraphs, preserving
                # single newlines as <br/> within each paragraph.
                for para in body.split("\n\n"):
                    para = para.strip()
                    if not para:
                        continue
                    text = _esc(para).replace("\n", "<br/>")
                    story.append(Paragraph(text, _STYLE_BODY))

    # ------------------------------------------------------------------
    # Build PDF
    # ------------------------------------------------------------------
    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
