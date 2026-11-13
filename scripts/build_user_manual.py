"""从通用 Markdown 手册生成可检索中文 PDF；不读取个人实例。"""
from pathlib import Path
from xml.sax.saxutils import escape
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]


def main():
    for name, filename in (("YaHei", "msyh.ttc"), ("YaHeiBold", "msyhbd.ttc")):
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / filename), subfontIndex=0))
    pdfmetrics.registerFontFamily("YaHei", normal="YaHei", bold="YaHeiBold", italic="YaHei", boldItalic="YaHeiBold")
    styles = {
        "body": ParagraphStyle("Body", fontName="YaHei", fontSize=10.2, leading=16, spaceAfter=7, wordWrap="CJK"),
        "title": ParagraphStyle("Title", fontName="YaHeiBold", fontSize=25, leading=34, spaceAfter=16, textColor=colors.black),
        "h1": ParagraphStyle("H1", fontName="YaHeiBold", fontSize=20, leading=28, spaceAfter=14, keepWithNext=True, textColor=colors.black),
        "h2": ParagraphStyle("H2", fontName="YaHeiBold", fontSize=13, leading=19, spaceBefore=10, spaceAfter=7, keepWithNext=True, textColor=colors.black),
        "caption": ParagraphStyle("Caption", fontName="YaHei", fontSize=8.5, leading=12, alignment=TA_CENTER, spaceAfter=8),
        "cell": ParagraphStyle("Cell", fontName="YaHei", fontSize=9.2, leading=14, wordWrap="CJK"),
        "code": ParagraphStyle("Code", fontName="YaHei", fontSize=9, leading=14, leftIndent=10, spaceAfter=8),
    }

    def inline(text):
        text = escape(text)
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        return re.sub(r"`([^`]+)`", r"\1", text)

    source = ROOT / "templates/distribution/操作手册.md"
    output = source.with_suffix(".pdf")
    document = SimpleDocTemplate(str(output), pagesize=(595.276, 841.89), leftMargin=52, rightMargin=52,
                                 topMargin=44, bottomMargin=43, title="千鱼操作手册", author="千鱼",
                                 subject="Windows 纯净版 0.3.14 安装与使用")
    story, lines, index, first_title = [], source.read_text(encoding="utf-8").splitlines(), 0, True
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line == "<!-- pagebreak -->":
            story.append(PageBreak())
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), styles["title" if first_title else "h1"]))
            first_title = False
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), styles["h2"]))
        elif line.startswith("```"):
            block = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            story.append(Paragraph("<br/>".join(escape(item).replace(" ", "&#160;") for item in block), styles["code"]))
        elif line.startswith("!["):
            match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
            label, relative = match.groups()
            path = ROOT / Path(relative).relative_to("程序")
            width, height = ImageReader(str(path)).getSize()
            scaled_width = 445
            story.append(Image(str(path), width=scaled_width, height=height * scaled_width / width))
            story.append(Spacer(1, 5))
            story.append(Paragraph(inline(label), styles["caption"]))
        elif line.startswith("|"):
            rows = [line]
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            parsed = [[item.strip() for item in row.strip("|").split("|")] for row in rows]
            parsed = [row for row in parsed if not all(re.fullmatch(r":?-+:?", item) for item in row)]
            data = [[Paragraph(inline(item), styles["cell"]) for item in row] for row in parsed]
            table = Table(data, colWidths=[130, 361], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DFEAF6")),
                ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#D9D9D9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([table, Spacer(1, 9)])
        else:
            story.append(Paragraph(inline(line), styles["body"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("YaHei", 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(297.638, 22, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(str(output))


if __name__ == "__main__":
    main()
