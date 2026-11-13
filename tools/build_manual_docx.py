"""把参赛材料（Markdown）排版成一份 Word：封面 + 目录域 + 正文 + 页脚。

用法：
    # 默认：参赛使用手册 + 团队分工报告
    .venv/Scripts/python.exe tools/build_manual_docx.py

    # 指定源文件与输出（可多个 --src，按顺序拼接）
    .venv/Scripts/python.exe tools/build_manual_docx.py \
        --src docs/参赛材料/职航罗盘四人演示分工与操作手册.md \
        --out docs/参赛材料/职航罗盘四人演示分工与操作手册.docx \
        --title 四人演示分工与操作手册 \
        --subtitle 演示分工 · 运行操作 · 代码详解
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "参赛材料"
SRC = [DOCS / "职航罗盘参赛使用手册.md", DOCS / "职航罗盘团队分工报告.md"]
OUT = DOCS / "职航罗盘参赛使用手册与团队分工报告.docx"

FONT = "微软雅黑"
MONO = "Consolas"
BLUE = RGBColor(0x1D, 0x4E, 0xD8)
DARK = RGBColor(0x1F, 0x29, 0x37)
GRAY = RGBColor(0x6B, 0x72, 0x80)


# ---------------------------------------------------------------- 基础排版
def set_font(run, name: str = FONT, size: float | None = None,
             bold: bool | None = None, color: RGBColor | None = None) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:fill"), hex_color)
    tcPr.append(el)


def cell_margins(table, left=90, right=90, top=40, bottom=40) -> None:
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for k, v in (("left", left), ("right", right), ("top", top), ("bottom", bottom)):
        el = OxmlElement(f"w:{k}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def add_page_number(par) -> None:
    run = par.add_run()
    for instr in ("begin", "PAGE", "end"):
        el = OxmlElement("w:fldChar") if instr != "PAGE" else OxmlElement("w:instrText")
        if instr == "PAGE":
            el.set(qn("xml:space"), "preserve")
            el.text = " PAGE "
        else:
            el.set(qn("w:fldCharType"), instr)
        run._r.append(el)
    set_font(run, size=9, color=GRAY)


INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def add_inline(par, text: str, size: float = 10.5, color: RGBColor | None = DARK) -> None:
    """处理 **粗体** 与 `代码`。"""
    for piece in INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            r = par.add_run(piece[2:-2])
            set_font(r, size=size, bold=True, color=color)
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            r = par.add_run(piece[1:-1])
            set_font(r, name=MONO, size=size - 0.5, color=RGBColor(0x9A, 0x34, 0x12))
        else:
            r = par.add_run(piece)
            set_font(r, size=size, color=color)


def body(doc, text: str, indent: float = 0.0, space_after: float = 4) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(space_after)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if indent:
        pf.left_indent = Cm(indent)
    add_inline(p, text)


def bullet(doc, text: str, numbered: bool = False, level: int = 0) -> None:
    p = doc.add_paragraph(style="List Number" if numbered else "List Bullet")
    pf = p.paragraph_format
    pf.left_indent = Cm(0.75 + 0.6 * level)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    add_inline(p, text)


def numbered(doc, num: str, text: str, level: int = 0) -> None:
    """带编号的条目：直接用源文件里的编号文本，避免 Word 自动编号跨列表累加。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.75 + 0.6 * level)
    pf.first_line_indent = Cm(-0.55)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    r = p.add_run(f"{num} ")
    set_font(r, size=10.5, bold=True, color=DARK)
    add_inline(p, text)


def setup_heading_styles(doc) -> None:
    """把内置 Heading 1/2/3 改成中文排版，导航窗格与自动目录都依赖它们。"""
    for level, size in ((1, 17), (2, 13.5), (3, 11.5)):
        st = doc.styles[f"Heading {level}"]
        st.font.name = FONT
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.italic = False
        st.font.color.rgb = BLUE if level < 3 else DARK
        rPr = st.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rFonts.set(qn(attr), FONT)
        pf = st.paragraph_format
        pf.space_before = Pt({1: 18, 2: 12, 3: 9}[level])
        pf.space_after = Pt({1: 8, 2: 5, 3: 3}[level])
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.keep_with_next = True          # 标题不与下文分页
        pf.page_break_before = False


