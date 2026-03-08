"""
pdf_report.py
Professional PDF report generator for Interview Coach.
Uses ReportLab Platypus with structured, well-aligned sections.
"""

import os
from datetime import datetime
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─── Directory setup ──────────────────────────────────────────────────────────
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# ─── Colour palette ───────────────────────────────────────────────────────────
C_BRAND       = colors.HexColor("#1E40AF")   # deep blue
C_BRAND_LIGHT = colors.HexColor("#DBEAFE")   # blue-100
C_HEADER_BG   = colors.HexColor("#1E3A8A")   # darker blue header
C_WHITE       = colors.white
C_SLATE_900   = colors.HexColor("#0F172A")
C_SLATE_700   = colors.HexColor("#334155")
C_SLATE_500   = colors.HexColor("#64748B")
C_SLATE_100   = colors.HexColor("#F1F5F9")
C_SLATE_50    = colors.HexColor("#F8FAFC")
C_GREEN       = colors.HexColor("#16A34A")
C_GREEN_BG    = colors.HexColor("#DCFCE7")
C_ORANGE      = colors.HexColor("#EA580C")
C_ORANGE_BG   = colors.HexColor("#FFEDD5")
C_RED         = colors.HexColor("#DC2626")
C_RED_BG      = colors.HexColor("#FEE2E2")
C_BORDER      = colors.HexColor("#CBD5E1")

# ─── Score colour helper ───────────────────────────────────────────────────────
def _score_color(score: float):
    if score >= 7: return C_GREEN,  C_GREEN_BG,  "Good"
    if score >= 4: return C_ORANGE, C_ORANGE_BG, "Average"
    return C_RED, C_RED_BG, "Needs Work"

def _safe(text):
    if not text: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ─── Styles factory ───────────────────────────────────────────────────────────
def _build_styles():
    base = getSampleStyleSheet()
    s = {}

    def add(name, **kw):
        s[name] = ParagraphStyle(name=f"IC_{name}", **kw)

    add("header_title",
        fontName="Helvetica-Bold", fontSize=22,
        textColor=C_WHITE, alignment=TA_CENTER, spaceAfter=2)
    add("header_sub",
        fontName="Helvetica", fontSize=9,
        textColor=colors.HexColor("#BFDBFE"), alignment=TA_CENTER, spaceAfter=2)
    add("header_maker",
        fontName="Helvetica-Oblique", fontSize=8,
        textColor=colors.HexColor("#93C5FD"), alignment=TA_CENTER)

    add("section_title",
        fontName="Helvetica-Bold", fontSize=11,
        textColor=C_BRAND, spaceBefore=4, spaceAfter=4)
    add("label",
        fontName="Helvetica-Bold", fontSize=8,
        textColor=C_SLATE_500, spaceAfter=1)
    add("value",
        fontName="Helvetica", fontSize=9,
        textColor=C_SLATE_900, spaceAfter=0)
    add("body",
        fontName="Helvetica", fontSize=9,
        textColor=C_SLATE_700, leading=14, spaceAfter=4)
    add("small",
        fontName="Helvetica", fontSize=8,
        textColor=C_SLATE_500, leading=12)
    add("score_big",
        fontName="Helvetica-Bold", fontSize=28,
        textColor=C_SLATE_900, alignment=TA_CENTER)
    add("score_label",
        fontName="Helvetica-Bold", fontSize=10,
        textColor=C_SLATE_500, alignment=TA_CENTER, spaceAfter=2)
    add("pill",
        fontName="Helvetica-Bold", fontSize=9,
        alignment=TA_CENTER)
    add("transcript_q",
        fontName="Helvetica-Bold", fontSize=9,
        textColor=C_BRAND, spaceAfter=2)
    add("transcript_label",
        fontName="Helvetica-Bold", fontSize=8,
        textColor=C_SLATE_500, spaceBefore=4, spaceAfter=1)
    add("transcript_body",
        fontName="Helvetica", fontSize=8.5,
        textColor=C_SLATE_700, leading=13, spaceAfter=2)
    add("footer",
        fontName="Helvetica", fontSize=7,
        textColor=C_SLATE_500, alignment=TA_CENTER)
    add("bullet",
        fontName="Helvetica", fontSize=9,
        textColor=C_SLATE_700, leading=13,
        leftIndent=8, spaceAfter=1)
    add("rec_title",
        fontName="Helvetica-Bold", fontSize=10,
        textColor=C_SLATE_900, spaceAfter=2)
    add("rec_body",
        fontName="Helvetica", fontSize=9,
        textColor=C_SLATE_700, leading=14)
    return s

