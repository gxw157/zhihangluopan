"""智能体：一个可以"在网页上搭"的流程引擎。

流程存在 config/agent_flow.json：节点有类型、工具、参数、依赖。
引擎只做三件事：按依赖排序 → 逐个执行工具 → 把结果交给成稿节点。
每个节点都留调用记录，答辩时可以直接点开看某句话是哪一次调用算出来的。
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import pandas as pd

from core import analyze, llm, semantic, skills as SK

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "config" / "agent_flow.json"
FLOW_VERSION = 4

DEFAULT_FLOW = {
    "version": 4,   # 流程版本：旧版本（教务口径的专业诊断）会被自动升级成学生成长版
    "name": "我的技能成长诊断",
    "major": "人工智能技术应用",
    "city": "全省",
    "nodes": [
        # ① 市场在要什么
        {"id": "n1", "type": "tool", "title": "取市场岗位需求", "tool": "skill_demand",
         "args": {"top_k": 10}, "deps": [], "enabled": True},
        {"id": "n2", "type": "gate", "title": "样本量校验", "tool": "sample_gate",
         "args": {"min_jd": 200}, "deps": ["n1"], "enabled": True},
        {"id": "n3", "type": "tool", "title": "算技能值多少钱", "tool": "salary_premium",
         "args": {"top_n": 8, "count_floor": 25}, "deps": ["n2"], "enabled": True},
        # ② 学校在教什么
        {"id": "n4", "type": "tool", "title": "查本专业课程覆盖", "tool": "curriculum_coverage",
         "args": {}, "deps": [], "enabled": True},
        # ③ 我差在哪里
        {"id": "n5", "type": "tool", "title": "算我的命中率", "tool": "my_match",
         "args": {}, "deps": ["n1"], "enabled": True},
        {"id": "n6", "type": "tool", "title": "列我的待补技能", "tool": "my_gap",
         "args": {"limit": 10}, "deps": ["n4", "n5"], "enabled": True},
        # ④ 我先补哪个
        {"id": "n7", "type": "tool", "title": "排十二周补课顺序", "tool": "learn_order",
         "args": {"weeks": 12, "per_week": 1}, "deps": ["n6"], "enabled": True},
        {"id": "n8", "type": "tool", "title": "新说法语义归并", "tool": "semantic_merge",
         "args": {}, "deps": [], "enabled": True},
        # ⑤ 我接下来做什么
        {"id": "n9", "type": "compose", "title": "生成成长方案", "tool": "compose_report",
         "args": {}, "deps": ["n3", "n7", "n8"], "enabled": True},
    ],
}

# 工具清单：界面上给用户选，选完填参数
TOOL_SPEC = {
    "skill_demand": {"label": "岗位技能需求", "args": {"top_k": 10}},
    "sample_gate": {"label": "样本量校验（不足就停）", "args": {"min_jd": 200}},
    "salary_premium": {"label": "技能薪资溢价", "args": {"top_n": 8, "count_floor": 25}},
    "curriculum_coverage": {"label": "课程覆盖率", "args": {}},
    "my_match": {"label": "我的岗位命中率", "args": {}},
    "my_gap": {"label": "我的待补技能清单", "args": {"limit": 10}},
    "learn_order": {"label": "补课顺序（按周排）", "args": {"weeks": 12, "per_week": 1}},
    "gap_list": {"label": "课程缺口清单", "args": {"grade": "红", "limit": 10}},
    "new_terms": {"label": "未入典新词发现", "args": {"min_n": 8}},
    "semantic_merge": {"label": "新词语义归并（向量）", "args": {}},
    "llm_terms": {"label": "大模型技能抽取对照（可选）", "args": {"limit": 10}},
    "compose_report": {"label": "生成报告（成稿节点）", "args": {}},
}


def load_flow() -> dict:
    if FLOW.exists():
        try:
            flow = json.loads(FLOW.read_text(encoding="utf-8"))
            # 旧版本流程（没有 version 或版本更低）直接用新默认流程，避免旧会话把旧节点写回来
            if int(flow.get("version", 0)) >= FLOW_VERSION:
                return flow
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return json.loads(json.dumps(DEFAULT_FLOW))


def save_flow(flow: dict) -> None:
    FLOW.parent.mkdir(parents=True, exist_ok=True)
    FLOW.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 工具实现
def _demand(ctx: dict, top_k: int = 10) -> dict:
    d = analyze.demand(top_k=int(top_k), city=ctx.get("city", "全省"))
    if d.empty:
        return {"ok": False, "msg": "还没有技能数据，先去「技能标注」页跑一次抽取"}
    return {"ok": True, "n_jd": int(ctx.get("overview", {}).get("n") or len(analyze.jobs())),
            "table": d, "brief": "Top%d：%s" % (len(d), "、".join(d["skill"].head(4)))}


def _gate(ctx: dict, min_jd: int = 200) -> dict:
    n = len(analyze.jobs())
    if n < int(min_jd):
        return {"ok": False, "halt": True, "msg": f"有效岗位 {n} 条，低于门槛 {min_jd} 条，不出结论"}
    return {"ok": True, "msg": f"样本 {n} 条，通过（门槛 {min_jd}）"}


def _premium(ctx: dict, top_n: int = 8, count_floor: int = 25) -> dict:
    r = analyze.salary_premium(count_floor=int(count_floor), top_n=int(top_n), boot=60)
    if not r.get("ok"):
        return r
    t = r["table"]
    return {"ok": True, **r, "table": t,
            "brief": "R²=%.3f（无技能基线 %.3f），溢价最高：%s" % (
                r["r2"], r.get("r2_base", 0), "、".join(
                    f"{x.skill}{x.premium:+.1%}" for x in t.head(3).itertuples()))}


def _coverage(ctx: dict) -> dict:
    r = analyze.coverage(ctx.get("major"))
    if not r.get("ok"):
        return r
    return {"ok": True, **r, "brief": "加权覆盖率 %.1f%%，红 %d / 橙 %d" % (
        r["coverage"] * 100, r["red"], r["orange"])}


def _gaps(ctx: dict, grade: str = "红", limit: int = 10) -> dict:
    d = analyze.gap_list(grade=grade, limit=int(limit))
    if d.empty:
        return {"ok": False, "msg": f"没有「{grade}」级缺口"}
    return {"ok": True, "table": d, "brief": f"{grade}级缺口 {len(d)} 项：{d['skill'].head(4).tolist()}"}


def _lp(ctx: dict, top: int = 12) -> dict:
    """学生画像 → 学习路径。三个学生侧节点共用一次计算，不重复查库。"""
    if "_lp" in ctx:
        return ctx["_lp"]
    from core import pathway as PW
    have = [str(s).strip() for s in (ctx.get("have") or []) if str(s).strip()]
    fam = ctx.get("family") or "全部"
    ctx["_lp"] = PW.build_path(have, fam, int(top), major=ctx.get("major"))
    return ctx["_lp"]


def _my_match(ctx: dict, top: int = 12) -> dict:
    """算我的命中率：目标岗位族的技能需求里，我已经会的那部分占多少。"""
    r = _lp(ctx, top=int(top))
    if not r.get("ok"):
        return r
    m = float(r["match"])
    have_n = len([s for s in (ctx.get("have") or []) if str(s).strip()])
    if have_n == 0:
        tail = "还没勾已会技能，先去「③ 我的定位」勾一遍再跑本流程"
    elif m >= 0.70:
        tail = "已越过 70% 可投实习线，可以开始投递"
    else:
        tail = f"距 70% 可投实习线还差 {0.70 - m:.0%}"
    return {"ok": True, "table": r["table"], "match": m, "family": r.get("family"),
            "have_n": have_n, "gap_n": int(len(r["gap"])),
            "n_family": int(r.get("n_family", 0)),
            "brief": f"{r.get('family')} 方向命中率 {m:.0%}（已会 {have_n} 项），{tail}"}


def _my_gap(ctx: dict, limit: int = 10) -> dict:
    """列我的待补技能：只保留我还没会的，按岗位需求次数排序。"""
    r = _lp(ctx)
    if not r.get("ok"):
        return r
    gap = r["gap"]
    if gap.empty:
        return {"ok": True, "table": gap, "n_gap": 0,
                "brief": "目标岗位族要求的技能都已掌握，可以往下一个岗位族扩"}
    g = gap.head(int(limit)).reset_index(drop=True).copy()
    g["优先级"] = range(1, len(g) + 1)   # 待补清单按 1、2、3 重排，不沿用含已会技能的名次
    return {"ok": True, "table": g, "n_gap": int(len(gap)),
            "brief": f"还差 {len(gap)} 项，最该先补：{'、'.join(g['技能'].head(3))}"}


def _learn_order(ctx: dict, weeks: int = 12, per_week: int = 1) -> dict:
    """排补课顺序：把待补技能按需求强度排进周次，每项挂本专业课程。"""
    r = _lp(ctx)
    if not r.get("ok"):
        return r
    gap = r["gap"]
    if gap.empty:
        return {"ok": True, "table": gap, "brief": "没有待补技能，无需排课"}
    per_week = max(int(per_week), 1)
    g = gap.head(max(int(weeks), 1) * per_week).reset_index(drop=True)
    rows = []
    for i, row in enumerate(g.itertuples(), 1):
        rows.append({"周次": f"第 {(i - 1) // per_week + 1} 周", "顺序": i,
                     "技能": row.技能, "岗位数": int(row.岗位数),
                     "课程覆盖": float(row.课程覆盖), "从哪学": row.相关课程})
    table = pd.DataFrame(rows)
    return {"ok": True, "table": table, "weeks": int(weeks), "n": len(table),
            "brief": f"{weeks} 周排 {len(table)} 项：先「{table['技能'].iloc[0]}」，"
                     f"再「{table['技能'].iloc[-1]}」"}


def _new_terms(ctx: dict, min_n: int = 8) -> dict:
    d = SK.unknown_tags(min_n=int(min_n), limit=15)
    if d.empty:
        return {"ok": True, "table": d, "brief": "没有达到门槛的新词"}
    return {"ok": True, "table": d, "brief": "候选新标签 " + "、".join(d["tag"].head(5))}


def _semantic_merge(ctx: dict, threshold: float | None = None) -> dict:
    """语义层：把新词向量化，找最相近的已有技能。规则引擎认不出的写法在这里认。

    threshold 不填时按向量后端自动取默认（transformer 0.72 / tfidf 0.52）。
    """
    r = semantic.merge_unknown(threshold=threshold, limit=15)
    if not r.get("ok"):
        return r
    return r


def _llm_terms(ctx: dict, limit: int = 10) -> dict:
    """可选节点：大模型把新词映射到词典技能，与规则/向量通道做三方对照。

    没配 config/llm.json 时返回 ok=False，节点显示"未通过（跳过）"，主流程不受影响。
    """
    if not llm.available():
        return {"ok": False, "msg": "未配置大模型（缺 config/llm.json），节点自动跳过，"
                                    "规则 + 向量通道兜底，流程不受影响"}
    unk = SK.unknown_tags(min_n=1, limit=int(limit))
    if unk.empty:
        return {"ok": True, "mapping": {}, "brief": "没有待映射的新词"}
    known = [s for s in SK.load_dict()["canonical"].dropna().unique() if str(s).strip()]
    r = llm.map_terms(unk["tag"].astype(str).tolist(), known)
    if not r.get("ok"):
        return r
    mapped = {k: v for k, v in r["mapping"].items() if v}
    return {"ok": True, "mapping": r["mapping"], "model": r.get("model", ""),
            "brief": f"大模型({r.get('model', '')})映射 {len(mapped)}/{len(r['mapping'])} 个，"
                     f"结果仅作对照，采纳需人工确认"}


def _compose(ctx: dict, by_tool: dict) -> dict:
    """成稿节点：只用上游工具的真实结果拼文字，不编数字。

    按学生动线组织：市场要什么 → 值多少钱 → 学校教什么 → 我在哪 → 先补哪个。
    """
    major = ctx.get("major") or "本专业"
    ov = ctx.get("overview") or analyze.overview()
    dem = by_tool.get("skill_demand")
    prem = by_tool.get("salary_premium")
    cov = by_tool.get("curriculum_coverage")
    mm = by_tool.get("my_match")
    mg = by_tool.get("my_gap")
    lo = by_tool.get("learn_order")
    gapw = by_tool.get("gap_list")
    fam = (mm or {}).get("family") or ctx.get("family") or "全部"
    fam_disp = "不限方向" if fam in ("全部", "", None) else f"{fam}方向"
    L: list[str] = []
    L.append(f"# {major} · 技能成长方案\n")
    L.append(f"**数据口径**：{ov.get('n', 0)} 条公开岗位，覆盖 {ov.get('cities', 0)} 个城市，"
             f"发布时间 {ov.get('date_min', '-')} 至 {ov.get('date_max', '-')}；"
             f"薪资可解析率 {ov.get('salary_rate', 0):.1%}。岗位信息来自智联招聘等公开招聘页面，"
             f"不含任何求职者信息。\n")

    L.append("## 一、市场在要什么\n")
    if dem and dem.get("ok"):
        t = dem["table"].head(6)
        L.append("招聘方要求最多的六项技能：" + "、".join(
            f"**{r.skill}**（{r.n} 条 / 占 {r.share:.0%}）" for r in t.itertuples()) + "。\n")
        top = t.iloc[0]
        L.append(f"排第一的 {top['skill']} 出现在 {top['n']} 条岗位里，是这个方向的基础门槛，"
                 f"不是加分项。层级加权后需求强度为 {top['weight']:.0f}"
                 f"（权重 = 次数 × 岗位层级系数，高级岗位算得更重）。\n")
    else:
        L.append("_需求数据缺失，本节跳过。_\n")

    L.append("## 二、这些技能值多少钱\n")
    if prem and prem.get("ok"):
        t = prem["table"].head(5)
        L.append("控制城市、岗位族、企业规模、经验、学历、岗位层级之后，技能带来的月薪差异"
                 f"（5 折交叉验证 R²={prem['r2']:.3f}，不含技能的基线 {prem.get('r2_base', 0):.3f}，"
                 f"样本 {prem['n']} 条）：\n")
        L.append("| 技能 | 关联溢价 | 95% 区间 | 样本 |")
        L.append("|---|---|---|---|")
        for r in t.itertuples():
            star = "显著" if r.significant else "不显著"
            L.append(f"| {r.skill} | {r.premium:+.1%} | [{r.ci_low:+.1%}, {r.ci_high:+.1%}] {star} | {r.n} |")
        delta = prem["r2"] - prem.get("r2_base", 0)
        if delta > 0.005:
            note = (f"技能带来了一点增量（R² 从 {prem.get('r2_base', 0):.3f} 提到 {prem['r2']:.3f}），"
                    "但提升不大。")
        else:
            note = (f"加入技能后交叉验证 R² 几乎没有变化（{prem.get('r2_base', 0):.3f} → {prem['r2']:.3f}），"
                    "说明**月薪主要由岗位族和工作经验决定，技能只是其中一小部分**。"
                    "这不妨碍我们看系数——系数带置信区间，能说清「要求这项技能的岗位，给的区间在哪」，"
                    "但不能说模型因为加了技能就变准了。")
        L.append(f"\n{note}\n")
        L.append("\n这是关联性估计，不是因果。企业愿意为某个技能多付钱，也可能只是因为它和"
                 "更高薪的岗位绑在一起。要谈因果得用面板数据或自然实验，我们没这个条件，"
                 "所以只说到「相关」为止。\n")
    else:
        L.append("_薪资样本不足，按规则拒答。_\n")

    L.append("## 三、学校教了什么\n")
    if cov and cov.get("ok"):
        L.append(f"按「0.6×需求分位 + 0.4×溢价分位」加权，本专业课程（"
                 f"{cov.get('major', ctx.get('major', '本专业'))}，{cov.get('n_courses', 0)} 门）"
                 f"的技能覆盖率为 **{cov['coverage']:.1%}**；红色缺口 {cov['red']} 项，"
                 f"橙色 {cov['orange']} 项。课程依据《职业教育专业教学标准》。\n")
        if gapw and gapw.get("ok"):
            L.append("| 缺口技能 | 岗位数 | 现有覆盖 | 需求权重 |")
            L.append("|---|---|---|---|")
            for r in gapw["table"].head(8).itertuples():
                L.append(f"| {r.skill} | {r.岗位数} | {r.现有覆盖:.1f} | {r.需求权重:.2f} |")
            L.append("")
    else:
        L.append("_覆盖率算不出来：先确认本专业的课程—技能映射表已生成。_\n")

    L.append("## 四、我现在到哪\n")
    if mm and mm.get("ok"):
        m = float(mm["match"])
        bar = "✅ 已越过 70% 可投实习线" if m >= 0.70 else f"⏳ 距 70% 可投实习线还差 {0.70 - m:.0%}"
        L.append(f"目标岗位族「{fam_disp}」共 {mm.get('n_family', 0)} 条岗位样本，"
                 f"你的技能命中率是 **{m:.0%}**，{bar}。\n")
        L.append(f"已勾选已会技能 {mm.get('have_n', 0)} 项；"
                 f"对照岗位要求，还有 **{mm.get('gap_n', 0)} 项待补**。\n")
        if mg and mg.get("ok") and len(mg["table"]):
            L.append("排在最前面的待补技能（按岗位要求次数）：\n")
            L.append("| 顺序 | 技能 | 岗位数 | 课程覆盖 | 从哪学 |")
            L.append("|---|---|---|---|---|")
            for r in mg["table"].head(6).itertuples():
                L.append(f"| {r.优先级} | {r.技能} | {r.岗位数} | {r.课程覆盖:.0%} | {r.相关课程} |")
            L.append("")
    else:
        L.append("_还没有学生画像：先去「③ 我的定位」勾上已会技能、选好目标岗位族，"
                 "再跑本流程，命中率与待补清单才会出现。_\n")

    L.append("## 五、接下来怎么补\n")
    if lo and lo.get("ok") and len(lo["table"]):
        L.append(f"按岗位需求强度排进 {lo.get('weeks', 12)} 周，每周一项，先做会被反复要求的那几个：\n")
        L.append("| 周次 | 技能 | 岗位数 | 课程覆盖 | 从哪学 |")
        L.append("|---|---|---|---|---|")
        for r in lo["table"].itertuples():
            L.append(f"| {r.周次} | {r.技能} | {r.岗位数} | {r.课程覆盖:.0%} | {r.从哪学} |")
    else:
        L.append("_待补清单为空或路径未生成，先去「④ 差距路径」生成一次。_\n")

    L.append("## 六、适用范围与阅读提示\n")
    L.append(f"- 样本 {ov.get('n', 0)} 条，反映的是采集时间窗内的公开岗位情况，为结论划定了清晰的观察范围；")
    L.append("- 岗位池以人工智能与数据类方向为主，其他专业方向的命中率会被低估，横向比较请以同岗位族为准；")
    L.append("- 技能识别采用平台标签 + 词典归一，个别标签暂未入典，相关需求可能被适度低估，可结合「新词发现」互补参考；")
    L.append("- 薪资为招聘方标价口径，与实际水平存在自然差异，报告统一采用中位数呈现，结论更为稳健；")
    L.append("- 课程覆盖度依据《职业教育专业教学标准》的课程—技能映射判定（1.0 独立教学单元 / 0.5 涉及支撑），每格保留标准条款证据，可逐条复核。")
    return {"ok": True, "report": "\n".join(L), "brief": f"方案 {len(L)} 段"}


IMPL = {
    "skill_demand": _demand, "sample_gate": _gate, "salary_premium": _premium,
    "curriculum_coverage": _coverage, "my_match": _my_match, "my_gap": _my_gap,
    "learn_order": _learn_order, "gap_list": _gaps, "new_terms": _new_terms,
    "semantic_merge": _semantic_merge, "llm_terms": _llm_terms,
}


# ---------------------------------------------------------------- 执行
def topo(flow: dict) -> list[str]:
    nodes = {n["id"]: n for n in flow["nodes"] if n.get("enabled", True)}
    order, seen = [], set()

    def visit(nid, stack):
        if nid in seen:
            return
        if nid in stack:
            raise ValueError(f"流程里有环：{' -> '.join(stack + [nid])}")
        for d in nodes.get(nid, {}).get("deps", []):
            if d in nodes:
                visit(d, stack + [nid])
        seen.add(nid)
        order.append(nid)

    for nid in nodes:
        visit(nid, [])
    return order


def run(flow: dict, ctx: dict | None = None, on_node=None) -> dict:
    ctx = dict(ctx or {})
    ctx.setdefault("major", flow.get("major", "人工智能技术应用"))
    ctx.setdefault("city", flow.get("city", "全省"))
    ctx["flow_name"] = flow.get("name")
    ctx.setdefault("overview", analyze.overview())
    nodes = {n["id"]: n for n in flow["nodes"]}
    state, by_tool, trace = {}, {}, []
    halted = False
    for nid in topo(flow):
        n = nodes[nid]
        t0 = time.perf_counter()
        row = {"节点": n["title"], "工具": TOOL_SPEC.get(n["tool"], {}).get("label", n["tool"]),
               "状态": "ok", "耗时ms": 0, "摘要": ""}
        if halted:
            row.update({"状态": "跳过", "摘要": "上游校验未通过"})
        else:
            try:
                if n["type"] == "compose":
                    res = _compose(ctx, by_tool)
                else:
                    fn = IMPL.get(n["tool"])
                    if fn is None:
                        raise KeyError(f"没有这个工具：{n['tool']}")
                    res = fn(ctx, **(n.get("args") or {}))
                state[nid] = res
                if res.get("ok"):
                    by_tool[n["tool"]] = res
                else:
                    row["状态"] = "未通过"
                if res.get("halt"):
                    halted = True
                row["摘要"] = res.get("brief") or res.get("msg") or ""
            except Exception as e:  # 单个节点出错不炸整个流程
                row.update({"状态": "报错", "摘要": f"{type(e).__name__}: {e}"})
                traceback.print_exc()
        row["耗时ms"] = int((time.perf_counter() - t0) * 1000)
        row["id"] = nid
        trace.append(row)
        if on_node:
            on_node(nid, row)
    report = (state.get([n["id"] for n in flow["nodes"] if n["type"] == "compose"][0], {})
              .get("report") if any(n["type"] == "compose" for n in flow["nodes"]) else None)
    return {"trace": trace, "state": state, "report": report,
            "halted": halted, "elapsed": round(sum(r["耗时ms"] for r in trace) / 1000, 2)}


# ---------------------------------------------------------------- 画图
TYPE_COLOR = {"tool": "#6c9bd1", "gate": "#d97706", "compose": "#059669"}
STATE_COLOR = {"pending": "#cbd5e1", "running": "#f59e0b", "ok": "#16a34a",
               "fail": "#dc2626", "error": "#dc2626", "skip": "#94a3b8"}


def svg(flow: dict, status: dict | None = None, selected: str | None = None) -> str:
    """把流程画成横向流程图。status: {node_id: 'ok'|'running'|...}"""
    status = status or {}
    nodes = [n for n in flow["nodes"] if n.get("enabled", True)]
    ids = [n["id"] for n in nodes]
    nmap = {n["id"]: n for n in nodes}
    depth: dict[str, int] = {}

    def dep(nid):
        return [d for d in nmap[nid].get("deps", []) if d in nmap and d != nid]

    def calc(nid, stack=frozenset()):
        if nid in depth:
            return depth[nid]
        if nid in stack:          # 防环：配置被改出环时画布不爆栈，按 0 层画
            return 0
        ds = dep(nid)
        depth[nid] = 0 if not ds else 1 + max(calc(x, stack | {nid}) for x in ds)
        return depth[nid]

    for n in nodes:
        calc(n["id"])
    cols: dict[int, list] = {}
    for n in nodes:
        cols.setdefault(depth[n["id"]], []).append(n)

    W, H, GX, GY, PAD = 300, 130, 80, 44, 26
    maxrow = max(len(v) for v in cols.values()) if cols else 1
    width = PAD * 2 + (max(cols) + 1) * W + max(cols) * GX if cols else 400
    height = PAD * 2 + maxrow * H + (maxrow - 1) * GY
    pos = {}
    for d, group in cols.items():
        for i, n in enumerate(group):
            pos[n["id"]] = (PAD + d * (W + GX), PAD + i * (H + GY) + (maxrow - len(group)) * (H + GY) / 2)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;'
             f'background:#fff;border-radius:10px">',
             '<defs><marker id="ah" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">'
             '<path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker></defs>']
    for n in nodes:
        x1, y1 = pos[n["id"]]
        for d in dep(n["id"]):
            x0, y0 = pos[d]
            sx, sy = x0 + W, y0 + H / 2
            tx, ty = x1, y1 + H / 2
            mx = (sx + tx) / 2
            parts.append(f'<path d="M{sx},{sy} C{mx},{sy} {mx},{ty} {tx-6},{ty}" fill="none" '
                         f'stroke="#94a3b8" stroke-width="2.6" marker-end="url(#ah)"/>')
    for n in nodes:
        x, y = pos[n["id"]]
        st_ = status.get(n["id"], "pending")
        border = STATE_COLOR.get(st_, "#cbd5e1")
        sel = "3" if selected == n["id"] else "1.6"
        fill = "#f8fafc" if st_ in ("pending", "skip") else "#ffffff"
        parts.append(f'<g><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="14" fill="{fill}" '
                     f'stroke="{border}" stroke-width="{sel}"/>'
                     f'<rect x="{x}" y="{y}" width="8" height="{H}" rx="4" fill="{TYPE_COLOR.get(n["type"], "#64748b")}"/>'
                     f'<text x="{x+24}" y="{y+52}" font-size="24" font-weight="600" fill="#0f172a" '
                     f'font-family="system-ui,Microsoft YaHei">{_cut(n["title"], 11)}</text>'
                     f'<text x="{x+24}" y="{y+92}" font-size="18" fill="#64748b" '
                     f'font-family="system-ui,Microsoft YaHei">{_cut(TOOL_SPEC.get(n["tool"], {}).get("label", n["tool"]), 14)}</text>'
                     f'<circle cx="{x+W-22}" cy="{y+24}" r="7" fill="{border}"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def _cut(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"