def heading(doc, text: str, level: int) -> None:
    # 关键：必须是内置标题样式，否则 Word「导航窗格」和自动目录抓不到
    p = doc.add_paragraph(style=f"Heading {level}")
    pf = p.paragraph_format
    if level == 1:
        pf.space_before = Pt(18)
        pf.space_after = Pt(8)
        pf.page_break_before = False
    elif level == 2:
        pf.space_before = Pt(12)
        pf.space_after = Pt(5)
    else:
        pf.space_before = Pt(9)
        pf.space_after = Pt(3)
    add_inline(p, text, size={1: 17, 2: 13.5, 3: 11.5}[level], color=BLUE if level < 3 else DARK)
    for r in p.runs:
        r.bold = True
    if level == 1:
        # 章标题下加一条细线
        pPr = p._p.get_or_add_pPr()
        bd = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "3")
        bottom.set(qn("w:color"), "BFD4F2")
        bd.append(bottom)
        pPr.append(bd)


def table(doc, rows: list[list[str]]) -> None:
    header, data = rows[0], rows[1:]
    t = doc.add_table(rows=len(rows), cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    cell_margins(t)
    for j, txt in enumerate(header):
        cell = t.rows[0].cells[j]
        cell.text = ""
        shade(cell, "E8F0FE")
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        add_inline(p, f"**{txt}**", size=9.5, color=RGBColor(0x0F, 0x33, 0x66))
    for i, row in enumerate(data, start=1):
        for j in range(len(header)):
            txt = row[j] if j < len(row) else ""
            cell = t.rows[i].cells[j]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            add_inline(p, txt, size=9)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def code_block(doc, lines: list[str]) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.5)
    pf.space_before = Pt(4)
    pf.space_after = Pt(8)
    pf.line_spacing = 1.0
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F5F7FA")
    pPr.append(shd)
    for i, ln in enumerate(lines):
        r = p.add_run(ln + ("\n" if i < len(lines) - 1 else ""))
        set_font(r, name=MONO, size=9, color=RGBColor(0x24, 0x29, 0x2E))


# ---------------------------------------------------------------- Markdown 解析
def render(doc, md: str) -> None:
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        if not s:
            i += 1
            continue

        # 代码块
        if s.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code_block(doc, buf)
            continue

        # 表格
        if s.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") and c for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                table(doc, rows)
            continue

        # 标题
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            heading(doc, m.group(2).strip(), len(m.group(1)))
            i += 1
            continue

        # 引用
        if s.startswith(">"):
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Cm(0.6)
            pf.space_before = Pt(2)
            pf.space_after = Pt(6)
            add_inline(p, s.lstrip("> "), size=9.5, color=GRAY)
            i += 1
            continue

        # 分隔线
        if s in ("---", "***"):
            i += 1
            continue

        # 列表
        if s.startswith("- "):
            bullet(doc, s[2:].strip())
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            numbered(doc, m.group(1) + ".", m.group(2))
            i += 1
            continue

        body(doc, s)
        i += 1


