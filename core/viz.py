"""三张自绘 SVG 图：溢价条形、技能网络、缺口四象限。

不用 plotly，一是少装依赖，二是这几张图的样式要跟页面统一。
"""
from __future__ import annotations

import math

import pandas as pd

RED, GREEN, GRAY, INK, MUTED = "#dc2626", "#16a34a", "#94a3b8", "#0f172a", "#64748b"
FONT = "system-ui,-apple-system,Microsoft YaHei"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def premium_bars(df: pd.DataFrame, top: int = 8) -> str:
    """技能溢价横向条形图，带 95% 区间。红涨绿跌。"""
    if df is None or df.empty:
        return '<div style="color:#64748b;font-size:13px">没有可用的溢价估计</div>'
    d = df.head(top).iloc[::-1].reset_index(drop=True)
    W, RH, LEFT, RIGHT = 860, 42, 220, 30
    H = 36 + RH * len(d)
    lo = min(d["ci_low"].min(), -0.01)
    hi = max(d["ci_high"].max(), 0.01)
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    def x(v):
        return LEFT + (v - lo) / (hi - lo) * (W - LEFT - RIGHT)

    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    p.append(f'<line x1="{x(0)}" y1="20" x2="{x(0)}" y2="{H-8}" stroke="#cbd5e1" stroke-width="1"/>')
    p.append(f'<text x="6" y="17" font-size="13" fill="{MUTED}" font-family="{FONT}">控制变量后的月薪差异</text>')
    for i, r in d.iterrows():
        y = 30 + i * RH
        x0, x1 = x(0), x(r["premium"])
        c = RED if r["premium"] >= 0 else GREEN
        p.append(f'<text x="{LEFT-10}" y="{y+15}" text-anchor="end" font-size="15" fill="{INK}" '
                 f'font-family="{FONT}">{_esc(r["skill"])}</text>')
        p.append(f'<rect x="{min(x0,x1)}" y="{y+5}" width="{abs(x1-x0)}" height="19" fill="{c}" opacity="0.85" rx="2"/>')
        p.append(f'<line x1="{x(r["ci_low"])}" y1="{y+14.5}" x2="{x(r["ci_high"])}" y2="{y+14.5}" stroke="{c}" '
                 f'stroke-width="1.4" opacity="0.55"/>')
        p.append(f'<line x1="{x(r["ci_low"])}" y1="{y+8.5}" x2="{x(r["ci_low"])}" y2="{y+20.5}" stroke="{c}" stroke-width="1.4" opacity="0.55"/>')
        p.append(f'<line x1="{x(r["ci_high"])}" y1="{y+8.5}" x2="{x(r["ci_high"])}" y2="{y+20.5}" stroke="{c}" stroke-width="1.4" opacity="0.55"/>')
        # 数值标在区间端点外侧，避免压在条上
        tx, anchor = max(x(r["ci_high"]), x0) + 8, "start"
        if tx > W - 62:
            tx, anchor = min(x(r["ci_low"]), x0) - 8, "end"
        p.append(f'<text x="{tx:.1f}" y="{y+15}" text-anchor="{anchor}" font-size="14" font-weight="600" '
                 f'fill="{c}" font-family="{FONT}">{r["premium"]:+.1%}</text>')
    p.append("</svg>")
    return "".join(p)


