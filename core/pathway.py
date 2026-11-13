"""学习路径：学生画像 → 目标岗位族 → 差距技能 → 补课顺序。

输入：学生已会的技能（勾选）+ 目标岗位族（算法/数据分析/后端…）。
输出：按岗位需求排序的差距清单，每项带相关课程与覆盖情况，可直接当补课清单用。

复用既有分析层，不引入新的模型——岗位需求次数就是优先级，
课程来自 course_skill_map.csv，按学生所选专业过滤（《职业教育专业教学标准》课程），口径与看板完全一致。
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from core import analyze, skills as SK

MAP_CSV = analyze.MAP_CSV


def families() -> list[str]:
    """岗位族清单（分析层 FAMILY_RULES 的顺序，末尾加"全部"）。"""
    return ["全部"] + [name for name, _ in analyze.FAMILY_RULES] + ["其他"]


def all_skills() -> list[str]:
    """可选技能 = 词典标准技能（按热门度排），学生从这里勾"已会"。"""
    df = SK.load_dict()
    return df.sort_values("popularity", ascending=False)["canonical"].dropna().unique().tolist()


def demand_of_family(family: str = "全部", top: int = 15) -> pd.DataFrame:
    """某岗位族的技能需求榜：skill, n（岗位数）, share（占该族岗位比例）。

    "全部" 走技术岗口径（与 ① 市场全景一致）；
    具体岗位族按族取全库岗位——会计、销售、护理这些族没有技术岗，
    只查技术岗会算成 0，学生选了方向却看不到数据。
    """
    j = analyze.jobs() if family in ("全部", "") else analyze.jobs(all_rows=True)
    if j.empty:
        return pd.DataFrame()
    if family not in ("全部", ""):
        j = j[j["family"] == family]
    if j.empty:
        return pd.DataFrame()
    ids = set(j["jd_id"])
    c = sqlite3.connect(SK.DB)
    js = pd.read_sql("SELECT jd_id, skill FROM job_skill", c)
    c.close()
    js = js[js["jd_id"].isin(ids)]
    if js.empty:
        return pd.DataFrame()
    g = js.groupby("skill").size().reset_index(name="n").sort_values("n", ascending=False)
    g["share"] = g["n"] / max(len(ids), 1)
    return g.head(int(top)).reset_index(drop=True)


def family_size(family: str = "全部") -> int:
    """某岗位族的岗位数（全库口径，用于提示"样本偏少"）。"""
    j = analyze.jobs(all_rows=True)
    if j.empty:
        return 0
    if family in ("全部", ""):
        return int(len(analyze.jobs()))
    return int((j["family"] == family).sum())


def _major_map(major: str | None) -> pd.DataFrame:
    """按专业过滤后的课程映射表。"""
    mp = pd.read_csv(MAP_CSV, encoding="utf-8-sig")
    if "major_code" not in mp.columns:
        return mp
    from core import majors as MJ
    code = MJ.code_of(major)
    if not code:
        return mp
    return mp[mp["major_code"].astype(str) == str(code)]


def course_map(major: str | None = None) -> dict[str, str]:
    """skill → 关联课程名（顿号连接）。"""
    try:
        mp = _major_map(major)
        s = mp.groupby("skill")["course_name"].apply(
            lambda x: "、".join(sorted(set(x.dropna().astype(str)))))
        return s.to_dict()
    except Exception:
        return {}


def cover_map(major: str | None = None) -> dict[str, float]:
    """skill → 课程覆盖度（0~1，同一技能取多门课最高分）。"""
    try:
        mp = _major_map(major)
        return mp.groupby("skill")["score"].max().round(2).to_dict()
    except Exception:
        return {}


def build_path(have: list[str], family: str = "全部", top: int = 12,
               demand_df: pd.DataFrame | None = None,
               major: str | None = None) -> dict:
    """生成学习路径。

    have        已掌握技能（与词典标准名一致）
    family      目标岗位族；"全部" 表示不限岗位族
    top         目标技能取前多少项
    demand_df   预算好的需求榜（页面缓存传入，避免每次重算）
    major       学生专业（专业名或代码），决定"相关课程 / 课程覆盖"取哪个专业的课程表
    返回 {ok, target, gap, table, match, n_family, brief}
    table 列：优先级 | 技能 | 岗位数 | 占比 | 已掌握 | 课程覆盖 | 相关课程
    """
    dem = demand_df if demand_df is not None else demand_of_family(family, top)
    if dem is None or dem.empty:
        return {"ok": False, "msg": "该岗位族还没有技能数据，先采集并跑一次技能标注"}
    have_set = {str(s).strip() for s in (have or []) if str(s).strip()}
    cmap, covm = course_map(major), cover_map(major)

    rows = []
    for i, r in enumerate(dem.itertuples(), 1):
        held = r.skill in have_set
        rows.append({
            "优先级": i, "技能": r.skill, "岗位数": int(r.n), "占比": float(r.share),
            "已掌握": held, "课程覆盖": float(covm.get(r.skill, 0.0)),
            "相关课程": cmap.get(r.skill, "") or "本专业暂无对应课程",
        })
    table = pd.DataFrame(rows)
    target_total = table["岗位数"].sum()
    held_cover = table.loc[table["已掌握"], "岗位数"].sum()
    match = held_cover / target_total if target_total else 0.0
    gap = table[~table["已掌握"]].reset_index(drop=True)
    brief = (f"目标 {family}：岗位需求命中率 {match:.0%}，"
             f"还差 {len(gap)} 项，最先补「{gap['技能'].iloc[0] if len(gap) else '—'}」")
    from core import majors as MJ
    return {"ok": True, "table": table, "gap": gap, "match": float(match),
            "n_family": int(target_total), "brief": brief, "family": family,
            "major": MJ.name_of(major), "major_code": MJ.code_of(major)}


def to_markdown(have: list[str], family: str, res: dict) -> str:
    """把路径结果导出成 Markdown（页面下载按钮用）。"""
    if not res.get("ok"):
        return res.get("msg", "没有可导出的结果")
    L = [f"# 个人学习路径（专业：{res.get('major', '')} · 目标：{family}）\n"]
    L.append(f"**已掌握**：{'、'.join(have) if have else '（未勾选）'}")
    L.append(f"**岗位需求命中率**：{res['match']:.0%}\n")
    L.append("| 优先级 | 技能 | 岗位数 | 占比 | 课程覆盖 | 相关课程 |")
    L.append("|---|---|---|---|---|---|")
    for r in res["gap"].itertuples():
        L.append(f"| {r.优先级} | {r.技能} | {r.岗位数} | {r.占比:.0%} | "
                 f"{r.课程覆盖:.0%} | {r.相关课程} |")
    L.append("\n> 优先级 = 该技能在目标岗位族里被要求的次数排名；"
             "课程覆盖来自《职业教育专业教学标准》课程—技能映射表，按本专业口径计算。")
    return "\n".join(L)
