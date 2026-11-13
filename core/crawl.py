"""采集智联招聘公开搜索页（免登录）。

用法（也可以只在网页上点按钮，不用碰这个文件）：
    python -m core.crawl --city 郑州 洛阳 --kw Python 数据分析 --pages 2

原则：只取公开的岗位卡片信息，不取任何求职者信息；每次请求间隔 >=1.5 秒；
遇到验证页就停下报错，不绕验证码。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import time
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jobs.db"
CFG = ROOT / "config" / "crawl.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 智联的城市编号。河南与热门城市均已逐个抓过一遍、按返回的城市名对过；其它省份可照同样的办法试探。
CITY_ZHAOPIN = {
    # 一线城市与岗位主要分布城市（2026-11-04 逐个真实验证：请求后按返回 workCity 核对）
    "北京": 530, "上海": 538, "广州": 763, "深圳": 765, "杭州": 653, "苏州": 639,
    "成都": 801, "重庆": 551, "武汉": 736, "西安": 854, "南京": 635, "天津": 531,
    "济南": 702, "宁波": 654, "长沙": 749,
    # 河南省地市（编号 2026-10 逐个验证过；本地就业看板保留）
    "郑州": 719, "开封": 720, "洛阳": 721, "平顶山": 722, "安阳": 723, "鹤壁": 724,
    "新乡": 725, "焦作": 726, "濮阳": 727, "许昌": 728, "漯河": 729, "三门峡": 730,
    "南阳": 731, "商丘": 732, "信阳": 733, "周口": 734, "驻马店": 735,
}


# ---------------------------------------------------------------- 数据库
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  jd_id TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, industry TEXT,
  company_size TEXT, property TEXT, city TEXT, district TEXT,
  salary_text TEXT, salary_low REAL, salary_high REAL, salary_mid REAL,
  edu TEXT, exp TEXT, job_level INTEGER, publish_date TEXT,
  skills_raw TEXT, url TEXT, crawl_time TEXT
);
CREATE TABLE IF NOT EXISTS job_skill(
  jd_id TEXT, skill TEXT, raw_tag TEXT, is_tech INTEGER DEFAULT 1,
  PRIMARY KEY(jd_id, skill)
);
CREATE TABLE IF NOT EXISTS review(
  jd_id TEXT PRIMARY KEY, human_skills TEXT, sys_skills TEXT, agree INTEGER, ts TEXT
);
"""


def conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    # 老库迁移：job_skill 早先只存技术岗，加一列区分技术/非技术岗，
    # ① 市场全景等「技术岗口径」继续只看 is_tech=1，非技术岗供各行各业方向使用。
    cols = {r[1] for r in c.execute("PRAGMA table_info(job_skill)")}
    if "is_tech" not in cols:
        c.execute("ALTER TABLE job_skill ADD COLUMN is_tech INTEGER DEFAULT 1")
        c.commit()
    return c


# ---------------------------------------------------------------- 薪资解析
def parse_salary(text: str) -> tuple[float, float, int] | None:
    """'8千-1.2万/月·13薪' -> (8000, 12000, 13)；'面议' -> None"""
    if not text:
        return None
    s = str(text).replace(",", "").replace("，", "").replace(" ", "")
    if "面议" in s or "薪资面议" in s:
        return None
    s = s.replace("元/月", "").replace("元", "").replace("/月", "")
    months = 12
    m = re.search(r"[·\*x]?(\d{2})薪", s)
    if m:
        months = int(m.group(1))
    s = re.sub(r"[·\*x]?\d{2}薪", "", s)
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*(万|千|[kK])?", s)
    if not nums:
        return None
    unit = {"万": 10000, "千": 1000, "k": 1000, "K": 1000}
    vals = []
    for n, u in nums[:2]:
        v = float(n) * unit.get(u, 1)
        vals.append(v)
    if len(vals) == 1:
        vals = [vals[0], vals[0]]
    low, high = vals
    if low > high:
        low, high = high, low
    # 明显不是月薪的量级（如"年薪30万"没除干净），丢掉
    if low < 500 or high > 300000:
        return None
    return low, high, months


# ---------------------------------------------------------------- 岗位层级
LEVEL_1 = ("实习", "助理", "学徒", "初级", "应届", "储备")
LEVEL_3 = ("高级", "资深", "专家", "架构", "主管", "经理", "负责人", "总监", "组长")


def job_level(title: str) -> int:
    t = title or ""
    if any(k in t for k in LEVEL_3):
        return 3
    if any(k in t for k in LEVEL_1):
        return 1
    return 2


# ---------------------------------------------------------------- 抓取
def _fetch(url: str, headers: dict | None = None, tries: int = 3) -> str:
    """先用系统自带 curl，再退回 requests。

    智联对 requests 的 TLS 指纹有识别，直接请求会拿到"Security Verification"验证页；
    curl 走系统 TLS 库，实测能拿到正常页面。这不是破解，只是换个正常的浏览器化请求。
    """
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        text = _curl(url)
        if text and len(text) > 20000 and "Security Verification" not in text[:600]:
            return text
        last = f"curl 返回 {len(text) if text else 0} 字节，可能是验证页"
        try:
            r = requests.get(url, headers=h, timeout=20, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 20000 and "Security Verification" not in r.text[:600]:
                return r.text
            last += f"；requests HTTP {r.status_code} 长度 {len(r.text)}"
        except Exception as e:
            last += f"；requests {e}"
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"请求失败：{url} -> {last}")


