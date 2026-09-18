"""
Client-facing exports for a pricing project -- an Excel workbook built
the way Somos's own hand-built proposal budgets are (a Title/Billing-Rate
header, a phase/line-item hours grid with live formulas, a rates
reference table, a budget summary rollup, and a scope-exclusions page),
plus a PDF version of the same proposal for sending directly to a
client.

This is deliberately not a data dump of the pricing_store JSON -- it's
meant to read as the same kind of work product as the two real sample
budgets this tool was built against (a single-firm hours matrix, and a
multi-firm/multi-phase budget with its own rates and exclusions tabs).
Excluded items (a role, a phase, a line item toggled off in the tool)
are shown struck through with their would-be cost rather than deleted,
so the export documents the choices made, not just the result.
"""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Somos brand-neutral palette, shared with the dashboard's charts
# (dashboard/charts/theme.py) so the exported proposal reads as the same
# system as the app it came from.
INK_PRIMARY = "0b0b0b"
INK_MUTED = "898781"
ACCENT = "2a78d6"
LIGHT_FILL = "F3F3F3"
EXCLUDED_GRAY = "9a9890"

BRAND_NAME = f"{config.HOME_FIRM_NAME.upper()} GROUP"
CONFIDENTIAL_NOTE = "Confidential -- Prepared exclusively for the addressed client"


def _sorted_roles(project: dict) -> list[dict]:
    return sorted(project["roles"], key=lambda r: (r["firm"], r["title"]))


def _phase_status(phase: dict) -> str:
    if not phase["enabled"]:
        return "Excluded"
    return "Included" if any(s["enabled"] for s in phase["subtasks"]) else "Excluded"


# ---------------------------------------------------------------------------
# Excel workbook
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor=LIGHT_FILL)
_HEADER_FONT = Font(bold=True, color=INK_PRIMARY)
_TITLE_FONT = Font(bold=True, size=16, color=INK_PRIMARY)
_SUBTITLE_FONT = Font(size=10, color=INK_MUTED)
_MONEY_FMT = '"$"#,##0.00'
_TOP_BORDER = Border(top=Side(style="thin", color=INK_MUTED))
_EXCLUDED_FONT = Font(italic=True, strike=True, color=EXCLUDED_GRAY)
_ACCENT_FILL = PatternFill("solid", fgColor=ACCENT)
_BAND_ROWS = 3  # brand banner + confidentiality line + spacer, before any sheet's own content


def _brand_band(ws, ncols: int, project_name: str):
    """Somos letterhead banner at the top of every sheet: an accent-color
    band with the firm wordmark and project name, a confidentiality line,
    then a spacer row before the sheet's own content starts."""
    last_col = get_column_letter(max(ncols, 1))
    ws.merge_cells(f"A1:{last_col}1")
    band = ws["A1"]
    band.value = f"{BRAND_NAME}   |   {project_name}"
    band.font = Font(bold=True, size=13, color="FFFFFF")
    band.fill = _ACCENT_FILL
    band.alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 24

    ws.merge_cells(f"A2:{last_col}2")
    note = ws["A2"]
    note.value = CONFIDENTIAL_NOTE
    note.font = Font(italic=True, size=9, color=INK_MUTED)


