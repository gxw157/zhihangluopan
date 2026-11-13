"""分析：需求、共现、薪资溢价、课程覆盖与缺口。

所有函数只读数据库，返回 DataFrame / dict，界面层不做计算。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jobs.db"
MAP_CSV = ROOT / "data" / "dict" / "course_skill_map.csv"

EDU_ORD = {"不限": 0, "初中": 1, "中专": 1, "中技": 1, "高中": 2, "大专": 3, "本科": 4, "硕士": 5, "博士": 6}
EXP_ORD = {"经验不限": 0, "无经验": 0, "应届": 0, "1年以下": 1, "1-3年": 2, "3-5年": 3, "5-10年": 4, "10年以上": 5}

from core.skills import is_tech  # noqa: E402  （岗位相关性粗筛，逻辑放在 skills 里）

# 岗位族：薪资差异很大，不控制它，"技能溢价"会把岗位差异算到技能头上。
# 分类顺序 = 命中优先级：越具体越靠前；「后端」只留 开发/工程师/研发 这类兜底词，
# 所以必须排在最后——否则「销售工程师」「机械工程师」会被它一口吞掉。
# 前半段是电子与信息大类（技术岗口径），后半段是各行各业（财经商贸、装备制造、
# 医药卫生、土木建筑、教育、旅游、文化艺术……），②方向 / ③目标岗位族 直接取这份清单。
FAMILY_RULES = [
    # ---- 电子与信息（技术岗）
    ("算法", ("算法", "机器学习", "深度学习", "人工智能", "AI", "大模型", "NLP", "视觉")),
    ("数据开发", ("数据开发", "大数据", "数仓", "数据仓库", "ETL", "BI")),
    ("数据分析", ("数据分析", "商业分析", "数据运营")),
    ("标注", ("标注",)),
    ("前端", ("前端", "web", "H5", "小程序")),
    ("测试", ("测试",)),
    ("运维", ("运维", "技术支持", "实施", "网络")),
    # ---- 财经商贸
    ("财务", ("会计", "财务", "出纳", "审计", "税务", "总账", "成本核算", "资金")),
    ("销售", ("销售", "业务员", "BD", "渠道", "大客户", "招商", "客户经理", "业务经理", "地推")),
    ("市场", ("市场", "品牌", "营销", "推广", "策划", "公关")),
    ("电商运营", ("电商", "网店", "店铺运营", "淘宝", "拼多多", "京东运营", "跨境电商", "独立站")),
    ("新媒体", ("新媒体", "直播", "短视频", "内容运营", "公众号", "视频号", "社媒", "文案")),
    ("客服", ("客服", "呼叫中心", "售后", "客诉")),
    ("人力", ("人力资源", "人事", "HR", "招聘", "薪酬", "绩效", "员工关系")),
    ("行政", ("行政", "前台", "文员", "秘书", "助理", "后勤", "档案")),
    ("物流外贸", ("物流", "仓储", "供应链", "采购", "外贸", "关务", "货运", "单证", "跟单")),
    # ---- 装备制造 / 土木建筑
    ("质量", ("质检", "质量管理", "QA", "QC", "审核员", "计量", "品控")),
    ("机械", ("机械", "模具", "夹具", "数控", "机加工", "工艺", "设备维护", "设备工程", "焊接")),
    ("电气自动化", ("电气", "自动化", "PLC", "机器人", "仪表", "硬件", "电子工程", "嵌入式")),
    ("汽车", ("汽车", "汽修", "4S", "整车", "三电")),
    ("建筑", ("建筑", "施工", "土木", "造价", "监理", "装修", "家装", "给排水", "幕墙", "市政")),
    # ---- 医药卫生 / 教育 / 旅游 / 文化艺术 / 农林
    ("医药", ("医药", "药品", "药店", "药师", "临床", "医疗器械", "注册专员", "制药")),
    ("护理", ("护理", "护士", "护师", "康复", "养老")),
    ("医学检验", ("医学检验", "化验", "病理", "检验科技")),
    ("教育", ("教师", "讲师", "助教", "教务", "课程顾问", "培训师", "幼教", "学前", "辅导")),
    ("旅游酒店", ("旅游", "酒店", "前厅", "客房", "餐饮", "导游", "民宿", "景区")),
    ("视觉设计", ("平面", "视觉", "美工", "UI", "插画", "包装设计", "电商设计", "摄影")),
    ("产品", ("产品经理", "产品专员", "产品运营", "需求分析")),
    ("项目", ("项目经理", "项目管理", "PMO", "实施顾问")),
    ("生产制造", ("生产", "车间", "班组长", "操作工", "储备干部", "计划员", "厂长")),
    ("农牧食品", ("养殖", "畜牧", "兽医", "种植", "农业", "园艺", "食品", "饮料", "烘焙")),
    ("化工环保", ("化工", "环保", "污水处理", "材料", "化验员")),
    # ---- 兜底：技术岗里剩下的「XX开发 / XX工程师 / 研发」
    ("后端", ("后端", "开发", "工程师", "研发", "程序员")),
]
SIZE_ORD = {"20人以下": 1, "20-99": 2, "100-299": 3, "300-499": 4, "500-999": 5,
            "1000-9999": 6, "10000": 7}


def family_of(title: str) -> str:
    t = str(title or "")
    for name, kws in FAMILY_RULES:
        if any(k in t for k in kws):
            return name
    return "其他"


def size_ord(s: str) -> int:
    s = str(s or "")
    for k, v in SIZE_ORD.items():
        if k in s:
            return v
    return 0


def _conn():
    return sqlite3.connect(DB)


def jobs(all_rows: bool = False) -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM jobs", _conn())
    if df.empty:
        return df
    df["edu_ord"] = df["edu"].fillna("不限").map(lambda x: _ord(x, EDU_ORD))
    df["exp_ord"] = df["exp"].fillna("经验不限").map(lambda x: _ord(x, EXP_ORD))
    df["job_level"] = df["job_level"].fillna(2).astype(int)
    df["family"] = df["title"].map(family_of)
    df["size_ord"] = df["company_size"].map(size_ord)
    df["is_tech"] = df["title"].map(is_tech)
    return df if all_rows else df[df["is_tech"]].copy()


def _ord(x: str, table: dict) -> int:
    x = str(x)
    for k, v in table.items():
        if k in x:
            return v
    return 0


def long_table(fams=None) -> pd.DataFrame:
    """技能×岗位长表。

    fams=None → 技术岗全局口径（旧口径，①「全部」与溢价模型用）；
    fams=岗位族列表 → 只取这些族里的岗位（全库，含非技术岗）及其全部技能标注。
    """
    j = jobs(all_rows=True) if fams else jobs()
    if fams:
        j = j[j["family"].isin(fams)]
    cols = ["jd_id", "city", "salary_mid", "edu", "exp", "job_level", "title"]
    if j.empty:
        return pd.DataFrame(columns=cols)
    sql = "SELECT jd_id, skill, raw_tag FROM job_skill"
    if not fams:
        sql += " WHERE is_tech=1"
    s = pd.read_sql(sql, _conn())
    return s.merge(j[cols], on="jd_id", how="inner")


def market_overview(fams=None) -> dict:
    """① 市场全景 KPI 口径。

    fams=None → 技术岗全局（与 overview() 同口径）；fams 给了 → 按岗位族取
    全库岗位（会计、护理这些族的岗位都在非技术岗里，必须用全库才数得到）。
    """
    if not fams:
        ov = overview()
        ov["fams"] = []
        return ov
    j = jobs(all_rows=True)
    j = j[j["family"].isin(fams)]
    if j.empty:
        return {"n": 0, "total": len(jobs(all_rows=True)), "fams": list(fams)}
    return {
        "n": len(j), "total": len(jobs(all_rows=True)), "fams": list(fams),
        "cities": j["city"].nunique(), "companies": j["company"].nunique(),
        "median": float(j["salary_mid"].median()),
        "salary_ok": int(j["salary_mid"].notna().sum()),
        "salary_rate": round(j["salary_mid"].notna().mean(), 3),
        "date_min": str(j["publish_date"].replace("", np.nan).dropna().min())[:10],
        "date_max": str(j["publish_date"].replace("", np.nan).dropna().max())[:10],
        "sources": j["source"].value_counts().to_dict(),
    }


def overview() -> dict:
    j = jobs()
    allj = jobs(all_rows=True)
    if j.empty:
        return {"n": 0, "total": len(allj)}
    return {
        "n": len(j),
        "total": len(allj),
        "cities": j["city"].nunique(),
        "companies": j["company"].nunique(),
        "skills": int(pd.read_sql("SELECT COUNT(DISTINCT skill) c FROM job_skill WHERE is_tech=1",
                                  _conn())["c"][0]),
        "salary_ok": int(j["salary_mid"].notna().sum()),
        "salary_rate": round(j["salary_mid"].notna().mean(), 3),
        "median": float(j["salary_mid"].median()),
        "date_min": str(j["publish_date"].replace("", np.nan).dropna().min())[:10],
        "date_max": str(j["publish_date"].replace("", np.nan).dropna().max())[:10],
        "sources": j["source"].value_counts().to_dict(),
    }


def demand(top_k: int = 20, city: str | None = None) -> pd.DataFrame:
    """技术岗口径的技能需求榜（① 市场全景专用；非技术岗见 demand_of_families）。"""
    sql = """SELECT s.skill, COUNT(*) n, AVG(j.salary_mid) sal, AVG(j.job_level) lvl
             FROM job_skill s JOIN jobs j ON j.jd_id=s.jd_id
             WHERE s.is_tech=1 """
    params: list = []
    if city and city != "全省":
        sql += " AND j.city=? "
        params.append(city)
    sql += " GROUP BY s.skill ORDER BY n DESC LIMIT ?"
    df = pd.read_sql(sql, _conn(), params=params + [top_k])
    if df.empty:
        return df
    total = len(jobs())
    df["share"] = (df["n"] / max(total, 1)).round(3)
    df["sal"] = df["sal"].round(0)
    df["lvl"] = df["lvl"].round(2)
    # 层级加权需求：高级岗位里的出现次数权重更高，避免"了解 Python"和"精通 Python"混在一起
    df["weight"] = (df["n"] * (0.6 + 0.2 * df["lvl"])).round(1)
    return df


def demand_of_families(fams: list[str], top_k: int = 200) -> pd.DataFrame:
    """指定岗位族子集的需求榜（口径同 demand，供"只看本专业相关岗位"使用）。

    给了岗位族就按族取全库岗位：会计、销售、护理这些族本来就没有技术岗，
    只用技术岗会算成 0；给了电子信息类的族时，结果与「技术岗口径」完全一致。
    """
    j = jobs(all_rows=True) if fams else jobs()
    if fams:
        j = j[j["family"].isin(fams)]
    if j.empty:
        return pd.DataFrame()
    ids = set(j["jd_id"])
    c = _conn()
    js = pd.read_sql("SELECT jd_id, skill FROM job_skill", c)
    c.close()
    js = js[js["jd_id"].isin(ids)]
    if js.empty:
        return pd.DataFrame()
    d = (js.groupby("skill").size().reset_index(name="n")
         .sort_values("n", ascending=False).head(int(top_k)).reset_index(drop=True))
    d["share"] = (d["n"] / max(len(ids), 1)).round(3)
    return d


def demand_trend(top_k: int = 8, months: int = 12, min_jobs: int = 30, fams=None) -> dict:
    """近 N 个月技能需求变化：按岗位发布时间分月，算每项技能的岗位占比。

    用于回答"这个技能是变热还是变冷"——比例而非条数，避免采集量波动干扰。
    只保留月岗位数 >= min_jobs 的月份：采集量太少的月份算比例没有意义，
    不足两个月时如实返回 ok=False，页面提示"持续采集后趋势会自动变长"。
    fams 给了就只在这些岗位族里算（专业相关口径）。
    """
    j = jobs() if not fams else jobs(all_rows=True)
    if fams:
        j = j[j["family"].isin(fams)]
    if j.empty:
        return {"ok": False, "msg": "还没有岗位数据"}
    d = j.copy()
    d["month"] = d["publish_date"].astype(str).str[:7]
    d = d[d["month"].str.match(r"^\d{4}-\d{2}$", na=False)]
    if d.empty:
        return {"ok": False, "msg": "岗位发布时间缺失，算不出趋势"}
    ms = sorted(d["month"].unique())[-int(months):]
    d = d[d["month"].isin(ms)]
    ids = set(d["jd_id"])
    c = _conn()
    js = pd.read_sql("SELECT jd_id, skill FROM job_skill", c)
    c.close()
    js = js[js["jd_id"].isin(ids)].merge(d[["jd_id", "month"]], on="jd_id")
    tops = (demand_of_families(list(fams), top_k=top_k)["skill"].tolist()
            if fams and not js.empty else
            demand(top_k=top_k)["skill"].tolist() if not js.empty else [])
    if not tops:
        return {"ok": False, "msg": "还没有技能标注结果"}
    base_all = d.groupby("month")["jd_id"].nunique().reindex(ms, fill_value=0)
    keep = [m for m in ms if int(base_all.get(m, 0)) >= int(min_jobs)]
    if len(keep) < 2:
        return {"ok": False, "n_jobs": base_all.astype(int).to_dict(),
                "msg": f"岗位发布时间集中在近 {len(keep)} 个月，月样本不足 {min_jobs} 条，"
                       "暂时看不出跨月趋势；持续采集后这里会自动变长"}
    g = (js[js["skill"].isin(tops) & js["month"].isin(keep)]
         .groupby(["month", "skill"]).size().unstack(fill_value=0))
    g = g.reindex(index=keep, columns=tops, fill_value=0)
    base = base_all.reindex(keep, fill_value=0)
    share = g.div(base.replace(0, np.nan), axis=0).fillna(0)
    delta = (share.iloc[-1] - share.iloc[-2]).sort_values(ascending=False) if len(keep) >= 2 else {}
    return {"ok": True, "months": keep, "skills": tops, "share": share.round(3),
            "n_jobs": base.astype(int).to_dict(),
            "delta": {k: round(float(v), 3) for k, v in delta.items()},
            "note": ("数据集中在最近两个月，曲线只反映短期波动，不代表长期趋势"
                     if len(keep) < 4 else "")}


def pmi_edges(min_n: int = 15, top_k: int = 30, fams=None) -> pd.DataFrame:
    lt = long_table(fams)
    if lt.empty:
        return pd.DataFrame()
    m = pd.crosstab(lt["jd_id"], lt["skill"]).astype(bool).astype(int)
    keep = m.sum()[m.sum() >= min_n].index
    m = m[keep]
    if m.shape[1] < 2:
        return pd.DataFrame()
    n = len(m)
    p = m.mean()
    co = (m.T @ m) / n
    rows = []
    cols = list(m.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            c = co.loc[a, b]
            if c * n < min_n:
                continue
            pmi = np.log(c / (p[a] * p[b])) if c > 0 else 0
            if pmi > 0:
                rows.append({"a": a, "b": b, "pmi": round(float(pmi), 3), "n": int(c * n)})
    df = pd.DataFrame(rows)
    return df.sort_values("pmi", ascending=False).head(top_k) if not df.empty else df


def salary_premium(count_floor: int = 25, top_n: int = 12, boot: int = 80, fams=None) -> dict:
    """控制城市/经验/学历/岗位层级之后，各技能的关联性薪资溢价。

    模型：log(月薪中位数) ~ 技能 multi-hot + 城市 + 经验 + 学历 + 岗位层级，Ridge。
    溢价 = exp(系数) - 1。这是关联估计，不是因果效应。
    fams 给了就只在这些岗位族内回归（专业相关口径），count_floor 也要相应调小。
    """
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import cross_val_score

    j = jobs() if not fams else jobs(all_rows=True)
    if fams:
        j = j[j["family"].isin(fams)]
    lt = long_table(fams)
    if j.empty or lt.empty:
        return {"ok": False, "msg": "没有可用数据"}
    d = j[j["salary_mid"].notna()].copy()
    if len(d) < 80:
        return {"ok": False, "msg": f"可解析薪资的岗位只有 {len(d)} 条，样本太少，不出结论"}
    cnt = lt["skill"].value_counts()
    skills = [s for s in cnt[cnt >= count_floor].index][:60]
    if not skills:
        return {"ok": False, "msg": f"没有技能出现次数达到 {count_floor} 条"}

    S = pd.crosstab(lt["jd_id"], lt["skill"]).reindex(columns=skills, fill_value=0).clip(0, 1)
    X = d[["jd_id", "city", "family", "size_ord", "exp_ord", "edu_ord", "job_level"]].merge(
        S, left_on="jd_id", right_index=True, how="left").fillna(0)
    y = np.log(d.set_index("jd_id").loc[X["jd_id"], "salary_mid"].astype(float).to_numpy())
    X = pd.get_dummies(X.drop(columns=["jd_id"]), columns=["city", "family"],
                       drop_first=True, dtype=float)

    base = Ridge(alpha=10.0)
    r2 = float(np.mean(cross_val_score(base, X, y, cv=5, scoring="r2")))
    # 不含技能的基线：用来回答"技能到底解释了多少"，比单看 R² 有意义
    ctrl = [c for c in X.columns if c not in skills]
    r2_base = float(np.mean(cross_val_score(Ridge(alpha=10.0), X[ctrl], y, cv=5, scoring="r2")))
    base.fit(X, y)
    coef = pd.Series(base.coef_, index=X.columns)

    rng = np.random.default_rng(20261101)
    boot_coef = []
    for _ in range(boot):
        idx = rng.integers(0, len(X), len(X))
        m = Ridge(alpha=10.0).fit(X.iloc[idx], y[idx])
        boot_coef.append(pd.Series(m.coef_, index=X.columns))
    B = pd.DataFrame(boot_coef)

    rows = []
    for s in skills:
        if s not in coef.index:
            continue
        lo, hi = np.percentile(B[s], [2.5, 97.5])
        rows.append({
            "skill": s, "premium": round(float(np.expm1(coef[s])), 4),
            "ci_low": round(float(np.expm1(lo)), 4), "ci_high": round(float(np.expm1(hi)), 4),
            "n": int(cnt[s]),
        })
    out = pd.DataFrame(rows).sort_values("premium", ascending=False)
    out["significant"] = (out["ci_low"] > 0) | (out["ci_high"] < 0)
    return {"ok": True, "r2": round(r2, 4), "r2_base": round(r2_base, 4), "n": len(d), "alpha": 10.0,
            "table": out.head(top_n), "full": out, "features": X.shape[1]}


def coverage(major: str | None = None, scope: str = "全部") -> dict:
    """加权课程覆盖率（按专业口径）。

    major 传专业名或专业代码；为空时用 majors.json 里的默认专业。
    scope = "全部" 用整个岗位池；"专业相关" 只用该专业对应的岗位族子集
           （majors.json 的 families 字段）——避免"课程表偏 AI 却拿全池岗位算覆盖率"。
    课程数据来自 course_skill_map.csv，按 major_code 过滤——不同专业各算各的覆盖率。
    权重 = 0.6×需求分位 + 0.4×溢价分位。
    """
    from core import majors as MJ

    mj = MJ.get(major)
    mp = pd.read_csv(MAP_CSV, encoding="utf-8-sig")
    if "major_code" in mp.columns and mj["code"]:
        mp = mp[mp["major_code"].astype(str) == str(mj["code"])]
    if mp.empty:
        return {"ok": False, "msg": f"专业「{mj['name']}」还没有课程映射数据"}
    cov = mp.groupby("skill")["score"].max()
    fams = MJ.families_of(mj["code"]) if scope == "专业相关" else []
    note = ""
    if not fams:
        # 非技术类专业（会计、护理、学前…）在技术岗池里没有足够的自己的岗位，
        # 拿全池算覆盖率会把课程全判成"没教"，这里自动退回本专业相关岗位族口径。
        _fams = MJ.families_of(mj["code"])
        if _fams:
            _tech = jobs()
            _n_self = int(_tech["family"].isin(_fams).sum())
            if _n_self < 30:      # 技术岗池里属于本专业的岗位太少，全池口径没有意义
                fams, scope = _fams, "专业相关"
                note = (f"该专业方向在技术岗池里只有 {_n_self} 条样本，"
                        f"覆盖率自动按「本专业相关岗位族」计算")
    if fams:
        _n_pool = int(jobs(all_rows=True)["family"].isin(fams).sum())
        if _n_pool < 10:
            return {"ok": False, "scope": scope, "families": fams, "n_pool": _n_pool,
                    "msg": f"「{mj['name']}」对应方向在库内只有 {_n_pool} 条岗位，样本太少，"
                           f"先采集更多该方向的岗位，覆盖率才有意义。"}
    dem = demand_of_families(fams, top_k=200) if fams else demand(top_k=200)
    if dem.empty:
        return {"ok": False, "msg": "先做技能抽取"}
    prem = salary_premium(top_n=200)
    ptab = prem["table"] if prem.get("ok") else pd.DataFrame(columns=["skill", "premium"])

    d = dem[["skill", "n", "share"]].copy()
    d["freq_rank"] = d["n"].rank(pct=True)
    d = d.merge(ptab[["skill", "premium"]], on="skill", how="left")
    d["premium"] = d["premium"].fillna(0)
    if d["premium"].abs().max() > 0:
        d["prem_rank"] = d["premium"].rank(pct=True)
    else:
        d["prem_rank"] = 0.5
    d["w"] = 0.6 * d["freq_rank"] + 0.4 * d["prem_rank"]
    d["cover"] = d["skill"].map(cov).fillna(0.0)
    # 技能对应的课程名，供图表悬浮提示展示
    cmap = mp.groupby("skill")["course_name"].apply(lambda s: "、".join(sorted(set(s.dropna()))))
    d["courses"] = d["skill"].map(cmap).fillna("")
    d["gap_type"] = np.select(
        [(d["w"] >= d["w"].quantile(0.7)) & (d["cover"] <= 0.5),
         (d["w"] >= d["w"].quantile(0.5)) & (d["cover"] < 1.0)],
        ["红", "橙"], default="绿")
    total = (d["w"] * d["cover"]).sum() / d["w"].sum()
    return {"ok": True, "coverage": round(float(total), 4), "table": d,
            "red": int((d["gap_type"] == "红").sum()), "orange": int((d["gap_type"] == "橙").sum()),
            "green": int((d["gap_type"] == "绿").sum()),
            "major": mj["name"], "major_code": mj["code"],
            "n_courses": int(mp["course_name"].nunique()),
            "n_links": int(len(mp)), "scope": scope, "families": fams,
            "scope_note": note}


def gap_list(grade: str = "红", limit: int = 15) -> pd.DataFrame:
    c = coverage()
    if not c.get("ok"):
        return pd.DataFrame()
    d = c["table"]
    if grade != "全部":
        d = d[d["gap_type"] == grade]
    d = d.sort_values("w", ascending=False).head(limit)
    return d[["skill", "n", "cover", "premium", "w", "gap_type"]].rename(
        columns={"n": "岗位数", "cover": "现有覆盖", "w": "需求权重", "gap_type": "缺口等级"})


def city_profile(fams=None) -> pd.DataFrame:
    j = jobs() if not fams else jobs(all_rows=True)
    if fams:
        j = j[j["family"].isin(fams)]
    if j.empty:
        return j
    g = j.groupby("city").agg(岗位数=("jd_id", "count"), 月薪中位=("salary_mid", "median")).reset_index()
    return g.sort_values("岗位数", ascending=False).head(12)
