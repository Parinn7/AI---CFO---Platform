"""PDF rendering for the three report types (task 8.4, FR-7.4).

**This module renders; it does not assemble and it does not calculate.** It
takes a `MonthlyReport` / `BoardReport` / `InvestorSummary` — already built by
`reports.service` out of Financial Engine output — and draws it. It has no
database session, no engine imports and no arithmetic on money beyond picking a
colour by sign. A figure that is wrong in a PDF is wrong upstream, which keeps
the "a report is an assembly" property of 8.1–8.3 true of the exported copy too.

**Nothing is stored.** `GET /reports/{type}/pdf` renders into a buffer and
returns the bytes; no file is written and no `reports` row is created. See
`schema.md` §10 for why that table was retired rather than built — briefly, a
report is a pure function of the company's transactions, so a regenerated PDF
can never disagree with the data while a stored one can.

**Every number is drawn through `core/formatting.py`**, the same module the AI
CFO's context block uses and a deliberate mirror of the frontend's
`lib/format.ts`. The point of a report is that it leaves the building: a rupee
that reads '₹4,21,573.50' on the dashboard and '₹422000' in the board pack is
the kind of discrepancy that gets noticed in the meeting and not before.

**The font is bundled on purpose.** ReportLab's built-in Type 1 faces are
WinAnsi-encoded and have no U+20B9 (₹) glyph — an INR report in Helvetica draws
every rupee sign as a black box. `fonts/DejaVuSans*.ttf` (upstream release
2.37, Bitstream Vera licence in `fonts/LICENSE.txt`) carries ₹ along with the
em-dashes and arrows the prose uses, and shipping it in the repo means the
deployed backend in Phase 10 renders identically to a laptop rather than
depending on whatever fonts the host image happens to have.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.formatting import (
    format_compact_inr,
    format_date,
    format_inr,
    format_month_key,
    format_months,
    format_pct,
)
from app.reports.schemas import (
    BoardReport,
    CategoryLine,
    InvestorSummary,
    MonthlyReport,
)
from app.financial_engine.schemas import KpiSnapshotRead, MonthlyPerformanceRead

# --- Fonts -------------------------------------------------------------------

FONTS_DIR = Path(__file__).parent / "fonts"
FONT_REGULAR = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"

_fonts_registered = False


def register_fonts() -> None:
    """Register the bundled DejaVu faces with ReportLab, once per process.

    Idempotent because it is called from every render rather than at import:
    a font registration failing at import time would take the whole app down at
    boot over a feature nobody may use that session.
    """
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONTS_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD)
    _fonts_registered = True


# --- Palette -----------------------------------------------------------------
#
# Near-monochrome with one accent, and green/red reserved exclusively for the
# sign of a number. A report is read in a meeting and often printed in
# greyscale, so colour carries emphasis but never the only copy of a fact —
# every positive/negative figure also carries its sign in the text.

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#E5E7EB")
BAND = colors.HexColor("#F9FAFB")
ACCENT = colors.HexColor("#1F2937")
POSITIVE = colors.HexColor("#15803D")
NEGATIVE = colors.HexColor("#B91C1C")

#: Readiness verdicts (8.3) → the colour their badge is drawn in. `attention`
#: is amber rather than red: the check is measurable and short of target, which
#: is a different statement from `gap`.
STATUS_COLORS = {
    "ready": POSITIVE,
    "attention": colors.HexColor("#B45309"),
    "gap": NEGATIVE,
    "not_applicable": MUTED,
}

STATUS_LABELS = {
    "ready": "Ready",
    "attention": "Attention",
    "gap": "Gap",
    "not_applicable": "Not measurable",
}

#: Tables up to this many rows are kept on one page; longer ones split. Eight
#: rows is roughly a third of a page, so a block that size reliably fits in
#: whatever is left rather than jumping to a fresh page and stranding the rest.
KEEP_WHOLE_MAX_ROWS = 8

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

APP_NAME = "AI CFO Platform"

#: Printed at the foot of every report. Reports carry figures the Financial
#: Engine computed and, in the investor summary, verdicts from fixed thresholds
#: — neither is professional advice (FR-6.5), and unlike a chat answer a PDF
#: outlives the conversation that produced it, so the statement travels with it.
DISCLAIMER = (
    "This report is generated automatically from the financial data recorded in "
    f"{APP_NAME}. All figures are calculated by the platform's financial engine "
    "from that data; no part of this report is written or estimated by an AI "
    "model. It is provided for information only and is not accounting, tax, "
    "legal or investment advice — consult a qualified professional before "
    "acting on it."
)


# --- Styles ------------------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    """Paragraph styles, built after `register_fonts()` so the faces exist."""
    base = ParagraphStyle(
        "base", fontName=FONT_REGULAR, fontSize=9, leading=13, textColor=INK
    )
    return {
        "title": ParagraphStyle(
            "title", parent=base, fontName=FONT_BOLD, fontSize=18, leading=22
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base, fontSize=10, leading=14, textColor=MUTED
        ),
        "section": ParagraphStyle(
            "section",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            textColor=ACCENT,
            spaceBefore=2,
            spaceAfter=4,
        ),
        "body": base,
        "note": ParagraphStyle(
            "note", parent=base, fontSize=8, leading=11, textColor=MUTED
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11),
        "cell_right": ParagraphStyle(
            "cell_right", parent=base, fontSize=8.5, leading=11, alignment=TA_RIGHT
        ),
        "head": ParagraphStyle(
            "head",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=MUTED,
        ),
        "head_right": ParagraphStyle(
            "head_right",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_RIGHT,
        ),
        "tile_label": ParagraphStyle(
            "tile_label", parent=base, fontSize=7.5, leading=10, textColor=MUTED
        ),
        "tile_value": ParagraphStyle(
            "tile_value", parent=base, fontName=FONT_BOLD, fontSize=12, leading=15
        ),
        "tile_note": ParagraphStyle(
            "tile_note", parent=base, fontSize=7.5, leading=10, textColor=MUTED
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base,
            fontSize=7.5,
            leading=10.5,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


# --- Value rendering ---------------------------------------------------------
#
# Every one of these renders an *already-computed* value. The `None` handling is
# the point: the engine returns null for genuinely undefined metrics (runway
# when not burning cash, margin at zero revenue, growth with no prior period),
# and a PDF that printed those as "0" would be asserting something false.

DASH = "—"


def _esc(text: str) -> str:
    """Escape user-supplied text for ReportLab's mini-HTML paragraph markup.

    Company names, category names and transaction descriptions are typed by
    users; an unescaped `&` or `<` raises a parse error mid-render, which would
    make "export the report" fail for anyone who named a category "R&D".
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _money(value: Decimal | None) -> str:
    return DASH if value is None else format_inr(value)