def network(edges: pd.DataFrame, top_nodes: int = 14) -> str:
    """技能共现网络：环形布局，边粗 = PMI 高。"""
    if edges is None or edges.empty:
        return '<div style="color:#64748b;font-size:13px">共现数据不足</div>'
    deg = pd.concat([edges["a"], edges["b"]]).value_counts()
    nodes = list(deg.head(top_nodes).index)
    e = edges[edges["a"].isin(nodes) & edges["b"].isin(nodes)]
    W, H, R = 780, 540, 196
    cx, cy = W / 2, H / 2
    pos = {}
    for i, n in enumerate(nodes):
        ang = -math.pi / 2 + 2 * math.pi * i / len(nodes)
        pos[n] = (cx + R * math.cos(ang) * 1.32, cy + R * math.sin(ang))
    mx = max(deg.max(), 1)
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    for r in e.itertuples():
        x1, y1 = pos[r.a]
        x2, y2 = pos[r.b]
        p.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="#8fb7e0" stroke-width="{0.4 + min(r.pmi,3)*0.9:.1f}" opacity="0.28"/>')
    for n in nodes:
        x, y = pos[n]
        rad = 6 + 8 * (deg[n] / mx) ** 0.6
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="#6c9bd1" opacity="0.9"/>')
        anchor = "middle"
        dx = 0
        if x < cx - 24:
            anchor, dx = "end", -rad - 6
        elif x > cx + 24:
            anchor, dx = "start", rad + 6
        dy = -rad - 6 if abs(y - cy) < 48 and y < cy else rad + 15
        p.append(f'<text x="{x+dx:.1f}" y="{y+dy:.1f}" text-anchor="{anchor}" font-size="14" fill="{INK}" '
                 f'font-family="{FONT}">{_esc(n)}</text>')
    p.append(f'<text x="14" y="{H-12}" font-size="13" fill="{MUTED}" font-family="{FONT}">'
             f'节点大小=出现次数，连线粗细=PMI（只画 PMI&gt;0 且共现≥15 次的边）</text>')
    p.append("</svg>")
    return "".join(p)


def quadrant(df: pd.DataFrame) -> str:
    """横轴课程覆盖度，纵轴需求权重。左上角越靠上越红 = 越该改课。"""
    if df is None or df.empty:
        return '<div style="color:#64748b;font-size:13px">没有覆盖数据</div>'
    d = df.copy()
    d["w"] = d["w"] / max(d["w"].max(), 1e-9)
    W, H, L, B, T, R = 1080, 620, 84, 62, 30, 26

    def X(v):
        return L + float(v) * (W - L - R)

    def Y(v):
        return H - B - float(v) * (H - B - T)

    col = {"红": RED, "橙": "#ea580c", "绿": "#16a34a"}
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    p.append(f'<rect x="{X(0)}" y="{Y(1)}" width="{X(0.5)-X(0)}" height="{Y(0.7)-Y(1)}" fill="#fef2f2"/>')
    p.append(f'<text x="{X(0.02)+6}" y="{Y(1)+26}" font-size="15" font-weight="600" fill="#b91c1c" font-family="{FONT}">'
             f'重点改课区（需求高·覆盖低）</text>')
    for gx in (0, 0.5, 1):
        p.append(f'<line x1="{X(gx)}" y1="{Y(0)}" x2="{X(gx)}" y2="{Y(1)}" stroke="#e2e8f0"/>')
        p.append(f'<text x="{X(gx)}" y="{H-B+24}" text-anchor="middle" font-size="14" fill="{MUTED}" '
                 f'font-family="{FONT}">{gx:.1f}</text>')
    for gy in (0, 0.5, 1):
        p.append(f'<line x1="{X(0)}" y1="{Y(gy)}" x2="{X(1)}" y2="{Y(gy)}" stroke="#e2e8f0"/>')
        p.append(f'<text x="{L-10}" y="{Y(gy)+5}" text-anchor="end" font-size="14" fill="{MUTED}" '
                 f'font-family="{FONT}">{gy:.1f}</text>')
    p.append(f'<text x="{(L+W-R)/2}" y="{H-14}" text-anchor="middle" font-size="16" font-weight="600" fill="{INK}" '
             f'font-family="{FONT}">课程覆盖度</text>')
    p.append(f'<text x="24" y="{(T+H-B)/2}" font-size="16" font-weight="600" fill="{INK}" font-family="{FONT}" '
             f'transform="rotate(-90 24 {(T+H-B)/2})" text-anchor="middle">需求权重（归一）</text>')
    # 只给最靠上的 12 个点打标签，否则十几个标签会叠在一起
    labeled = set(d.sort_values("w", ascending=False).head(12)["skill"])
    for r in d.sort_values("w").itertuples():
        x, y = X(min(r.cover, 1)), Y(min(r.w, 1))
        c = col.get(r.gap_type, GRAY)
        rad = 6 + 5 * math.sqrt(r.n / max(d["n"].max(), 1))
        # 悬浮提示：技能概况 + 相关课程（SVG 原生 <title>，鼠标停留即显示）
        courses = str(getattr(r, "courses", "") or "").strip()
        tip = (f"{r.skill}\n覆盖度 {r.cover:.0%} · 需求权重 {r.w:.2f} · {r.n} 条岗位\n"
               + (f"相关课程：{courses}" if courses else "暂无课程覆盖"))
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{c}" opacity="0.75" '
                 f'stroke="#fff" stroke-width="1.5"><title>{_esc(tip)}</title></circle>')
        if r.skill in labeled:
            p.append(f'<text x="{x+rad+4:.1f}" y="{y+5:.1f}" font-size="14" fill="{INK}" '
                     f'font-family="{FONT}">{_esc(r.skill)}</text>')
    p.append("</svg>")
    return "".join(p)


