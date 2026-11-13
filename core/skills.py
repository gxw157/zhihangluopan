"""技能归一：平台给的标签 → 108 个标准技能节点。

只做三件事：
1. 别名合并（llm / 大模型 / AIGC 都归到「大语言模型应用」）
2. 把标题里能被词典认出来的技能补进来（平台标签有时漏标）
3. 认不出来的标签单独存一张表，给"新词发现"节点用
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jobs.db"
DICT = ROOT / "data" / "dict" / "skill_dict.csv"

# 太短的英文缩写只在完全相等时才算命中，否则 "es" 会把 "Tesla" 认成 Elasticsearch
SHORT_LATIN = {"js", "es", "go", "c", "r", "bi", "dl", "ml", "tf", "np", "pd", "py", "ai", "k8s", "cv"}

# 招聘站的关键词搜索会带出无关岗位（搜"数据分析"能搜到会计和销售）。
# 按标题做一次粗筛，宁可少几百条，也不让销售岗污染技能统计。
TECH_WORDS = ("开发", "工程师", "算法", "数据", "运维", "测试", "前端", "后端", "架构", "技术",
              "IT", "AI", "人工智能", "机器学习", "深度学习", "大模型", "爬虫", "全栈", "研发",
              "程序员", "系统", "网络", "实施", "标注", "分析", "产品经理")
NON_TECH_WORDS = ("销售", "会计", "财务", "出纳", "运营", "客服", "文员", "行政", "人事", "招聘",
                  "采购", "主播", "直播", "市场", "商务", "店长", "策划", "教师", "讲师", "督导",
                  "经纪人", "保险", "房产", "中介")


def is_tech(title: str) -> bool:
    t = str(title or "")
    return any(k in t for k in TECH_WORDS) and not any(k in t for k in NON_TECH_WORDS)


def load_dict() -> pd.DataFrame:
    return pd.read_csv(DICT, encoding="utf-8-sig")


def build_index(df: pd.DataFrame) -> dict[str, str]:
    """alias(小写) -> 标准技能名"""
    idx: dict[str, str] = {}
    for r in df.itertuples():
        idx[str(r.canonical).lower()] = r.canonical
        for a in str(r.aliases).split("|"):
            a = a.strip().lower().replace("＋", "+")
            if a:
                idx.setdefault(a, r.canonical)
    return idx


# 全局只建一次
_DF = load_dict()
_INDEX = build_index(_DF)

# 语义归并产出的别名表（机器建议走这里，人工词典本体不动，删掉别名文件即可回退）
_ALIAS_FILE = ROOT / "data" / "dict" / "skill_alias.csv"
if _ALIAS_FILE.exists():
    try:
        _adf = pd.read_csv(_ALIAS_FILE, encoding="utf-8-sig")
        _valid = set(_DF["canonical"].astype(str))
        for _r in _adf.itertuples():
            _a = str(_r.alias).strip().lower()
            if _a and str(_r.skill) in _valid:
                _INDEX.setdefault(_a, str(_r.skill))
    except Exception:
        pass  # 别名表损坏时忽略，不影响主流程

_ALIASES = sorted(_INDEX, key=len, reverse=True)
_LATIN = re.compile(r"^[a-z0-9+#./\- ]+$")


def normalize(tag: str) -> str | None:
    """单个标签归一。认不出返回 None。"""
    if not tag:
        return None
    t = str(tag).strip().lower().replace("＋", "+")
    t = re.sub(r"\s+", " ", t)
    if t in _INDEX:
        return _INDEX[t]
    t2 = t.replace(" ", "")
    if t2 in _INDEX:
        return _INDEX[t2]
    # 带后缀的写法：「Python开发」「Java工程师」
    for a in _ALIASES:
        if len(a) < 3 or a in SHORT_LATIN:
            continue
        if not _LATIN.match(a):
            continue
        if re.match(rf"^{re.escape(a)}(开发|工程师|编程|语言|方向|相关)?$", t2):
            return _INDEX[a]
    return None


def titles_hit(title: str, known: set[str]) -> list[str]:
    """从标题里再捞一遍词典里有的技能（只补标题，不动平台标签）。"""
    if not title:
        return []
    t = str(title).lower().replace("＋", "+")
    found = []
    for a in _ALIASES:
        if a in SHORT_LATIN or len(a) < 2:
            continue
        if not _LATIN.match(a):
            # 中文别名按子串匹配
            if a in t:
                c = _INDEX[a]
                if c not in known and c not in found:
                    found.append(c)
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", t):
            c = _INDEX[a]
            if c not in known and c not in found:
                found.append(c)
    return found


def extract(title: str, tags: list[str], title_hits: bool = True) -> tuple[list[dict], list[str]]:
    """返回 (命中的标准技能, 没认出来的原始标签)

    title_hits=False 时不去标题里捞技能：非技术岗标题（"课程顾问""销售助理"）
    里常常埋着 AI、开发、Python 这类词，扫标题会捞出一堆不相干的技能，
    所以只有技术岗才做标题补捞，非技术岗一律以平台标签为准。
    """
    hits, miss, seen = [], [], set()
    for tag in tags:
        c = normalize(tag)
        if c:
            if c not in seen:
                hits.append({"skill": c, "raw": tag})
                seen.add(c)
        else:
            miss.append(tag)
    if title_hits:
        for c in titles_hit(title, seen):
            hits.append({"skill": c, "raw": "（标题）"})
            seen.add(c)
    return hits, miss


def scan_text(text: str) -> dict[str, int]:
    """自由文本（如学生粘贴的招聘 JD）里出现的标准技能 -> 出现次数。

    与 extract 的区别：JD 是整段文字，没有现成标签可归一，
    所以按词典别名做子串（中文）/词边界（拉丁）扫描，口径与平台标注一致。
    """
    if not text:
        return {}
    t = str(text).lower().replace("＋", "+")
    counts: dict[str, int] = {}
    for a in _ALIASES:
        if a in SHORT_LATIN or len(a) < 2:
            continue
        if _LATIN.match(a):
            n = len(re.findall(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", t))
        else:
            n = t.count(a)
        if n:
            c = _INDEX[a]
            counts[c] = counts.get(c, 0) + n
    return counts


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS tag_pool(
                   tag TEXT PRIMARY KEY, n INTEGER, sample_title TEXT)""")
    # 老库迁移：job_skill 早期没有 is_tech 列（那时只标技术岗）
    cols = {r[1] for r in c.execute("PRAGMA table_info(job_skill)")}
    if "is_tech" not in cols:
        c.execute("ALTER TABLE job_skill ADD COLUMN is_tech INTEGER DEFAULT 1")
        c.commit()
    return c


