"""职航罗盘 · 工程后台（方案 C 独立入口的渲染层）

学生端 app_all.py 不再加载本模块：采集引擎、MySQL 直连、账号台账全部收在这里，
由 app_all.py 内嵌调用（⑧ 工程后台屏）。开发者名单在 config/admin.json。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import pymysql
except ImportError:            # 没装驱动时页面照样能开，只是采集不可用
    pymysql = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import auth as AU  # noqa: E402
from core import crawl as ZP  # noqa: E402
from core import majors as MJ  # noqa: E402
from core import skills as SK  # noqa: E402
from core import sms as SMS  # noqa: E402
from core import syncpack as SP  # noqa: E402

SQLITE_DB = ROOT / "data" / "jobs.db"


# ================================================================ MySQL 配置
DEFAULT_DB = {"host": "127.0.0.1", "port": 3306, "user": "root",
              "password": "root", "database": "gangke"}

DDL = [
    """CREATE TABLE IF NOT EXISTS jobs(
        jd_id VARCHAR(64) NOT NULL PRIMARY KEY,
        source VARCHAR(32), title VARCHAR(255), company VARCHAR(255),
        industry VARCHAR(128), company_size VARCHAR(64), property VARCHAR(64),
        city VARCHAR(32), district VARCHAR(64),
        salary_text VARCHAR(64), salary_low FLOAT, salary_high FLOAT, salary_mid FLOAT,
        edu VARCHAR(32), exp VARCHAR(32), job_level TINYINT,
        publish_date VARCHAR(16), skills_raw TEXT, url VARCHAR(512),
        crawl_time DATETIME,
        KEY idx_city (city), KEY idx_pub (publish_date), KEY idx_salary (salary_mid)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS crawl_progress(
        city VARCHAR(32) NOT NULL, kw VARCHAR(64) NOT NULL,
        next_page INT NOT NULL DEFAULT 1,
        done TINYINT NOT NULL DEFAULT 0,
        added INT NOT NULL DEFAULT 0,
        updated_at DATETIME,
        PRIMARY KEY(city, kw)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS crawl_log(
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        ts DATETIME, city VARCHAR(32), kw VARCHAR(64), page INT,
        fetched INT, added INT, note VARCHAR(255)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

COLS = ["jd_id", "source", "title", "company", "industry", "company_size", "property",
        "city", "district", "salary_text", "salary_low", "salary_high", "salary_mid",
        "edu", "exp", "job_level", "publish_date", "skills_raw", "url"]


def connect(cfg: dict, with_db: bool = True) -> pymysql.connections.Connection:
    if pymysql is None:
        raise RuntimeError("没装 MySQL 驱动：执行 .venv\\Scripts\\python -m pip install pymysql "
                           "-i https://mirrors.aliyun.com/pypi/simple/ 后刷新页面")
    kw = dict(host=cfg["host"], port=int(cfg["port"]), user=cfg["user"],
              password=cfg["password"], charset="utf8mb4", autocommit=True,
              connect_timeout=6)
    if with_db:
        kw["database"] = cfg["database"]
    return pymysql.connect(**kw)


def init_db(cfg: dict) -> None:
    """库不存在就建，表不存在就建。重复执行无副作用。"""
    cn = connect(cfg, with_db=False)
    try:
        with cn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
                        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
    finally:
        cn.close()
    cn = connect(cfg)
    try:
        with cn.cursor() as cur:
            for sql in DDL:
                cur.execute(sql)
    finally:
        cn.close()


def query_df(cn, sql: str, args=None) -> pd.DataFrame:
    """pymysql 不是 SQLAlchemy 连接，直接喂 pandas 会告警，这里手工拼。"""
    with cn.cursor() as cur:
        cur.execute(sql, args or ())
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _clean(v):
    """pandas 的 nan / numpy 标量 pymysql 不认，统一转 None 或原生类型。"""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and v != v:
        return None
    if hasattr(v, "item"):
        v = v.item()
        if isinstance(v, float) and v != v:
            return None
    return v


# ================================================================ 断点与写库
def next_page_of(cn, city: str, kw: str) -> tuple[int, int]:
    with cn.cursor() as cur:
        cur.execute("SELECT next_page, done FROM crawl_progress WHERE city=%s AND kw=%s",
                    (city, kw))
        r = cur.fetchone()
    return (r[0], r[1]) if r else (1, 0)


def save_cursor(cn, city: str, kw: str, next_page: int, done: int, added: int) -> None:
    with cn.cursor() as cur:
        cur.execute(
            """INSERT INTO crawl_progress(city,kw,next_page,done,added,updated_at)
               VALUES(%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE next_page=VALUES(next_page), done=VALUES(done),
                 added=added+VALUES(added), updated_at=VALUES(updated_at)""",
            (city, kw, next_page, done, added, datetime.now()))


def reset_cursor(cn) -> int:
    with cn.cursor() as cur:
        return cur.execute("DELETE FROM crawl_progress")


def save_rows(cn, rows: list[dict]) -> tuple[int, int]:
    """INSERT IGNORE：jd_id 撞了就跳过，重复采集不会产生重复数据。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vals = []
    for r in rows:
        if not r.get("jd_id") or not r.get("title"):
            continue
        vals.append([_clean(r.get(k)) for k in COLS] + [now])
    if not vals:
        return 0, 0
    ph = ",".join(["%s"] * (len(COLS) + 1))
    sql = f"INSERT IGNORE INTO jobs({','.join(COLS)},crawl_time) VALUES({ph})"
    with cn.cursor() as cur:
        cur.executemany(sql, vals)
        added = max(cur.rowcount, 0)
    return added, len(vals) - added


def write_log(cn, city, kw, page, fetched, added, note) -> None:
    with cn.cursor() as cur:
        cur.execute("INSERT INTO crawl_log(ts,city,kw,page,fetched,added,note) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (datetime.now(), city, kw, page, fetched, added, str(note)[:255]))


def mirror_rows(sq: sqlite3.Connection, rows: list[dict]) -> int:
    """把刚入库的岗位同步进分析快照（INSERT OR REPLACE，已有则更新）。

    已有 crawl_time 的原样带过来，避免"重建一次全库时间都变成今天"。
    """
    n = 0
    for r in rows:
        if not r.get("jd_id") or not r.get("title"):
            continue
        ts = r.get("crawl_time")
        if hasattr(ts, "strftime"):          # MySQL 取回来是 datetime，转成字符串给 SQLite
            ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        vals = [r.get(k) for k in COLS] + [ts]
        sq.execute(
            f"INSERT OR REPLACE INTO jobs({','.join(COLS)},crawl_time) "
            f"VALUES({','.join('?' * 20)})", vals)
        n += 1
    sq.commit()
    return n


def rebuild_mirror(cfg: dict) -> tuple[int, int]:
    """把 MySQL 主库全量灌进分析快照。返回 (同步条数, 快照总条数)。"""
    cn = connect(cfg)
    df = query_df(cn, "SELECT * FROM jobs")
    cn.close()
    sq = ZP.conn()
    n = mirror_rows(sq, df.to_dict("records"))
    total = sq.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    sq.close()
    return n, total


# ================================================================ 采集任务
class CrawlJob:
    """后台线程与页面之间的共享状态。线程只写，页面只读。"""

    def __init__(self, cities, kws, pages, delay):
        self.cities, self.kws, self.pages, self.delay = cities, kws, pages, delay
        self.pause = threading.Event()
        self.lock = threading.Lock()
        self.logs: list[str] = []
        self.cur = ("", "", 0)
        self.added = 0
        self.done_tasks = 0
        self.total_tasks = len(cities) * len(kws)
        self.running = True
        self.finished = False
        self.stopped_by_pause = False
        self.error = ""

    def log(self, msg: str) -> None:
        with self.lock:
            self.logs.append(f"{datetime.now():%H:%M:%S}  {msg}")
            del self.logs[:-300]

    def snapshot(self) -> list[str]:
        with self.lock:
            return list(self.logs)

    def nap(self, seconds: float) -> bool:
        """分段睡眠，期间按了暂停能马上醒；返回 True 表示该停了。"""
        end = time.time() + seconds
        while time.time() < end:
            if self.pause.is_set():
                return True
            time.sleep(0.1)
        return self.pause.is_set()


def run_crawl(cfg: dict, job: CrawlJob) -> None:
    """采集主循环：每页开始前查暂停，采完一页同时写 MySQL 和分析快照。"""
    cn = None
    sq = None
    try:
        cn = connect(cfg)
        sq = ZP.conn()
        for city in job.cities:
            jl = ZP.CITY_ZHAOPIN.get(city)
            if not jl:
                job.log(f"[跳过] 没有 {city} 的城市编号")
                continue
            for kw in job.kws:
                start, done = next_page_of(cn, city, kw)
                if done or start > job.pages:
                    job.log(f"[已完成] {city} / {kw or '全部'} 采到第 {job.pages} 页了，跳过")
                    job.done_tasks += 1
                    continue
                if start > 1:
                    job.log(f"[续采] {city} / {kw or '全部'} 从第 {start} 页继续")
                for p in range(start, job.pages + 1):
                    if job.pause.is_set():
                        job.stopped_by_pause = True
                        job.log(f"[暂停] 停在 {city} / {kw or '全部'} 第 {p} 页之前，下次从这一页继续")
                        return
                    job.cur = (city, kw, p)
                    # 留空关键词 = 不限类型，URL 不带 kw 参数，智联会返回该城市全部岗位
                    url = (f"https://sou.zhaopin.com/?jl={jl}&p={p}" if not kw else
                           f"https://sou.zhaopin.com/?jl={jl}&kw={ZP.quote(kw)}&p={p}")
                    try:
                        rows = ZP.parse_zhaopin(ZP._fetch(url))
                    except Exception as e:
                        job.error = str(e)
                        job.log(f"[中断] {city} / {kw or '全部'} 第 {p} 页：{e}")
                        job.log("被拦了就先停手。等十分钟或换个网络再点继续，会从这一页接着采。")
                        return
                    if not rows:
                        save_cursor(cn, city, kw, job.pages + 1, 1, 0)
                        write_log(cn, city, kw, p, 0, 0, "空页，判定该词采完")
                        job.log(f"{city} / {kw or '全部'} 第 {p} 页没有结果，该词标记为采完")
                        break
                    added, dup = save_rows(cn, rows)
                    mirror_rows(sq, rows)
                    last = p >= job.pages
                    save_cursor(cn, city, kw, p + 1, 1 if last else 0, added)
                    write_log(cn, city, kw, p, len(rows), added, f"重复 {dup}")
                    job.added += added
                    job.log(f"{city} / {kw or '全部'} 第 {p} 页：{len(rows)} 条，新增 {added}，重复 {dup}")
                    if job.nap(job.delay):
                        job.stopped_by_pause = True
                        job.log(f"[暂停] 第 {p} 页已完成，下次从第 {p + 1} 页继续")
                        return
                job.done_tasks += 1
        job.log("[完成] 所有城市和关键词（或全部类型）都采完了")
    except Exception as e:
        job.error = str(e)
        job.log(f"[出错] {e}")
    finally:
        for c in (cn, sq):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        job.running = False
        job.finished = True


def start_job(cfg, cities, kws, pages, delay) -> None:
    job = CrawlJob(cities, kws, pages, delay)
    st.session_state["job"] = job
    threading.Thread(target=run_crawl, args=(cfg, job), daemon=True).start()



def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="k">{label}</div><div class="v">{value}</div>'
                 f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)



def hint(msg: str) -> None:
    """空状态提示：无底色无边框，与页面正文同风格。"""
    st.markdown(f'<div class="hint">{msg}</div>', unsafe_allow_html=True)



def sqlite_total() -> int:
    if not SQLITE_DB.exists():
        return 0
    c = sqlite3.connect(SQLITE_DB)
    try:
        return int(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        c.close()



def clear_analysis_cache() -> None:
    """后台页不缓存分析结果（KPI 每轮即时读库），保留接口兼容原调用点。"""


def _n_skill_rows() -> int:
    """job_skill 全表行数（技术岗 + 非技术岗，全部标注记录）。"""
    import sqlite3
    c = sqlite3.connect(A.DB)
    n = int(c.execute("SELECT COUNT(*) FROM job_skill").fetchone()[0])
    c.close()
    return n


def write_ledger(major: str | None = None) -> Path:
    ov = A.overview()
    dem = A.demand(10)
    prem = A.salary_premium(top_n=8, count_floor=25, boot=60)
    cov = A.coverage(major, scope="专业相关")   # 与②页面默认口径一致
    k = SK.kappa_vs_human()
    L = ["# 指标台账（单一事实源）", ""]
    L += ["## 1 数据规模", "", "| 项 | 值 |", "|---|---|",
          f"| 抓取岗位总数 | {ov.get('total', 0)} 条 |",
          f"| 技术岗（粗筛后） | {ov.get('n', 0)} 条 |",
          f"| 覆盖城市 | {ov.get('cities', 0)} 个 |",
          f"| 招聘企业 | {ov.get('companies', 0)} 家 |",
          f"| 薪资可解析率 | {ov.get('salary_rate', 0):.1%}（{ov.get('salary_ok', 0)} 条） |",
          f"| 月薪中位数 | ¥{ov.get('median', 0):,.0f} |",
          f"| 发布时间范围 | {ov.get('date_min', '-')} ~ {ov.get('date_max', '-')} |",
          f"| 标准技能节点 | {len(SK._DF)} 个 |",
          f"| 技能记录 | {ov.get('skills', 0)} 类 · 技术岗 {int(A.long_table().shape[0])} 条 / 非技术岗 "
          f"{_n_skill_rows() - int(A.long_table().shape[0])} 条，合计 {_n_skill_rows()} 条 |", ""]
    if not dem.empty:
        L += ["## 2 需求 Top10", "", "| 技能 | 岗位数 | 占比 | 均薪 |", "|---|---|---|---|"]
        for r in dem.head(10).itertuples():
            L.append(f"| {r.skill} | {r.n} | {r.share:.1%} | ¥{r.sal:,.0f} |")
        L.append("")
    if prem.get("ok"):
        L += ["## 3 薪资溢价（Ridge，控制城市/岗位族/规模/经验/学历/层级）", "",
              f"5 折 CV R² = {prem['r2']:.4f}（无技能基线 {prem.get('r2_base', 0):.4f}），"
              f"样本 {prem['n']} 条。", "",
              "| 技能 | 溢价 | 95% 区间 | 显著 |", "|---|---|---|---|"]
        for r in prem["table"].head(6).itertuples():
            L.append(f"| {r.skill} | {r.premium:+.1%} | [{r.ci_low:+.1%}, {r.ci_high:+.1%}] | "
                     f"{'是' if r.significant else '否'} |")
        L.append("")
    if cov.get("ok"):
        L += ["## 4 课程覆盖", "", "| 项 | 值 |", "|---|---|",
              f"| 专业 | {cov.get('major', '')}（{cov.get('major_code', '')}） |",
              f"| 课程门数 | {cov.get('n_courses', 0)} 门 / {cov.get('n_links', 0)} 条映射 |",
              f"| 加权覆盖率 | {cov['coverage']:.1%} |",
              f"| 红色缺口 | {cov['red']} 项 |", f"| 橙色缺口 | {cov['orange']} 项 |",
              f"| 已覆盖 | {cov['green']} 项 |", ""]
    L += ["## 5 标注抽检", "", "| 项 | 值 |", "|---|---|"]
    if k.get("n"):
        L += [f"| 抽检条数 | {k['n']} |", f"| cell 级一致率 | {k['agree_cells']:.1%} |",
              f"| 岗位级完全一致 | {k.get('exact_rate', 0):.1%}（κ={k['kappa']:.3f}，整条一致口径） |",
              f"| 精确率 / 召回率 / F1 | {k.get('precision', 0):.1%} / {k.get('recall', 0):.1%} / {k.get('f1', 0):.3f} |",
              f"| Jaccard 平均 | {k.get('jaccard', 0):.3f} |"]
    else:
        L.append("| 抽检 | 未做 |")
    L.append("")
    out = ROOT / "docs" / "指标台账.md"
    out.write_text("\n".join(L), encoding="utf-8")
    clear_analysis_cache()
    return out



# ================================================================ 采集进度面板
@st.fragment(run_every=2.0)
def panel() -> None:
    j: CrawlJob | None = st.session_state.get("job")
    if not j:
        st.markdown('<div class="blk"><span class="tag idle">空闲</span>'
                    '　还没有开始过。设好城市和关键词，点「开始 / 继续采集」。</div>',
                    unsafe_allow_html=True)
        return
    if j.running:
        tag = '<span class="tag run">采集中</span>'
    elif j.error:
        tag = '<span class="tag warn">已中断</span>'
    elif j.stopped_by_pause:
        tag = '<span class="tag stop">已暂停</span>'
    else:
        tag = '<span class="tag idle">已结束</span>'
    city, kw, p = j.cur
    st.markdown(
        f'<div class="blk">{tag}　当前：<b>{city or "-"}</b> / <b>{kw or "-"}</b>'
        f' / 第 <b>{p or "-"}</b> 页　·　本次新增 <b>{j.added}</b> 条'
        f'　·　任务 {j.done_tasks}/{j.total_tasks}</div>', unsafe_allow_html=True)
    logs = j.snapshot()[-12:]
    if logs:
        st.markdown('<div class="mono">' + "\n".join(logs).replace("<", "&lt;") + "</div>",
                    unsafe_allow_html=True)

    # 采集线程刚停下来时，刷新整页，让看板和统计立刻用上新数据
    if j.finished and not st.session_state.get("_flushed"):
        st.session_state["_flushed"] = id(j)
        clear_analysis_cache()
        st.rerun(scope="app")



# ================================================================ MySQL 状态与开发者名单
def mysql_status() -> dict:
    """连主库、数条数。返回 {cfg, ok, err, n}，失败不抛错只记原因。"""
    cfg = st.session_state.get("db_cfg", dict(DEFAULT_DB))
    ok, err, n = False, "", 0
    if pymysql is None:
        err = "未安装 MySQL 驱动（可选功能）"
    else:
        try:
            init_db(cfg)
            cn = connect(cfg)
            with cn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM jobs")
                n = int(cur.fetchone()[0])
            cn.close()
            ok = True
        except Exception as e:
            err = str(e)
    return {"cfg": cfg, "ok": ok, "err": err, "n": n}


def load_admins() -> list[str]:
    """开发者账号名单：config/admin.json 的 admins 数组。"""
    f = ROOT / "config" / "admin.json"
    try:
        return [str(x) for x in (json.loads(f.read_text(encoding="utf-8")).get("admins") or [])]
    except Exception:
        return []


def is_admin(account: str) -> bool:
    return str(account) in load_admins()


# ================================================================ 工程后台（四个 tab）
def render_admin_screen(uid: int, account: dict) -> None:
    """工程后台全部界面。uid/account 是当前登录的开发者（用于同步包导出导入）。"""
    my = mysql_status()
    cfg = my["cfg"]
    mysql_ok, mysql_err, mysql_n = my["ok"], my["err"], my["n"]
    ov = A.overview()
    major_name = MJ.default_name()
    UID, ACCOUNT = int(uid), account
    e1, e2, e3, e4 = st.tabs(["采集入库", "技能标注", "数据规范与台账", "账号与登录"])

    # ---------- 采集入库
    with e1:
        st.markdown("## 采集入库")

        st.markdown('<div class="flat">'
                    
                    '</div>',
                    unsafe_allow_html=True)

        st.write("")

        with st.expander("数据库连接", expanded=not mysql_ok):
            c = st.columns([1, 0.55, 0.9, 1, 0.9])
            host = c[0].text_input("主机", cfg["host"])
            port = c[1].number_input("端口", 1, 65535, int(cfg["port"]))
            user = c[2].text_input("用户", cfg["user"])
            pwd = c[3].text_input("密码", cfg["password"], type="password")
            dbn = c[4].text_input("库名", cfg["database"])
            if st.button("测试连接并建表"):
                new = {"host": host, "port": int(port), "user": user,
                       "password": pwd, "database": dbn}
                try:
                    init_db(new)
                    st.session_state["db_cfg"] = new
                    st.success(f"连接成功，库 {dbn} 已就绪")
                    st.rerun()
                except Exception as e:
                    st.error(f"连不上：{e}")

        if not mysql_ok:
            if pymysql is None:
                st.info("云端部署未装 MySQL 驱动，本机的「采集入 MySQL」增强功能不可用；"
                        "分析快照已随项目带上，学生端五屏全部正常。"
                        "本机要启用：.venv\\Scripts\\python -m pip install pymysql")
            else:
                st.error(f"MySQL 没连上：{mysql_err}")
                st.info("展开「数据库连接」填账号密码，点「测试连接并建表」。本机默认 root / root / gangke。"
                        "　学生端五屏不受影响，仍然读本地快照。")

        m1, m2, m3, m4 = st.columns(4)
        kpi(m1, "MySQL 主库", f"{mysql_n:,}" if mysql_ok else "—", "岗位去重后")
        kpi(m2, "分析快照", f"{sqlite_total():,}", "与主库同源")
        kpi(m3, "技术岗", ov.get("n", 0), "标题粗筛后")
        kpi(m4, "覆盖城市", ov.get("cities", 0), "一线 + 主要分布城市")

        st.write("")
        zcfg = ZP.load_config()
        st.markdown("### 采集设置")
        a, b, c2 = st.columns([1.2, 1.6, 0.85])
        cities = a.multiselect("城市", list(ZP.CITY_ZHAOPIN.keys()), default=zcfg["cities"])
        kw_text = b.text_input("关键词（逗号分隔，留空 = 全部类型）", "，".join(zcfg["keywords"]),
                               help="留空表示不限关键词：采集该城市下全部类型的岗位，不再按词拆任务")
        kws = [k.strip() for k in kw_text.replace("，", ",").split(",") if k.strip()] or [""]
        pages = c2.number_input("每个词采到第几页", 1, value=int(zcfg.get("pages", 2)),
                                step=1,
                                help="不限制页数：想采多少页填多少，中途暂停会按页断点续采")
        delay = st.slider("每页之间歇几秒", 1.0, 5.0, 1.8, 0.2)
        if kws == [""]:
            st.caption(f"任务数 {len(cities)} 个（城市 × 全部类型：不限关键词）")
        else:
            st.caption(f"任务数 {len(cities) * len(kws)} 个（城市 × 关键词）"
                       "")

        job: CrawlJob | None = st.session_state.get("job")
        running = bool(job and job.running)

        b1, b2, b3 = st.columns([0.95, 0.85, 1.4])
        start_clicked = b1.button("▶ 开始 / 继续采集", type="primary", width="stretch",
                                  disabled=running or not cities or not mysql_ok)
        pause_clicked = b2.button("⏸ 暂停采集", width="stretch", disabled=not running)
        reset_clicked = b3.button("清空断点", disabled=not mysql_ok)

        if start_clicked:
            st.session_state.pop("_flushed", None)
            start_job(cfg, cities, kws, int(pages), float(delay))
            st.rerun()
        if pause_clicked and job:
            job.pause.set()
            st.toast("正在停，当前这页采完就停")
        if reset_clicked:
            n = reset_cursor(connect(cfg))
            st.session_state.pop("job", None)
            st.success(f"已清掉 {n} 条断点。")

        panel()

        st.divider()
        left, right = st.columns([1.15, 1])
        with left:
            st.markdown("### 断点记录")
            #st.caption("「下一页」就是下次要请求的页码。暂停、关页面、关机都不影响。")
            if mysql_ok:
                try:
                    pt = query_df(connect(cfg),
                                  "SELECT city AS 城市, IF(kw='','全部类型',kw) AS 关键词, next_page AS 下一页, "
                                  "IF(done=1,'已完成','未完成') AS 状态, added AS 累计新增, "
                                  "updated_at AS 更新时间 FROM crawl_progress "
                                  "ORDER BY updated_at DESC")
                    if pt.empty:
                        hint("还没有断点记录。")
                    else:
                        st.dataframe(pt, width="stretch", hide_index=True, height=250)
                except Exception as e:
                    st.warning(f"读断点失败：{e}")
        with right:
            st.markdown("### 两条库对不对得上")
            #st.caption("主库是 MySQL，分析快照是本地 SQLite。采集时两边同时写，" "正常情况下条数一致；不一致就用下面的按钮强对齐。")
            d = sqlite_total() - mysql_n
            if d == 0:
                hint(f"一致：两边都是 {mysql_n} 条")
            else:
                st.warning(f"差 {d:+d} 条（快照 {sqlite_total()} / 主库 {mysql_n}）")
            g1, g2 = st.columns(2)
            if g1.button("MySQL → 分析快照", disabled=not mysql_ok, width="stretch"):
                try:
                    n, total = rebuild_mirror(cfg)
                    clear_analysis_cache()
                    st.success(f"已同步 {n} 条，快照现有 {total} 条")
                    st.rerun()
                except Exception as e:
                    st.error(f"同步失败：{e}")
            if g2.button("把 SQLite 存量导进 MySQL", disabled=not mysql_ok, width="stretch"):
                try:
                    s = sqlite3.connect(SQLITE_DB)
                    df = pd.read_sql("SELECT * FROM jobs", s)
                    s.close()
                    added, dup = save_rows(connect(cfg), df.to_dict("records"))
                    st.success(f"导入完成：新增 {added} 条，已存在 {dup} 条")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败：{e}")

        st.markdown("### 最近入库的 200 条")
        try:
            recent = query_df(
                connect(cfg),
                "SELECT title AS 岗位, company AS 公司, city AS 城市, salary_text AS 薪资, "
                "edu AS 学历, exp AS 经验, crawl_time AS 入库时间 FROM jobs "
                "ORDER BY crawl_time DESC LIMIT 200") if mysql_ok else pd.DataFrame()
            if recent.empty:
                hint("主库还没有数据。选几个城市，点「开始 / 继续采集」。")
            else:
                st.dataframe(recent, width="stretch", height=340, hide_index=True)
                st.download_button("下载全量 CSV",
                                   query_df(connect(cfg), "SELECT * FROM jobs")
                                   .to_csv(index=False).encode("utf-8-sig"),
                                   "岗位库_MySQL.csv", "text/csv")
        except Exception as e:
            st.warning(f"读数据失败：{e}")

    # ---------- 技能标注
    with e2:
        st.markdown("## 技能标注（归一层）")
        st.markdown('<div class="flat">'
                    ''
                    '</div>',
                    unsafe_allow_html=True)

        a, b = st.columns([1, 2])
        with a:
            if st.button("① 跑技能归一", type="primary"):
                box = st.status("抽取中…", expanded=True)
                SK.run_extract(log=lambda m: box.write(m))
                box.update(label="抽取完成", state="complete")
                clear_analysis_cache()
                st.rerun()
            kval = SK.kappa_vs_human()
            if kval.get("n"):
                st.metric("抽检一致率（cell 级）", f"{kval['agree_cells']:.1%}", f"{kval['n']} 条抽检")
                st.metric("岗位级完全一致", f"{kval.get('exact_rate', 0):.1%}",
                          f"κ={kval['kappa']:.3f}")
                st.caption(f"精确率 {kval.get('precision', 0):.1%} · 召回率 {kval.get('recall', 0):.1%}"
                           f" · F1 {kval.get('f1', 0):.3f} · Jaccard {kval.get('jaccard', 0):.3f}"
                           "")

        with b:
            st.markdown("#### 没认出来的标签")
            un = SK.unknown_tags(min_n=3, limit=25)
            if un.empty:
                st.caption("还没有未识别标签，或还没跑归一。")
            else:
                st.dataframe(un.rename(columns={"tag": "原始标签", "n": "出现次数",
                                                "sample_title": "示例岗位"}),
                             width="stretch", hide_index=True, height=260)
                #st.caption(f"这些词出现次数到了门槛，却没进 {len(SK._DF)} 个标准节点。"  "")

        st.divider()
        st.markdown("#### 抽检：系统漏标了多少")
        #st.caption("随机抽 8 条，看一眼平台标签和系统归一结果，把漏掉的技能填进去（逗号分隔，没漏就留空）。")
        if st.button("抽取一批样本") or "batch" not in st.session_state:
            con = sqlite3.connect(SQLITE_DB)
            st.session_state["batch"] = pd.read_sql(
                "SELECT jd_id,title,skills_raw FROM jobs ORDER BY RANDOM() LIMIT 8", con)
            con.close()
        batch = st.session_state.get("batch")
        if batch is not None and not batch.empty:
            con = sqlite3.connect(SQLITE_DB)
            rows = []
            for r in batch.itertuples():
                s = pd.read_sql("SELECT skill FROM job_skill WHERE jd_id=?", con, params=(r.jd_id,))
                raw = "、".join(json.loads(r.skills_raw or "[]"))
                rows.append({"岗位": r.title, "平台标签": raw,
                             "系统归一": "、".join(s["skill"].tolist()), "漏标补充": ""})
            con.close()
            ed = st.data_editor(pd.DataFrame(rows), width="stretch", hide_index=True,
                                disabled=["岗位", "平台标签", "系统归一"], key="ed_review")
            if st.button("提交抽检结果"):
                con = sqlite3.connect(SQLITE_DB)
                for i, row in ed.iterrows():
                    sysl = [] if not row["系统归一"] else row["系统归一"].split("、")
                    extra = [x.strip() for x in re.split(r"[,，、]", str(row["漏标补充"])) if x.strip()]
                    human = sorted(set(sysl) | set(extra))
                    con.execute("INSERT OR REPLACE INTO review VALUES(?,?,?,?,datetime('now'))",
                                (batch.iloc[i]["jd_id"], json.dumps(human, ensure_ascii=False),
                                 json.dumps(sysl, ensure_ascii=False), 0 if extra else 1))
                con.commit()
                con.close()
                st.success("已记录，κ 会更新到左边。")
                st.session_state.pop("batch", None)
                st.rerun()

    # ---------- 数据规范与台账
    with e3:
        st.markdown("## 数据规范")
        st.markdown("### 库表")
        st.markdown("""
| 表 | 位置 | 作用 |
|---|---|---|
| `jobs` | MySQL | 岗位主表，`jd_id` 主键，重复采到自动跳过 |
| `crawl_progress` | MySQL | 断点表：城市 × 关键词 → 下一页页码、是否采完 |
| `crawl_log` | MySQL | 请求流水：每次采了几条、新增几条、为什么停 |
| `jobs` / `job_skill` / `tag_pool` / `review` | SQLite `data/jobs.db` | 分析快照：岗位副本、技能记录、未识别标签、抽检 |
| `career_snapshot` | SQLite | **成长档案**：每次定位的技能、命中率、缺口快照，跨学期叠比 |
| `job_skill` | SQLite | 归一后的技能长表，分析全部从它出发 |
""")

        st.markdown("### 目录")
        st.markdown("""
| 路径 | 作用 |
|---|---|
| `app_all.py` | **本页**：学生端五屏 + AI 顾问 + 求职实战 + 工程后台，八个标签 |
| `core/coze.py` | **Coze 双引擎**：上下文注入式 RAG、Chat SSE、规划书工作流、离线规则兜底 |
| `core/profile.py` | **成长档案**：定位快照、跨期对比、命中率曲线数据 |
| `core/pathway.py` | **学习路径**：学生画像 → 目标岗位族 → 补课清单（按专业取课程） |
| `core/analyze.py` | 分析层：需求、共现、薪资回归、覆盖与缺口 |
| `core/skills.py` | 技能归一、未识别标签、抽检 κ（含语义别名表生效逻辑） |
| `core/semantic.py` | 语义层：新词向量归并（transformer/tfidf 双后端）、别名写回 |
| `core/agent.py` | 平台引擎流程 + 流程图渲染（九节点 DAG，可页面编辑） |
| `core/crawl.py` | 智联采集与薪资解析 |
| `core/majors.py` | 专业目录：专业元数据、课程口径切换 |
| `core/jd.py` | **JD 透视镜**：把粘贴的招聘 JD 解析成标准技能，猜岗位族，出模拟面试题 |
| `core/factcheck.py` | **AI 事实校验**：生成文本里的数字与平台计算结果逐个核对 |
| `core/weekly.py` | **周任务卡 / 成长周报**：把补课表拆到"这周做什么"，按快照生成周报 |
| `core/viz.py` | 自绘 SVG：需求榜、溢价条形、技能网络、缺口四象限、路线图、成长曲线、月度趋势 |
| `tools/seed_demo.py` | 演示档案：3 位学生的跨学期快照（可反复运行） |
| `core/demo_seed.py` | **演示账号自动播种**：换电脑登录同一演示账号，档案/投递剧本数据自动补齐（幂等） |
| `core/syncpack.py` | **账号数据同步包**：把账号数据导出成 JSON，另一台电脑同账号导入合并（判重幂等） |
| `config/agent_flow.json` | 智能体流程，页面上改完就存这里 |
| `config/coze.json.example` | Coze 接入配置模板（token / bot_id / workflow_id） |
| `config/llm.json.example` | OpenAI 兼容接口模板（二级兜底） |
| `config/crawl.json` | 采集配置（城市、关键词、页数） |
| `tools/build_major_courses.py` | 多专业课程数据生成脚本（新增专业改这里） |
| `data/dict/majors.json` | 9 个专业的代码、名称、专业组与课程统计 |
""")

        st.divider()
        st.markdown("**指标台账**")
        if st.button("按当前分析快照重新生成 docs/指标台账.md"):
            path = write_ledger(major_name)
            hint(f"已更新 {path.relative_to(ROOT)} · 台账是所有指标的唯一事实源")
            with st.expander("查看台账内容", expanded=False):
                st.markdown(path.read_text(encoding="utf-8"))

    # ---------- 账号与登录
    with e4:
        st.markdown("## 账号与登录")
        st.markdown('<div class="flat"></div>', unsafe_allow_html=True)
        _st = AU.stats()
        a1, a2, a3, a4, a5 = st.columns(5)
        kpi(a1, "注册账号", _st["users"])
        kpi(a2, "支持密码登录", _st.get("with_pw", 0), "PBKDF2 加盐哈希存储")
        kpi(a3, "今日登录", _st["active_today"], "按最后登录时间算")
        kpi(a4, "有效会话", _st["sessions"], f"{AU.SESSION_DAYS} 天过期")
        kpi(a5, "验证码记录", _st["codes"])

        st.write("")
        st.markdown("#### 账号列表")
        _rows = AU.list_users(100)
        if _rows:
            _df = pd.DataFrame([{
                "账号": r["id"], "登录账号": r["account_masked"], "档案名": r["nickname"],
                "专业": r["major"] or "—", "密码登录": "已设置" if r.get("has_pw") else "未设置",
                "注册时间": r["created_at"],
                "最近登录": r["last_login"] or "—", "登录次数": r["login_count"],
            } for r in _rows])
            st.dataframe(_df, width="stretch", hide_index=True,
                         height=min(46 + 32 * len(_df), 300))
        else:
            st.caption("还没有账号。首页注册一个，或用「演示账号 · 一键进入」。")

        st.write("")
        st.markdown("#### 每个账号存了多少数据")
        c = sqlite3.connect(SQLITE_DB)
        try:
            cnt = pd.read_sql("SELECT user_id AS 账号, COUNT(*) AS 定位记录 "
                              "FROM career_snapshot GROUP BY user_id ORDER BY user_id", c)
            acnt = pd.read_sql("SELECT user_id AS 账号, COUNT(*) AS 投递记录 "
                               "FROM apply_log GROUP BY user_id ORDER BY user_id", c)
        except Exception:
            cnt, acnt = pd.DataFrame(), pd.DataFrame()
        finally:
            c.close()
        if cnt.empty and acnt.empty:
            st.caption("成长档案和投递记录都还是空的。")
        else:
            cc1, cc2 = st.columns(2)
            with cc1:
                #st.caption("成长档案 career_snapshot（按 user_id 分组）")
                st.dataframe(cnt, width="stretch", hide_index=True, height=200)
            with cc2:
                #st.caption("投递记录 apply_log（按 user_id 分组）")
                    st.dataframe(acnt, width="stretch", hide_index=True, height=200)

        st.write("")

        sp1, sp2 = st.columns(2, gap="medium")
        with sp1:
            st.download_button(
                "导出同步包（JSON）",
                data=SP.export_json(UID, ACCOUNT.get("account", "")),
                file_name=f"职航罗盘同步包_{ACCOUNT.get('account','')}_{time.strftime('%Y%m%d')}.json",
                mime="application/json", key="sp_download", width="stretch")
        with sp2:
            _pack = st.file_uploader("选择同步包 JSON 文件", type=["json"], key="sp_upload",
                                     label_visibility="collapsed")
            if _pack is not None and st.button("导入到当前账号", type="primary",
                                               key="sp_import", width="stretch"):
                try:
                    payload = json.loads(_pack.getvalue().decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    st.error(f"文件读不出来：{e}")
                else:
                    r = SP.import_pack(UID, payload)
                    if r.get("ok"):
                        st.success(r.get("msg", "导入完成"))
                        st.rerun()
                    else:
                        st.error(r.get("msg", "导入失败"))

        # ============================================================
        # 短信通道配置（服务商 / 密钥 / 测试发送 / 开通指引）已按要求关闭。
        # 代码整体注释保留，恢复时把下面 begin/end 两行标记之间的注释去掉即可：
        #   ---- 短信通道 begin ----
        # ============================================================

        # st.divider()
        # st.markdown("#### 短信通道")
        # _stt = SMS.status()
        # if _stt["ready"]:
            # st.success(f"已接入 **{_stt['provider_label']}**：验证码真实发送。")

        # with st.expander("⚙️ 配置短信网关（保存即自动真发）",
                         # expanded=not _stt["ready"]):
            # _cfg = SMS.load_cfg()
            # _provs = list(SMS.PROVIDERS.keys())
            # _cur = _stt["provider"] or "aliyun"
            # _p = st.selectbox("服务商", _provs,
                              # index=_provs.index(_cur) if _cur in _provs else 0,
                              # format_func=lambda k: SMS.PROVIDERS[k], key="sms_provider")
            # _sec = dict(SMS.DEFAULTS.get(_p, {}))
            # _sec.update(_cfg.get(_p) or {})
            # _vals: dict[str, str] = {}
            # _fields = SMS.FIELDS[_p]
            # for _i in range(0, len(_fields), 2):
                # _row = st.columns(2)
                # for _j, (_key, _label, _secret) in enumerate(_fields[_i:_i + 2]):
                    # _vals[_key] = _row[_j].text_input(
                        # _label, value=str(_sec.get(_key) or ""),
                        # type="password" if _secret else "default",
                        # key=f"sms_{_p}_{_key}")
            # _tp = st.text_input("测试手机号",
                                # key="sms_test_phone", max_chars=11,
                                # placeholder="11 位手机号")
            # _c1, _c2 = st.columns([1, 1])
            # if _c1.button("💾 保存配置", type="primary", key="sms_save", width="stretch"):
                # _new = dict(_cfg)
                # _new["provider"] = _p
                # _new["enabled"] = True
                # _new[_p] = {k: str(v).strip() for k, v in _vals.items() if str(v).strip()}
                # SMS.save_cfg(_new)
                # st.session_state.pop("sms_test_res", None)
                # st.success(f"已保存到 config/sms.json（{SMS.PROVIDERS[_p]}），立即生效。")
                # st.rerun()
            # if _c2.button("📤 发一条测试短信", key="sms_test", width="stretch"):
                # if not AU.valid_phone(_tp):
                    # st.session_state["sms_test_res"] = {
                        # "ok": False, "msg": "先在上面填一个 11 位手机号再测"}
                # else:
                    # st.session_state["sms_test_res"] = SMS.send_test(_tp)
            # _tr = st.session_state.get("sms_test_res")
            # if _tr:
                # (st.success if _tr.get("ok") else st.error)(_tr.get("msg", ""))

            # if _p == "aliyun":
                # st.markdown("""**阿里云四步开通**
# 1. **开通短信服务** → 国内消息 → 签名管理：申请签名（如「职航罗盘」，需资质，审核约 2 小时）；
# 2. **模板管理**：申请验证码模板，内容填「您的验证码是 ${code}，5 分钟内有效，请勿泄露。」，
   # 变量名就是上面的「模板变量名」（默认 `code`）；
# 3. **访问控制 RAM**：建个子账号只给 `AliyunDysmsFullAccess`，生成 AccessKey（比主账号密钥安全）；
# 4. 回来填 AccessKeyId / Secret / 签名 / 模板 CODE（`SMS_` 开头）→ 保存 → 发测试。

# > 常见报错都在这里看得到：`isv.SMS_SIGNATURE_ILLEGAL` 签名没审核过、
# > `isv.SMS_TEMPLATE_ILLEGAL` 模板没审核过、`isv.AMOUNT_NOT_ENOUGH` 余额不足、
# > `isv.BUSINESS_LIMIT_CONTROL` 触发流控（同号码 1 分钟内 1 条、1 小时 5 条，平台侧冷却 60 秒）。""")
            # elif _p == "tencent":
                # st.markdown("""**腾讯云四步开通**
# 1. **短信控制台** → 国内短信 → 签名管理：申请签名；
# 2. **正文模板**：申请验证码模板，参数 1 个（`{1}`），内容如「您的验证码是 {1}，5 分钟内有效。」；
# 3. **应用管理**：拿到 SdkAppId（1400 开头）；**访问管理**建子账号（QcloudSMSFullAccess）拿 SecretId/Key；
# 4. 回来填 5 项 → 保存 → 发测试。""")
            # elif _p == "mob":
                # st.markdown("""**Mob 免费短信五步开通**
# 1. **注册** [mob.com](https://www.mob.com) → 右上角进后台 → 创建应用；
# 2. **添加产品** → 选「短信验证码 SMSSDK」（不是「秒验 / 一键登录」，那是另一个计费产品）；
# 3. **短信设置 → 全球设置**：打开 **http-api / web 发送短信** 开关和 **服务端验证** 开关，
   # 再把本机公网 IP 填进**服务器白名单**（这两个不开，只会返回 469 / 474 / 471）；
# 4. 在「概况」里记下 **AppKey / AppSecret**（Secret 只填在这台服务器上）；
# 5. 回来填 AppKey / AppSecret / 区号(86) → 保存 → 填自己手机号点「发一条测试短信」。

# > **和前两家不一样的地方**：Mob 自己生成验证码（后台可设 4 位或 6 位），平台拿不到明文，
# > 所以页面不回显、也不显示「测试验证码」；学生填的码由平台转给 Mob 的 `/sms/verify` 校验。
# >
# > **限制先说清**：包名未审核时每个 AppKey 每天 20 条；同一号码 12 小时 5 条、每天 10 条
# > （含 WebApi）；签名必须绑营业执照，**个人主体目前不支持**，学校/企业主体才行。""")
            # else:
                # st.markdown("""**通用网关协议**：平台向 `url` 发一条 POST，

# ```json
# {"phone": "13800000000", "code": "123456", "tpl": "career_compass", "sign": "职航罗盘"}
# ```

# 网关返回 HTTP 2xx 即视为发送成功；填了 `token` 会带 `Authorization: Bearer <token>` 头。
# 本地验证链路可用 `tools/mock_sms_gateway.py`（起一个模拟网关，终端会打印收到的验证码）。""")


        # _rule = ("Mob 后台设定的位数（默认 4 位）" if SMS.remote_verify() else "6 位数字")
        # #st.caption(f"验证码规则：{_rule} · 5 分钟有效 · 60 秒重发冷却 · 同一号码每小时最多 10 条 · 用后即废。")
        # ---- 短信通道 end ----
