"""
Compact PDF report generator for internal Kimai team timesheets.
Portrait A4: employee summary grouped by leader + per-project breakdown.
"""

import io
import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PAGE_W, PAGE_H = A4

NAVY = colors.HexColor("#1a1a2e")
ACCENT = colors.HexColor("#4a90d9")
LIGHT_BLUE = colors.HexColor("#e8f0fe")
LIGHT_GRAY = colors.HexColor("#f5f5f5")
MID_GRAY = colors.HexColor("#cccccc")
DARK = colors.HexColor("#2c2c2c")
GREEN_BG = colors.HexColor("#e2efda")
YELLOW_BG = colors.HexColor("#fff2cc")
LEADER_BG = colors.HexColor("#dce6f1")
WHITE = colors.white

_LOGO_PATHS = [
    os.path.join(os.path.dirname(__file__), "assets", "logo.png"),
    os.path.join(os.path.dirname(__file__), "..", "mini_app", "static", "logo.png"),
]
LOGO_PATH = next((p for p in _LOGO_PATHS if os.path.exists(p)), _LOGO_PATHS[0])

_RE_PCT = re.compile(r"^(\d+(?:\.\d+)?)\s*%$")
_RE_HOURLY = re.compile(r"^(\d+(?:\.\d+)?)\s*\$")
_RE_HOURLY_RUB = re.compile(r"(\d+(?:\.\d+)?)\s*РУБ", re.IGNORECASE)


def _register_fonts():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("CyrFont", fp))
            for bp in bold_paths:
                if os.path.exists(bp):
                    pdfmetrics.registerFont(TTFont("CyrFontBold", bp))
                    return "CyrFont", "CyrFontBold"
            return "CyrFont", "CyrFont"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_B = _register_fonts()


def _is_rub(account_number: str) -> bool:
    """Return True if the employee's rates are denominated in rubles.
    Matches 'РУБ', 'руб', '1500 РУБ', 'рублей' etc.
    """
    if not account_number:
        return False
    return bool(re.search(r"РУБ", account_number, re.IGNORECASE))


def _money(val: float, is_rub: bool = False) -> str:
    if val == 0:
        return "—"
    if is_rub:
        return f"₽{val:,.0f}"
    return f"${val:,.2f}"


def _hours(h: float) -> str:
    if h == 0:
        return "—"
    total_min = int(round(h * 60))
    hrs, mins = divmod(total_min, 60)
    return f"{hrs}ч {mins:02d}м"


def _parse_bonus_rate(account_number: str) -> tuple:
    """Parse accountNumber field into bonus type.

    Returns ("pct", fraction), ("hourly", dollars), ("hourly_rub", rubles) or (None, 0).
    """
    if not account_number:
        return (None, 0)
    s = account_number.strip()
    m = _RE_PCT.match(s)
    if m:
        return ("pct", float(m.group(1)) / 100.0)
    m = _RE_HOURLY.match(s)
    if m:
        return ("hourly", float(m.group(1)))
    m = _RE_HOURLY_RUB.search(s)
    if m:
        return ("hourly_rub", float(m.group(1)))
    return (None, 0)


def _calc_employee_bonus(member: dict) -> float:
    """Calculate what bonus this employee generates for their team lead."""
    btype, bval = _parse_bonus_rate(member.get("account_number", ""))
    if btype == "pct":
        return member["total_money"] * bval
    elif btype in ("hourly", "hourly_rub"):
        return member["total_hours"] * bval
    return 0.0


def _draw_watermark(canvas):
    """Draw a subtle centred logo watermark on the page."""
    if not os.path.exists(LOGO_PATH):
        return
    wm_size = 80 * mm
    cx = (PAGE_W - wm_size) / 2
    cy = (PAGE_H - wm_size) / 2
    canvas.saveState()
    canvas.setFillAlpha(0.04)
    canvas.drawImage(LOGO_PATH, cx, cy, width=wm_size, height=wm_size,
                     mask="auto", preserveAspectRatio=True, anchor="c")
    canvas.restoreState()


