"""
Excel export of the budget with live formulas: change an assumption, a
person's hours or rate, an overhead line or a driver in the workbook and
every total recalculates, the same way the Budget page does.

Sheets: Read Me, Assumptions, People, Revenue by Person, Salary by Person,
Overhead, Drivers, Budget P&L. Blue text = inputs, black = formulas,
green = links to another sheet, yellow fill = key assumptions.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.datavalidation import DataValidation

from dashboard.budget_model import (
    BASES, DRIVER_SECTIONS, MONTH_LABELS, PEOPLE_PLAN, PRIOR_PLUS, TREATMENTS, Assumptions,
)

FONT = "Arial"
BLUE = Font(name=FONT, color="0000FF")
BLACK = Font(name=FONT)
GREEN = Font(name=FONT, color="008000")
BOLD = Font(name=FONT, bold=True)
TITLE = Font(name=FONT, bold=True, size=14)
HEADER = Font(name=FONT, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
YELLOW = PatternFill("solid", fgColor="FFFF00")
TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
TOP = Border(top=Side(style="thin"))
USD = '$#,##0;($#,##0);"-"'
PCT = '0.0%;(0.0%);"-"'
NUM = '#,##0;(#,##0);"-"'
RATE = '$#,##0.00;($#,##0.00);"-"'

FIRST_ROW = 5  # first data row on the list sheets


def _header(ws, row, labels, widths=None):
    for i, text in enumerate(labels, start=1):
        c = ws.cell(row, i, text)
        c.font, c.fill = HEADER, HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[L(i)].width = w
    ws.freeze_panes = ws.cell(row + 1, 3)


def _put(ws, row, col, value, font=BLACK, fmt=None, fill=None):
    if isinstance(value, float) and np.isnan(value):
        value = None
    c = ws.cell(row, col, value)
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    return c


def _month_header(ws, row, first_col):
    """Month labels in `row`, month numbers (used by formulas) in row-1."""
    for i, label in enumerate(MONTH_LABELS):
        _put(ws, row - 1, first_col + i, i + 1, font=Font(name=FONT, color="808080"))
        c = ws.cell(row, first_col + i, label)
        c.font, c.fill = HEADER, HEADER_FILL
        c.alignment = Alignment(horizontal="center")


def build_workbook(a: Assumptions, people: pd.DataFrame, overhead: pd.DataFrame, drivers: pd.DataFrame) -> Workbook:
    wb = Workbook()

    # ---------------- Read Me ----------------
    ws = wb.active
    ws.title = "Read Me"
    lines = [
        (f"Somos Group budget, calendar {a.year}", TITLE),
        ("", BLACK),
        ("How it works", BOLD),
        ("Fee revenue = billable hours x seasonality weight x billing rate x realization, for each month a person is on staff.", BLACK),
        ("Salaries = annual salary / 12 for each month on staff, with the raise from the raise month. Fringe % is added on top.", BLACK),
        ("Overhead = prior-year actual x (1 + change %), or a fixed amount if you type one, spread evenly over 12 months.", BLACK),
        ("Prior-year revenue and payroll lines marked 'People plan' are replaced by the people plan, so they aren't counted twice.", BLACK),
        ("Drivers = lines you enter: owner draws, guaranteed payments, bonuses, leases, capex. Owner draws sit below net income.", BLACK),
        ("", BLACK),
        ("What to edit", BOLD),
        ("Blue text = inputs you can change. Black = formulas. Green = links to another sheet. Yellow = key assumptions.", BLACK),
        ("Assumptions: rates, raises, fringe, realization, seasonality.", BLACK),
        ("People: Include (Y/N), start/end month, salary, billable hours, rate, realization. Add a row for a new hire.", BLACK),
        ("Overhead: Treatment, Change %, or a Fixed amount (overrides Change %).", BLACK),
        ("Drivers: amount, basis (Per month / Per year / One-time), start and end month. Section 'Owner draws' goes below net income.", BLACK),
        ("To add people, overhead lines or drivers, insert rows inside each table (above its last row) so the totals pick them up.", BLACK),
        ("", BLACK),
        ("Sources: Vantagepoint (employee cost rates, labor detail, targets) and the firm's P&L workbook or GL, as loaded in the dashboard.", BLACK),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        _put(ws, i, 1, text, font)
    ws.column_dimensions["A"].width = 120

    # ---------------- Assumptions ----------------
    ws = wb.create_sheet("Assumptions")
    _put(ws, 1, 1, "Assumptions", TITLE)
    items = [
        ("Budget year", str(a.year), None, "Calendar year"),
        ("Billing rate increase", a.rate_increase_pct, PCT, "Applied to every person's rate"),
        ("Rate increase month (1-12)", a.rate_increase_month, "0", "New rates apply from this month"),
        ("Salary increase", a.salary_increase_pct, PCT, "Annual raise"),
        ("Salary increase month (1-12)", a.salary_increase_month, "0", "Raises apply from this month"),
        ("Payroll taxes & benefits (fringe)", a.fringe_pct, PCT, "On top of salaries. Fringe only, not overhead."),
        ("Default realization", a.realization_pct, PCT, "Billed / standard value, for new people rows"),
        ("Default overhead change", a.overhead_growth_pct, PCT, "For prior-year overhead lines"),
    ]
    _header(ws, 3, ["Assumption", "Value", "Note"], [36, 14, 60])
    ws.freeze_panes = None
    ref = {}
    for i, (label, value, fmt, note) in enumerate(items):
        r = 4 + i
        _put(ws, r, 1, label)
        _put(ws, r, 2, value, BLUE, fmt, YELLOW)
        _put(ws, r, 3, note, Font(name=FONT, italic=True, color="808080"))
        ref[label] = f"Assumptions!$B${r}"
    A_RATE, A_RATE_M = ref["Billing rate increase"], ref["Rate increase month (1-12)"]
    A_RAISE, A_RAISE_M = ref["Salary increase"], ref["Salary increase month (1-12)"]
    A_FRINGE = ref["Payroll taxes & benefits (fringe)"]

    sr = 4 + len(items) + 2
    _put(ws, sr, 1, "Seasonality (share of annual billable hours by month)", BOLD)
    _put(ws, sr + 1, 1, "Default = share of Mon-Fri workdays. Must total 100%.",
         Font(name=FONT, italic=True, color="808080"))
    for i, label in enumerate(MONTH_LABELS):
        _put(ws, sr + 2 + i, 1, label)
        _put(ws, sr + 2 + i, 2, float(a.seasonality[i]), BLUE, PCT)
    total_r = sr + 14
    _put(ws, total_r, 1, "Total", BOLD)
    _put(ws, total_r, 2, f"=SUM(B{sr + 2}:B{sr + 13})", BOLD, PCT)
    _put(ws, total_r, 3, f'=IF(ABS(B{total_r}-1)>0.0001,"Check: weights should total 100%","OK")')
    # Seasonality weight for month number m -> normalized so a typo can't inflate revenue.
    season = lambda col_month_ref: (  # noqa: E731
        f"INDEX(Assumptions!$B${sr + 2}:$B${sr + 13},{col_month_ref})/Assumptions!$B${total_r}"
    )

    # ---------------- People ----------------
    ws = wb.create_sheet("People")
    n = len(people)
    last = FIRST_ROW + max(n, 1)  # one blank row at the end for inserting
    _put(ws, 1, 1, "People plan", TITLE)
    _put(ws, 2, 1, "Example of a new hire row: Y | New Associate | Attorney | 4 | 12 | 150000 | 1900 | 325 | 90%",
         Font(name=FONT, italic=True, color="808080"))
    cols = ["Include (Y/N)", "Name", "Role", "Start month", "End month", "Annual salary ($)",
            "Billable hours (annual)", "Billing rate ($/hr)", "Realization", "Budget revenue ($)",
            "Salary + fringe ($)", "Contribution ($)", "Prior billable hours", "Prior rate ($/hr)", "Note"]
    _header(ws, FIRST_ROW - 1, cols, [9, 28, 12, 8, 8, 14, 12, 12, 11, 15, 15, 15, 12, 12, 40])
    for i, r in enumerate(people.itertuples(index=False)):
        row = FIRST_ROW + i
        _put(ws, row, 1, "Y" if bool(r.include) else "N", BLUE)
        _put(ws, row, 2, r.name, BLUE)
        _put(ws, row, 3, r.role or "", BLUE)
        _put(ws, row, 4, int(r.start_month or 1), BLUE, "0")
        _put(ws, row, 5, int(r.end_month or 12), BLUE, "0")
        _put(ws, row, 6, float(r.annual_salary or 0), BLUE, USD)
        _put(ws, row, 7, float(r.billable_hours or 0), BLUE, NUM)
        _put(ws, row, 8, float(r.bill_rate or 0), BLUE, RATE)
        _put(ws, row, 9, float(r.realization_pct if pd.notna(r.realization_pct) else a.realization_pct), BLUE, PCT)
        _put(ws, row, 10, f"=SUM('Revenue by Person'!C{row}:N{row})", GREEN, USD)
        _put(ws, row, 11, f"=SUM('Salary by Person'!C{row}:N{row})*(1+{A_FRINGE})", GREEN, USD)
        _put(ws, row, 12, f"=J{row}-K{row}", BLACK, USD)
        _put(ws, row, 13, r.prior_billable_hours, BLACK, NUM)
        _put(ws, row, 14, r.prior_rate, BLACK, RATE)
        _put(ws, row, 15, r.note or "")
    ws.cell(FIRST_ROW, 13).comment = Comment("Prior columns: last 12 months from Vantagepoint labor detail.", "Budget")
    _put(ws, last + 1, 2, "Total", BOLD)
    for c in (6, 7, 10, 11, 12):
        _put(ws, last + 1, c, f"=SUM({L(c)}{FIRST_ROW}:{L(c)}{last})", BOLD, NUM if c == 7 else USD).border = TOP
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"A{FIRST_ROW}:A{last}")
    people_last = last

    # ---------------- Revenue / Salary by person ----------------
    for title, kind in (("Revenue by Person", "rev"), ("Salary by Person", "sal")):
        ws = wb.create_sheet(title)
        _put(ws, 1, 1, title + (" (hours x weight x rate x realization)" if kind == "rev" else " (before fringe)"), TITLE)
        ws.cell(FIRST_ROW - 1, 1, "Name").font = HEADER
        ws.cell(FIRST_ROW - 1, 1).fill = HEADER_FILL
        ws.cell(FIRST_ROW - 1, 2, "Total").font = HEADER
        ws.cell(FIRST_ROW - 1, 2).fill = HEADER_FILL
        _month_header(ws, FIRST_ROW - 1, 3)
        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 14
        for c in range(3, 15):
            ws.column_dimensions[L(c)].width = 12
        ws.freeze_panes = "C5"
        for row in range(FIRST_ROW, people_last + 1):
            _put(ws, row, 1, f'=IF(People!B{row}="","",People!B{row})', GREEN)
            _put(ws, row, 2, f"=SUM(C{row}:N{row})", BLACK, USD)
            for i in range(12):
                col = 3 + i
                m = f"{L(col)}$3"
                on = f'AND(People!$A{row}="Y",{m}>=People!$D{row},{m}<=People!$E{row})'
                if kind == "rev":
                    calc = (f"People!$G{row}*{season(m)}*People!$H{row}"
                            f"*IF({m}>={A_RATE_M},1+{A_RATE},1)*People!$I{row}")
                else:
                    calc = f"People!$F{row}/12*IF({m}>={A_RAISE_M},1+{A_RAISE},1)"
                _put(ws, row, col, f"=IF({on},{calc},0)", BLACK, USD)
        _put(ws, people_last + 1, 1, "Total", BOLD)
        for c in range(2, 15):
            _put(ws, people_last + 1, c, f"=SUM({L(c)}{FIRST_ROW}:{L(c)}{people_last})", BOLD, USD).border = TOP

    # ---------------- Overhead ----------------
    ws = wb.create_sheet("Overhead")
    _put(ws, 1, 1, "Prior-year lines (overhead and other)", TITLE)
    _put(ws, 2, 1, f"Treatment: '{PRIOR_PLUS}' grows the line; '{PEOPLE_PLAN}' replaces it with the people plan "
                   "(fee revenue / payroll); 'Exclude' drops it. Fixed amount overrides Change %.",
         Font(name=FONT, italic=True, color="808080"))
    cols = ["Section", "Category", "Account", "Line item", "Treatment", "Prior year ($)", "Change %",
            "Fixed amount ($)", "Budget ($)"]
    _header(ws, FIRST_ROW - 1, cols, [14, 24, 10, 36, 16, 15, 10, 15, 15])
    ov_last = FIRST_ROW + max(len(overhead), 1)
    for i, r in enumerate(overhead.itertuples(index=False)):
        row = FIRST_ROW + i
        _put(ws, row, 1, r.section)
        _put(ws, row, 2, r.category or "")
        _put(ws, row, 3, r.account_number or "")
        _put(ws, row, 4, r.line_item)
        _put(ws, row, 5, r.treatment, BLUE)
        _put(ws, row, 6, float(r.prior_amount or 0), BLACK, USD)
        _put(ws, row, 7, float(r.growth_pct if pd.notna(r.growth_pct) else a.overhead_growth_pct), BLUE, PCT)
        _put(ws, row, 8, r.override_amount if pd.notna(r.override_amount) else None, BLUE, USD)
        _put(ws, row, 9, f'=IF(E{row}="{PRIOR_PLUS}",IF(H{row}<>"",H{row},F{row}*(1+G{row})),0)', BLACK, USD)
    _put(ws, ov_last + 1, 4, "Total", BOLD)
    for c in (6, 9):
        _put(ws, ov_last + 1, c, f"=SUM({L(c)}{FIRST_ROW}:{L(c)}{ov_last})", BOLD, USD).border = TOP
    dv = DataValidation(type="list", formula1='"' + ",".join(TREATMENTS) + '"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"E{FIRST_ROW}:E{ov_last}")
    ov_rng = lambda col: f"Overhead!${col}${FIRST_ROW}:${col}${ov_last}"  # noqa: E731

    # ---------------- Drivers ----------------
    ws = wb.create_sheet("Drivers")
    _put(ws, 1, 1, "Budget drivers (owner draws, guaranteed payments, bonuses, leases, capex...)", TITLE)
    _put(ws, 2, 1, "Example: Y | Owner draw - Partner A | Owner draws | Partner A | 50000 | Per month | 1 | 12",
         Font(name=FONT, italic=True, color="808080"))
    cols = ["Include (Y/N)", "Driver", "Section", "Person", "Amount ($)", "Basis", "Start month", "End month",
            "Annual total ($)", "Note"]
    _header(ws, FIRST_ROW - 1, cols, [9, 34, 18, 18, 14, 12, 8, 8, 15, 36])
    for i, label in enumerate(MONTH_LABELS):
        c = ws.cell(FIRST_ROW - 1, 11 + i, label)
        c.font, c.fill = HEADER, HEADER_FILL
        _put(ws, FIRST_ROW - 2, 11 + i, i + 1, Font(name=FONT, color="808080"))
        ws.column_dimensions[L(11 + i)].width = 12
    drv_last = FIRST_ROW + max(len(drivers), 1)
    for i, r in enumerate(drivers.itertuples(index=False)):
        row = FIRST_ROW + i
        inc = r.include if pd.notna(r.include) else True
        _put(ws, row, 1, "Y" if bool(inc) else "N", BLUE)
        _put(ws, row, 2, r.driver, BLUE)
        _put(ws, row, 3, r.section, BLUE)
        _put(ws, row, 4, r.person or "", BLUE)
        _put(ws, row, 5, float(r.amount or 0), BLUE, USD)
        _put(ws, row, 6, r.basis or "Per month", BLUE)
        _put(ws, row, 7, int(r.start_month or 1), BLUE, "0")
        _put(ws, row, 8, int(r.end_month or 12), BLUE, "0")
        _put(ws, row, 10, r.note or "")
    for row in range(FIRST_ROW, drv_last + 1):
        _put(ws, row, 9, f"=SUM(K{row}:V{row})", BLACK, USD)
        for i in range(12):
            col = 11 + i
            m = f"{L(col)}$3"
            end = f"MAX($H{row},$G{row})"
            f = (f'=IF($A{row}="Y",IF($F{row}="One-time",IF({m}=$G{row},$E{row},0),'
                 f'IF(AND({m}>=$G{row},{m}<={end}),IF($F{row}="Per year",$E{row}/({end}-$G{row}+1),$E{row}),0)),0)')
            _put(ws, row, col, f, BLACK, USD)
    for col, opts in ((1, "Y,N"), (3, ",".join(DRIVER_SECTIONS)), (6, ",".join(BASES))):
        dv = DataValidation(type="list", formula1=f'"{opts}"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{L(col)}{FIRST_ROW}:{L(col)}{drv_last}")
    ws.freeze_panes = "C5"
    drv_sum = lambda section, col: (  # noqa: E731
        f'SUMIFS(Drivers!{col}${FIRST_ROW}:{col}${drv_last},Drivers!$C${FIRST_ROW}:$C${drv_last},"{section}")'
    )

    # ---------------- Budget P&L ----------------
    ws = wb.create_sheet("Budget P&L")
    _put(ws, 1, 1, f"Budget P&L, calendar {a.year}", TITLE)
    ws["A3"] = ""
    labels = ["Line"] + MONTH_LABELS + ["Total", "Prior year", "Change ($)", "Change %"]
    _header(ws, 4, labels, [44] + [12] * 12 + [14, 14, 13, 10])
    _month_header(ws, 4, 2)
    ws.freeze_panes = "B5"
    row = [5]
    MC = [L(2 + i) for i in range(12)]  # month columns B..M on this sheet

    def line(label, month_formula, prior=None, font=BLACK, total=False, pct_row=False):
        r = row[0]
        _put(ws, r, 1, label, BOLD if total else BLACK)
        for i, col in enumerate(MC):
            c = _put(ws, r, 2 + i, month_formula(i, col), font, PCT if pct_row else USD)
            if total:
                c.font, c.fill, c.border = BOLD, TOTAL_FILL, TOP
        tot = _put(ws, r, 14, f"=SUM(B{r}:M{r})" if not pct_row else None, BOLD if total else BLACK, USD)
        if prior is not None:
            _put(ws, r, 15, prior, GREEN, USD)
            _put(ws, r, 16, f"=N{r}-O{r}", BLACK, USD)
            _put(ws, r, 17, f'=IF(O{r}=0,"",N{r}/O{r}-1)', BLACK, PCT)
        if total:
            for c in range(1, 18):
                ws.cell(r, c).fill = TOTAL_FILL
                ws.cell(r, c).border = TOP
            ws.cell(r, 1).font = BOLD
            tot.font = BOLD
        row[0] += 1
        return r

    def section_title(text):
        _put(ws, row[0], 1, text, BOLD)
        row[0] += 1

    def blank():
        row[0] += 1

    def sum_rows(rows_):
        return lambda i, col: "=" + ("+".join(f"{col}{x}" for x in rows_) if rows_ else "0")

    def ov_line_rows(section):
        rows_ = []
        for i, r in enumerate(overhead.itertuples(index=False)):
            if r.section != section or r.treatment != PRIOR_PLUS:
                continue
            orow = FIRST_ROW + i
            label = r.line_item if not r.category else f"{r.category}: {r.line_item}"
            rows_.append(line("  " + label, lambda _i, _c, orow=orow: f"=Overhead!$I${orow}/12",
                              prior=f"=Overhead!F{orow}"))
        return rows_

    def drv_line_rows(section):
        rows_ = []
        for i, r in enumerate(drivers.itertuples(index=False)):
            if r.section != section:
                continue
            drow = FIRST_ROW + i
            rows_.append(line("  " + str(r.driver), lambda _i, _c, drow=drow: f"=Drivers!{L(11 + _i)}{drow}",
                              font=GREEN))
        return rows_

    replaced = lambda section_crit: (  # noqa: E731
        f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"{section_crit}",{ov_rng("E")},"{PEOPLE_PLAN}")'
    )

    section_title("Revenue")
    fee = line("  Fee revenue (people plan)",
               lambda i, col: f"='Revenue by Person'!{L(3 + i)}{people_last + 1}", prior=replaced("Revenue"), font=GREEN)
    rev_rows = [fee] + ov_line_rows("Revenue") + drv_line_rows("Revenue")
    total_rev = line("Total revenue", sum_rows(rev_rows),
                     prior=f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"Revenue",{ov_rng("E")},"<>Exclude")', total=True)
    blank()

    cogs_rows = []
    if ((overhead["section"] == "COGS") & (overhead["treatment"] == PRIOR_PLUS)).any() if not overhead.empty else False:
        section_title("Cost of sales")
        cogs_rows = ov_line_rows("COGS")
        cogs_total = line("Total cost of sales", sum_rows(cogs_rows),
                          prior=f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"COGS",{ov_rng("E")},"{PRIOR_PLUS}")', total=True)
        cogs_rows = [cogs_total]
        blank()

    section_title("Personnel")
    sal = line("  Salaries (people plan)", lambda i, col: f"='Salary by Person'!{L(3 + i)}{people_last + 1}", font=GREEN)
    fr = line("  Payroll taxes & benefits (fringe)", lambda i, col: f"={col}{sal}*{A_FRINGE}")
    pers_rows = [sal, fr] + drv_line_rows("Personnel")
    payroll_prior = (f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"Expense",{ov_rng("E")},"{PEOPLE_PLAN}")'
                     f'+SUMIFS({ov_rng("F")},{ov_rng("A")},"COGS",{ov_rng("E")},"{PEOPLE_PLAN}")')
    pers_total = line("Total personnel", sum_rows(pers_rows), prior=payroll_prior, total=True)
    blank()

    section_title("Operating expenses")
    opex_rows = ov_line_rows("Expense") + drv_line_rows("Operating expense")
    opex_total = line("Total operating expenses", sum_rows(opex_rows),
                      prior=f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"Expense",{ov_rng("E")},"{PRIOR_PLUS}")', total=True)
    blank()

    section_title("Other income & expense")
    oi_rows = ov_line_rows("Other Income") + drv_line_rows("Other income")
    oe_rows = ov_line_rows("Other Expense") + drv_line_rows("Other expense")
    blank()

    exp_rows = cogs_rows + [pers_total, opex_total] + oe_rows
    exp_prior = (f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"COGS",{ov_rng("E")},"<>Exclude")'
                 f'+SUMIFS({ov_rng("F")},{ov_rng("A")},"Expense",{ov_rng("E")},"<>Exclude")'
                 f'+SUMIFS({ov_rng("F")},{ov_rng("A")},"Other Expense",{ov_rng("E")},"<>Exclude")')
    total_exp = line("Total expenses", sum_rows(exp_rows), prior=exp_prior, total=True)
    net_prior = (f'=SUMIFS({ov_rng("F")},{ov_rng("A")},"Revenue",{ov_rng("E")},"<>Exclude")'
                 f'+SUMIFS({ov_rng("F")},{ov_rng("A")},"Other Income",{ov_rng("E")},"<>Exclude")'
                 f'-SUMIFS({ov_rng("F")},{ov_rng("A")},"COGS",{ov_rng("E")},"<>Exclude")'
                 f'-SUMIFS({ov_rng("F")},{ov_rng("A")},"Expense",{ov_rng("E")},"<>Exclude")'
                 f'-SUMIFS({ov_rng("F")},{ov_rng("A")},"Other Expense",{ov_rng("E")},"<>Exclude")')
    oi = "+".join(f"{{col}}{x}" for x in oi_rows)
    net = line("Net income before owner draws",
               lambda i, col: f"={col}{total_rev}" + ("+" + oi.format(col=col) if oi_rows else "") + f"-{col}{total_exp}",
               prior=net_prior, total=True)
    line("  Net margin", lambda i, col: f'=IF({col}{total_rev}=0,0,{col}{net}/{col}{total_rev})', pct_row=True)
    r_margin = row[0] - 1
    _put(ws, r_margin, 14, f'=IF(N{total_rev}=0,0,N{net}/N{total_rev})', BLACK, PCT)
    blank()

    section_title("Owner draws")
    draw_rows = drv_line_rows("Owner draws")
    draws = line("Total owner draws", sum_rows(draw_rows), total=True)
    line("Remaining after owner draws", lambda i, col: f"={col}{net}-{col}{draws}", total=True)

    # Driver section totals as a cross-check that nothing was left off the P&L.
    blank()
    _put(ws, row[0], 1, "Check: drivers not on the P&L (should be 0)", Font(name=FONT, italic=True, color="808080"))
    known = "+".join(drv_sum(s, "I") for s in DRIVER_SECTIONS)
    _put(ws, row[0], 14, f'=SUM(Drivers!I{FIRST_ROW}:I{drv_last})-({known})', BLACK, USD)

    wb.move_sheet("Budget P&L", offset=-(len(wb.sheetnames) - 2))
    return wb


def to_bytes(a: Assumptions, people: pd.DataFrame, overhead: pd.DataFrame, drivers: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    build_workbook(a, people, overhead, drivers).save(buf)
    return buf.getvalue()
