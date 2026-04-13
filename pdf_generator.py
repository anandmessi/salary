"""
pdf_generator.py — Salary Slip matching the Kerala / Nirbhik format
=====================================================================
• Two-column table: Salary & Allowances | Deductions
• Zero-value rows are NEVER printed
• Gross Monthly Emoluments + Total Deductions share the bottom row
• Net Salary Paid spans full width
• Bank details, Prepared by / Received by, legal footer
"""

import os
import zipfile
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable,
)

from schema import PayrollResult, CompanyConfig

# ── Colours (conservative, print-friendly) ──────────────────────────────────
HDR_BG   = colors.HexColor("#1A3C6E")   # dark navy  — header banner
TH_BG    = colors.HexColor("#2C3E50")   # dark grey  — table column headers
ALT_ROW  = colors.HexColor("#EBF5FB")   # light blue — alternating rows
NET_BG   = colors.HexColor("#1E8449")   # green      — net pay banner
BORDER   = colors.HexColor("#AEB6BF")   # grey       — cell borders
WHITE    = colors.white
BLACK    = colors.black

PAGE_W   = A4[0]
PAGE_H   = A4[1]
L_MARGIN = 15 * mm
R_MARGIN = 15 * mm
CONTENT_W = PAGE_W - L_MARGIN - R_MARGIN   # ~180 mm