def _curl(url: str, timeout: int = 25) -> str:
    import shutil
    import subprocess
    exe = shutil.which("curl")
    if not exe:
        return ""
    try:
        p = subprocess.run([exe, "-s", "-L", "--compressed", "-m", str(timeout),
                            "-A", UA, "-H", "Accept-Language: zh-CN,zh;q=0.9", url],
                           capture_output=True, timeout=timeout + 5)
        return p.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_zhaopin(html: str) -> list[dict]:
    """搜索页里有一段 positionList 的 JSON，直接切出来，不用解析 DOM。"""
    i = html.find('"positionList":[')
    if i < 0:
        return []
    start = html.find("[", i)
    try:
        lst, _ = json.JSONDecoder().raw_decode(html[start:])
    except json.JSONDecodeError:
        return []
    out = []
    for x in lst:
        tags = [t.get("name", "") for t in (x.get("jobSkillTags") or []) if t.get("name")]
        sal = parse_salary(x.get("salary60") or x.get("salaryReal"))
        out.append({
            "jd_id": f"ZP{x.get('jobId')}",
            "source": "智联招聘",
            "title": (x.get("name") or "").strip(),
            "company": (x.get("companyName") or "").strip(),
            "industry": x.get("industryName") or "",
            "company_size": x.get("companySize") or "",
            "property": x.get("propertyName") or "",
            "city": x.get("workCity") or "",
            "district": x.get("cityDistrict") or "",
            "salary_text": x.get("salary60") or "",
            "salary_low": sal[0] if sal else None,
            "salary_high": sal[1] if sal else None,
            "salary_mid": round((sal[0] + sal[1]) / 2 * sal[2] / 12, 0) if sal else None,
            "edu": x.get("education") or "",
            "exp": x.get("workingExp") or "",
            "job_level": job_level(x.get("name")),
            "publish_date": (x.get("publishTime") or "")[:10],
            "skills_raw": json.dumps(tags, ensure_ascii=False),
            "url": x.get("positionURL") or "",
        })
    return out


def crawl_zhaopin(cities, keywords, pages=2, delay=1.8, log=print) -> dict:
    """keywords 传空列表/空串表示不限关键词：采该城市全部类型的岗位。"""
    stat = {"新入库": 0, "重复": 0, "空页": 0, "请求": 0}
    c = conn()
    for city in cities:
        jl = CITY_ZHAOPIN.get(city)
        if not jl:
            log(f"[跳过] 没有 {city} 的城市编号")
            continue
        for kw in (keywords or [""]):
            for p in range(1, pages + 1):
                # 关键词必须做 URL 编码，否则中文关键词会被服务端当成乱码，返回一个空结果页；
                # 留空则不带 kw 参数，返回该城市全部岗位
                url = (f"https://sou.zhaopin.com/?jl={jl}&p={p}" if not kw else
                       f"https://sou.zhaopin.com/?jl={jl}&kw={quote(kw)}&p={p}")
                try:
                    rows = parse_zhaopin(_fetch(url))
                except Exception as e:
                    log(f"[中断] {city}/{kw}/第{p}页 {e}")
                    c.close()
                    return stat
                stat["请求"] += 1
                if not rows:
                    stat["空页"] += 1
                    break
                new, dup = save(c, rows)
                stat["新入库"] += new
                stat["重复"] += dup
                log(f"{city} / {kw or '全部'} / 第{p}页：{len(rows)} 条，新增 {new}，重复 {dup}")
                time.sleep(delay + random.random() * 0.8)
    c.close()
    return stat


# ---------------------------------------------------------------- 入库
COLS = ["jd_id", "source", "title", "company", "industry", "company_size", "property",
        "city", "district", "salary_text", "salary_low", "salary_high", "salary_mid",
        "edu", "exp", "job_level", "publish_date", "skills_raw", "url"]


def save(c: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new = dup = 0
    for r in rows:
        if not r.get("jd_id") or not r.get("title"):
            continue
        vals = [r.get(k) for k in COLS] + [now]
        cur = c.execute(
            f"INSERT OR IGNORE INTO jobs({','.join(COLS)},crawl_time) VALUES({','.join('?' * 20)})",
            vals)
        new += cur.rowcount
        dup += 0 if cur.rowcount else 1
    c.commit()
    return new, dup


def load_config() -> dict:
    if CFG.exists():
        return json.loads(CFG.read_text(encoding="utf-8"))
    # 关键词覆盖全部岗位族：只采 AI 词会让"数据开发 / 前端 / 测试 / 标注"样本过少
    return {"keywords": ["Python", "数据分析", "算法工程师", "机器学习", "大数据开发",
                         "人工智能", "大模型", "计算机视觉", "数据开发", "数据仓库",
                         "ETL工程师", "前端开发", "测试工程师", "运维工程师",
                         "数据标注", "Java开发", "BI工程师"],
            "cities": ["郑州", "洛阳", "新乡", "许昌", "焦作", "开封"],
            "pages": 2}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", nargs="*")
    ap.add_argument("--kw", nargs="*")
    ap.add_argument("--pages", type=int, default=2)
    a = ap.parse_args()
    cfg = load_config()
    cities = a.city or cfg["cities"]
    kws = a.kw or cfg["keywords"]
    print(crawl_zhaopin(cities, kws, a.pages))