# ---------------------------------------------------------------- 封面与页脚
def cover(doc, title: str = "参赛使用手册与团队分工报告",
          subtitle: str = "") -> None:
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("职航罗盘")
    set_font(r, size=36, bold=True, color=RGBColor(0x0B, 0x2A, 0x5B))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("CAREER COMPASS · 学生职业规划大数据平台")
    set_font(r, size=12, color=GRAY)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(title)
    set_font(r, size=22, bold=True, color=BLUE)

    if subtitle:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(subtitle)
        set_font(r, size=11, color=GRAY)

    doc.add_paragraph()
    doc.add_paragraph()
    for txt in ("职业院校技能大赛",
                "2026 年 11 月",
                "3,851 条公开岗位 · 22 个城市 · 113 个标准技能 · 9 个专业"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(txt)
        set_font(r, size=11 if txt != "3,851 条公开岗位 · 22 个城市 · 113 个标准技能 · 9 个专业"
                 else 10, color=DARK if txt != "3,851 条公开岗位 · 22 个城市 · 113 个标准技能 · 9 个专业"
                 else GRAY)

    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("本手册所引数字以 docs/指标台账.md 为唯一事实源")
    set_font(r, size=9, color=GRAY)

    doc.add_page_break()


def toc_page(doc) -> None:
    """目录页：真实的 TOC 域（Word 可一键更新页码，并支持点击跳转）。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("目　录")
    set_font(r, size=20, bold=True, color=RGBColor(0x0B, 0x2A, 0x5B))
    p2 = doc.add_paragraph()
    p2.paragraph_format.space_after = Pt(12)
    r = p2.add_run("CONTENTS")
    set_font(r, size=9, color=GRAY)

    par = doc.add_paragraph()
    par.paragraph_format.space_after = Pt(0)
    run = par.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r' TOC \o "1-2" \h \z \u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "（目录将在打开文档时自动生成；若未显示，右键此处 →「更新域」）"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    for el in (fld_begin, instr, fld_sep, placeholder, fld_end):
        run._r.append(el)
    set_font(run, size=10, color=GRAY)

    doc.add_page_break()


def enable_update_fields(doc) -> None:
    """让 Word 打开文档时自动刷新目录页码（域）。"""
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        el = OxmlElement("w:updateFields")
        el.set(qn("w:val"), "true")
        settings.append(el)


def footer(doc, label: str = "参赛使用手册与团队分工报告") -> None:
    sec = doc.sections[0]
    p = sec.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"职航罗盘 · {label}　—　第 ")
    set_font(r, size=9, color=GRAY)
    add_page_number(p)
    r = p.add_run(" 页")
    set_font(r, size=9, color=GRAY)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Markdown → Word（封面 + 目录域 + 正文）")
    ap.add_argument("--src", action="append", default=None,
                    help="源 Markdown（可多次指定，按顺序拼接）")
    ap.add_argument("--out", default=None, help="输出 docx 路径")
    ap.add_argument("--title", default="参赛使用手册与团队分工报告", help="封面主标题")
    ap.add_argument("--subtitle", default="", help="封面副标题")
    ap.add_argument("--label", default=None, help="页脚文字（默认同主标题）")
    args = ap.parse_args(argv)

    src = [Path(p) if Path(p).is_absolute() else (ROOT / p) for p in args.src] if args.src else SRC
    out = (Path(args.out) if args.out and Path(args.out).is_absolute()
           else ROOT / args.out) if args.out else OUT

    doc = Document()
    sec = doc.sections[0]
    sec.page_height = Cm(29.7)
    sec.page_width = Cm(21.0)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    setup_heading_styles(doc)   # 标题必须挂内置样式，导航窗格才有结构
    enable_update_fields(doc)   # 打开时自动刷新目录页码

    footer(doc, args.label or args.title)
    cover(doc, args.title, args.subtitle)
    toc_page(doc)

    for idx, path in enumerate(src):
        if not path.exists():
            raise SystemExit(f"缺少源文件：{path}")
        if idx:
            doc.add_page_break()
        render(doc, path.read_text(encoding="utf-8"))

    out.parent.mkdir(parents=True, exist_ok=True)
    # 文档可能正被 Word / 预览占用：先写临时文件，再尝试替换，失败则保留副本
    tmp = out.with_name("_build_tmp.docx")
    doc.save(tmp)
    try:
        os.replace(tmp, out)
        saved = out
    except PermissionError:
        saved = out.with_name(f"{out.stem}_新.docx")
        os.replace(tmp, saved)
        print("⚠ 原文件被占用（Word 或预览里打开着），已另存为：", saved.name)

    # 自检：段落/表格/标题层级/目录域
    chk = Document(saved)
    lv = {i: 0 for i in (1, 2, 3)}
    for p in chk.paragraphs:
        sn = (p.style.name or "")
        for i in (1, 2, 3):
            if sn == f"Heading {i}":
                lv[i] += 1
    has_toc = any("TOC" in (e.text or "") for e in chk.element.body.iter(qn("w:instrText")))
    print(f"已生成：{saved}")
    print(f"  段落 {len(chk.paragraphs)} · 表格 {len(chk.tables)} · "
          f"{saved.stat().st_size / 1024:.0f} KB")
    print(f"  标题 H1={lv[1]} H2={lv[2]} H3={lv[3]} · 目录域：{'有' if has_toc else '无'}")


if __name__ == "__main__":
    main()