def run_extract(log=print) -> dict:
    """全库跑一遍抽取，写 job_skill 和 tag_pool。

    技术岗与非技术岗都抽：技术岗进「① 市场全景」的技术岗口径，
    非技术岗（会计、销售、运营、护理…）只服务对应岗位族的方向分析，
    用 is_tech 列区分，互不污染。
    """
    c = conn()
    jobs = pd.read_sql("SELECT jd_id,title,skills_raw FROM jobs", c)
    total = len(jobs)
    jobs["is_tech"] = jobs["title"].map(is_tech)
    c.execute("DELETE FROM job_skill")
    c.execute("DELETE FROM tag_pool")
    rows, pool = [], {}
    hit_n = job_hit = 0
    for r in jobs.itertuples():
        try:
            tags = json.loads(r.skills_raw or "[]")
        except json.JSONDecodeError:
            tags = []
        hits, miss = extract(r.title, tags, title_hits=bool(r.is_tech))
        if hits:
            job_hit += 1
        hit_n += len(hits)
        for h in hits:
            rows.append((r.jd_id, h["skill"], h["raw"], int(r.is_tech)))
        for m in miss:
            pool.setdefault(m, [0, r.title])
            pool[m][0] += 1
    c.executemany(
        "INSERT OR REPLACE INTO job_skill(jd_id,skill,raw_tag,is_tech) VALUES(?,?,?,?)", rows)
    c.executemany("INSERT OR REPLACE INTO tag_pool(tag,n,sample_title) VALUES(?,?,?)",
                  [(k, v[0], v[1]) for k, v in pool.items()])
    c.commit()
    c.close()
    n_tech = int(jobs["is_tech"].sum())
    stat = {"岗位总数": total, "技术岗": n_tech, "非技术岗": total - n_tech,
            "有技能命中": job_hit, "技能记录": len(rows),
            "未识别标签": len(pool),
            "平均每岗技能": round(hit_n / max(len(jobs), 1), 2)}
    log("抽取完成：" + "，".join(f"{k} {v}" for k, v in stat.items()))
    return stat


