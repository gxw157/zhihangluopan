"""成长档案：让职业规划"追得住"。

每次生成学习路径时可以保存一份快照（本人技能、命中率、缺口清单）。第二次生成时
自动对比："上学期你缺 8 项，现在缺 5 项，命中率从 41% 到 63%——你正在变强。"
学期叠比、命中率曲线、已补齐技能一目了然，直接产出可复用的成长证明材料。

存储：与分析快照同一个 SQLite（data/jobs.db），新增 career_snapshot 表，
按「账号 user_id + 学生姓名 + 专业 + 岗位族」一组档案，互不干扰。

数据隔离的钥匙是 user_id（登录账号），不是姓名：两个账号都叫「同学」也不会串档；
uid=None 时按 0 处理，兼容登录体系上线前的历史数据。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd

from core import analyze

DB = analyze.DB

DDL = """
CREATE TABLE IF NOT EXISTS career_snapshot(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT 0,
    student TEXT NOT NULL,
    major TEXT,
    major_code TEXT,
    family TEXT,
    have_json TEXT,
    n_held INTEGER,
    match REAL,
    n_gap INTEGER,
    gap_json TEXT,
    note TEXT,
    ts TEXT
)
"""


IV_DDL = """
CREATE TABLE IF NOT EXISTS interview_session(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT 0,
    student TEXT,
    family TEXT,
    persona TEXT,
    mode TEXT,
    n_turns INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    level TEXT,
    report_md TEXT,
    state_json TEXT,
    started_at TEXT,
    ended_at TEXT
)
"""

IV_TURN_DDL = """
CREATE TABLE IF NOT EXISTS interview_turn(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    seq INTEGER,
    role TEXT,
    kind TEXT,
    content TEXT,
    score INTEGER DEFAULT 0,
    dims_json TEXT,
    ts TEXT
)
"""


APPLY_DDL = """
CREATE TABLE IF NOT EXISTS apply_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT 0,
    student TEXT NOT NULL,
    title TEXT,
    company TEXT,
    city TEXT,
    status TEXT,
    note TEXT,
    ts TEXT
)
"""


def _uid(uid) -> int:
    try:
        return int(uid or 0)
    except (TypeError, ValueError):
        return 0


def _migrate(c: sqlite3.Connection, table: str) -> None:
    """老库补 user_id 列（登录体系上线前的数据归到 0 号，仍能看）。"""
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if "user_id" not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 0")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_uid ON {table}(user_id)")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute(DDL)
    c.execute(APPLY_DDL)
    c.execute(IV_DDL)
    c.execute(IV_TURN_DDL)
    _migrate(c, "career_snapshot")
    # 老库补 source 列：标记快照来源（③手动定位 / ④补课清单勾选提交），默认归"定位"
    _cols = [r[1] for r in c.execute("PRAGMA table_info(career_snapshot)").fetchall()]
    if "source" not in _cols:
        c.execute("ALTER TABLE career_snapshot ADD COLUMN source TEXT DEFAULT '定位'")
    _migrate(c, "apply_log")
    _migrate(c, "interview_session")
    c.commit()
    return c


def save_snapshot(student: str, lp: dict, have: list[str], note: str = "",
                  ts: str | None = None, uid: int | None = None,
                  source: str = "定位") -> int:
    """保存一次定位快照，返回快照 id。lp 是 pathway.build_path 的结果。

    ts：可选，自定义记录时间（格式 YYYY-MM-DD HH:MM:SS），用于补录或演示数据。
    uid：登录账号 id，数据按它隔离；不传则归到 0 号（历史数据）。
    source：快照来源——「定位」=③手动保存；「补课勾选」=④补课清单勾选提交，
            ⑤档案据此区分进步从哪来。
    """
    if not lp or not lp.get("ok"):
        return 0
    gap = lp["gap"][["技能", "岗位数", "课程覆盖"]].to_dict("records")
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO career_snapshot(user_id,student,major,major_code,family,have_json,"
            "n_held,match,n_gap,gap_json,note,ts,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_uid(uid),
             str(student).strip() or "同学",
             str(lp.get("major", "")), str(lp.get("major_code", "")),
             str(lp.get("family", "") or ""), json.dumps(have, ensure_ascii=False),
             int(len(have or [])), float(lp.get("match", 0)),
             int(len(lp.get("gap", []))), json.dumps(gap, ensure_ascii=False),
             str(note or "")[:200],
             ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "补课勾选" if "勾选" in str(source) else "定位"))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def rename_student(uid: int | None, new_name: str) -> int:
    """改名：把本账号下所有记录的主人名一起改掉。

    隔离钥匙是 user_id，姓名只是显示标签；不跟着改，学生改个名就会「看不见」自己的档案。
    返回改动的记录数（快照 + 投递）。
    """
    nm = str(new_name or "").strip()
    if not nm:
        return 0
    c = _conn()
    try:
        n = c.execute("UPDATE career_snapshot SET student=? WHERE COALESCE(user_id,0)=?",
                      (nm, _uid(uid))).rowcount
        n += c.execute("UPDATE apply_log SET student=? WHERE COALESCE(user_id,0)=?",
                       (nm, _uid(uid))).rowcount
        c.commit()
        return int(n)
    finally:
        c.close()


def list_snapshots(student: str, uid: int | None = None) -> pd.DataFrame:
    """某位学生的全部快照，旧→新。"""
    c = _conn()
    try:
        df = pd.read_sql(
            "SELECT id, ts AS 时间, major AS 专业, family AS 岗位族, n_held AS 已会技能数, "
            "match AS 命中率, n_gap AS 缺口数, COALESCE(source,'定位') AS 来源, note AS 备注 "
            "FROM career_snapshot WHERE student=? AND COALESCE(user_id,0)=? ORDER BY id",
            c, params=(str(student), _uid(uid)))
    except sqlite3.Error:
        df = pd.DataFrame()
    finally:
        c.close()
    return df


def delete_snapshot(sid: int, uid: int | None = None) -> int:
    """删除一条定位快照，返回受影响行数（0 = 不是这个账号的记录）。

    只删快照，不动 ③ 里当前的定位状态：删的是档案里的一条历史事实，
    不是把"现在的你"退回去。删完 compare / history / 曲线自动重算。
    """
    c = _conn()
    try:
        cur = c.execute("DELETE FROM career_snapshot WHERE id=? AND COALESCE(user_id,0)=?",
                        (int(sid), _uid(uid)))
        c.commit()
        return int(cur.rowcount)
    finally:
        c.close()


def compare(student: str, uid: int | None = None) -> dict:
    """最近两次快照对比：命中率变化、已补齐技能、新出现的缺口、快增项。"""
    c = _conn()
    try:
        rows = pd.read_sql(
            "SELECT * FROM career_snapshot WHERE student=? AND COALESCE(user_id,0)=? "
            "ORDER BY id DESC LIMIT 2",
            c, params=(str(student), _uid(uid))).iloc[::-1]
    except sqlite3.Error:
        rows = pd.DataFrame()
    finally:
        c.close()
    if len(rows) < 2:
        return {"ok": False, "msg": "快照不足两份——每次生成路径后点「存入成长档案」，下次就有对比了"}
    prev, now = rows.iloc[0], rows.iloc[1]
    prev_gaps = {g["技能"] for g in json.loads(prev["gap_json"] or "[]")}
    now_gaps = {g["技能"] for g in json.loads(now["gap_json"] or "[]")}
    fixed = sorted(prev_gaps - now_gaps)
    new_gap = sorted(now_gaps - prev_gaps)
    # 本次补齐的技能打上来源标记：最新一份快照若是④补课清单勾选提交的，
    # 这些"补齐"就是清单打卡的成果，档案里要能看出来进步从哪来。
    src_now = str(now.get("source") or "定位")
    fixed_src = "④补课清单提交" if "勾选" in src_now else "重新定位"
    d_match = float(now["match"]) - float(prev["match"])
    t1 = datetime.strptime(str(prev["ts"]), "%Y-%m-%d %H:%M:%S")
    t2 = datetime.strptime(str(now["ts"]), "%Y-%m-%d %H:%M:%S")
    days = max((t2 - t1).days, 0)
    fam_prev = str(prev.get("family") or "")
    fam_now = str(now.get("family") or "")
    fam_changed = bool(fam_prev and fam_now and fam_prev != fam_now)
    # 口径：这是"最近一次记录比上一次"的历史事实，不是当前状态。
    # 旧文案"距上次记录…——你正在变强"像刚发生的事，反复进页面会重放同一句，被当成缓存。
    headline = (f"最近一次记录（{t2:%m月%d日 %H:%M}）比上一次（{t1:%m月%d日}，{days} 天前）："
                f"命中率 {prev['match']:.0%} → {now['match']:.0%}"
                f"（{'↑' if d_match >= 0 else '↓'}{abs(d_match):.0%}），"
                f"缺口 {prev['n_gap']} → {now['n_gap']} 项。"
                + (f"补齐 {'、'.join(fixed[:6])}（来自{fixed_src}）。" if fixed else "")
                + (f"新增缺口 {len(new_gap)} 项。" if new_gap else ""))
    if fam_changed:
        # 换了目标方向，两次命中率不是同一把尺子：必须说明，否则会被读成"退步了"
        headline += (f"（注意：目标方向从「{fam_prev}」换成了「{fam_now}」，"
                     "两次命中率口径不同，不宜直接比高低）")
    return {"ok": True, "headline": headline, "d_match": d_match,
            "fixed": fixed, "fixed_src": fixed_src, "src_now": src_now,
            "new_gap": new_gap, "days": days,
            "t_prev": f"{t1:%Y-%m-%d %H:%M}", "t_now": f"{t2:%Y-%m-%d %H:%M}",
            "fam_changed": fam_changed, "fam_prev": fam_prev, "fam_now": fam_now,
            "prev": prev.to_dict(), "now": now.to_dict()}


def history(student: str, uid: int | None = None) -> pd.DataFrame:
    """命中率曲线数据：时间 x 命中率 x 缺口数（含来源，供曲线区分定位/补课提交）。"""
    c = _conn()
    try:
        df = pd.read_sql(
            "SELECT ts, match, n_gap, n_held, COALESCE(source,'定位') AS source "
            "FROM career_snapshot "
            "WHERE student=? AND COALESCE(user_id,0)=? ORDER BY id",
            c, params=(str(student), _uid(uid)))
    except sqlite3.Error:
        df = pd.DataFrame()
    finally:
        c.close()
    return df


def export_markdown(student: str, uid: int | None = None) -> str:
    """整份成长档案导出为 Markdown（可作求职、实习与成长记录材料）。"""
    snaps = list_snapshots(student, uid)
    cmp_ = compare(student, uid)
    L = [f"# 成长档案 · {student}\n",
         f"> 生成时间 {datetime.now():%Y-%m-%d %H:%M} · 共 {len(snaps)} 次定位记录。"
         "所有数字来自职航罗盘平台引擎，可追溯。\n"]
    if cmp_.get("ok"):
        L += ["## 最新变化\n", cmp_["headline"], ""]
    if len(snaps):
        L += ["## 定位记录\n", "| 时间 | 专业 | 目标方向 | 已会技能 | 命中率 | 缺口 | 来源 | 备注 |",
              "|---|---|---|---|---|---|---|---|"]
        for r in snaps.itertuples():
            L.append(f"| {r.时间} | {r.专业} | {r.岗位族 or '全部'} | {r.已会技能数} | "
                     f"{r.命中率:.0%} | {r.缺口数} | {getattr(r, '来源', '定位') or '定位'} | "
                     f"{r.备注 or '—'} |")
        L.append("")
    else:
        L.append("还没有定位记录。在「③ 我的定位」生成路径后点「存入成长档案」。")
    return "\n".join(L)


# ================================================================ 投递记录（求职实战）
STATUSES = ["已投递", "已约面", "已面试", "已录用", "无回音"]


def save_application(student: str, title: str, company: str = "", city: str = "",
                     status: str = "已投递", note: str = "", uid: int | None = None) -> int:
    """记一条投递。返回 id；标题为空则不记。"""
    if not str(title or "").strip():
        return 0
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO apply_log(user_id,student,title,company,city,status,note,ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (_uid(uid), str(student).strip() or "同学", str(title).strip()[:120],
             str(company)[:80], str(city)[:40], str(status)[:20], str(note)[:200],
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def list_applications(student: str, uid: int | None = None) -> pd.DataFrame:
    c = _conn()
    try:
        df = pd.read_sql(
            "SELECT id, ts AS 时间, title AS 岗位, company AS 公司, city AS 城市, "
            "status AS 状态, note AS 备注 FROM apply_log "
            "WHERE student=? AND COALESCE(user_id,0)=? ORDER BY id DESC",
            c, params=(str(student), _uid(uid)))
    except sqlite3.Error:
        df = pd.DataFrame()
    finally:
        c.close()
    return df


def apply_stats(student: str, uid: int | None = None) -> dict:
    """投递转化：投了几家、几个约面、几个录用。"""
    df = list_applications(student, uid)
    if df.empty:
        return {"n": 0, "interview": 0, "offer": 0, "no_reply": 0, "rate": 0.0}
    n = len(df)
    interview = int(df["状态"].isin(["已约面", "已面试", "已录用"]).sum())
    offer = int((df["状态"] == "已录用").sum())
    no_reply = int((df["状态"] == "无回音").sum())
    return {"n": n, "interview": interview, "offer": offer, "no_reply": no_reply,
            "rate": round(interview / n, 3) if n else 0.0}


def delete_application(app_id: int, uid: int | None = None) -> int:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM apply_log WHERE id=? AND COALESCE(user_id,0)=?",
                        (int(app_id), _uid(uid)))
        c.commit()
        return int(cur.rowcount)
    finally:
        c.close()


# ================================================================ 模拟面试记录
def save_interview(student: str, st: dict, uid: int | None = None) -> int:
    """保存/更新一场模拟面试，返回 session id。

    st 是 core.interview 的 state：第一次存会 INSERT 并回填 st["sid"]，
    之后每答完一轮再调一次就 UPDATE——刷新页面能接着面，报告定稿也在这里落库。
    turns 表每次先删后插（一场面试最多十几轮，代价可以忽略）。
    """
    if not st:
        return 0
    from core import interview as IV

    ov = IV.overall(st)
    sid = int(st.get("sid") or 0)
    payload = (str(student).strip() or "同学", str(st.get("family", "")),
               str(st.get("persona", "")), str(st.get("mode", "rules")),
               int(len(st.get("scores") or [])), float(ov["score"]), str(ov["level"]),
               str(st.get("report") or ""), json.dumps(st, ensure_ascii=False),
               str(st.get("started_at", "")), str(st.get("ended_at", "")))
    c = _conn()
    try:
        if sid:
            owned = c.execute(
                "SELECT 1 FROM interview_session WHERE id=? AND COALESCE(user_id,0)=?",
                (sid, _uid(uid))).fetchone()
            if not owned:          # 不是这个账号的记录，绝不能改
                sid = 0
        if sid:
            c.execute("UPDATE interview_session SET student=?,family=?,persona=?,mode=?,n_turns=?,"
                      "score=?,level=?,report_md=?,state_json=?,started_at=?,ended_at=? WHERE id=?",
                      payload + (sid,))
        else:
            cur = c.execute(
                "INSERT INTO interview_session(user_id,student,family,persona,mode,n_turns,score,"
                "level,report_md,state_json,started_at,ended_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (_uid(uid),) + payload)
            sid = int(cur.lastrowid)
            st["sid"] = sid

        c.execute("DELETE FROM interview_turn WHERE session_id=?", (sid,))
        scores = st.get("scores") or []
        seq, rows = 0, []
        turn_score = {i: r.get("score", 0) for i, r in enumerate(scores)}
        q_i = -1
        for t in (st.get("turns") or []):
            if t.get("kind") == "answer":
                q_i += 1
            rows.append((sid, seq, str(t.get("role", "")), str(t.get("kind", "")),
                         str(t.get("text", ""))[:2000],
                         int(turn_score.get(q_i, 0)) if t.get("kind") == "answer" else 0,
                         json.dumps((scores[q_i]["dims"] if t.get("kind") == "answer"
                                     and 0 <= q_i < len(scores) else {}), ensure_ascii=False),
                         str(st.get("started_at", ""))))
            seq += 1
        if rows:
            c.executemany(
                "INSERT INTO interview_turn(session_id,seq,role,kind,content,score,dims_json,ts) "
                "VALUES(?,?,?,?,?,?,?,?)", rows)
        c.commit()
        return sid
    finally:
        c.close()


def list_interviews(student: str, uid: int | None = None) -> pd.DataFrame:
    """本账号的历史面试（新→旧）。换账号看不到别人的。"""
    c = _conn()
    try:
        df = pd.read_sql(
            "SELECT id, substr(COALESCE(ended_at,started_at),1,16) AS 时间, family AS 方向, "
            "persona AS 面试官, n_turns AS 题数, score AS 得分, level AS 评价 "
            "FROM interview_session WHERE student=? AND COALESCE(user_id,0)=? "
            "AND COALESCE(report_md,'')<>'' ORDER BY id DESC",
            c, params=(str(student), _uid(uid)))
    except sqlite3.Error:
        df = pd.DataFrame()
    finally:
        c.close()
    return df


def load_interview(sid: int, uid: int | None = None) -> dict:
    """读回一场面试：{ok, report, state}。只读本账号的。"""
    c = _conn()
    try:
        row = c.execute(
            "SELECT report_md, state_json FROM interview_session "
            "WHERE id=? AND COALESCE(user_id,0)=?", (int(sid), _uid(uid))).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        c.close()
    if not row:
        return {"ok": False, "msg": "没有这条记录（可能不属于当前账号）"}
    try:
        state = json.loads(row[1] or "{}")
    except Exception:
        state = {}
    return {"ok": True, "report": row[0] or "", "state": state}


def pending_interview(student: str, uid: int | None = None) -> dict:
    """最近一场没走完的面试（刷新/断线后接着面用）；没有则 ok=False。

    只认本账号、且还没定稿（report_md 为空）的那场——已经出过报告的不能续，
    否则学生点进来会看到一份旧报告当成新的。
    """
    c = _conn()
    try:
        row = c.execute(
            "SELECT id, state_json, started_at FROM interview_session "
            "WHERE student=? AND COALESCE(user_id,0)=? AND COALESCE(report_md,'')='' "
            "ORDER BY id DESC LIMIT 1",
            (str(student), _uid(uid))).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        c.close()
    if not row:
        return {"ok": False}
    try:
        state = json.loads(row[1] or "{}")
    except Exception:
        state = {}
    if not state or state.get("stage") == "report":
        return {"ok": False}
    return {"ok": True, "sid": int(row[0]), "state": state,
            "started_at": row[2] or "", "idx": int(state.get("idx", 0)) + 1,
            "n": len(state.get("qs") or [])}


def delete_interview(sid: int, uid: int | None = None) -> int:
    """删掉一场面试（放弃本场时清掉半截记录，别让历史列表里堆垃圾行）。"""
    if not sid:
        return 0
    c = _conn()
    try:
        c.execute("DELETE FROM interview_turn WHERE session_id=?", (int(sid),))
        n = c.execute("DELETE FROM interview_session WHERE id=? AND COALESCE(user_id,0)=?",
                      (int(sid), _uid(uid))).rowcount
        c.commit()
        return int(n)
    finally:
        c.close()
