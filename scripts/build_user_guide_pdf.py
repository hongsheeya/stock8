#!/usr/bin/env python3
import html
import re
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, Preformatted, Spacer, Table, TableStyle
from reportlab.platypus import SimpleDocTemplate

try:
    from svglib.svglib import svg2rlg
except Exception:
    svg2rlg = None


ROOT = Path(__file__).resolve().parents[1]
GUIDE_MD = ROOT / "docs" / "user-guide" / "README.md"
PDF_NAME = "InfinityStock_User_Guide.pdf"
DOCS_PDF = ROOT / "docs" / "user-guide" / PDF_NAME
ASSET_PDF = ROOT / "src" / "assets" / PDF_NAME

FONT_REGULAR = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"


def register_fonts():
    pdfmetrics.registerFont(TTFont("NanumGothic", FONT_REGULAR))
    pdfmetrics.registerFont(TTFont("NanumGothicBold", FONT_BOLD))


def styles():
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="NanumGothicBold",
            fontSize=26,
            leading=34,
            textColor=colors.HexColor("#162033"),
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["BodyText"],
            fontName="NanumGothic",
            fontSize=11,
            leading=18,
            textColor=colors.HexColor("#475569"),
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="NanumGothicBold",
            fontSize=20,
            leading=27,
            textColor=colors.HexColor("#111827"),
            spaceBefore=12,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="NanumGothicBold",
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#1d4ed8"),
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Heading3"],
            fontName="NanumGothicBold",
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#334155"),
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="NanumGothic",
            fontSize=9.4,
            leading=15,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=5,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["BodyText"],
            fontName="NanumGothic",
            fontSize=9,
            leading=15,
            textColor=colors.HexColor("#475569"),
            backColor=colors.HexColor("#eef6ff"),
            borderColor=colors.HexColor("#bfdbfe"),
            borderWidth=0.6,
            borderPadding=7,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName="NanumGothic",
            fontSize=8.2,
            leading=12,
            textColor=colors.HexColor("#111827"),
            backColor=colors.HexColor("#f1f5f9"),
            borderColor=colors.HexColor("#d8e0ec"),
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=5,
            spaceAfter=7,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["BodyText"],
            fontName="NanumGothic",
            fontSize=8.4,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
    }


def inline(text):
    text = html.escape(str(text or ""))
    text = re.sub(r"`([^`]+)`", r'<font name="NanumGothicBold">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r'<font name="NanumGothicBold">\1</font>', text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    return text


def is_table_start(lines, index):
    if index + 1 >= len(lines):
        return False
    return lines[index].strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[index + 1]) is not None


def split_table_row(line):
    text = line.strip().strip("|")
    return [cell.strip() for cell in text.split("|")]


def add_table(story, rows, style_map, doc_width):
    if not rows:
        return
    col_count = max(len(row) for row in rows)
    normalized = []
    for row in rows:
        cells = row + [""] * (col_count - len(row))
        normalized.append([Paragraph(inline(cell), style_map["body"]) for cell in cells])
    table = Table(normalized, colWidths=[doc_width / col_count] * col_count, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "NanumGothic"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 7))


def add_svg(story, image_path, alt, doc_width):
    if svg2rlg is None or image_path.exists() is False:
        story.append(Paragraph(inline(f"[이미지] {alt}"), styles()["caption"]))
        return
    drawing = svg2rlg(str(image_path))
    if not drawing:
        story.append(Paragraph(inline(f"[이미지] {alt}"), styles()["caption"]))
        return
    max_height = 145 * mm
    scale = min(doc_width / float(drawing.width or doc_width), max_height / float(drawing.height or max_height), 1.0)
    drawing.width = float(drawing.width) * scale
    drawing.height = float(drawing.height) * scale
    drawing.scale(scale, scale)
    story.append(drawing)
    story.append(Paragraph(inline(alt), styles()["caption"]))