# ── Style helpers ────────────────────────────────────────────────────────────
def _s(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9, leading=12,
                textColor=BLACK, spaceAfter=0, spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(name, **base)


S_CO_NAME = _s("co",   fontName="Helvetica-Bold", fontSize=12,
               textColor=WHITE, alignment=TA_CENTER)
S_CO_ADDR = _s("addr", fontSize=8, textColor=colors.HexColor("#D5D8DC"),
               alignment=TA_CENTER)
S_TITLE   = _s("title",fontName="Helvetica-Bold", fontSize=10,
               textColor=WHITE, alignment=TA_CENTER)
S_LBL     = _s("lbl",  fontSize=8.5, textColor=colors.HexColor("#555555"))
S_VAL     = _s("val",  fontSize=8.5, fontName="Helvetica-Bold")
S_TH      = _s("th",   fontSize=8.5, fontName="Helvetica-Bold",
               textColor=WHITE)
S_CELL    = _s("cell", fontSize=8.5)
S_BOLD    = _s("bold", fontSize=8.5, fontName="Helvetica-Bold")
S_NET_LBL = _s("netlbl",fontName="Helvetica-Bold", fontSize=11,
               textColor=WHITE)
S_NET_VAL = _s("netval",fontName="Helvetica-Bold", fontSize=13,
               textColor=colors.HexColor("#ABEBC6"), alignment=TA_RIGHT)
S_SMALL   = _s("sm",   fontSize=7.5, textColor=colors.grey, alignment=TA_CENTER)
S_LEGAL   = _s("legal",fontSize=7, textColor=colors.HexColor("#555555"),
               leading=10)


def _fmt(amount: float) -> str:
    """Rs.17,688.00 style — Indian comma grouping."""
    s  = f"{abs(amount):,.2f}"
    # convert Western commas → Indian grouping
    p  = s.split(".")
    n  = p[0].replace(",", "")
    if len(n) <= 3:
        fmt = n
    else:
        last3 = n[-3:]
        rest  = n[:-3]
        grps  = []
        while len(rest) > 2:
            grps.insert(0, rest[-2:]); rest = rest[:-2]
        if rest: grps.insert(0, rest)
        fmt = ",".join(grps) + "," + last3
    result = f"Rs.{fmt}.{p[1]}"
    return ("-" + result) if amount < 0 else result


# ── Main slip builder ────────────────────────────────────────────────────────
def _build_flowables(r: PayrollResult, cfg: CompanyConfig) -> list:
    story = []

    # ── 1. Company header ────────────────────────────────────────────────
    hdr = Table(
        [[Paragraph(cfg.company_name, S_CO_NAME)],
         [Paragraph(f"{cfg.address_line1}, {cfg.address_line2}", S_CO_ADDR)]],
        colWidths=[CONTENT_W],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HDR_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(hdr)

    title_bar = Table(
        [[Paragraph("Salary Slip", S_TITLE)]],
        colWidths=[CONTENT_W],
    )
    title_bar.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), TH_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(title_bar)
    story.append(Spacer(1, 3 * mm))

    # ── 2. Employee info block ───────────────────────────────────────────
    def lv(lbl, val):
        return [Paragraph(lbl, S_LBL), Paragraph(": " + (str(val) if val else "—"), S_VAL)]

    col_a = CONTENT_W * 0.38
    col_b = CONTENT_W * 0.62

    info_rows = [
        lv("Establishment Name",      cfg.company_name),
        lv("Address of Establishment",f"{cfg.address_line1}, {cfg.address_line2}"),
        lv("Name of the Employee",    f"{r.worker_name} , {r.worker_id}"),
        lv("Period of Payment",       r.period_label),
        lv("Designation",             r.profile_title),
        lv("Date of Joining",         r.joining_date or "—"),
        lv("Total No. of Days Worked",f"{r.days_present} days"),
    ]

    info_t = Table(info_rows, colWidths=[col_a, col_b])
    info_t.setStyle(TableStyle([
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND",    (0, 0), (0, -1), ALT_ROW),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]))
    story.append(info_t)
    story.append(Spacer(1, 4 * mm))

    # ── 3. Salary & Deductions table ─────────────────────────────────────
    earn_items = r.earnings_items()   # non-zero only
    ded_items  = r.deduction_items()  # non-zero only

    # Pad to same length so the two columns align
    max_rows = max(len(earn_items), len(ded_items))
    while len(earn_items) < max_rows: earn_items.append(("", ""))
    while len(ded_items)  < max_rows: ded_items.append(("", ""))

    # Column widths: [earn_label | earn_amt || ded_label | ded_amt]
    CW = [CONTENT_W * 0.32, CONTENT_W * 0.18,
          CONTENT_W * 0.32, CONTENT_W * 0.18]

    # Header row
    table_rows = [[
        Paragraph("Salary & Allowances", S_TH),
        Paragraph("",                    S_TH),
        Paragraph("Deductions",          S_TH),
        Paragraph("",                    S_TH),
    ]]

    # Data rows
    for i in range(max_rows):
        el, ev = earn_items[i]
        dl, dv = ded_items[i]
        table_rows.append([
            Paragraph(el, S_CELL),
            Paragraph(_fmt(ev) if ev else "", S_CELL),
            Paragraph(dl, S_CELL),
            Paragraph(_fmt(dv) if dv else "", S_CELL),
        ])

    # Gross / Total Deductions footer row
    table_rows.append([
        Paragraph("Gross Monthly Emoluments", S_BOLD),
        Paragraph("",                          S_BOLD),
        Paragraph("Total Deductions",          S_BOLD),
        Paragraph("",                          S_BOLD),
    ])
    table_rows.append([
        Paragraph(_fmt(r.gross),            S_BOLD),
        Paragraph("",                       S_BOLD),
        Paragraph(_fmt(r.total_deductions), S_BOLD),
        Paragraph("",                       S_BOLD),
    ])

    sal_t = Table(table_rows, colWidths=CW)

    # Build alternating-row colours for data rows (index 1 … max_rows)
    style_cmds = [
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), TH_BG),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        # Full grid
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        # Amounts right-aligned
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("ALIGN",         (3, 0), (3, -1), "RIGHT"),
        # Vertical divider between earn / ded sections
        ("LINEAFTER",     (1, 0), (1, -1), 1.0, HDR_BG),
        # Gross / total footer rows
        ("BACKGROUND",    (0, -2), (-1, -1), ALT_ROW),
        ("FONTNAME",      (0, -2), (-1, -1), "Helvetica-Bold"),
        ("SPAN",          (0, -2), (1, -2)),   # merge gross label cols
        ("SPAN",          (2, -2), (3, -2)),   # merge total ded label cols
        ("SPAN",          (0, -1), (1, -1)),   # merge gross value cols
        ("SPAN",          (2, -1), (3, -1)),   # merge total ded value cols
    ]

    # Alternating rows for data section
    for i in range(1, max_rows + 1):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ALT_ROW))

    sal_t.setStyle(TableStyle(style_cmds))
    story.append(sal_t)

    # ── 4. Net Salary Paid ───────────────────────────────────────────────
    net_t = Table(
        [[Paragraph(f"Net Salary Paid  -  {_fmt(r.net_pay)}", S_NET_LBL)]],
        colWidths=[CONTENT_W],
    )
    net_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NET_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(net_t)

    # Remarks line
    month_name = ""
    try:
        import datetime as dt
        month_name = dt.datetime.strptime(r.month, "%Y-%m").strftime("%B").upper()
    except Exception:
        month_name = r.month
    remarks_t = Table(
        [[Paragraph(f"Remarks ::: SALARY FOR THE MONTH {month_name}", S_SMALL)]],
        colWidths=[CONTENT_W],
    )
    remarks_t.setStyle(TableStyle([
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(remarks_t)
    story.append(Spacer(1, 4 * mm))

    # ── 5. Bank details ──────────────────────────────────────────────────
    bank_text = (
        f"Wages and Other Allowances are Credited to your Account No"
        f" &nbsp; : &nbsp; <b>{r.bank_account or '—'}</b>"
    )
    story.append(Paragraph(bank_text,
                            _s("bt", fontSize=8.5, leading=14)))
    story.append(Spacer(1, 2 * mm))

    bank_row = Table(
        [[Paragraph(f"Bank Name &nbsp;: <b>{r.bank_name or '—'}</b>", S_CELL),
          Paragraph(f"IFSC Code &nbsp;: <b>{r.ifsc_code or '—'}</b>", S_CELL)]],
        colWidths=[CONTENT_W / 2, CONTENT_W / 2],
    )
    story.append(bank_row)
    story.append(Spacer(1, 5 * mm))

    # ── 6. Prepared / Received ───────────────────────────────────────────
    sig_t = Table(
        [[Paragraph("Prepared by", S_TH),
          Paragraph("Received by",  S_TH)]],
        colWidths=[CONTENT_W / 2, CONTENT_W / 2],
    )
    sig_t.setStyle(TableStyle([
        ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
        ("BACKGROUND",    (0, 0), (-1, -1), TH_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
    ]))
    story.append(sig_t)
    story.append(Spacer(1, 4 * mm))

    # ── 7. Legal footer ──────────────────────────────────────────────────
    story.append(Paragraph(
        "(This wages slip generated from the Wage Protection System is an "
        "alternate form under Rule 29B of the Kerala Minimum Wages Rules, "
        "1958 and is legally valid for the purpose of Rule 29(2) of the said Rules.)",
        S_LEGAL,
    ))

    return story


# ── Public API ────────────────────────────────────────────────────────────────
def generate_slip_pdf(
    result    : PayrollResult,
    config    : CompanyConfig,
    output_dir: str = "salary_slips",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    safe = result.worker_name.replace(" ", "_").replace("/", "-")
    path = os.path.join(output_dir,
                        f"SalarySlip_{safe}_{result.worker_id}_{result.month}.pdf")
    doc  = SimpleDocTemplate(
        path, pagesize=A4,
        topMargin=12*mm, bottomMargin=12*mm,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
    )
    doc.build(_build_flowables(result, config))
    return path


def generate_bulk_pdfs(
    results   : List[PayrollResult],
    config    : CompanyConfig,
    output_dir: str = "salary_slips",
    zip_output: bool = True,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    pdf_paths, errors = [], []

    for r in results:
        try:
            pdf_paths.append(generate_slip_pdf(r, config, output_dir))
        except Exception as e:
            errors.append(f"{r.worker_name}: {e}")

    zip_path = None
    if zip_output and pdf_paths:
        month    = results[0].month if results else "unknown"
        zip_path = os.path.join(output_dir, f"SalarySlips_{month}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in pdf_paths:
                zf.write(p, arcname=os.path.basename(p))

    return {
        "pdf_paths"    : pdf_paths,
        "zip_path"     : zip_path,
        "errors"       : errors,
        "success_count": len(pdf_paths),
    }