def build_workbook(project: dict, comp: dict) -> bytes:
    wb = Workbook()

    _sheet_cover(wb.active, project, comp)
    _sheet_rates(wb.create_sheet("Rates"), project)
    _sheet_budget(wb.create_sheet("Budget"), project, comp)
    _sheet_summary(wb.create_sheet("Budget Summary"), project, comp)
    _sheet_exclusions(wb.create_sheet("Exclusions"), project)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet_cover(ws, project: dict, comp: dict):
    ws.title = "Cover"
    ws.column_dimensions["A"].width = 100
    _brand_band(ws, 1, project["project_name"])
    ws["A4"] = project["project_name"]
    ws["A4"].font = Font(bold=True, size=20, color=INK_PRIMARY)
    row = 6
    if project.get("client_name"):
        ws[f"A{row}"] = f"Prepared for: {project['client_name']}"
        ws[f"A{row}"].font = _SUBTITLE_FONT
        row += 1
    ws[f"A{row}"] = f"Prepared by: {BRAND_NAME.title()}"
    ws[f"A{row}"].font = _SUBTITLE_FONT
    row += 1
    ws[f"A{row}"] = f"Date: {datetime.date.today():%B %d, %Y}"
    ws[f"A{row}"].font = _SUBTITLE_FONT
    row += 2
    if project.get("notes"):
        ws[f"A{row}"] = project["notes"]
        ws[f"A{row}"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = max(30, 14 * (len(project["notes"]) // 90 + 1))
        row += 2
    ws[f"A{row}"] = "Project Total"
    ws[f"A{row}"].font = _HEADER_FONT
    row += 1
    ws[f"A{row}"] = comp["grand_total"]
    ws[f"A{row}"].number_format = _MONEY_FMT
    ws[f"A{row}"].font = Font(bold=True, size=14, color=ACCENT)


def _sheet_rates(ws, project: dict):
    headers = ["Firm", "Role", "Rate ($/hr)", "Status"]
    _brand_band(ws, len(headers), project["project_name"])
    header_row = _BAND_ROWS + 1
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    for i, role in enumerate(_sorted_roles(project), start=header_row + 1):
        status = "Included" if role["enabled"] else "Excluded"
        vals = [role["firm"], role["title"], role["rate"], status]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            if c == 3:
                cell.number_format = _MONEY_FMT
            if not role["enabled"]:
                cell.font = _EXCLUDED_FONT
    for col, width in zip("ABCD", [22, 26, 14, 12]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = f"A{header_row + 1}"


def _sheet_budget(ws, project: dict, comp: dict):
    roles = [r for r in _sorted_roles(project) if r["enabled"]]
    role_col_start = 6  # F
    headers = ["Line Item", "Status", "Notes", "Total Hours", "Total Cost"] + [
        f"{r['firm']}: {r['title']}" for r in roles
    ]
    _brand_band(ws, len(headers), project["project_name"])
    header_row = _BAND_ROWS + 1
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL

    rate_row = header_row + 1
    ws.cell(row=rate_row, column=1, value="Billing Rate ($/hr)").font = _HEADER_FONT
    for i, role in enumerate(roles):
        cell = ws.cell(row=rate_row, column=role_col_start + i, value=role["rate"])
        cell.font = Font(bold=True)
        cell.number_format = _MONEY_FMT

    row = rate_row
    phase_cost_cells = []
    for phase in project["phases"]:
        sub_start = row + 1
        for sub in phase["subtasks"]:
            row += 1
            status = "Included" if (phase["enabled"] and sub["enabled"]) else "Excluded"
            font = None if status == "Included" else _EXCLUDED_FONT
            ws.cell(row=row, column=1, value=f"  {sub['name']}").font = font
            ws.cell(row=row, column=2, value=status).font = font

            first_role_col = get_column_letter(role_col_start)
            last_role_col = get_column_letter(role_col_start + len(roles) - 1)
            hours_cell = ws.cell(row=row, column=4, value=f"=SUM({first_role_col}{row}:{last_role_col}{row})")
            hours_cell.font = font
            cost_cell = ws.cell(
                row=row,
                column=5,
                value=(
                    f"=SUMPRODUCT({first_role_col}{rate_row}:{last_role_col}{rate_row},"
                    f"{first_role_col}{row}:{last_role_col}{row})"
                ),
            )
            cost_cell.number_format = _MONEY_FMT
            cost_cell.font = font
            for i, role in enumerate(roles):
                hrs = sub["hours"].get(role["id"], 0) or 0
                c = ws.cell(row=row, column=role_col_start + i, value=hrs)
                c.font = font
        sub_end = row
        if not phase["subtasks"]:
            sub_start, sub_end = row + 1, row + 1
            row += 1

        row += 1
        status_col = get_column_letter(2)
        cost_col = get_column_letter(5)
        hours_col = get_column_letter(4)
        phase_status = _phase_status(phase)
        phase_font = Font(bold=True) if phase_status == "Included" else Font(bold=True, italic=True, strike=True, color=EXCLUDED_GRAY)
        ws.cell(row=row, column=1, value=phase["name"]).font = phase_font
        ws.cell(row=row, column=2, value=phase_status).font = phase_font
        ws.cell(row=row, column=3, value=phase.get("note", "")).font = Font(italic=True, color=INK_MUTED)
        hours_formula = f"=SUMIF({status_col}{sub_start}:{status_col}{sub_end},\"Included\",{hours_col}{sub_start}:{hours_col}{sub_end})"
        cost_formula = f"=SUMIF({status_col}{sub_start}:{status_col}{sub_end},\"Included\",{cost_col}{sub_start}:{cost_col}{sub_end})"
        ws.cell(row=row, column=4, value=hours_formula).font = phase_font
        cost_cell = ws.cell(row=row, column=5, value=cost_formula)
        cost_cell.font = phase_font
        cost_cell.number_format = _MONEY_FMT
        for c in range(1, len(headers) + 1):
            ws.cell(row=row, column=c).fill = _HEADER_FILL
        phase_cost_cells.append(f"E{row}")
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="PROJECT TOTAL").font = Font(bold=True, size=12)
    total_cell = ws.cell(row=row, column=5, value=f"=SUM({','.join(phase_cost_cells)})" if phase_cost_cells else 0)
    total_cell.font = Font(bold=True, size=12, color=ACCENT)
    total_cell.number_format = _MONEY_FMT
    for c in range(1, len(headers) + 1):
        ws.cell(row=row, column=c).border = _TOP_BORDER

    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 11
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 14
    for i in range(len(roles)):
        ws.column_dimensions[get_column_letter(role_col_start + i)].width = 14
    ws.freeze_panes = f"A{rate_row + 1}"


def _sheet_summary(ws, project: dict, comp: dict):
    headers = ["Firm", "Labor", "Expenses", "Total"]
    _brand_band(ws, len(headers), project["project_name"])
    header_row = _BAND_ROWS + 1
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    row = header_row + 1
    for firm in sorted(comp["firm_total"], key=lambda f: -comp["firm_total"][f]):
        vals = [firm, comp["firm_labor"].get(firm, 0), comp["firm_expenses"].get(firm, 0), comp["firm_total"][firm]]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=row, column=c, value=v)
            if c > 1:
                cell.number_format = _MONEY_FMT
        row += 1
    ws.cell(row=row, column=1, value="PROPOSAL TOTAL").font = Font(bold=True)
    for c, v in zip([2, 3, 4], [comp["labor_total"], comp["expense_total"], comp["grand_total"]]):
        cell = ws.cell(row=row, column=c, value=v)
        cell.number_format = _MONEY_FMT
        cell.font = Font(bold=True, color=ACCENT)
    for c in range(1, 5):
        ws.cell(row=row, column=c).border = _TOP_BORDER
    for col, width in zip("ABCD", [22, 16, 16, 16]):
        ws.column_dimensions[col].width = width


def _sheet_exclusions(ws, project: dict):
    ws.column_dimensions["A"].width = 100
    _brand_band(ws, 1, project["project_name"])
    title_row = _BAND_ROWS + 1
    ws.cell(row=title_row, column=1, value="Scope Exclusions & Assumptions").font = Font(bold=True, size=14, color=INK_PRIMARY)
    exclusions = project.get("exclusions") or []
    if not exclusions:
        ws.cell(row=title_row + 2, column=1, value="No exclusions or assumptions have been specified for this proposal.").font = Font(
            italic=True, color=INK_MUTED
        )
        return
    for i, item in enumerate(exclusions, start=title_row + 2):
        ws.cell(row=i, column=1, value=f"• {item}").alignment = Alignment(wrap_text=True)


# ---------------------------------------------------------------------------
# PDF proposal
# ---------------------------------------------------------------------------

_PDF_ACCENT = colors.HexColor(f"#{ACCENT}")
_PDF_MUTED = colors.HexColor(f"#{INK_MUTED}")
_PDF_EXCLUDED = colors.HexColor(f"#{EXCLUDED_GRAY}")
_PDF_LIGHT = colors.HexColor(f"#{LIGHT_FILL}")


def _pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ProposalTitle", parent=styles["Title"], fontSize=24, spaceAfter=6))
    styles.add(ParagraphStyle("ProposalMeta", parent=styles["Normal"], textColor=_PDF_MUTED, fontSize=10))
    styles.add(ParagraphStyle("SectionHeading", parent=styles["Heading2"], textColor=colors.HexColor(f"#{INK_PRIMARY}"), spaceBefore=16))
    styles.add(ParagraphStyle("PhaseHeading", parent=styles["Heading3"], textColor=_PDF_ACCENT, spaceBefore=10))
    styles.add(ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14))
    styles.add(ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle("CellExcluded", parent=styles["Cell"], textColor=_PDF_EXCLUDED))
    return styles


def _draw_letterhead(canvas, doc, project_name: str):
    """Somos letterhead: an accent band with the firm wordmark and
    project name on every page, plus a confidentiality/page-number
    footer -- drawn once per page rather than as flowable content so it
    stays fixed regardless of how the story reflows."""
    canvas.saveState()
    width, height = doc.pagesize
    band_height = 0.4 * inch

    canvas.setFillColor(_PDF_ACCENT)
    canvas.rect(0, height - band_height, width, band_height, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(0.6 * inch, height - band_height + 0.12 * inch, BRAND_NAME)
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(width - 0.6 * inch, height - band_height + 0.14 * inch, project_name)

    canvas.setFont("Helvetica-Oblique", 8)
    canvas.setFillColor(_PDF_MUTED)
    canvas.drawString(0.6 * inch, 0.35 * inch, CONFIDENTIAL_NOTE)
    canvas.drawRightString(width - 0.6 * inch, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(project: dict, comp: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.75 * inch,
        title=f"{project['project_name']} -- Pricing Proposal",
    )
    styles = _pdf_styles()
    story = []

    story += _pdf_cover(project, comp, styles)
    story.append(PageBreak())
    story += _pdf_rates(project, styles)
    story.append(PageBreak())
    story += _pdf_budget(project, comp, styles)
    story.append(PageBreak())
    story += _pdf_summary(comp, styles)
    story.append(PageBreak())
    story += _pdf_exclusions(project, styles)

    def _on_page(canvas, doc_):
        _draw_letterhead(canvas, doc_, project["project_name"])

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


def _pdf_cover(project: dict, comp: dict, styles) -> list:
    story = [
        Spacer(1, 1.2 * inch),
        Paragraph(project["project_name"], styles["ProposalTitle"]),
        Paragraph("Project Pricing Proposal", styles["ProposalMeta"]),
        Spacer(1, 0.25 * inch),
    ]
    import config as _config

    if project.get("client_name"):
        story.append(Paragraph(f"Prepared for: {project['client_name']}", styles["ProposalMeta"]))
    story.append(Paragraph(f"Prepared by: {_config.HOME_FIRM_NAME} Group", styles["ProposalMeta"]))
    story.append(Paragraph(f"Date: {datetime.date.today():%B %d, %Y}", styles["ProposalMeta"]))
    if project.get("notes"):
        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph(project["notes"], styles["Body"]))
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(f"Estimated Project Total: {_fmt(comp['grand_total'])}", styles["SectionHeading"]))
    return story


def _pdf_rates(project: dict, styles) -> list:
    story = [Paragraph("Team & Rates", styles["SectionHeading"])]
    rows = [["Firm", "Role", "Rate ($/hr)", "Status"]]
    row_styles = []
    for i, role in enumerate(_sorted_roles(project), start=1):
        status = "Included" if role["enabled"] else "Excluded"
        cell_style = styles["Cell"] if role["enabled"] else styles["CellExcluded"]
        rows.append(
            [Paragraph(role["firm"], cell_style), Paragraph(role["title"], cell_style), _fmt(role["rate"]), status]
        )
        if not role["enabled"]:
            row_styles.append(("TEXTCOLOR", (2, i), (-1, i), _PDF_EXCLUDED))
    t = Table(rows, hAlign="LEFT", colWidths=[1.8 * inch, 2.2 * inch, 1.2 * inch, 1 * inch])
    t.setStyle(TableStyle(_base_table_style() + row_styles))
    story.append(t)
    return story


def _pdf_budget(project: dict, comp: dict, styles) -> list:
    story = [Paragraph("Scope & Budget", styles["SectionHeading"])]
    roles = [r for r in _sorted_roles(project) if r["enabled"]]
    role_labels = [f"{r['firm']}\n{r['title']}" for r in roles]

    for phase, comp_phase in zip(project["phases"], comp["phases"]):
        status = _phase_status(phase)
        title = f"{phase['name']} -- {_fmt(comp_phase['cost'])} ({comp_phase['hours']:.0f} hrs)"
        if phase.get("note"):
            title += f"  [{phase['note']}]"
        heading_style = styles["PhaseHeading"] if status == "Included" else ParagraphStyle(
            "PhaseHeadingExcluded", parent=styles["PhaseHeading"], textColor=_PDF_EXCLUDED
        )
        story.append(Paragraph(title + (" (EXCLUDED)" if status == "Excluded" else ""), heading_style))

        header = ["Line Item", "Status", "Hours", "Cost"] + role_labels
        rows = [header]
        row_styles = []
        for i, sub in enumerate(phase["subtasks"], start=1):
            sub_status = "Included" if (phase["enabled"] and sub["enabled"]) else "Excluded"
            hours_by_role = [sub["hours"].get(r["id"], 0) or 0 for r in roles]
            cost = sum(h * r["rate"] for h, r in zip(hours_by_role, roles))
            cell_style = styles["Cell"] if sub_status == "Included" else styles["CellExcluded"]
            rows.append(
                [Paragraph(sub["name"], cell_style), sub_status, f"{sum(hours_by_role):.0f}", _fmt(cost)]
                + [(f"{h:g}" if h else "") for h in hours_by_role]
            )
            if sub_status == "Excluded":
                row_styles.append(("TEXTCOLOR", (1, i), (-1, i), _PDF_EXCLUDED))
        col_widths = [2.6 * inch, 0.8 * inch, 0.6 * inch, 0.8 * inch] + [0.75 * inch] * len(roles)
        t = Table(rows, hAlign="LEFT", colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle(_base_table_style() + row_styles))
        story.append(t)
        story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph(f"PROJECT TOTAL: {_fmt(comp['grand_total'])}", styles["SectionHeading"]))
    return story