def _signed_money(value: Decimal) -> str:
    """A movement, always with its direction — '+₹1,00,000.00' / '-₹20,000.00'.

    Mirrors the `signed()` helper on the report screens so a change reads the
    same in the PDF as on the page it was exported from.
    """
    sign = "+" if value >= 0 else "-"
    return f"{sign}{format_inr(abs(value))}"


def _signed_compact(value: Decimal) -> str:
    """A movement at magnitude scale — '+₹1.96Cr' / '-₹47.6L'.

    Used only where a column is too narrow for the rupee-exact form. Everywhere
    a figure is the record of what happened, `_signed_money` is used instead.
    """
    sign = "+" if value >= 0 else "-"
    return f"{sign}{format_compact_inr(abs(value))}"


def _pct(value: Decimal | None, *, signed: bool = False) -> str:
    return DASH if value is None else format_pct(value, signed=signed)


def _months(value: Decimal | None) -> str:
    return DASH if value is None else f"{format_months(value)} months"


def _sign_color(value: Decimal | None) -> colors.Color:
    if value is None:
        return INK
    return POSITIVE if value >= 0 else NEGATIVE


def _colored(text: str, color: colors.Color, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f'<font color="{color.hexval()}">{text}</font>', style)


# --- Shared building blocks --------------------------------------------------


def _header_block(
    title: str, company_name: str, subtitle: str, generated_at: dt.datetime, st
) -> list:
    """The title block every report opens with.

    The company is named on the report itself, not just in the filename, for
    the reason `ReportCompany` exists at all: a PDF gets forwarded, printed and
    read months later, detached from the account that produced it.
    """
    return [
        Paragraph(_esc(title), st["title"]),
        Spacer(1, 2),
        Paragraph(
            f"<b>{_esc(company_name)}</b> &nbsp;·&nbsp; {_esc(subtitle)}",
            st["subtitle"],
        ),
        Spacer(1, 1),
        Paragraph(
            f"Generated {format_date(generated_at.date())}", st["note"]
        ),
        Spacer(1, 10),
        _rule(),
        Spacer(1, 10),
    ]


def _rule() -> Table:
    """A full-width hairline."""
    t = Table([[""]], colWidths=[CONTENT_WIDTH], rowHeights=[0.4])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
    return t


def _section(title: str, st) -> Paragraph:
    return Paragraph(_esc(title), st["section"])