def flush_paragraph(story, paragraph_lines, style_map):
    if not paragraph_lines:
        return
    text = " ".join(line.strip() for line in paragraph_lines).strip()
    if text:
        story.append(Paragraph(inline(text), style_map["body"]))
    paragraph_lines.clear()


def markdown_story(markdown, style_map, doc_width):
    story = []
    lines = markdown.splitlines()
    i = 0
    paragraph_lines = []
    in_code = False
    code_lines = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), style_map["code"]))
                code_lines = []
                in_code = False
            else:
                flush_paragraph(story, paragraph_lines, style_map)
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line.rstrip())
            i += 1
            continue

        if stripped == "":
            flush_paragraph(story, paragraph_lines, style_map)
            i += 1
            continue

        image_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph(story, paragraph_lines, style_map)
            alt = image_match.group(1)
            rel = image_match.group(2).replace("./", "")
            add_svg(story, GUIDE_MD.parent / rel, alt, doc_width)
            i += 1
            continue

        if is_table_start(lines, i):
            flush_paragraph(story, paragraph_lines, style_map)
            table_rows = [split_table_row(lines[i])]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_rows.append(split_table_row(lines[i]))
                i += 1
            add_table(story, table_rows, style_map, doc_width)
            continue

        if stripped.startswith("# "):
            flush_paragraph(story, paragraph_lines, style_map)
            story.append(Paragraph(inline(stripped[2:]), style_map["h1"]))
        elif stripped.startswith("## "):
            flush_paragraph(story, paragraph_lines, style_map)
            story.append(Paragraph(inline(stripped[3:]), style_map["h2"]))
        elif stripped.startswith("### "):
            flush_paragraph(story, paragraph_lines, style_map)
            story.append(Paragraph(inline(stripped[4:]), style_map["h3"]))
        elif stripped.startswith(">"):
            flush_paragraph(story, paragraph_lines, style_map)
            story.append(Paragraph(inline(stripped.lstrip("> ").strip()), style_map["note"]))
        elif re.match(r"^[-*]\s+", stripped):
            flush_paragraph(story, paragraph_lines, style_map)
            item = re.sub(r"^[-*]\s+", "", stripped)
            item = item.replace("[ ] ", "□ ").replace("[x] ", "■ ").replace("[X] ", "■ ")
            story.append(Paragraph("• " + inline(item), style_map["body"]))
        elif re.match(r"^\d+\.\s+", stripped):
            flush_paragraph(story, paragraph_lines, style_map)
            story.append(Paragraph(inline(stripped), style_map["body"]))
        else:
            paragraph_lines.append(line)
        i += 1

    flush_paragraph(story, paragraph_lines, style_map)
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), style_map["code"]))
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("NanumGothic", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(18 * mm, 12 * mm, "InfinityStock 사용자 가이드북")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def build_pdf():
    register_fonts()
    style_map = styles()
    ASSET_PDF.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PDF.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(DOCS_PDF),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="InfinityStock 사용자 가이드북",
        author="InfinityStock",
    )

    markdown = GUIDE_MD.read_text(encoding="utf-8")
    story = [
        Spacer(1, 45 * mm),
        Paragraph("InfinityStock 사용자 가이드북", style_map["cover_title"]),
        Paragraph("회원가입부터 증권사 API, FireGate 연동, 무한매수 운영까지", style_map["cover_subtitle"]),
        Paragraph("일반 사용자를 위한 설정 및 운영 템플릿", style_map["cover_subtitle"]),
        Spacer(1, 80 * mm),
        Paragraph("민감 정보는 문서에 기록하지 말고 사이트 설정 화면에만 저장하세요.", style_map["note"]),
        PageBreak(),
    ]
    story.extend(markdown_story(markdown, style_map, doc.width))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    shutil.copyfile(DOCS_PDF, ASSET_PDF)
    print(DOCS_PDF)
    print(ASSET_PDF)


if __name__ == "__main__":
    build_pdf()