GENERIC = {"设计", "研发", "工程师", "技术", "管理", "沟通", "团队", "经验", "能力", "办公软件",
           "英语", "计算机", "专业", "工作", "项目", "产品", "服务", "客户", "销售", "运营",
           "学历", "证书", "培训", "实习", "全职", "兼职", "五险一金", "双休"}


def unknown_tags(min_n: int = 5, limit: int = 30) -> pd.DataFrame:
    c = conn()
    df = pd.read_sql(
        "SELECT tag,n,sample_title FROM tag_pool WHERE n>=? ORDER BY n DESC LIMIT 300",
        c, params=(min_n,))
    c.close()
    if df.empty:
        return df
    df = df[~df["tag"].isin(GENERIC)]
    df = df[df["tag"].str.len() >= 2]
    return df.head(limit)


def kappa_vs_human() -> dict:
    """人工抽检 vs 系统抽取的多标签一致度。

    三个坑，都踩过：
    ① 只在「人工 ∪ 系统」的并集上铺 0-1 向量 —— 并集里人工侧恒为 1，pe 必然等于 pa，κ 恒为 0；
    ② 改成在 113 个技能全量列上铺 —— 绝大多数格子是 0-0 一致，κ 被阴性样本推到 1.0（kappa 悖论）；
    ③ 所以主指标不用 cell 级 κ，改用多标签抽取的通行口径：
       cell 级一致率、岗位级完全一致率、集合级 P/R/F1、Jaccard 平均；
       κ 只作为「整条岗位是否完全一致」的二分类一致性，并注明口径。
    """
    c = conn()
    df = pd.read_sql("SELECT * FROM review", c)
    c.close()
    if df.empty:
        return {"n": 0}
    a, b = [], []
    tp = fp = fn = 0
    exact = 0
    jac = []
    for r in df.itertuples():
        hs = set(json.loads(r.human_skills or "[]"))
        ss = set(json.loads(r.sys_skills or "[]"))
        uni = sorted(hs | ss)
        a += [1 if u in hs else 0 for u in uni]
        b += [1 if u in ss else 0 for u in uni]
        tp += len(hs & ss)
        fp += len(ss - hs)
        fn += len(hs - ss)
        exact += 1 if hs == ss else 0
        jac.append(len(hs & ss) / max(len(hs | ss), 1))
    n = max(len(a), 1)
    pa = sum(x == y for x, y in zip(a, b)) / n
    p = tp / max(tp + fp, 1)
    rcl = tp / max(tp + fn, 1)
    f1 = 2 * p * rcl / max(p + rcl, 1e-9)
    po = exact / len(df)
    pe = po ** 2 + (1 - po) ** 2
    k = (po - pe) / (1 - pe) if pe < 1 else 0.0
    return {"n": len(df), "agree_cells": round(pa, 4), "kappa": round(k, 4),
            "exact_rate": round(po, 4), "jaccard": round(sum(jac) / len(jac), 4),
            "precision": round(p, 4), "recall": round(rcl, 4), "f1": round(f1, 4)}
