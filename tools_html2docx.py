"""Builds the proposal .docx from proposal.html, so both stay in sync.

Usage: python tools_html2docx.py proposal.html "AV2 Mobile Decoding Proposal.docx"
"""
import sys

from bs4 import BeautifulSoup, NavigableString
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ACCENT = RGBColor(0x0B, 0x6B, 0x7A)
MUTED = RGBColor(0x56, 0x60, 0x6B)
BODY_FONT, MONO_FONT = "Calibri", "Consolas"


def add_runs(par, node, bold=False, italic=False, mono=False, link=None):
    """Adds the inline content of `node` to `par`, keeping bold, code and links."""
    for child in node.children:
        if isinstance(child, NavigableString):
            text = " ".join(str(child).split()) if not mono else str(child)
            if str(child)[:1].isspace() and text:
                text = " " + text
            if str(child)[-1:].isspace() and text and not text.endswith(" "):
                text += " "
            if not text:
                continue
            run = par.add_run(text)
            run.bold, run.italic = bold or None, italic or None
            if mono:
                run.font.name = MONO_FONT
                run.font.size = Pt(9.5)
            if link:
                run.font.color.rgb = ACCENT
                run.underline = True
        elif child.name == "br":
            par.add_run().add_break()
        elif child.name in ("b", "strong"):
            add_runs(par, child, True, italic, mono, link)
        elif child.name in ("i", "em"):
            add_runs(par, child, bold, True, mono, link)
        elif child.name == "code":
            add_runs(par, child, bold, italic, True, link)
        elif child.name == "a":
            add_runs(par, child, bold, italic, mono, child.get("href"))
            if child.get("href") and child.get_text(strip=True) != child.get("href"):
                url = par.add_run(f" ({child['href']})")
                url.font.size = Pt(8.5)
                url.font.color.rgb = MUTED
        else:
            add_runs(par, child, bold, italic, mono, link)
    # collapse the leading space of the first run
    if par.runs and par.runs[0].text.startswith(" "):
        par.runs[0].text = par.runs[0].text.lstrip()


def shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def add_table(doc, table):
    rows = table.find_all("tr")
    ncols = max(len(r.find_all(["th", "td"])) for r in rows)
    t = doc.add_table(rows=len(rows), cols=ncols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, cell in enumerate(row.find_all(["th", "td"])):
            c = t.cell(i, j)
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            add_runs(p, cell, bold=(cell.name == "th"))
            for r in p.runs:
                if r.font.size is None:
                    r.font.size = Pt(9.5)
            if i == 0 and row.parent.name == "thead":
                shade(c, "E3EEF0")
    # repeat the header row on page breaks
    tr_pr = t.rows[0]._tr.get_or_add_trPr()
    hdr = OxmlElement("w:tblHeader")
    hdr.set(qn("w:val"), "true")
    tr_pr.append(hdr)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def main(src, dst):
    soup = BeautifulSoup(open(src, encoding="utf-8").read(), "html.parser")
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(2.2))
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name, size in (("Title", 22), ("Heading 1", 14), ("Heading 2", 11.5)):
        st = doc.styles[name]
        st.font.name = BODY_FONT
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor(0x15, 0x1A, 0x20) if name != "Heading 1" else ACCENT
        st.font.bold = True

    main_el = soup.find("main")
    header = main_el.find("header")
    kicker = doc.add_paragraph(header.find(class_="kicker").get_text(strip=True).upper())
    kicker.runs[0].font.color.rgb = ACCENT
    kicker.runs[0].font.size = Pt(9)
    doc.add_paragraph(header.find("h1").get_text(strip=True), style="Title")
    meta = doc.add_paragraph(header.find(class_="meta").get_text(strip=True))
    meta.runs[0].font.color.rgb = MUTED
    meta.runs[0].font.size = Pt(9.5)

    for section in main_el.find_all("section", recursive=False):
        for el in section.find_all(["h2", "h3", "p", "ul", "ol", "table", "div", "span"], recursive=True):
            if el.find_parent(["li", "table", "p"]) is not None:
                continue
            if el.name == "h2":
                doc.add_heading(el.get_text(strip=True), level=1)
            elif el.name == "h3":
                doc.add_heading(el.get_text(strip=True), level=2)
            elif el.name == "span" and "tag" in (el.get("class") or []):
                p = doc.add_paragraph()
                r = p.add_run(el.get_text(strip=True).upper())
                r.font.size, r.font.color.rgb, r.bold = Pt(8.5), ACCENT, True
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.keep_with_next = True
            elif el.name == "div" and el.find_parent(class_="rq") is not None and el.find("b"):
                p = doc.add_paragraph()
                r = p.add_run(el.find("b").get_text(strip=True) + "  ")
                r.bold, r.font.color.rgb = True, ACCENT
                add_runs(p, el.find("p"))
            elif el.name == "p" and el.find_parent(class_="rq") is None:
                p = doc.add_paragraph()
                add_runs(p, el)
                if "meta" in (el.get("class") or []):
                    for r in p.runs:
                        r.font.size, r.font.color.rgb = Pt(9), MUTED
            elif el.name in ("ul", "ol"):
                style = "List Bullet" if el.name == "ul" else "List Number"
                for li in el.find_all("li", recursive=False):
                    p = doc.add_paragraph(style=style)
                    add_runs(p, li)
            elif el.name == "table":
                add_table(doc, el)

    foot = doc.add_paragraph(main_el.find("footer").get_text(strip=True))
    foot.runs[0].font.size, foot.runs[0].font.color.rgb = Pt(9), MUTED
    foot.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.save(dst)
    print("Saved", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