def demand_bars(df: pd.DataFrame, top: int = 15) -> str:
    """技能需求榜横向条形图（市场全景屏）：条长 = 要求该技能的岗位数。"""
    if df is None or df.empty:
        return '<div style="color:#64748b;font-size:13px">还没有需求数据，先采集并跑技能归一</div>'
    d = df.head(top).iloc[::-1].reset_index(drop=True)
    W, RH, LEFT, RIGHT = 900, 40, 190, 84
    H = 34 + RH * len(d)
    nmax = max(d["n"].max(), 1)
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    p.append(f'<text x="6" y="16" font-size="13" fill="{MUTED}" font-family="{FONT}">'
             f'要求该技能的岗位数（共 {int(df["n"].max())} 条岗位出现过最热门技能）</text>')
    for i, r in d.iterrows():
        y = 28 + i * RH
        w_ = max(float(r["n"]) / nmax * (W - LEFT - RIGHT), 2)
        hot = i >= len(d) - 3          # 最热门的三条加深
        c = "#5586bd" if hot else "#60a5fa"
        p.append(f'<text x="{LEFT-10}" y="{y+16}" text-anchor="end" font-size="15" '
                 f'fill="{INK}" font-family="{FONT}">{_esc(str(r["skill"])[:9])}</text>')
        p.append(f'<rect x="{LEFT}" y="{y+3}" width="{w_:.1f}" height="22" rx="4" '
                 f'fill="{c}" opacity="0.88"/>')
        p.append(f'<text x="{LEFT+w_+8:.1f}" y="{y+20}" font-size="14" font-weight="600" '
                 f'fill="{c}" font-family="{FONT}">{int(r["n"])} 条 · {r["share"]:.0%}</text>')
    p.append("</svg>")
    return "".join(p)


