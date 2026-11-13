"""把逐字稿 Markdown 排成 Word：封面 + 目录 + 分角色台词 + 灰字动作提示。

和 build_manual_docx.py 的区别：这份是给台上念的，所以
    · 说话人名字按角色着色并加粗（1 蓝 / 2 青 / 3 紫 / 4 橙 / 齐声 红）
    · 括号里的动作提示排成灰色斜体小字，一眼能和台词分开
    · 引用块排成浅灰提示框（排演说明、注意事项）
    · 台词字号 11pt、行距 1.5，站在台上也能看清

用法：
    .venv/Scripts/python.exe tools/build_script_docx.py \
        --src docs/参赛材料/职航罗盘四人演示逐字稿_v2.md \
        --out docs/参赛材料/职航罗盘四人演示逐字稿_v2.docx
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document                                    # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING  # noqa: E402
from docx.oxml import OxmlElement                            # noqa: E402
from docx.oxml.ns import qn                                  # noqa: E402
from docx.shared import Cm, Pt, RGBColor                     # noqa: E402

from build_manual_docx import (                              # noqa: E402
    BLUE, DARK, GRAY, ROOT, add_inline, code_block, cover, enable_update_fields,
    footer, heading, set_font, setup_heading_styles, table, toc_page,
)

DEFAULT_SRC = ROOT / "docs" / "参赛材料" / "职航罗盘四人演示逐字稿.md"
DEFAULT_OUT = ROOT / "docs" / "参赛材料" / "职航罗盘四人演示逐字稿.docx"

# 角色色：四个人四个颜色，台上扫一眼就知道轮到谁
ROLE_COLOR = {
    "1 号": RGBColor(0x1D, 0x4E, 0xD8),
    "2 号": RGBColor(0x0F, 0x76, 0x6E),
    "3 号": RGBColor(0x6D, 0x28, 0xD9),
    "4 号": RGBColor(0xB4, 0x53, 0x09),
    "齐声": RGBColor(0xB9, 0x1C, 0x1C),
}
LINE_PT = 11          # 台词字号

SPEAKER = re.compile(r"^\*\*(.+?)\*\*\s*[：:]\s*(.*)$")
ACTION = re.compile(r"^[（(].*[）)]$")


def cue(doc, text: str) -> None:
    """动作提示：灰色斜体，缩进，前后留白。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.55)
    pf.space_before = Pt(2)
    pf.space_after = Pt(4)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    add_inline(p, text, size=9.5, color=RGBColor(0x8A, 0x8F, 0x98))
    for r in p.runs:
        r.italic = True


def line(doc, who: str, words: str) -> None:
    """一句台词：说话人按角色着色加粗，台词 11pt 行距 1.5。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(3)
    pf.space_after = Pt(3)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE

    r = p.add_run(who)
    color = ROLE_COLOR.get(who.strip(), BLUE)
    set_font(r, size=LINE_PT, bold=True, color=color)
    r2 = p.add_run("　")
    set_font(r2, size=LINE_PT)

    add_inline(p, words, size=LINE_PT, color=RGBColor(0x1A, 0x1F, 0x2B))


def tip_box(doc, text: str) -> None:
    """提示框：浅灰底 + 左侧竖线，用于排演说明。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.35)
    pf.right_indent = Cm(0.2)
    pf.space_before = Pt(4)
    pf.space_after = Pt(6)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE

    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F4F7FB")
    pPr.append(shd)
    bdr = OxmlElement("w:pBdr")
    for side, sz, color in (("left", "18", "6C9BD1"), ("top", "2", "E3EAF3"),
                            ("bottom", "2", "E3EAF3"), ("right", "2", "E3EAF3")):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), sz)
        el.set(qn("w:space"), "6")
        el.set(qn("w:color"), color)
        bdr.append(el)
    pPr.append(bdr)

    add_inline(p, text, size=9.5, color=RGBColor(0x44, 0x52, 0x66))


def bullet(doc, text: str, level: int = 0) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.85 + 0.6 * level)
    pf.first_line_indent = Cm(-0.4)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    r = p.add_run("· ")
    set_font(r, size=LINE_PT - 1, bold=True, color=BLUE)
    add_inline(p, text, size=LINE_PT - 1, color=DARK)


def numbered(doc, num: str, text: str) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.9)
    pf.first_line_indent = Cm(-0.55)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    r = p.add_run(f"{num} ")
    set_font(r, size=LINE_PT - 1, bold=True, color=DARK)
    add_inline(p, text, size=LINE_PT - 1, color=DARK)


def render(doc, md: str) -> None:
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
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

        # 引用块 → 提示框
        if s.startswith(">"):
            tip_box(doc, s.lstrip("> ").strip())
            i += 1
            continue

        if s in ("---", "***"):
            i += 1
            continue

        # 台词（说话人 + 台词）
        m = SPEAKER.match(s)
        if m:
            line(doc, m.group(1).strip(), m.group(2).strip())
            i += 1
            continue

        # 纯动作提示（整段被括号包住）
        if ACTION.match(s):
            cue(doc, s)
            i += 1
            continue

        if s.startswith("- "):
            bullet(doc, s[2:].strip())
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            numbered(doc, m.group(1) + ".", m.group(2))
            i += 1
            continue

        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(4)
        pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        add_inline(p, s, size=LINE_PT - 0.5)
        i += 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="逐字稿 Markdown → Word（分角色着色）")
    ap.add_argument("--src", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default="四人演示逐字稿")
    ap.add_argument("--subtitle", default="⑧①② / ③④⑤ / ⑥+Dify / ⑦ 分工 · 18 分钟 · 逐句可念")
    args = ap.parse_args(argv)

    src = Path(args.src) if args.src else DEFAULT_SRC
    if not src.is_absolute():
        src = ROOT / src
    out = Path(args.out) if args.out else DEFAULT_OUT
    if not out.is_absolute():
        out = ROOT / out
    if not src.exists():
        raise SystemExit(f"缺少源文件：{src}")

    doc = Document()
    sec = doc.sections[0]
    sec.page_height = Cm(29.7)
    sec.page_width = Cm(21.0)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.font.size = Pt(LINE_PT)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    setup_heading_styles(doc)
    enable_update_fields(doc)
    footer(doc, args.title)
    cover(doc, args.title, args.subtitle)
    toc_page(doc)

    render(doc, src.read_text(encoding="utf-8"))

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)

    chk = Document(out)
    lv = {1: 0, 2: 0, 3: 0}
    for p in chk.paragraphs:
        for k in (1, 2, 3):
            if (p.style.name or "") == f"Heading {k}":
                lv[k] += 1
    speakers: dict[str, int] = {}
    for p in chk.paragraphs:
        for r in p.runs[:1]:
            name = (r.text or "").strip()
            if name in ROLE_COLOR:
                speakers[name] = speakers.get(name, 0) + 1
    print(f"已生成：{out}")
    print(f"  段落 {len(chk.paragraphs)} · 表格 {len(chk.tables)} · {out.stat().st_size / 1024:.0f} KB")
    print(f"  标题 H1={lv[1]} H2={lv[2]} H3={lv[3]}")
    print(f"  台词条数：{speakers} 合计 {sum(speakers.values())}")


if __name__ == "__main__":
    main()