def _money_tile(
    label: str,
    value: Decimal,
    note: str | None = None,
    *,
    suffix: str = "",
    sign: str = "",
) -> tuple[str, str, str]:
    """A tile stating an amount as a magnitude, with the exact figure beneath.

    An A4 page divided five ways leaves a tile about 83pt wide, and
    '₹4,21,573.50/mo' set at tile size is half as wide again — it wraps
    mid-number, which is exactly the defect the dashboard's `StatCard` is
    already known to have on its narrow grid. Shrinking the type only moves the
    threshold: a crore-scale burn rate breaks it again.

    So the headline is the magnitude a founder would actually say out loud
    ('₹4.2L/mo') and the rupee-exact figure sits directly under it. Both are
    the *same stored number* rendered two ways — the pattern
    `core.formatting.format_money` already applies to the AI CFO's prose — so
    nothing is rounded away, and the figure of record is still on the page.

    `sign` prefixes both renderings, for the one figure whose stored sign is the
    opposite of how it reads: a negative burn rate is a surplus.
    """
    exact = sign + format_inr(value) + suffix
    return (
        label,
        sign + format_compact_inr(value) + suffix,
        f"{exact} · {note}" if note else exact,
    )


def _tiles(items: Sequence[tuple[str, str, str | None]], st, *, per_row: int = 4):
    """A row of stat tiles — the PDF equivalent of the dashboard's KPI cards.

    Each item is `(label, value, note)`; `note` may be None. Laid out as a
    bordered table rather than free-drawn boxes so the row paginates and
    column-balances like every other flowable.
    """
    flowables = []
    for start in range(0, len(items), per_row):
        chunk = list(items[start : start + per_row])
        cells = []
        for label, value, note in chunk:
            stack = [
                Paragraph(_esc(label), st["tile_label"]),
                Spacer(1, 2),
                Paragraph(_esc(value), st["tile_value"]),
            ]
            if note:
                stack += [Spacer(1, 1), Paragraph(_esc(note), st["tile_note"])]
            cells.append(stack)
        # Pad a short final row so the tiles keep their width instead of
        # stretching to fill it.
        while len(cells) < per_row:
            cells.append("")
        width = CONTENT_WIDTH / per_row
        t = Table([cells], colWidths=[width] * per_row)
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, -1), BAND),
                    ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
                ]
            )
        )
        flowables += [t, Spacer(1, 6)]
    return flowables


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence],
    col_widths: Sequence[float],
    st,
    *,
    right_align_from: int = 1,
) -> Table:
    """A standard data table: muted header row, hairline rules, banded body.

    Cells arrive as strings (wrapped in the right-aligned or left-aligned cell
    style here) or as ready-made flowables when a cell needs its own colour.
    """
    head = [
        Paragraph(_esc(h), st["head_right"] if i >= right_align_from else st["head"])
        for i, h in enumerate(headers)
    ]
    body = []
    for row in rows:
        cells = []
        for i, value in enumerate(row):
            if isinstance(value, str):
                style = st["cell_right"] if i >= right_align_from else st["cell"]
                cells.append(Paragraph(_esc(value), style))
            else:
                cells.append(value)
        body.append(cells)

    t = Table([head] + body, colWidths=list(col_widths), repeatRows=1)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
    ]
    for i in range(1, len(body) + 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), BAND))
    t.setStyle(TableStyle(style))
    return t


def _kpi_tiles(kpis: KpiSnapshotRead, st, *, growth_note: str) -> list:
    """The five headline KPIs (FR-4.1–4.6), drawn from one `kpi_snapshots` row.

    The same row the dashboard's tiles and the AI CFO's context read — which is
    why the undefined cases show a dash and a reason rather than a zero.
    """
    # A negative burn rate is a surplus, and is stated as one — '-₹2.8L/mo' under
    # the word "outflow" is arithmetically true and reads as a loss. The
    # dashboard's `KpiCards` flips the sign and the label the same way, and this
    # is the tile a founder is most likely to read side by side with it.
    burn = kpis.burn_rate
    burning = burn > 0
    return _tiles(
        [
            _money_tile(
                "Burn rate",
                burn if burning else -burn,
                "net monthly cash burn" if burning else "net monthly cash surplus",
                suffix="/mo",
                sign="" if burning else "+",
            ),
            (
                "Runway",
                DASH
                if kpis.runway_months is None
                else format_months(kpis.runway_months),
                "Not burning cash"
                if kpis.runway_months is None
                else "months, at current burn rate",
            ),
            (
                "Gross margin",
                _pct(kpis.gross_margin_pct),
                "No revenue in period" if kpis.gross_margin_pct is None else None,
            ),
            (
                "Operating margin",
                _pct(kpis.operating_margin_pct),
                "No revenue in period"
                if kpis.operating_margin_pct is None
                else None,
            ),
            (
                "Revenue growth",
                _pct(kpis.revenue_growth_pct, signed=True),
                "No prior period" if kpis.revenue_growth_pct is None else growth_note,
            ),
        ],
        st,
        per_row=5,
    )