def growth_curve(hist: pd.DataFrame, sel: int | None = None) -> str:
    """成长档案：命中率曲线 + 缺口数，一次定位一个点。

    sel：要高亮的点序号（0 起，按时间旧→新）。⑤ 屏在记录表里点选某一行时传进来，
    该点会被竖虚线 + 光环标出，配合"删除这条记录"让人先看清删的是哪一个。
    """
    if hist is None or len(hist) == 0:
        return ('<div style="color:#64748b;font-size:13px">'
                '还没有快照——生成路径后点「存入成长档案」，第二次来就能看到曲线</div>')
    d = hist.reset_index(drop=True)
    n = len(d)
    W, H, L, R, T, B = 900, 320, 70, 66, 26, 46

    def X(i):
        return L + (i / max(n - 1, 1)) * (W - L - R)

    def Y(v):
        return H - B - float(v) * (H - T - B)

    ymax = max(d["n_gap"].max() * 1.15, 4)
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    for gv in (0, 0.25, 0.5, 0.75, 1.0):
        p.append(f'<line x1="{L}" y1="{Y(gv):.1f}" x2="{W-R}" y2="{Y(gv):.1f}" stroke="#e2e8f0"/>')
        p.append(f'<text x="{L-8}" y="{Y(gv)+5:.1f}" text-anchor="end" font-size="13" '
                 f'fill="{MUTED}" font-family="{FONT}">{gv:.0%}</text>')
    # 缺口数（浅橙面积，右轴）
    pts_gap = " ".join(f"{X(i):.1f},{Y(float(r.n_gap) / ymax):.1f}" for i, r in d.iterrows())
    p.append(f'<polygon points="{L},{H-B} {pts_gap} {X(n-1):.1f},{H-B}" fill="#ffedd5" opacity="0.55"/>')
    # 命中率折线
    pts = " ".join(f"{X(i):.1f},{Y(float(r.match)):.1f}" for i, r in d.iterrows())
    p.append(f'<polyline points="{pts}" fill="none" stroke="#5586bd" stroke-width="3" '
             f'stroke-linejoin="round"/>')
    _sel = None if sel is None else int(sel)
    if _sel is not None and 0 <= _sel < n:
        # 选中点：竖虚线拉到 x 轴，配合光环，一眼看出选的是哪一次记录
        p.append(f'<line x1="{X(_sel):.1f}" y1="{T}" x2="{X(_sel):.1f}" y2="{H-B}" '
                 f'stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5 5"/>')
    for i, r in d.iterrows():
        x, y = X(i), Y(float(r.match))
        # ④补课清单勾选提交的快照点画橙色：一眼看出"哪次提交补课 → 命中率跳升"
        is_check = "勾选" in str(r.get("source") or "")
        dot_fill = "#ea580c" if is_check else "#5586bd"
        tip = f"{_esc(r.ts[:16])}\n命中率 {r.match:.0%} · 缺口 {int(r.n_gap)} 项 · 已会 {int(r.n_held)} 项"
        if is_check:
            tip += "\n来源：④补课清单勾选提交"
        _hit = _sel is not None and i == _sel
        if _hit:
            tip += "\n（已选中：可在下方删除这条记录）"
            p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" fill="none" stroke="{dot_fill}" '
                     f'stroke-opacity="0.30" stroke-width="7"/>')
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{8.2 if _hit else 5.5}" fill="{dot_fill}" '
                 f'stroke="#fff" stroke-width="2"><title>{tip}</title></circle>')
        p.append(f'<text x="{x:.1f}" y="{y-12:.1f}" text-anchor="middle" font-size="13" '
                 f'font-weight="600" fill="{dot_fill}" font-family="{FONT}">{r.match:.0%}</text>')
    p.append(f'<text x="{(L+W-R)/2}" y="{H-12}" text-anchor="middle" font-size="13.5" '
             f'fill="{MUTED}" font-family="{FONT}">蓝点=定位 · 橙点=补课清单提交　'
             f'浅橙面积=待补缺口数</text>')
    p.append("</svg>")
    return "".join(p)


