"""
Beautiful PDF report generator for client-facing Kimai timesheets.
Uses reportlab for professional-quality output with logo, tables, and styling.
"""

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PAGE_W, PAGE_H = A4

NAVY = colors.HexColor("#1a1a2e")
ACCENT_BLUE = colors.HexColor("#4a90d9")
LIGHT_BLUE = colors.HexColor("#e8f0fe")
LIGHT_GRAY = colors.HexColor("#f5f5f5")
MID_GRAY = colors.HexColor("#cccccc")
DARK_TEXT = colors.HexColor("#2c2c2c")
WHITE = colors.white

_LOGO_PATHS = [
    os.path.join(os.path.dirname(__file__), "assets", "logo.png"),
    os.path.join(os.path.dirname(__file__), "..", "mini_app", "static", "logo.png"),
]
LOGO_PATH = next((p for p in _LOGO_PATHS if os.path.exists(p)), _LOGO_PATHS[0])


def _register_fonts():
    """Register DejaVu Sans for Cyrillic support if available, otherwise fall back to Helvetica."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("CyrFont", fp))
            for bp in bold_paths:
                if os.path.exists(bp):
                    pdfmetrics.registerFont(TTFont("CyrFontBold", bp))
                    return "CyrFont", "CyrFontBold"
            return "CyrFont", "CyrFont"
    return "Helvetica", "Helvetica-Bold"


FONT_NAME, FONT_NAME_BOLD = _register_fonts()


def _fmt_hours(h: float) -> str:
    total_min = int(round(h * 60))
    hrs, mins = divmod(total_min, 60)
    return f"{hrs}ч {mins:02d}м"


def _fmt_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except (ValueError, AttributeError):
        return str(iso_str)[:10]


def _truncate(text: str, max_len: int = 200) -> str:
    text = text.replace("\n", " ").replace("\r", "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


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
    canvas.setFont(FONT_NAME, 8)
    canvas.setFillColor(MID_GRAY)
    canvas.drawString(
        doc.leftMargin,
        15 * mm,
        f"Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    )
    canvas.drawRightString(
        PAGE_W - doc.rightMargin,
        15 * mm,
        f"Страница {doc.page}",
    )
    canvas.setStrokeColor(MID_GRAY)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 20 * mm, PAGE_W - doc.rightMargin, 20 * mm)
    canvas.restoreState()


def generate_client_report_pdf(
    customer_name: str,
    projects_map: dict[int, str],
    report_by_project: dict[int, list[dict]],
    begin_label: str,
    end_label: str,
    company_name: str = "НейроСофт",
) -> bytes:
    """Generate a professional PDF report for a client.

    Returns PDF content as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=25 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=f"Отчёт — {customer_name}",
        author=company_name,
    )

    styles = getSampleStyleSheet()

    s_company = ParagraphStyle(
        "Company", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=20, leading=24,
        alignment=TA_CENTER, textColor=NAVY, spaceAfter=2 * mm,
    )
    s_title = ParagraphStyle(
        "ReportTitle", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=16, leading=20,
        alignment=TA_CENTER, textColor=DARK_TEXT, spaceAfter=3 * mm,
    )
    s_subtitle = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontName=FONT_NAME, fontSize=12, leading=15,
        alignment=TA_CENTER, textColor=DARK_TEXT, spaceAfter=1 * mm,
    )
    s_section = ParagraphStyle(
        "Section", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=14, leading=18,
        textColor=WHITE, spaceBefore=8 * mm, spaceAfter=4 * mm,
    )
    s_activity_header = ParagraphStyle(
        "ActivityHeader", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=11, leading=14,
        textColor=ACCENT_BLUE, spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    s_cell = ParagraphStyle(
        "Cell", parent=styles["Normal"],
        fontName=FONT_NAME, fontSize=9, leading=11,
        textColor=DARK_TEXT,
    )
    s_cell_bold = ParagraphStyle(
        "CellBold", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=9, leading=11,
        textColor=DARK_TEXT,
    )
    s_total_label = ParagraphStyle(
        "TotalLabel", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=11, leading=14,
        textColor=NAVY,
    )
    s_total_value = ParagraphStyle(
        "TotalValue", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=11, leading=14,
        textColor=NAVY, alignment=TA_RIGHT,
    )

    elements: list = []

    # --- Cover / Header ---
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=30 * mm, height=30 * mm)
        logo.hAlign = "CENTER"
        elements.append(Spacer(1, 5 * mm))
        elements.append(logo)
        elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph(company_name, s_company))
    elements.append(Spacer(1, 2 * mm))

    elements.append(HRFlowable(
        width="60%", thickness=1.5, color=ACCENT_BLUE,
        spaceAfter=6 * mm, spaceBefore=2 * mm, hAlign="CENTER",
    ))

    project_names = [projects_map.get(pid, f"Проект {pid}") for pid in report_by_project]
    if len(project_names) == 1:
        title_text = f"Отчёт по проекту: {project_names[0]}"
    else:
        title_text = "Отчёт по проектам"
    elements.append(Paragraph(title_text, s_title))

    elements.append(Paragraph(f"Период: {begin_label} — {end_label}", s_subtitle))
    elements.append(Paragraph(f"Заказчик: {customer_name}", s_subtitle))
    elements.append(Spacer(1, 8 * mm))

    elements.append(HRFlowable(
        width="100%", thickness=0.5, color=MID_GRAY,
        spaceAfter=4 * mm, spaceBefore=2 * mm,
    ))

    grand_total_hours = 0.0
    avail_width = PAGE_W - doc.leftMargin - doc.rightMargin

    for pid, entries in report_by_project.items():
        proj_name = projects_map.get(pid, f"Проект {pid}")

        # Section header as a small colored table
        section_tbl = Table(
            [[Paragraph(f"  {proj_name}", s_section)]],
            colWidths=[avail_width],
            rowHeights=[10 * mm],
        )
        section_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ]))
        elements.append(section_tbl)
        elements.append(Spacer(1, 3 * mm))

        if not entries:
            elements.append(Paragraph("Нет записей за выбранный период.", s_cell))
            elements.append(Spacer(1, 4 * mm))
            continue

        # Group by activity
        by_activity: dict[str, list[dict]] = {}
        for e in entries:
            act = e["activity"]
            by_activity.setdefault(act, []).append(e)

        project_total_hours = 0.0

        for activity_name, activity_entries in sorted(by_activity.items()):
            elements.append(Paragraph(f"▸ {activity_name}", s_activity_header))

            # Table header
            col_widths = [22 * mm, 30 * mm, avail_width - 22 * mm - 30 * mm - 22 * mm, 22 * mm]
            header_row = [
                Paragraph("Дата", s_cell_bold),
                Paragraph("Сотрудник", s_cell_bold),
                Paragraph("Описание", s_cell_bold),
                Paragraph("Часы", s_cell_bold),
            ]
            data_rows = [header_row]

            activity_hours = 0.0
            for i, e in enumerate(activity_entries):
                activity_hours += e["hours"]
                data_rows.append([
                    Paragraph(_fmt_date(e["date"]), s_cell),
                    Paragraph(e["user"], s_cell),
                    Paragraph(_truncate(e["description"]), s_cell),
                    Paragraph(_fmt_hours(e["hours"]), s_cell),
                ])

            # Subtotal row
            data_rows.append([
                Paragraph("", s_cell),
                Paragraph("", s_cell),
                Paragraph(f"Итого {activity_name}:", s_cell_bold),
                Paragraph(_fmt_hours(activity_hours), s_cell_bold),
            ])

            tbl = Table(data_rows, colWidths=col_widths, repeatRows=1)

            row_styles = [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, MID_GRAY),
                ("LINEBELOW", (0, -1), (-1, -1), 1, ACCENT_BLUE),
                ("BACKGROUND", (0, -1), (-1, -1), LIGHT_BLUE),
            ]
            # Alternating row colors
            for row_idx in range(1, len(data_rows) - 1):
                if row_idx % 2 == 0:
                    row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), LIGHT_GRAY))

            tbl.setStyle(TableStyle(row_styles))
            elements.append(tbl)
            elements.append(Spacer(1, 2 * mm))
            project_total_hours += activity_hours

        # Project total
        proj_total_tbl = Table(
            [[
                Paragraph(f"Всего по проекту «{proj_name}»:", s_total_label),
                Paragraph(_fmt_hours(project_total_hours), s_total_value),
            ]],
            colWidths=[avail_width - 30 * mm, 30 * mm],
        )
        proj_total_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 4 * mm),
            ("LINEABOVE", (0, 0), (-1, 0), 1.5, ACCENT_BLUE),
        ]))
        elements.append(proj_total_tbl)
        elements.append(Spacer(1, 6 * mm))
        grand_total_hours += project_total_hours

    # --- Summary + Grand Total ---
    num_projects = len([v for v in report_by_project.values() if v])

    if num_projects > 1:
        elements.append(Spacer(1, 4 * mm))

        s_summary_title = ParagraphStyle(
            "SummaryTitle", parent=styles["Normal"],
            fontName=FONT_NAME_BOLD, fontSize=13, leading=17,
            textColor=NAVY, spaceBefore=2 * mm, spaceAfter=3 * mm,
        )
        elements.append(Paragraph("Сводка по проектам", s_summary_title))

        elements.append(HRFlowable(
            width="100%", thickness=1, color=ACCENT_BLUE,
            spaceAfter=3 * mm,
        ))

        s_sum_proj = ParagraphStyle(
            "SumProj", parent=styles["Normal"],
            fontName=FONT_NAME, fontSize=11, leading=14,
            textColor=DARK_TEXT,
        )
        s_sum_proj_bold = ParagraphStyle(
            "SumProjBold", parent=styles["Normal"],
            fontName=FONT_NAME_BOLD, fontSize=11, leading=14,
            textColor=DARK_TEXT,
        )
        s_sum_hours = ParagraphStyle(
            "SumHours", parent=styles["Normal"],
            fontName=FONT_NAME_BOLD, fontSize=11, leading=14,
            textColor=NAVY, alignment=TA_RIGHT,
        )

        summary_rows = []
        summary_rows.append([
            Paragraph("Проект", s_sum_proj_bold),
            Paragraph("Часы", s_sum_proj_bold),
        ])

        for pid, entries in report_by_project.items():
            proj_name = projects_map.get(pid, f"Проект {pid}")
            proj_hours = sum(e["hours"] for e in entries)
            if not entries:
                continue
            summary_rows.append([
                Paragraph(proj_name, s_sum_proj),
                Paragraph(_fmt_hours(proj_hours), s_sum_hours),
            ])

        summary_tbl = Table(
            summary_rows,
            colWidths=[avail_width - 35 * mm, 35 * mm],
        )

        summary_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT_BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("LEFTPADDING", (0, 0), (0, -1), 4 * mm),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 4 * mm),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, MID_GRAY),
        ]
        for row_idx in range(1, len(summary_rows)):
            if row_idx % 2 == 0:
                summary_styles.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), LIGHT_GRAY)
                )

        summary_tbl.setStyle(TableStyle(summary_styles))
        elements.append(summary_tbl)
        elements.append(Spacer(1, 2 * mm))

    elements.append(HRFlowable(
        width="100%", thickness=1.5, color=NAVY,
        spaceAfter=4 * mm, spaceBefore=4 * mm if num_projects <= 1 else 1 * mm,
    ))

    s_grand_label = ParagraphStyle(
        "GrandLabel", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=14, leading=18,
        textColor=WHITE,
    )
    s_grand_value = ParagraphStyle(
        "GrandValue", parent=styles["Normal"],
        fontName=FONT_NAME_BOLD, fontSize=14, leading=18,
        textColor=WHITE, alignment=TA_RIGHT,
    )

    grand_tbl = Table(
        [[
            Paragraph("ИТОГО ПО ВСЕМ ПРОЕКТАМ:" if num_projects > 1 else "ИТОГО:", s_grand_label),
            Paragraph(_fmt_hours(grand_total_hours), s_grand_value),
        ]],
        colWidths=[avail_width - 35 * mm, 35 * mm],
    )
    grand_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("LEFTPADDING", (0, 0), (0, 0), 5 * mm),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 5 * mm),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    elements.append(grand_tbl)

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