def _pdf_summary(comp: dict, styles) -> list:
    story = [Paragraph("Budget Summary", styles["SectionHeading"])]
    rows = [["Firm", "Labor", "Expenses", "Total"]]
    for firm in sorted(comp["firm_total"], key=lambda f: -comp["firm_total"][f]):
        rows.append(
            [firm, _fmt(comp["firm_labor"].get(firm, 0)), _fmt(comp["firm_expenses"].get(firm, 0)), _fmt(comp["firm_total"][firm])]
        )
    rows.append(["PROPOSAL TOTAL", _fmt(comp["labor_total"]), _fmt(comp["expense_total"]), _fmt(comp["grand_total"])])
    t = Table(rows, hAlign="LEFT", colWidths=[2.2 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    style = _base_table_style() + [
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor(f"#{INK_MUTED}")),
    ]
    t.setStyle(TableStyle(style))
    story.append(t)
    return story


def _pdf_exclusions(project: dict, styles) -> list:
    story = [Paragraph("Scope Exclusions & Assumptions", styles["SectionHeading"])]
    exclusions = project.get("exclusions") or []
    if not exclusions:
        story.append(Paragraph("No exclusions or assumptions have been specified for this proposal.", styles["Body"]))
        return story
    items = [ListItem(Paragraph(e, styles["Body"])) for e in exclusions]
    story.append(ListFlowable(items, bulletType="bullet"))
    return story


def _base_table_style() -> list:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), _PDF_LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(f"#{INK_MUTED}")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]


def _fmt(v: float) -> str:
    return f"${v:,.0f}"