def roadmap(gap: pd.DataFrame, n_held: int, match: float) -> str:
    """学习路径路线图：已掌握起点 → 按优先级排列的差距技能，箭头串联（蛇形折行）。

    颜色按课程覆盖度：0 覆盖=红（要先开课）、不满=橙（课程里加深）、已覆盖=绿（自学可到）。
    差距项可能多达 10 个，一行平铺会把 SVG 压到看不清，这里每行最多 4 个节点、自动折行，
    行与行之间用弧线箭头回折，顺序仍按节点左上角的序号。
    """
    if gap is None or gap.empty:
        return '<div style="color:#64748b;font-size:13px">没有差距项——目标岗位族的技能都已掌握</div>'
    NW, NH, GX, PAD = 190, 96, 46, 24
    PER_ROW = 4                       # 每行 4 个节点（首行起点+3 个），总宽 ~946px，1:1 渲染文字清晰
    VX = 52                           # 行间距（留给折行箭头）
    rows: list[list[tuple[int, object]]] = []   # 每行 [(序号, 行记录)]
    items = list(gap.iterrows())
    if len(items) <= PER_ROW:
        rows.append(items)
    else:
        rows.append(items[:PER_ROW - 1])          # 首行要给起点框让位：起点+3 节点
        for k in range(PER_ROW - 1, len(items), PER_ROW):
            rows.append(items[k:k + PER_ROW])
    width = PAD * 2 + PER_ROW * NW + PER_ROW * GX
    height = PAD * 2 + len(rows) * NH + (len(rows) - 1) * VX + 46
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">',
             '<defs><marker id="rmah" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">'
             '<path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker></defs>']

    def node_svg(x: float, y: float, r, prio: int | None = None) -> None:
        cov = float(r.get("课程覆盖", 0) or 0)
        c = RED if cov <= 0 else ("#ea580c" if cov < 1 else GREEN)
        fill = "#fef2f2" if cov <= 0 else ("#fff7ed" if cov < 1 else "#f0fdf4")
        prio = int(r.get("优先级", 0) or 0) if prio is None else prio
        name = str(r.get("技能", "") or "")
        n_dem = int(r.get("岗位数", 0) or 0)
        course = str(r.get("相关课程", "") or "")
        tip = (f"{name}｜{n_dem} 条岗位要求｜课程覆盖 {cov:.0%}\n"
               f"相关课程：{course or '暂无'}")
        # 注意：<rect> 必须自闭合；否则 <text> 会变成 rect 的子元素而不渲染（框内空白的根因）
        parts.append(f'<g><title>{_esc(tip)}</title>'
                     f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" rx="12" fill="{fill}" '
                     f'stroke="{c}" stroke-width="2"/>'
                     f'<circle cx="{x+22:.0f}" cy="{y+22:.0f}" r="13" fill="{c}"/>'
                     f'<text x="{x+22:.0f}" y="{y+27:.0f}" text-anchor="middle" font-size="14" font-weight="700" '
                     f'fill="#fff" font-family="{FONT}">{prio}</text>'
                     f'<text x="{x+NW/2:.0f}" y="{y+52:.0f}" text-anchor="middle" font-size="17" font-weight="600" '
                     f'fill="{INK}" font-family="{FONT}">{_esc(name[:9])}</text>'
                     f'<text x="{x+NW/2:.0f}" y="{y+76:.0f}" text-anchor="middle" font-size="12.5" fill="{MUTED}" '
                     f'font-family="{FONT}">{n_dem} 条岗位 · 覆盖 {cov:.0%}</text></g>')

    prev_tail: tuple[float, float] | None = None   # 上一行末节点的 (右边缘中点, 行y)
    for ri, row in enumerate(rows):
        y = PAD + ri * (NH + VX)
        # 起点：仅第一行行首
        if ri == 0:
            parts.append(f'<rect x="{PAD}" y="{y}" width="{NW}" height="{NH}" rx="12" fill="#ecfdf5" '
                         f'stroke="#16a34a" stroke-width="2"/>'
                         f'<text x="{PAD+NW/2}" y="{y+40}" text-anchor="middle" font-size="26" font-weight="700" '
                         f'fill="#15803d" font-family="{FONT}">{n_held}</text>'
                         f'<text x="{PAD+NW/2}" y="{y+68}" text-anchor="middle" font-size="15" fill="#166534" '
                         f'font-family="{FONT}">已掌握技能</text>')
            x = PAD + NW
        else:
            x = PAD
        for k, (_, r) in enumerate(row):
            nx = x + (GX if k or ri == 0 else 0)
            # 行内箭头（同行前一节点 → 本节点）；首节点由上一行折线接入
            if k or ri == 0:
                parts.append(f'<path d="M{x if k or ri else PAD+NW},{y+NH/2} L{nx-8},{y+NH/2}" '
                             f'fill="none" stroke="#94a3b8" stroke-width="2.4" marker-end="url(#rmah)"/>')
            node_svg(nx, y, r)
            x = nx + NW
        if prev_tail is not None:
            # 行间折线：上一行末节点底部中心 → 本行首节点顶部中心（弧线，不出画布）
            sxp, syp = prev_tail
            cx, cy = PAD + NW / 2, y
            parts.append(f'<path d="M{sxp:.0f},{syp+NH:.0f} C{sxp:.0f},{syp+NH+VX/2:.0f} '
                         f'{cx:.0f},{cy-VX/2:.0f} {cx:.0f},{cy-6}" fill="none" '
                         f'stroke="#94a3b8" stroke-width="2.4" marker-end="url(#rmah)"/>')
        prev_tail = (x, y)
    parts.append(f'<text x="{PAD}" y="{height-10}" font-size="13" fill="{MUTED}" font-family="{FONT}">'
                 f'岗位需求命中率 {match:.0%}　|　红=课程零覆盖需先开课，橙=现有课程加深，绿=已覆盖自学可达　'
                 f'|　序号即补课顺序，悬浮看岗位次数与关联课程</text>')
    parts.append("</svg>")
    return "".join(parts)