def _totals_tiles(kpis: KpiSnapshotRead, closing_cash: Decimal, st) -> list:
    """Revenue in, expenses out, what that left, and cash at the end."""
    net = kpis.net_cash_flow
    return _tiles(
        [
            _money_tile("Revenue", kpis.total_revenue, "money in"),
            _money_tile("Expenses", kpis.total_expenses, "money out"),
            (
                "Net cash flow",
                f"{'+' if net >= 0 else '-'}{format_compact_inr(abs(net))}",
                f"{_signed_money(net)} · revenue minus expenses",
            ),
            _money_tile("Cash on hand", closing_cash, "at period end"),
        ],
        st,
        per_row=4,
    )


def _category_table(lines: Iterable[CategoryLine], st) -> list:
    """Where the money came from and went (FR-3.4), income then expenses.

    "Uncategorized" is listed rather than dropped, which is what keeps the
    lines adding up to the totals stated above them.
    """
    income = [ln for ln in lines if ln.type == "income"]
    expense = [ln for ln in lines if ln.type == "expense"]
    flowables: list = []

    for label, group in (("Income", income), ("Expenses", expense)):
        if not group:
            continue
        rows = [
            (
                ln.name,
                str(ln.transaction_count),
                _pct(ln.share_pct),
                format_inr(ln.total),
            )
            for ln in group
        ]
        total = sum((ln.total for ln in group), Decimal("0"))
        rows.append(
            (
                Paragraph(f"<b>Total {label.lower()}</b>", st["cell"]),
                "",
                "",
                Paragraph(f"<b>{format_inr(total)}</b>", st["cell_right"]),
            )
        )
        flowables += [
            KeepTogether(
                [
                    Paragraph(label, st["head"]),
                    Spacer(1, 3),
                    _table(
                        ["Category", "Entries", "Share", "Total"],
                        rows,
                        [
                            CONTENT_WIDTH * 0.46,
                            CONTENT_WIDTH * 0.14,
                            CONTENT_WIDTH * 0.16,
                            CONTENT_WIDTH * 0.24,
                        ],
                        st,
                    ),
                ]
            ),
            Spacer(1, 8),
        ]
    if not flowables:
        flowables.append(Paragraph("No categorized activity in this period.", st["note"]))
    return flowables


def _monthly_table(months: Sequence[MonthlyPerformanceRead], st, title: str) -> list:
    """The month-by-month series, oldest first — the table behind the chart.

    A PDF gets read in print and forwarded as a file, so the series is drawn as
    figures rather than as a rendered chart image: the numbers are the content,
    and a table of them survives a photocopier.
    """
    if not months:
        return []
    rows = [
        (
            format_month_key(m.month),
            format_inr(m.revenue),
            format_inr(m.expenses),
            _colored(
                _signed_money(m.net_cash_flow),
                _sign_color(m.net_cash_flow),
                st["cell_right"],
            ),
            _pct(m.margin_pct),
        )
        for m in months
    ]
    block = [
        _section(title, st),
        _table(
            ["Month", "Revenue", "Expenses", "Net", "Margin"],
            rows,
            [
                CONTENT_WIDTH * 0.22,
                CONTENT_WIDTH * 0.21,
                CONTENT_WIDTH * 0.21,
                CONTENT_WIDTH * 0.21,
                CONTENT_WIDTH * 0.15,
            ],
            st,
        ),
    ]
    # A short series is held whole — a heading followed by one orphan row and a
    # page break is the worst way to show a trend. A long one (a board report's
    # twelve months) is allowed to split instead: holding it whole pushes the
    # entire table to a fresh page and strands most of the one above it, and a
    # split table repeats its header row anyway.
    held: list = (
        [KeepTogether(block)] if len(rows) <= KEEP_WHOLE_MAX_ROWS else block
    )
    return held + [Spacer(1, 10)]


# --- Document shell ----------------------------------------------------------


class _ReportDoc(BaseDocTemplate):
    """A report page: one frame, plus a footer drawn on every page.

    The footer carries the company and the page number because a board pack is
    routinely split, stapled and passed around a table — a loose page with no
    company on it belongs to nobody.
    """

    def __init__(self, buffer: io.BytesIO, *, title: str, company: str, author: str):
        super().__init__(
            buffer,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN + 8 * mm,
            title=title,
            author=author,
            subject=title,
            creator=APP_NAME,
        )
        self._company = company
        self._footer_label = title
        frame = Frame(
            MARGIN,
            self.bottomMargin,
            CONTENT_WIDTH,
            PAGE_HEIGHT - self.topMargin - self.bottomMargin,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="report", frames=[frame], onPage=self._footer)])

    def _footer(self, canvas, doc) -> None:
        canvas.saveState()
        y = MARGIN + 4 * mm
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y + 5 * mm, PAGE_WIDTH - MARGIN, y + 5 * mm)
        canvas.setFont(FONT_REGULAR, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, y, f"{self._company} · {self._footer_label}")
        canvas.drawRightString(
            PAGE_WIDTH - MARGIN, y, f"{APP_NAME} · Page {canvas.getPageNumber()}"
        )
        canvas.restoreState()