def _footer(canvas, doc):
    _draw_watermark(canvas)
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MID_GRAY)
    canvas.drawString(doc.leftMargin, 10 * mm,
                      f"Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    canvas.drawRightString(PAGE_W - doc.rightMargin, 10 * mm, f"стр. {doc.page}")
    canvas.setStrokeColor(MID_GRAY)
    canvas.setLineWidth(0.4)
    canvas.line(doc.leftMargin, 13 * mm, PAGE_W - doc.rightMargin, 13 * mm)
    canvas.restoreState()


def generate_team_report_excel(
    teams: list[dict],
    projects_map: dict[int, str],
    report_by_team: dict[int, list[dict]],
    begin_label: str,
    end_label: str,
    company_name: str = "РусНейроСофт",
) -> bytes:
    """Generate a compact portrait-A4 PDF team report. Returns PDF bytes."""

    # ── Deduplicate members across teams, build team structures ──
    seen_uids: set[int] = set()
    team_groups: list[dict] = []

    for team in teams:
        tid = team["id"]
        tname = team.get("name", f"Команда {tid}")
        members_raw = report_by_team.get(tid, [])

        leader = None
        members = []
        for m in members_raw:
            uid = m["user_id"]
            if uid in seen_uids:
                continue
            seen_uids.add(uid)
            m["_team"] = tname
            if m["is_teamlead"]:
                leader = m
            else:
                members.append(m)

        if leader is None:
            for m in members:
                m["_bonus"] = 0.0
                m["_total"] = m["total_money"]
            if members:
                team_groups.append({"leader": None, "team_name": tname, "members": members})
            continue

        total_bonus = 0.0
        for m in members:
            emp_bonus = _calc_employee_bonus(m)
            total_bonus += emp_bonus
            # Employee's own bonus = activity "Бонусы" entries
            m["_bonus"] = m.get("bonus_from_activity", 0.0)
            m["_total"] = m["total_money"] + m["_bonus"]

        # Team lead gets: formula bonuses from members + own activity bonuses
        leader["_bonus"] = total_bonus + leader.get("bonus_from_activity", 0.0)
        leader["_total"] = leader["total_money"] + leader["_bonus"]

        members.sort(key=lambda x: x["_total"], reverse=True)
        team_groups.append({"leader": leader, "team_name": tname, "members": members})

    team_groups.sort(key=lambda g: g["leader"]["_total"] if g["leader"] else 0, reverse=True)

    all_members: list[dict] = []
    for g in team_groups:
        if g["leader"]:
            all_members.append(g["leader"])
        all_members.extend(g["members"])

    all_pids: set[int] = set()
    for m in all_members:
        all_pids.update(m["project_money"].keys())
    project_ids = sorted(all_pids, key=lambda pid: sum(
        mm["project_money"].get(pid, 0) for mm in all_members
    ), reverse=True)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=12 * mm, bottomMargin=16 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm,
        title=f"Отчёт по сотрудникам {begin_label} — {end_label}",
        author=company_name,
    )
    W = PAGE_W - doc.leftMargin - doc.rightMargin

    # ── Styles ──
    s_company = ParagraphStyle("Co", fontName=FONT_B, fontSize=16, leading=19,
                               alignment=TA_CENTER, textColor=NAVY)
    s_title = ParagraphStyle("Ti", fontName=FONT_B, fontSize=12, leading=15,
                             alignment=TA_CENTER, textColor=DARK)
    s_period = ParagraphStyle("Pe", fontName=FONT, fontSize=9, leading=12,
                              alignment=TA_CENTER, textColor=DARK)
    s_sec = ParagraphStyle("Sec", fontName=FONT_B, fontSize=10, leading=13, textColor=WHITE)
    s_h = ParagraphStyle("H", fontName=FONT_B, fontSize=8, leading=10,
                         textColor=WHITE, alignment=TA_CENTER)
    s_h_left = ParagraphStyle("HL", fontName=FONT_B, fontSize=8, leading=10, textColor=WHITE)
    s_c = ParagraphStyle("C", fontName=FONT, fontSize=8, leading=10, textColor=DARK)
    s_cc = ParagraphStyle("CC", fontName=FONT, fontSize=8, leading=10,
                          textColor=DARK, alignment=TA_CENTER)
    s_cr = ParagraphStyle("CR", fontName=FONT, fontSize=8, leading=10,
                          textColor=DARK, alignment=TA_RIGHT)
    s_b = ParagraphStyle("B", fontName=FONT_B, fontSize=8, leading=10, textColor=DARK)
    s_bc = ParagraphStyle("BC", fontName=FONT_B, fontSize=8, leading=10,
                          textColor=DARK, alignment=TA_CENTER)
    s_br = ParagraphStyle("BR", fontName=FONT_B, fontSize=8, leading=10,
                          textColor=DARK, alignment=TA_RIGHT)
    s_grand = ParagraphStyle("G", fontName=FONT_B, fontSize=9, leading=12, textColor=WHITE)

    elements: list = []

    # ── Header ──
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=16 * mm, height=16 * mm)
        logo.hAlign = "CENTER"
        elements.append(logo)
        elements.append(Spacer(1, 1.5 * mm))

    elements.append(Paragraph(company_name, s_company))
    elements.append(Spacer(1, 1 * mm))
    elements.append(Paragraph("Отчёт по сотрудникам", s_title))
    elements.append(Paragraph(f"{begin_label} — {end_label}", s_period))
    elements.append(HRFlowable(width="50%", thickness=0.8, color=ACCENT,
                               spaceAfter=4 * mm, spaceBefore=2 * mm, hAlign="CENTER"))

    if not all_members:
        elements.append(Paragraph("Нет данных за выбранный период.", s_c))
        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        return buf.getvalue()

    # ── Section 1: Employee summary grouped by leader ──
    _section_bar(elements, "Сводка по сотрудникам", W, s_sec)
    elements.append(Spacer(1, 1.5 * mm))

    cw1 = [W * 0.04, W * 0.28, W * 0.18, W * 0.14, W * 0.12, W * 0.12, W * 0.12]
    header = [
        Paragraph("#", s_h), Paragraph("Сотрудник", s_h_left),
        Paragraph("Команда", s_h), Paragraph("Часы", s_h),
        Paragraph("Сумма", s_h), Paragraph("Бонус", s_h),
        Paragraph("Итого", s_h),
    ]
    rows = [header]

    sum_hrs = 0.0
    sum_money_usd = sum_bonus_usd = sum_total_usd = 0.0
    sum_money_rub = sum_bonus_rub = sum_total_rub = 0.0
    idx = 0
    leader_row_indices: list[int] = []
    group_first_rows: list[int] = []

    for gi, g in enumerate(team_groups):
        group_first_rows.append(len(rows))
        tname = g["team_name"]

        if g["leader"]:
            m = g["leader"]
            idx += 1
            rub = _is_rub(m.get("account_number", ""))
            leader_row_indices.append(len(rows))
            rows.append([
                Paragraph(str(idx), s_bc),
                Paragraph(m["name"], s_b),
                Paragraph(tname, s_bc),
                Paragraph(_hours(m["total_hours"]), s_bc),
                Paragraph(_money(m["total_money"], rub), s_br),
                Paragraph(_money(m["_bonus"], rub), s_br),
                Paragraph(_money(m["_total"], rub), s_br),
            ])
            sum_hrs += m["total_hours"]
            if rub:
                sum_money_rub += m["total_money"]
                sum_bonus_rub += m["_bonus"]
                sum_total_rub += m["_total"]
            else:
                sum_money_usd += m["total_money"]
                sum_bonus_usd += m["_bonus"]
                sum_total_usd += m["_total"]

        for m in g["members"]:
            idx += 1
            rub = _is_rub(m.get("account_number", ""))
            rows.append([
                Paragraph(str(idx), s_cc),
                Paragraph(m["name"], s_c),
                Paragraph(tname, s_cc),
                Paragraph(_hours(m["total_hours"]), s_cc),
                Paragraph(_money(m["total_money"], rub), s_cr),
                Paragraph(_money(m["_bonus"], rub), s_cr),
                Paragraph(_money(m["_total"], rub), s_cr),
            ])
            sum_hrs += m["total_hours"]
            if rub:
                sum_money_rub += m["total_money"]
                sum_bonus_rub += m["_bonus"]
                sum_total_rub += m["_total"]
            else:
                sum_money_usd += m["total_money"]
                sum_bonus_usd += m["_bonus"]
                sum_total_usd += m["_total"]

    # Totals row(s) — split by currency if both present
    has_usd = sum_total_usd > 0 or sum_money_usd > 0
    has_rub = sum_total_rub > 0 or sum_money_rub > 0
    if has_usd:
        rows.append([
            Paragraph("", s_b), Paragraph("ИТОГО $", s_b),
            Paragraph("", s_b),
            Paragraph(_hours(sum_hrs) if not has_rub else "", s_bc),
            Paragraph(_money(sum_money_usd, False), s_br),
            Paragraph(_money(sum_bonus_usd, False), s_br),
            Paragraph(_money(sum_total_usd, False), s_br),
        ])
    if has_rub:
        rows.append([
            Paragraph("", s_b), Paragraph("ИТОГО ₽", s_b),
            Paragraph("", s_b),
            Paragraph(_hours(sum_hrs) if not has_usd else "", s_bc),
            Paragraph(_money(sum_money_rub, True), s_br),
            Paragraph(_money(sum_bonus_rub, True), s_br),
            Paragraph(_money(sum_total_rub, True), s_br),
        ])
    if not has_usd and not has_rub:
        rows.append([
            Paragraph("", s_b), Paragraph("ИТОГО", s_b),
            Paragraph("", s_b),
            Paragraph(_hours(sum_hrs), s_bc),
            Paragraph("—", s_br), Paragraph("—", s_br), Paragraph("—", s_br),
        ])

    n_totals = (1 if has_usd else 0) + (1 if has_rub else 0) or 1
    first_total_row = len(rows) - n_totals

    tbl = Table(rows, colWidths=cw1, repeatRows=1)
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("LINEBELOW", (0, 0), (-1, first_total_row - 1), 0.25, MID_GRAY),
        # Highlight totals rows
        ("BACKGROUND", (0, first_total_row), (-1, -1), YELLOW_BG),
        ("LINEABOVE", (0, first_total_row), (-1, first_total_row), 1, NAVY),
        # Blue highlight for "Итого" column (data rows only)
        ("BACKGROUND", (-1, 1), (-1, first_total_row - 1), LIGHT_BLUE),
    ]
    for ri in leader_row_indices:
        st.append(("BACKGROUND", (0, ri), (-2, ri), LEADER_BG))
    for ri in group_first_rows:
        if ri > 1:
            st.append(("LINEABOVE", (0, ri), (-1, ri), 0.8, ACCENT))
    tbl.setStyle(TableStyle(st))
    elements.append(tbl)
    elements.append(Spacer(1, 6 * mm))

    # ── Section 2: Per-project breakdown ──
    _section_bar(elements, "Разбивка по проектам", W, s_sec)
    elements.append(Spacer(1, 2 * mm))

    cw2 = [W * 0.40, W * 0.20, W * 0.20, W * 0.20]

    for pid in project_ids:
        pname = projects_map.get(pid, f"Проект {pid}")

        contributors = [
            m for m in all_members
            if m["project_hours"].get(pid, 0) > 0 or m["project_money"].get(pid, 0) > 0
        ]
        if not contributors:
            continue

        proj_label = Table(
            [[Paragraph(f"  {pname}", ParagraphStyle(
                "PL", fontName=FONT_B, fontSize=9, leading=11, textColor=NAVY))]],
            colWidths=[W], rowHeights=[7 * mm],
        )
        proj_label.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        elements.append(proj_label)

        p_header = [
            Paragraph("Сотрудник", s_h_left), Paragraph("Команда", s_h),
            Paragraph("Часы", s_h), Paragraph("Сумма", s_h),
        ]
        p_rows = [p_header]
        p_hrs = p_money = 0.0

        for m in contributors:
            hrs = m["project_hours"].get(pid, 0)
            money = m["project_money"].get(pid, 0)
            p_hrs += hrs
            p_money += money
            p_rows.append([
                Paragraph(m["name"], s_b if m["is_teamlead"] else s_c),
                Paragraph(m.get("_team", ""), s_cc),
                Paragraph(_hours(hrs), s_cc),
                Paragraph(_money(money), s_cr),
            ])

        p_rows.append([
            Paragraph("Итого", s_b), Paragraph("", s_b),
            Paragraph(_hours(p_hrs), s_bc),
            Paragraph(_money(p_money), s_br),
        ])

        p_tbl = Table(p_rows, colWidths=cw2, repeatRows=1)
        p_st = [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("LINEBELOW", (0, 0), (-1, -2), 0.2, MID_GRAY),
            ("BACKGROUND", (0, -1), (-1, -1), GREEN_BG),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY),
        ]
        for ri in range(1, len(p_rows) - 1):
            if ri % 2 == 0:
                p_st.append(("BACKGROUND", (0, ri), (-1, ri), LIGHT_GRAY))
        p_tbl.setStyle(TableStyle(p_st))
        elements.append(p_tbl)
        elements.append(Spacer(1, 4 * mm))

    # ── Grand total bar ──
    elements.append(Spacer(1, 2 * mm))
    budget_parts = []
    if has_usd:
        budget_parts.append(_money(sum_total_usd, False))
    if has_rub:
        budget_parts.append(_money(sum_total_rub, True))
    budget_str = "  +  ".join(budget_parts) if budget_parts else "—"
    grand_text = (
        f"  Бюджет: {budget_str}     |     "
        f"Часов: {_hours(sum_hrs)}     |     "
        f"Сотрудников: {len(all_members)}"
    )
    grand_bar = Table(
        [[Paragraph(grand_text, s_grand)]],
        colWidths=[W], rowHeights=[10 * mm],
    )
    grand_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    elements.append(grand_bar)

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _section_bar(elements: list, title: str, width: float, style: ParagraphStyle):
    bar = Table(
        [[Paragraph(f"  {title}", style)]],
        colWidths=[width], rowHeights=[8 * mm],
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    elements.append(bar)