def trend_lines(share: pd.DataFrame, months: list[str], skills: list[str]) -> str:
    """技能需求月度趋势折线图（占比口径，多技能同图）。"""
    if share is None or share.empty or not months:
        return '<div style="color:#64748b;font-size:13px">暂无月度数据</div>'
    W, H = 1080, 360
    L, R, T, B = 62, 210, 26, 48
    pw, ph = W - L - R, H - T - B
    ymax = max(float(share.max().max()), 0.05) * 1.15
    colors = ["#6c9bd1", "#0ea5e9", "#16a34a", "#f59e0b", "#8b5cf6",
              "#ef4444", "#0891b2", "#64748b"]
    n = max(len(months) - 1, 1)
    xs = {m: L + pw * i / n for i, m in enumerate(months)}

    def y(v: float) -> float:
        return T + ph - (float(v) / ymax) * ph

    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:100%;height:auto" '
         f'font-family="{FONT}" xmlns="http://www.w3.org/2000/svg">']
    # 网格与 y 轴
    for i in range(5):
        v = ymax * i / 4
        yy = y(v)
        p.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{L + pw}" y2="{yy:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        p.append(f'<text x="{L - 10}" y="{yy + 4:.1f}" font-size="12" fill="{MUTED}" '
                 f'text-anchor="end">{v:.0%}</text>')
    # x 轴刻度
    for m in months:
        p.append(f'<text x="{xs[m]:.1f}" y="{T + ph + 22}" font-size="12.5" fill="{MUTED}" '
                 f'text-anchor="middle">{m[5:]}月</text>')
        p.append(f'<line x1="{xs[m]:.1f}" y1="{T + ph}" x2="{xs[m]:.1f}" y2="{T + ph + 5}" '
                 f'stroke="#cbd5e1"/>')
    # 折线
    for i, s in enumerate(skills):
        if s not in share.columns:
            continue
        col = colors[i % len(colors)]
        pts = " ".join(f"{xs[m]:.1f},{y(share.loc[m, s]):.1f}" for m in months)
        p.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.4" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
        for m in months:
            p.append(f'<circle cx="{xs[m]:.1f}" cy="{y(share.loc[m, s]):.1f}" r="4" fill="#fff" '
                     f'stroke="{col}" stroke-width="2.4"><title>{_esc(s)} {m}：'
                     f'{float(share.loc[m, s]):.1%}</title></circle>')
    # 图例（右侧两列）
    for i, s in enumerate(skills):
        col = colors[i % len(colors)]
        lx = L + pw + 26 + (i // 4) * 108
        ly = T + 14 + (i % 4) * 26
        p.append(f'<rect x="{lx}" y="{ly - 8}" width="12" height="12" rx="3" fill="{col}"/>')
        p.append(f'<text x="{lx + 18}" y="{ly + 2}" font-size="12.5" fill="{INK}">{_esc(s)}</text>')
    p.append(f'<text x="{L}" y="{T - 8}" font-size="12.5" fill="{MUTED}">'
             f'每月「要求该技能的岗位数 ÷ 当月岗位总数」</text>')
    p.append("</svg>")
    return "".join(p)
