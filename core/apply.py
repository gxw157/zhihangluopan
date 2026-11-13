"""投递事实 + 事件流 + 状态推导：四个数字全部自动生成，学生不用手记状态。

设计要点
--------
- **投递是事实**：``apply_log`` 一行 = 投过一次（同账号同岗位 jd_id 唯一，重复点不重复记）。
- **状态是结论**：``apply_event`` 只追加事件，状态由 :func:`derive_status` 现算，
  页面上没有任何"选状态"的控件。旧 ``apply_log.status`` 列**保留但停写**，
  这样 ⑧ 工程后台的旧统计与既有测试不会被打破。
- **四类信号来源**
  ① 站内「立即投递」→ ``applied`` 事件（零配置，100% 自动）；
  ② 截图 OCR（本地 RapidOCR，断网可用）→ 面试邀请 / 录用 / 拒信事件；
  ③ 时间规则：投递满 14 天且期间无任何正向信号 → ``silent``（无回音），纯自动；
  ④ （预留）邮箱 IMAP 归集，复用 :func:`parse_notice` 同一套规则，不必再写一遍。
- **可回滚**：第 20 天忽然来了面试邀请，插入邀请事件后状态自动从「无回音」翻回
  「已约面」，历史事件全部保留——超时不是给人打标签，一有真信号就纠正。
- **数据隔离**：所有读写都带 ``COALESCE(user_id,0)=?``，换账号互不可见；
  写事件前先校验这条投递确实属于该账号，防止越权挂靠。

存储：与分析快照同一个 SQLite（data/jobs.db），表 apply_log / apply_event。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DB = Path(__file__).resolve().parents[1] / "data" / "jobs.db"

TIMEOUT_DAYS = 14          # 投递后多少天没有正向信号就判「无回音」
SILENT_RULE = f"rule:timeout-{TIMEOUT_DAYS}d"

KINDS = ("applied", "viewed", "assessment", "interview_invite",
         "interview_done", "offer", "rejected", "silent")

KIND_LABEL = {
    "applied": "投递", "viewed": "简历被查看", "assessment": "笔试/测评",
    "interview_invite": "面试邀请", "interview_done": "面试完成",
    "offer": "录用通知", "rejected": "明确拒信", "silent": f"超 {TIMEOUT_DAYS} 天无回音",
}

# 推导出来的状态（页面展示用）；与旧 STATUSES 不完全相同，多了「未通过」
DERIVED = ("已投递", "已约面", "已面试", "已录用", "无回音", "未通过")

LOG_DDL = """
CREATE TABLE IF NOT EXISTS apply_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student TEXT, title TEXT, company TEXT, city TEXT,
    status TEXT, note TEXT, ts TEXT, user_id INTEGER,
    jd_id TEXT, match_rate REAL, source TEXT, url TEXT
)
"""

EVENT_DDL = """
CREATE TABLE IF NOT EXISTS apply_event(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, apply_id INTEGER, kind TEXT,
    occurred_at TEXT, evidence TEXT, auto INTEGER DEFAULT 1,
    note TEXT, created_at TEXT
)
"""


# ================================================================ 基础
def _uid(uid) -> int:
    try:
        return int(uid or 0)
    except (TypeError, ValueError):
        return 0


def _now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute(LOG_DDL)
    c.execute(EVENT_DDL)
    # 老库补列：jd_id / match_rate / source / url（自动迁移，不手工改表）
    cols = {r[1] for r in c.execute("PRAGMA table_info(apply_log)")}
    for name, typ in (("jd_id", "TEXT"), ("match_rate", "REAL"),
                      ("source", "TEXT"), ("url", "TEXT")):
        if name not in cols:
            c.execute(f"ALTER TABLE apply_log ADD COLUMN {name} {typ}")
    # 同账号同岗位只允许一条：幂等的物理保证（手动补记 jd_id 为空，不受约束）
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_apply_user_jd "
              "ON apply_log(user_id, jd_id) WHERE jd_id IS NOT NULL AND jd_id<>''")
    c.execute("CREATE INDEX IF NOT EXISTS idx_apply_user ON apply_log(user_id, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_event_apply ON apply_event(apply_id)")
    c.commit()
    return c


# ================================================================ 规则引擎（截图 / 邮件共用）
# 顺序即优先级：录用 > 拒信 > 面试 > 测评 > 被查看
_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("offer", ("录用通知", "录用意向", "拟录用", "入职通知", "入职邀请",
               "恭喜您通过面试", "offer letter")),
    ("rejected", ("暂不合适", "已招满", "感谢您的投递", "感谢投递", "很遗憾",
                  "未通过", "不合适", "简历未通过", "不再考虑")),
    ("interview_invite", ("面试邀请", "面试通知", "面试安排", "参加面试", "面试时间",
                          "请您于", "请于", "现场面试", "视频面试", "电话面试",
                          "一面", "二面", "终面", "复试")),
    ("assessment", ("笔试", "在线测评", "性格测试", "测评链接", "在线考试", "能力测试")),
    ("viewed", ("已被查看", "简历已被查看", "您的简历被查看", "查看了您的简历")),
]

_COMPANY_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}?"
    r"(?:股份有限公司|有限责任公司|有限公司|集团|银行|医院|研究院|事务所|学院|大学|科技|数据|网络)"
)

_DT_FULL = re.compile(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})")
_DT_CN = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(?:[（(]?\s*(?:周|星期)[一二三四五六日天]\s*[)）]?)?"
                    r"\s*(上午|下午|晚上)?\s*(\d{1,2})\s*[:：]\s*(\d{1,2})")
_DT_CLOCK = re.compile(r"(上午|下午|晚上)?\s*(\d{1,2})\s*[:：]\s*(\d{2})")


def _parse_when(text: str, base: datetime | None = None) -> str:
    """从通知正文里提面试/入职时间；提不到返回空串（不编时间）。"""
    base = base or _now()
    m = _DT_FULL.search(text or "")
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = _DT_CN.search(text or "")
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        ap, hh, mm = m.group(3), int(m.group(4)), int(m.group(5))
        if ap == "下午" and hh < 12:
            hh += 12
        if ap == "晚上" and hh < 12:
            hh += 12
        try:
            dt = datetime(base.year, mon, day, hh, mm)
            if dt < base - timedelta(days=180):      # 明显是明年的通知
                dt = dt.replace(year=base.year + 1)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return f"{mon:02d}-{day:02d}"
    m = _DT_CLOCK.search(text or "")
    if m:
        return f"{int(m.group(2)):02d}:{int(m.group(3)):02d}"
    return ""


def parse_notice(text: str) -> dict:
    """识别一段通知文字（截图 OCR 或邮件正文）属于哪类信号。

    返回 {ok, kind, kind_label, company, when, hits}；识别不出类型时 ok=False。
    """
    t = str(text or "").strip()
    if not t:
        return {"ok": False, "msg": "没有识别到文字"}
    low = t.lower()
    kind, hits = "", []
    for k, words in _SIGNALS:
        hit = [w for w in words if w.lower() in low]
        if hit:
            kind, hits = k, hit
            break
    co = ""
    m = _COMPANY_RE.search(t)
    if m:
        co = m.group(0).strip()
    if not co:
        for line in t.splitlines():
            line = line.strip()
            if 4 <= len(line) <= 30 and any(w in line for w in ("公司", "集团", "银行", "医院")):
                co = line
                break
    return {"ok": bool(kind), "kind": kind, "kind_label": KIND_LABEL.get(kind, ""),
            "company": co, "when": _parse_when(t), "hits": hits,
            "msg": "" if kind else "认不出这是面试/录用/拒信里的哪一类，可手动选一下类型"}


def _norm_co(s: str) -> str:
    s = str(s or "")
    for w in ("股份有限公司", "有限责任公司", "有限公司", "分公司", "集团",
              "（", "）", "(", ")", " ", "　"):
        s = s.replace(w, "")
    return s.strip()


def match_applies(uid, company: str) -> pd.DataFrame:
    """把识别到的公司名对到本账号已投的岗位上（只在本账号内匹配）。"""
    df = board(uid)
    if df.empty or not str(company or "").strip():
        return df.iloc[0:0]
    key = _norm_co(company)
    if not key:
        return df.iloc[0:0]
    norm = df["公司"].map(_norm_co)
    hit = df[norm == key]
    if hit.empty:
        hit = df[norm.map(lambda x: bool(x) and (x in key or key in x))]
    if hit.empty and len(key) >= 4:
        hit = df[norm.str[:4] == key[:4]]
    return hit


# ================================================================ 写入
def log_apply(uid, student: str, jd_id: str, title: str, company: str = "",
              city: str = "", hit: float | None = None, source: str = "JD体检",
              url: str = "") -> dict:
    """记一条投递事实 + applied 事件。同一账号同一岗位只记一次（幂等）。"""
    u, jid = _uid(uid), str(jd_id or "").strip()
    title = str(title or "").strip()
    if not title:
        return {"ok": False, "msg": "岗位名称为空"}
    c = _conn()
    try:
        if jid:
            row = c.execute("SELECT id FROM apply_log WHERE COALESCE(user_id,0)=? AND jd_id=?",
                            (u, jid)).fetchone()
            if row:
                return {"ok": True, "dup": True, "id": int(row[0]),
                        "msg": "这条岗位已经记过了"}
        note = f"⑦JD体检 · 命中 {hit:.0%}" if isinstance(hit, (int, float)) else "⑦JD体检"
        now = _now()
        cur = c.execute(
            "INSERT INTO apply_log(user_id,student,title,company,city,status,note,ts,"
            "jd_id,match_rate,source,url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (u, str(student).strip() or "同学", title[:120], str(company)[:80],
             str(city)[:40], "已投递", note, _fmt(now), jid, hit, source, str(url)[:300]))
        aid = int(cur.lastrowid)
        c.execute("INSERT INTO apply_event(user_id,apply_id,kind,occurred_at,evidence,auto,note,created_at) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (u, aid, "applied", _fmt(now), source, 1, "", _fmt(now)))
        c.commit()
        return {"ok": True, "dup": False, "id": aid}
    finally:
        c.close()


def add_event(uid, apply_id: int, kind: str, occurred_at: str = "",
              evidence: str = "", auto: int = 1, note: str = "") -> dict:
    """追加一条事件（先校验这条投递属于本账号，防越权挂靠）。"""
    u = _uid(uid)
    if kind not in KINDS:
        return {"ok": False, "msg": f"未知事件类型 {kind}"}
    c = _conn()
    try:
        row = c.execute("SELECT id FROM apply_log WHERE id=? AND COALESCE(user_id,0)=?",
                        (int(apply_id), u)).fetchone()
        if not row:
            return {"ok": False, "msg": "这条投递不属于当前账号"}
        now = _fmt(_now())
        c.execute("INSERT INTO apply_event(user_id,apply_id,kind,occurred_at,evidence,auto,note,created_at) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (u, int(apply_id), kind, str(occurred_at or now), str(evidence or "")[:120],
                   int(auto), str(note or "")[:200], now))
        c.commit()
        return {"ok": True}
    finally:
        c.close()


def ingest_notice(uid, text: str, evidence: str = "截图OCR") -> dict:
    """截图/邮件文字 → 识别类型 → 挂到本账号的某条投递。

    返回 {ok, kind, kind_label, company, when, candidates(DataFrame), applied_id, msg}
    公司名对上唯一一条时直接写事件（演示要的"拖一张图就自动记"）；
    对不上或多条时把候选交回页面，让人点一下"是这家"。
    """
    r = parse_notice(text)
    if not r["ok"]:
        return {**r, "candidates": pd.DataFrame(), "applied_id": 0}
    cand = match_applies(uid, r["company"])
    r["candidates"] = cand
    if len(cand) == 1:
        aid = int(cand.iloc[0]["id"])
        w = add_event(uid, aid, r["kind"], r["when"], f"{evidence}:{r['company']}", 1)
        if w.get("ok"):
            r["applied_id"] = aid
            r["msg"] = (f"已记到「{cand.iloc[0]['岗位']}」，状态自动变为"
                        f"{KIND_LABEL.get(r['kind'], '')}")
    elif len(cand) > 1:
        r["msg"] = f"识别到 {len(cand)} 条同公司投递，选一条挂上"
    else:
        r["msg"] = "本账号没有这家公司的投递记录：先去 ⑦ 点「立即投递」，再来挂结果"
    return r


def delete_apply(uid, apply_id: int) -> int:
    """删一条投递（连带事件）。只能删自己的。"""
    u = _uid(uid)
    c = _conn()
    try:
        c.execute("DELETE FROM apply_event WHERE apply_id=? AND COALESCE(user_id,0)=?",
                  (int(apply_id), u))
        cur = c.execute("DELETE FROM apply_log WHERE id=? AND COALESCE(user_id,0)=?",
                        (int(apply_id), u))
        c.commit()
        return int(cur.rowcount)
    finally:
        c.close()


def legacy_import(uid, student: str, title: str, company: str = "", city: str = "",
                  status: str = "已投递", note: str = "", ts: str | None = None) -> int:
    """补记一条历史投递（没有 jd_id）：写事实 + 按旧状态回填事件。"""
    u = _uid(uid)
    ts = ts or _fmt(_now())
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO apply_log(user_id,student,title,company,city,status,note,ts,"
            "jd_id,match_rate,source,url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (u, str(student).strip() or "同学", str(title).strip()[:120], str(company)[:80],
             str(city)[:40], str(status)[:20], str(note)[:200], ts, None, None, "补记", ""))
        aid = int(cur.lastrowid)
        _backfill_events(c, u, aid, status, ts)
        c.commit()
        return aid
    finally:
        c.close()


def _backfill_events(c: sqlite3.Connection, uid: int, aid: int, status: str, ts: str) -> None:
    """按旧 status 回填事件流水（历史数据迁移用，幂等）。"""
    have = {r[0] for r in c.execute("SELECT kind FROM apply_event WHERE apply_id=?", (aid,))}
    now = _fmt(_now())

    def put(kind: str, when: str, ev: str) -> None:
        if kind in have:
            return
        c.execute("INSERT INTO apply_event(user_id,apply_id,kind,occurred_at,evidence,auto,note,created_at) "
                  "VALUES(?,?,?,?,?,?,?,?)", (uid, aid, kind, when, ev, 0, "", now))

    put("applied", ts, "历史补录")
    if status in ("已约面", "已面试", "已录用"):
        put("interview_invite", ts, "历史补录")
    if status in ("已面试", "已录用"):
        put("interview_done", ts, "历史补录")
    if status == "已录用":
        put("offer", ts, "历史补录")
    if status == "无回音":
        put("silent", ts, "历史补录")


def ensure_legacy() -> int:
    """老数据迁移：没有事件的旧投递按旧 status 回填事件（幂等，只在启动时补一次）。

    回填后 林小雨「4 投 2 约面」= 50% 与原有演示口径完全一致，逐字稿不用改。
    """
    c = _conn()
    try:
        rows = c.execute(
            "SELECT a.id, a.user_id, a.status, a.ts FROM apply_log a "
            "LEFT JOIN apply_event e ON e.apply_id = a.id WHERE e.id IS NULL").fetchall()
        for aid, u, status, ts in rows:
            _backfill_events(c, _uid(u), int(aid), str(status or "已投递"),
                             ts or _fmt(_now()))
        c.commit()
        return len(rows)
    finally:
        c.close()


# ================================================================ 推导
def _parse_dt(s: str) -> datetime | None:
    s = str(s or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(f) + 2].strip(), f)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def derive_status(applied_at: str, events: list[dict], now: datetime | None = None) -> dict:
    """状态 = f(投递时间, 事件流, 现在)。优先级：录用 > 拒信 > 面试过 > 约面 > 超时 > 投递。"""
    now = now or _now()
    kinds = [e.get("kind") for e in events]
    by = {e.get("kind"): e for e in events}
    silent = by.get("silent")
    active = any(k in kinds for k in ("assessment", "interview_invite",
                                      "interview_done", "offer", "rejected"))
    days = 0
    t0 = _parse_dt(applied_at)
    if t0:
        days = max((now - t0).days, 0)
    if "offer" in kinds:
        status, since = "已录用", by["offer"].get("occurred_at", "")
    elif "rejected" in kinds:
        status, since = "未通过", by["rejected"].get("occurred_at", "")
    elif "interview_done" in kinds:
        status, since = "已面试", by["interview_done"].get("occurred_at", "")
    elif "interview_invite" in kinds:
        status, since = "已约面", by["interview_invite"].get("occurred_at", "")
    elif silent or (days >= TIMEOUT_DAYS and not active):
        status, since = "无回音", (silent or {}).get("occurred_at", "")
    else:
        status, since = "已投递", applied_at
    return {"status": status, "since": since, "days": days,
            "timeout": status == "无回音", "kinds": kinds}


def _why(applied_at: str, events: list[dict], status: str) -> str:
    """一行依据：11-04 投递 · 11-08 面试邀请（截图）→ 已约面。"""
    parts = []
    for e in sorted(events, key=lambda x: str(x.get("occurred_at") or "")):
        k = e.get("kind")
        if k == "silent":
            continue
        d = str(e.get("occurred_at") or "")[5:10]
        ev = str(e.get("evidence") or "")
        src = ""
        if "截图" in ev:
            src = "（截图）"
        elif "邮件" in ev:
            src = "（邮件）"
        parts.append(f"{d} {KIND_LABEL.get(k, k)}{src}")
    if status == "无回音":
        parts.append(f"满 {TIMEOUT_DAYS} 天无正向信号")
    return " · ".join(parts) or "—"


def board(uid) -> pd.DataFrame:
    """本账号的投递流水（状态现算，不读旧 status 列）。"""
    u = _uid(uid)
    c = _conn()
    try:
        aps = pd.read_sql(
            "SELECT id, ts, title, company, city, jd_id, match_rate, source, url, user_id "
            "FROM apply_log WHERE COALESCE(user_id,0)=? ORDER BY id DESC", c, params=(u,))
        evs = pd.read_sql(
            "SELECT apply_id, kind, occurred_at, evidence FROM apply_event "
            "WHERE COALESCE(user_id,0)=? ORDER BY occurred_at", c, params=(u,))
    except sqlite3.Error:
        return pd.DataFrame()
    finally:
        c.close()
    if aps.empty:
        return pd.DataFrame(columns=["id", "时间", "岗位", "公司", "城市", "命中率",
                                     "状态", "依据", "来源", "jd_id", "url"])
    by_aid: dict[int, list[dict]] = {}
    for r in evs.itertuples():
        by_aid.setdefault(int(r.apply_id), []).append(
            {"kind": r.kind, "occurred_at": r.occurred_at, "evidence": r.evidence})
    rows = []
    for r in aps.itertuples():
        ev = by_aid.get(int(r.id), [])
        d = derive_status(r.ts, ev)
        rows.append({
            "id": int(r.id), "时间": str(r.ts)[:16], "岗位": r.title, "公司": r.company or "—",
            "城市": r.city or "—",
            "命中率": (f"{r.match_rate:.0%}" if isinstance(r.match_rate, (int, float)) else "—"),
            "状态": d["status"], "依据": _why(r.ts, ev, d["status"]),
            "来源": r.source or "补记", "jd_id": r.jd_id or "", "url": r.url or "",
            "投递天数": d["days"],
        })
    return pd.DataFrame(rows)


def stats(uid) -> dict:
    """四个数字全从这里出：已投递 / 约面·面试 / 已录用 / 无回音。"""
    df = board(uid)
    if df.empty:
        return {"n": 0, "interview": 0, "offer": 0, "no_reply": 0, "reject": 0,
                "pending": 0, "rate": 0.0, "rows": df}
    n = len(df)
    interview = int(df["状态"].isin(["已约面", "已面试", "已录用"]).sum())
    offer = int((df["状态"] == "已录用").sum())
    reject = int((df["状态"] == "未通过").sum())
    silent = int((df["状态"] == "无回音").sum())
    pending = int((df["状态"] == "已投递").sum())
    return {"n": n, "interview": interview, "offer": offer,
            "no_reply": silent + reject, "silent": silent, "reject": reject,
            "pending": pending, "rate": round(interview / n, 3) if n else 0.0,
            "rows": df}


def applied_jd_ids(uid) -> set[str]:
    c = _conn()
    try:
        return {str(r[0]) for r in c.execute(
            "SELECT jd_id FROM apply_log WHERE COALESCE(user_id,0)=? AND jd_id<>''",
            (_uid(uid),))}
    finally:
        c.close()


def timeout_sweep(uid, now: datetime | None = None) -> int:
    """14 天规则：满期且无正向信号 → 补一条 silent 事件（幂等，一天只补一次）。"""
    now = now or _now()
    df = board(uid)
    if df.empty:
        return 0
    u = _uid(uid)
    made = 0
    c = _conn()
    try:
        for r in df.itertuples():
            if r.状态 != "无回音":
                continue
            hit = c.execute("SELECT id FROM apply_event WHERE apply_id=? AND kind='silent'",
                            (int(r.id),)).fetchone()
            if hit:
                continue
            t0 = _parse_dt(r.时间)
            when = _fmt((t0 or now) + timedelta(days=TIMEOUT_DAYS))
            c.execute("INSERT INTO apply_event(user_id,apply_id,kind,occurred_at,evidence,auto,note,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (u, int(r.id), "silent", when, SILENT_RULE, 1,
                       f"投递满 {TIMEOUT_DAYS} 天无正向信号", _fmt(now)))
            made += 1
        c.commit()
    finally:
        c.close()
    return made


# ================================================================ 截图 OCR
_ENGINE = None
_OCR_ERR = ""


def ocr_available() -> tuple[bool, str]:
    """本地 OCR 是否可用（装了 rapidocr_onnxruntime 即可用，断网也能跑）。"""
    global _ENGINE, _OCR_ERR
    if _ENGINE is not None:
        return True, ""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        return True, ""
    except Exception as e:                        # pragma: no cover
        _OCR_ERR = f"{type(e).__name__}: {e}"
        return False, _OCR_ERR


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(data: bytes | str, max_side: int = 1600) -> dict:
    """图片 → 文字。失败时返回 {ok:False, msg}，页面回退到「粘贴通知文字」。"""
    ok, err = ocr_available()
    if not ok:
        return {"ok": False, "text": "", "msg": f"本机没装 OCR 引擎（{err}）"}
    try:
        import numpy as np
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:                   # 大图先缩，OCR 更快也更准
            k = max_side / max(w, h)
            img = img.resize((int(w * k), int(h * k)))
        arr = np.array(img)
        res, _ = _engine()(arr)
        lines = [str(r[1]) for r in (res or []) if r and len(r) > 1]
        return {"ok": bool(lines), "text": "\n".join(lines), "lines": lines,
                "msg": "" if lines else "图里没识别到文字，换一张清晰的截图"}
    except Exception as e:                        # pragma: no cover
        return {"ok": False, "text": "", "msg": f"识别失败：{type(e).__name__}: {e}"}