def _build(story: list, *, title: str, company: str, st) -> bytes:
    """Render a story to PDF bytes, closing with the disclaimer."""
    story = list(story) + [
        Spacer(1, 6),
        _rule(),
        Spacer(1, 6),
        Paragraph(DISCLAIMER, st["disclaimer"]),
    ]
    buffer = io.BytesIO()
    doc = _ReportDoc(buffer, title=title, company=company, author=APP_NAME)
    doc.build(story)
    return buffer.getvalue()


# --- Filenames ---------------------------------------------------------------


def _slug(text: str) -> str:
    """A filename-safe slug of a company name — 'Northwind Analytics' →
    'Northwind-Analytics'.

    Company names are user-typed and may contain slashes, quotes or non-Latin
    scripts, none of which belong in a `Content-Disposition` filename. Anything
    that doesn't survive is dropped; a name that reduces to nothing falls back
    to 'company' rather than producing a file called '-Monthly.pdf'.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return cleaned[:60] or "company"


def monthly_filename(report: MonthlyReport) -> str:
    return f"{_slug(report.company.name)}-Monthly-Report-{report.month}.pdf"


def board_filename(report: BoardReport) -> str:
    return (
        f"{_slug(report.company.name)}-Board-Report-"
        f"{report.period.capitalize()}-{report.current.end_month}.pdf"
    )


def investor_filename(report: InvestorSummary) -> str:
    return (
        f"{_slug(report.company.name)}-Investor-Readiness-"
        f"{report.window.end_month}.pdf"
    )


# --- Monthly Financial Report (FR-7.1) ---------------------------------------


def render_monthly_report(report: MonthlyReport) -> bytes:
    """The Monthly Financial Report as a PDF (FR-7.1 + FR-7.4)."""
    register_fonts()
    st = _styles()
    month_label = format_month_key(report.month)

    story = _header_block(
        "Monthly Financial Report",
        report.company.name,
        f"{month_label} · {format_date(report.period_start)} – "
        f"{format_date(report.period_end)}",
        report.generated_at,
        st,
    )

    story += [_section("Headline figures", st)]
    story += _totals_tiles(report.kpis, report.closing_cash, st)
    story += [
        Paragraph(
            f"{report.transaction_count} entries recorded this month "
            f"({report.income_count} income, {report.expense_count} expense).",
            st["note"],
        ),
        Spacer(1, 10),
    ]

    story += [_section("Key performance indicators", st)]
    story += _kpi_tiles(report.kpis, st, growth_note="vs. previous month")
    story += [Spacer(1, 4)]

    # --- Against the previous month ---
    comp = report.comparison
    prev_label = format_month_key(comp.month)
    rows = [
        (
            "Revenue",
            format_inr(comp.total_revenue),
            format_inr(report.kpis.total_revenue),
            _colored(
                _signed_money(comp.revenue_change),
                _sign_color(comp.revenue_change),
                st["cell_right"],
            ),
        ),
        (
            "Expenses",
            format_inr(comp.total_expenses),
            format_inr(report.kpis.total_expenses),
            # More spend is not "good": expenses are shown uncoloured so the
            # sign is read rather than the colour.
            _signed_money(comp.expenses_change),
        ),
        (
            "Net cash flow",
            _signed_money(comp.net_cash_flow),
            _signed_money(report.kpis.net_cash_flow),
            _colored(
                _signed_money(comp.net_change),
                _sign_color(comp.net_change),
                st["cell_right"],
            ),
        ),
    ]
    story += [
        _section(f"{month_label} against {prev_label}", st),
        _table(
            ["", prev_label, month_label, "Change"],
            rows,
            [
                CONTENT_WIDTH * 0.22,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
            ],
            st,
        ),
    ]
    if not comp.has_data:
        story += [
            Spacer(1, 3),
            Paragraph(
                f"Nothing was recorded in {prev_label}, so these changes are "
                "differences against zero — they mean “no record of that month”, "
                "not “the business did nothing”.",
                st["note"],
            ),
        ]
    story += [Spacer(1, 10)]

    story += [_section("Where the money went", st)]
    story += _category_table(report.categories, st)

    story += _monthly_table(report.trend, st, "Recent trend")

    # --- Flagged expenses ---
    story += [_section("Flagged expenses", st)]
    if report.anomalies:
        rows = [
            (
                format_date(a.date),
                a.category_name,
                a.description or DASH,
                format_inr(a.amount),
            )
            for a in report.anomalies
        ]
        story += [
            _table(
                ["Date", "Category", "Description", "Amount"],
                rows,
                [
                    CONTENT_WIDTH * 0.16,
                    CONTENT_WIDTH * 0.20,
                    CONTENT_WIDTH * 0.42,
                    CONTENT_WIDTH * 0.22,
                ],
                st,
                right_align_from=3,
            ),
            Spacer(1, 3),
            Paragraph(
                "Expenses that sit well above this category's own recent pattern. "
                "A flag is a prompt to look, not a finding of error.",
                st["note"],
            ),
        ]
    else:
        story += [
            Paragraph(
                "Nothing in this month sat far enough outside its category's "
                "usual pattern to flag.",
                st["note"],
            )
        ]

    return _build(
        story,
        title=f"Monthly Financial Report — {month_label}",
        company=report.company.name,
        st=st,
    )


# --- Board Report (FR-7.2) ---------------------------------------------------


def render_board_report(report: BoardReport) -> bytes:
    """The Board Report as a PDF (FR-7.2 + FR-7.4)."""
    register_fonts()
    st = _styles()

    cur, prev = report.current, report.previous
    period_label = "Quarter" if report.period == "quarter" else "Year"
    cur_label = f"{format_month_key(cur.start_month)} – {format_month_key(cur.end_month)}"
    prev_label = (
        f"{format_month_key(prev.start_month)} – {format_month_key(prev.end_month)}"
    )

    story = _header_block(
        f"Board Report — Trailing {period_label}",
        report.company.name,
        f"{cur_label} · {report.num_months} months",
        report.generated_at,
        st,
    )

    story += [_section("Headline figures", st)]
    story += _totals_tiles(cur.kpis, report.cash.closing_cash, st)
    story += [
        Paragraph(
            f"{cur.transaction_count} entries recorded across the period.",
            st["note"],
        ),
        Spacer(1, 10),
    ]

    story += [_section("Key performance indicators", st)]
    story += _kpi_tiles(cur.kpis, st, growth_note=f"vs. previous {report.period}")
    story += [Spacer(1, 4)]

    # --- Cash position ---
    cash = report.cash
    story += [_section("Cash position", st)]
    story += _tiles(
        [
            _money_tile("Opening cash", cash.opening_cash, "at period start"),
            _money_tile("Closing cash", cash.closing_cash, "at period end"),
            (
                "Movement",
                f"{'+' if cash.net_change >= 0 else '-'}"
                f"{format_compact_inr(abs(cash.net_change))}",
                f"{_signed_money(cash.net_change)} · closing minus opening",
            ),
        ],
        st,
        per_row=3,
    )
    story += [Spacer(1, 4)]

    # --- This period against the last ---
    mv = report.movement
    rows = [
        (
            "Revenue",
            format_inr(prev.kpis.total_revenue),
            format_inr(cur.kpis.total_revenue),
            _colored(
                _signed_money(mv.revenue_change),
                _sign_color(mv.revenue_change),
                st["cell_right"],
            ),
        ),
        (
            "Expenses",
            format_inr(prev.kpis.total_expenses),
            format_inr(cur.kpis.total_expenses),
            _signed_money(mv.expenses_change),
        ),
        (
            "Net cash flow",
            _signed_money(prev.kpis.net_cash_flow),
            _signed_money(cur.kpis.net_cash_flow),
            _colored(
                _signed_money(mv.net_change),
                _sign_color(mv.net_change),
                st["cell_right"],
            ),
        ),
        (
            "Burn rate (per month)",
            f"{format_inr(prev.kpis.burn_rate)}/mo",
            f"{format_inr(cur.kpis.burn_rate)}/mo",
            # The change is itself a per-month figure; without the suffix it
            # reads as a total and understates by a factor of three.
            f"{_signed_money(mv.burn_rate_change)}/mo",
        ),
    ]
    story += [
        _section(f"This {report.period} against the last", st),
        _table(
            ["", f"Previous ({prev_label})", f"Current ({cur_label})", "Change"],
            rows,
            [
                CONTENT_WIDTH * 0.22,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
            ],
            st,
        ),
    ]
    if not prev.has_data:
        story += [
            Spacer(1, 3),
            Paragraph(
                f"Nothing was recorded in {prev_label}, so these changes are "
                "differences against zero — the comparison period has no data, "
                "rather than no activity.",
                st["note"],
            ),
        ]
    story += [Spacer(1, 10)]

    story += _monthly_table(report.monthly, st, "Month by month")

    story += [_section("Cost structure", st)]
    story += _category_table(report.categories, st)

    # --- Watch items ---
    story += [_section("What we're watching", st)]
    if report.watch_items:
        rows = [
            (
                format_month_key(w.month),
                w.category_name,
                str(w.transaction_count),
                format_inr(w.total),
            )
            for w in report.watch_items
        ]
        story += [
            _table(
                ["Month", "Category", "Entries", "Flagged spend"],
                rows,
                [
                    CONTENT_WIDTH * 0.20,
                    CONTENT_WIDTH * 0.36,
                    CONTENT_WIDTH * 0.16,
                    CONTENT_WIDTH * 0.28,
                ],
                st,
                right_align_from=2,
            ),
            Spacer(1, 3),
            Paragraph(
                "Spend flagged as well above its category's own recent pattern, "
                "grouped by category and month.",
                st["note"],
            ),
        ]
    else:
        story += [
            Paragraph(
                "No spend in this period sat far enough outside its category's "
                "usual pattern to flag.",
                st["note"],
            )
        ]
    story += [Spacer(1, 10)]

    # --- Scenarios on the table ---
    story += [_section("Scenarios modelled", st)]
    if report.scenarios:
        rows = []
        for sc in report.scenarios:
            # Baseline → scenario, with the unit in the column header rather
            # than repeated twice inside a cell narrow enough to wrap on it.
            base = (
                DASH
                if sc.baseline_runway_months is None
                else format_months(sc.baseline_runway_months)
            )
            after = (
                DASH
                if sc.scenario_runway_months is None
                else format_months(sc.scenario_runway_months)
            )
            rows.append(
                (
                    sc.name,
                    _signed_compact(sc.revenue_change),
                    _signed_compact(sc.expenses_change),
                    _colored(
                        _signed_compact(sc.net_cash_flow_change),
                        _sign_color(sc.net_cash_flow_change),
                        st["cell_right"],
                    ),
                    f"{base} → {after}",
                )
            )
        story += [
            _table(
                ["Scenario", "Revenue", "Expenses", "Net", "Runway (months)"],
                rows,
                [
                    CONTENT_WIDTH * 0.34,
                    CONTENT_WIDTH * 0.14,
                    CONTENT_WIDTH * 0.14,
                    CONTENT_WIDTH * 0.14,
                    CONTENT_WIDTH * 0.24,
                ],
                st,
            ),
            Spacer(1, 3),
            Paragraph(
                "Saved what-if models, shown as they were calculated when saved, "
                "and rounded to magnitude. They are plans, not results.",
                st["note"],
            ),
        ]
    else:
        story += [Paragraph("No scenarios have been saved yet.", st["note"])]

    return _build(
        story,
        title=f"Board Report — {cur_label}",
        company=report.company.name,
        st=st,
    )


# --- Investor Readiness Summary (FR-7.3) -------------------------------------


def _check_rows(report: InvestorSummary, st) -> list[list]:
    """One row per graded check, with the threshold it was graded against.

    The threshold travels beside the verdict for the same reason the screen
    shows it: "Runway — Attention" is an opinion until the reader can see that
    the rule was 12 months ready / 6 months attention, and that the rule is
    fixed rather than chosen after the fact.
    """
    rows = []
    for check in report.checks:
        color = STATUS_COLORS.get(check.status, MUTED)
        label = STATUS_LABELS.get(check.status, check.status)
        if check.value is None:
            value = DASH
        elif check.unit == "months":
            value = format_months(check.value)
        else:
            value = format_pct(check.value)
        rule = (
            f"{format_months(check.ready_at)}+ ready, "
            f"{format_months(check.attention_at)}+ attention"
            if check.unit == "months"
            else (
                f"{format_pct(check.ready_at)}+ ready, "
                f"{format_pct(check.attention_at)}+ attention"
            )
        )
        rows.append(
            [
                Paragraph(
                    f"<b>{_esc(check.label)}</b><br/>"
                    f'<font size="7.5" color="{MUTED.hexval()}">{_esc(check.detail)}</font>',
                    st["cell"],
                ),
                Paragraph(_esc(value), st["cell_right"]),
                Paragraph(
                    f'<font size="7.5" color="{MUTED.hexval()}">{_esc(rule)}</font>',
                    st["cell_right"],
                ),
                _colored(f"<b>{label}</b>", color, st["cell_right"]),
            ]
        )
    return rows


def render_investor_summary(report: InvestorSummary) -> bytes:
    """The Investor Readiness Summary as a PDF (FR-7.3 + FR-7.4)."""
    register_fonts()
    st = _styles()

    win, prev = report.window, report.previous
    win_label = f"{format_month_key(win.start_month)} – {format_month_key(win.end_month)}"
    prev_label = (
        f"{format_month_key(prev.start_month)} – {format_month_key(prev.end_month)}"
    )

    story = _header_block(
        "Investor Readiness Summary",
        report.company.name,
        f"Trailing {report.num_months} months · {win_label}",
        report.generated_at,
        st,
    )

    # --- Overall verdict ---
    overall_color = STATUS_COLORS.get(report.overall_status, MUTED)
    overall_label = STATUS_LABELS.get(report.overall_status, report.overall_status)
    verdict = Table(
        [
            [
                [
                    Paragraph("Overall readiness", st["tile_label"]),
                    Spacer(1, 2),
                    _colored(f"<b>{overall_label}</b>", overall_color, st["tile_value"]),
                ],
                [
                    Paragraph(
                        "This is the <b>weakest of the six checks below</b>, not a "
                        "score. There is deliberately no combined rating: a single "
                        "number would imply a precision this data cannot support, "
                        "and would invite being read as a valuation.",
                        st["cell"],
                    )
                ],
            ]
        ],
        colWidths=[CONTENT_WIDTH * 0.28, CONTENT_WIDTH * 0.72],
    )
    verdict.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
                ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                ("LINEAFTER", (0, 0), (0, 0), 0.4, RULE),
            ]
        )
    )
    story += [verdict, Spacer(1, 12)]

    # --- Run-rate and efficiency ---
    story += [_section("The headline numbers", st)]
    story += _tiles(
        [
            _money_tile(
                "Monthly run-rate",
                report.run_rate.monthly,
                f"revenue in {format_month_key(report.run_rate.month)}",
            ),
            _money_tile(
                "Annualised run-rate",
                report.run_rate.annualised,
                "latest month × 12",
            ),
            _money_tile(
                "Revenue (trailing year)", win.kpis.total_revenue, win_label
            ),
            (
                "Burn multiple",
                DASH if report.burn_multiple is None else str(
                    report.burn_multiple.quantize(Decimal("0.01"))
                ),
                "Not burning cash"
                if report.burn_multiple is None
                else "Burn per ₹1 of new revenue",
            ),
        ],
        st,
        per_row=4,
    )
    story += [
        Paragraph(
            "The run-rate is taken from the latest month with data, not the "
            "trailing year averaged — averaging in months before the company "
            "was selling would understate it. The trailing-year total is shown "
            "beside it so both are visible.",
            st["note"],
        ),
        Spacer(1, 10),
    ]

    story += [_section("Key performance indicators", st)]
    story += _kpi_tiles(win.kpis, st, growth_note="vs. previous year")
    story += [Spacer(1, 4)]

    story += [_section("Cash position", st)]
    story += _tiles(
        [
            _money_tile("Opening cash", report.cash.opening_cash, "at period start"),
            _money_tile("Closing cash", report.cash.closing_cash, "at period end"),
            (
                "Movement",
                f"{'+' if report.cash.net_change >= 0 else '-'}"
                f"{format_compact_inr(abs(report.cash.net_change))}",
                f"{_signed_money(report.cash.net_change)} · closing minus opening",
            ),
        ],
        st,
        per_row=3,
    )
    story += [Spacer(1, 4)]

    # --- Readiness checks: the point of the document, kept on one page. ---
    # Deliberately not wrapped in KeepTogether: six checks with their prose run
    # tall enough that holding the block whole strands half a page above it. The
    # table repeats its header row when it splits, which reads fine.
    story += [
        _section("Readiness checks", st),
        _table(
            ["Check", "Value", "Threshold", "Status"],
            _check_rows(report, st),
            [
                CONTENT_WIDTH * 0.46,
                CONTENT_WIDTH * 0.12,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.16,
            ],
            st,
        ),
        Spacer(1, 3),
        Paragraph(
            "Each check is graded against a fixed threshold stated beside it — "
            "the same rule for every company, applied to this platform's own "
            "calculations. A check that could not be measured reads “Not "
            "measurable” and is never counted as a pass.",
            st["note"],
        ),
        Spacer(1, 10),
    ]

    # --- Track record ---
    mv = report.movement
    rows = [
        (
            "Revenue",
            format_inr(prev.kpis.total_revenue),
            format_inr(win.kpis.total_revenue),
            _colored(
                _signed_money(mv.revenue_change),
                _sign_color(mv.revenue_change),
                st["cell_right"],
            ),
        ),
        (
            "Expenses",
            format_inr(prev.kpis.total_expenses),
            format_inr(win.kpis.total_expenses),
            _signed_money(mv.expenses_change),
        ),
        (
            "Net cash flow",
            _signed_money(prev.kpis.net_cash_flow),
            _signed_money(win.kpis.net_cash_flow),
            _colored(
                _signed_money(mv.net_change),
                _sign_color(mv.net_change),
                st["cell_right"],
            ),
        ),
    ]
    story += [
        _section("This year against the year before", st),
        _table(
            ["", f"Previous ({prev_label})", f"Current ({win_label})", "Change"],
            rows,
            [
                CONTENT_WIDTH * 0.22,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
                CONTENT_WIDTH * 0.26,
            ],
            st,
        ),
        Spacer(1, 3),
        Paragraph(
            f"{report.months_of_history} months of recorded history, "
            f"{report.months_with_revenue} of them with revenue.",
            st["note"],
        ),
        Spacer(1, 10),
    ]

    story += _monthly_table(report.monthly, st, "Month by month")

    story += [_section("Cost structure", st)]
    story += _category_table(report.categories, st)

    return _build(
        story,
        title=f"Investor Readiness Summary — {win_label}",
        company=report.company.name,
        st=st,
    )