# ─── Header / Footer canvas ───────────────────────────────────────────────────
class _PageTemplate:
    def __init__(self, date_str: str):
        self.date_str = date_str

    def __call__(self, canvas, doc):
        W, H = A4
        canvas.saveState()

        # Header background (only page 1)
        if doc.page == 1:
            canvas.setFillColor(C_HEADER_BG)
            canvas.rect(0, H - 60*mm, W, 60*mm, fill=1, stroke=0)

        # Footer bar
        canvas.setFillColor(C_SLATE_100)
        canvas.rect(0, 0, W, 10*mm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_SLATE_500)
        footer = f"Interview Coach  ·  Confidential Report  ·  {self.date_str}  ·  Page {doc.page}"
        canvas.drawCentredString(W / 2, 3.5*mm, footer)

        canvas.restoreState()

# ─── Section heading helper ───────────────────────────────────────────────────
def _section_heading(title: str, styles: dict):
    return [
        Paragraph(title.upper(), styles["section_title"]),
        HRFlowable(width="100%", thickness=0.5, color=C_BORDER, spaceAfter=6),
    ]

# ─── Main generator ───────────────────────────────────────────────────────────
def generate_pdf_report(report_data: dict, file_path: str = None) -> str:
    if file_path:
        filepath = file_path
    else:
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = str(REPORTS_DIR / filename)

    W, H = A4
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        topMargin=65*mm,    # leave room for header block on page 1
        bottomMargin=18*mm,
        leftMargin=18*mm,
        rightMargin=18*mm,
    )

    s = _build_styles()
    now_str = datetime.now().strftime("%B %d, %Y")
    elements = []

    # ── 1. HEADER (drawn on canvas) ─── just add Paragraph over it
    elements += [
        Paragraph("Interview Coach", s["header_title"]),
        Paragraph("AI-Powered Interview Practice Platform", s["header_sub"]),
        Paragraph("Made by hrohit12", s["header_maker"]),
        Spacer(1, 6*mm),
    ]

    # ── 2. CANDIDATE INFORMATION CARD ────────────────────────────────────────
    name         = _safe(report_data.get("candidate_name", "—"))
    qualification = _safe(report_data.get("qualification", "—"))
    topic        = _safe(report_data.get("topic", "—"))
    difficulty   = _safe(report_data.get("difficulty", "—").capitalize())
    total_q      = report_data.get("total_questions", 0)
    duration     = _safe(report_data.get("duration", "N/A"))

    info_data = [
        [
            Paragraph("<b>Candidate Name</b>", s["label"]),
            Paragraph("", s["label"]),
            Paragraph("<b>Interview Date</b>", s["label"]),
        ],
        [
            Paragraph(name, s["value"]),
            Paragraph("", s["value"]),
            Paragraph(now_str, s["value"]),
        ],
        [
            Paragraph("<b>Qualification</b>", s["label"]),
            Paragraph("", s["label"]),
            Paragraph("<b>Topic</b>", s["label"]),
        ],
        [
            Paragraph(qualification, s["value"]),
            Paragraph("", s["value"]),
            Paragraph(topic, s["value"]),
        ],
        [
            Paragraph("<b>Duration</b>", s["label"]),
            Paragraph("", s["label"]),
            Paragraph("<b>Difficulty · Total Questions</b>", s["label"]),
        ],
        [
            Paragraph(duration, s["value"]),
            Paragraph("", s["value"]),
            Paragraph(f"{difficulty}  ·  {total_q}", s["value"]),
        ],
    ]
    col_w = [75*mm, 15*mm, 75*mm]
    info_table = Table(info_data, colWidths=col_w)
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_SLATE_50),
        ("BOX",        (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_SLATE_50, C_WHITE]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBEFORE", (2, 0), (2, -1), 0.5, C_BORDER),
    ]))
    elements.append(KeepTogether([
        *_section_heading("Candidate Information", s),
        info_table,
        Spacer(1, 6*mm),
    ]))

    # ── 3. OVERALL SCORE ──────────────────────────────────────────────────────
    overall = float(report_data.get("overall_score", 0))
    fg, bg, status_label = _score_color(overall)

    score_data = [[
        Paragraph(f"{overall:.1f}", s["score_big"]),
        Paragraph("/ 10", s["score_label"]),
        Paragraph(status_label, ParagraphStyle(
            name="IC_pill_dyn", fontName="Helvetica-Bold",
            fontSize=10, textColor=fg, alignment=TA_CENTER
        )),
    ]]
    score_table = Table(score_data, colWidths=[35*mm, 22*mm, 45*mm])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [6]),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("BOX",           (0, 0), (-1, -1), 1.5, fg),
    ]))

    # Center the score table
    outer = Table([[score_table]], colWidths=[doc.width])
    outer.setStyle(TableStyle([
        ("ALIGN",   (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",  (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(KeepTogether([
        *_section_heading("Overall Score", s),
        outer,
        Spacer(1, 8*mm),
    ]))

    # ── 4. PERFORMANCE SCORES TABLE ───────────────────────────────────────────
    tech   = float(report_data.get("technical_score", 0))
    comm   = float(report_data.get("communication_score", 0))
    conf   = float(report_data.get("confidence_score", 0))

    def score_row(label, val):
        fg2, bg2, lab2 = _score_color(val)
        return [
            Paragraph(label, s["body"]),
            Paragraph(f"<b>{val:.1f} / 10</b>", ParagraphStyle(
                name=f"IC_sv_{label[:4]}", fontName="Helvetica-Bold",
                fontSize=10, textColor=fg2, alignment=TA_CENTER)),
            Paragraph(lab2, ParagraphStyle(
                name=f"IC_sl_{label[:4]}", fontName="Helvetica-Bold",
                fontSize=9, textColor=fg2, alignment=TA_CENTER)),
        ]

    metrics_header = [
        Paragraph("<b>Metric</b>", s["label"]),
        Paragraph("<b>Score</b>", s["label"]),
        Paragraph("<b>Status</b>", s["label"]),
    ]
    metrics_data = [
        metrics_header,
        score_row("Technical Accuracy",    tech),
        score_row("Communication Clarity", comm),
        score_row("Confidence Level",      conf),
    ]
    col_w2 = [100*mm, 35*mm, 30*mm]
    metrics_table = Table(metrics_data, colWidths=col_w2)
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_SLATE_100),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_SLATE_700),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_SLATE_50]),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (1, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(KeepTogether([
        *_section_heading("Performance Scores", s),
        metrics_table,
        Spacer(1, 8*mm),
    ]))

    # ── 5. OVERALL ASSESSMENT ─────────────────────────────────────────────────
    summary = _safe(report_data.get("overall_summary", ""))
    if summary:
        assess_block = [
            *_section_heading("Overall Assessment", s),
            Paragraph(summary, s["body"]),
            Spacer(1, 6*mm),
        ]
        elements.append(KeepTogether(assess_block))

    # ── 6. STRENGTHS & IMPROVEMENTS (two column) ──────────────────────────────
    strengths    = report_data.get("strengths", [])
    improvements = report_data.get("improvements", [])

    def _bullets(items, icon, color):
        if not items:
            return [Paragraph(f"<font color='#{int(color.red*255):02X}{int(color.green*255):02X}{int(color.blue*255):02X}'>—</font>", s["bullet"])]
        return [
            Paragraph(f"<font color='#{int(color.red*255):02X}{int(color.green*255):02X}{int(color.blue*255):02X}'>{icon}</font> {_safe(item)}", s["bullet"])
            for item in items
        ]

    str_bullets = _bullets(strengths,    "✓", C_GREEN)
    imp_bullets = _bullets(improvements, "!", C_ORANGE)

    s_col = [Paragraph("<b>✓ Strengths</b>", ParagraphStyle(
        name="IC_sh", fontName="Helvetica-Bold", fontSize=9,
        textColor=C_GREEN, spaceAfter=4))] + str_bullets
    i_col = [Paragraph("<b>⚠ Areas to Improve</b>", ParagraphStyle(
        name="IC_ih", fontName="Helvetica-Bold", fontSize=9,
        textColor=C_ORANGE, spaceAfter=4))] + imp_bullets

    max_rows = max(len(s_col), len(i_col))
    while len(s_col) < max_rows: s_col.append(Spacer(1, 0))
    while len(i_col) < max_rows: i_col.append(Spacer(1, 0))

    si_data = [[s_item, i_item] for s_item, i_item in zip(s_col, i_col)]
    si_table = Table(si_data, colWidths=[82*mm, 83*mm])
    si_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_SLATE_50),
        ("BOX",        (0, 0), (0, -1),  0.5, C_BORDER),
        ("BOX",        (1, 0), (1, -1),  0.5, C_BORDER),
        ("LINEBETWEEN",(0, 0), (1, -1),  0.5, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(KeepTogether([
        *_section_heading("Strengths & Improvement Areas", s),
        si_table,
        Spacer(1, 6*mm),
    ]))

    # ── 7. PREPARATION STATUS / RECOMMENDATION ────────────────────────────────
    rec        = _safe(report_data.get("recommendation", "consider")).lower()
    rec_note   = _safe(report_data.get("recommendation_note", ""))

    rec_map = {
        "hire":       ("Ready to Hire",         C_GREEN,  C_GREEN_BG),
        "consider":   ("Worth Considering",     C_BRAND,  C_BRAND_LIGHT),
        "needs work": ("Needs Further Preparation", C_ORANGE, C_ORANGE_BG),
    }
    rec_label, rec_fg, rec_bg = rec_map.get(rec, rec_map["consider"])

    rec_data = [[
        Paragraph(f"<b>{rec_label}</b>", ParagraphStyle(
            name="IC_rl", fontName="Helvetica-Bold", fontSize=11,
            textColor=rec_fg, spaceAfter=4)),
    ],
    [
        Paragraph(rec_note, ParagraphStyle(
            name="IC_rn", fontName="Helvetica", fontSize=9,
            textColor=C_SLATE_700, leading=14)) if rec_note else Spacer(1, 0),
    ]]
    rec_table = Table(rec_data, colWidths=[doc.width])
    rec_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), rec_bg),
        ("BOX",           (0, 0), (-1, -1), 1.0, rec_fg),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(KeepTogether([
        *_section_heading("Preparation Status", s),
        rec_table,
        Spacer(1, 8*mm),
    ]))

    # ── 8. INTERVIEW TRANSCRIPT ───────────────────────────────────────────────
    history = report_data.get("conversation_history", [])
    if history:
        elements += _section_heading("Interview Transcript", s)
        for idx, item in enumerate(history, 1):
            q_text  = _safe(item.get("question", ""))
            a_text  = _safe(item.get("answer",   ""))
            fb_text = _safe(item.get("feedback", ""))

            q_label_style = ParagraphStyle(
                name=f"IC_qlabel_{idx}", fontName="Helvetica-Bold",
                fontSize=9, textColor=C_WHITE, spaceAfter=2)
            a_label_style = ParagraphStyle(
                name=f"IC_alabel_{idx}", fontName="Helvetica-Bold",
                fontSize=8, textColor=C_SLATE_500, spaceBefore=4, spaceAfter=1)
            f_label_style = ParagraphStyle(
                name=f"IC_flabel_{idx}", fontName="Helvetica-Bold",
                fontSize=8, textColor=C_SLATE_500, spaceBefore=4, spaceAfter=1)
            body_style = ParagraphStyle(
                name=f"IC_tbody_{idx}", fontName="Helvetica",
                fontSize=8.5, textColor=C_SLATE_700, leading=13, spaceAfter=2)

            inner_content = []
            # Question header strip
            q_header_data = [[Paragraph(f"Q{idx}  Interviewer Question", q_label_style)]]
            q_header = Table(q_header_data, colWidths=[doc.width - 1*mm])
            q_header.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_BRAND),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            inner_content.append(q_header)

            body_rows = []
            if q_text:
                body_rows.append([Paragraph(q_text, body_style)])
            if a_text:
                body_rows.append([Paragraph("Candidate Response", a_label_style)])
                body_rows.append([Paragraph(a_text, body_style)])
            if fb_text:
                body_rows.append([Paragraph("AI Feedback", f_label_style)])
                body_rows.append([Paragraph(fb_text, body_style)])

            if body_rows:
                body_table = Table(body_rows, colWidths=[doc.width - 1*mm])
                body_table.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                    ("TOPPADDING",    (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                inner_content.append(body_table)

            # Wrap in outer bordered table
            card_data = [[item] for item in inner_content]
            card = Table([[row[0]] for row in card_data], colWidths=[doc.width])
            card.setStyle(TableStyle([
                ("BOX",   (0, 0), (-1, -1), 0.5, C_BORDER),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))

            elements.append(KeepTogether([card, Spacer(1, 5*mm)]))

    # ─── Build ────────────────────────────────────────────────────────────────
    page_cb = _PageTemplate(now_str)
    doc.build(elements, onFirstPage=page_cb, onLaterPages=page_cb)
    return filepath
