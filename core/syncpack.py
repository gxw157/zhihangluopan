"""账号数据同步包：同一账号在不同电脑之间迁移数据（导出 JSON → 另一台导入合并）。

背景：业务数据存在本机 data/jobs.db（SQLite，离线可用是卖点），换一台电脑登录
同一个账号不会自动带数据过来。本模块把「属于这个账号的数据」打包成一个 JSON
文件（同步包），拷到另一台电脑后用同一账号登录、导入合并，两边数据即完全一致。

打包范围（全部带 user_id 隔离钥匙的表）：
    career_snapshot   成长档案定位快照（③④⑤ 的数据源）
    apply_log         投递事实（⑦ 投递看板）
    apply_event       投递事件流水（状态推导的依据）
    interview_session 模拟面试会话（⑥ 历史记录）
    interview_turn    面试逐轮对话

合并规则（幂等，重复导入不会产生双份）：
    快照按 (记录时间, 岗位族, 备注) 判重；投递按 (投递时间, 岗位) 判重；
    事件按 (所属投递, 类型, 发生时间) 判重；面试会话按 (开始时间) 判重。
导入时所有数据都挂到「当前登录账号」的 user_id 上——同步包里不写死账号 id，
换库后 id 不同也能正确归属。

使用：⑧ 工程后台 → 账号与登录 → 跨电脑同步。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402

PACK_TYPE = "zhihang-luopan-syncpack"
PACK_VERSION = 1


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(A.DB)
    c.row_factory = sqlite3.Row
    return c


def _rows(c: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


# ================================================================ 导出
def export(uid: int) -> dict:
    """把某账号的全部业务数据打成同步包字典（不含会话/密码等敏感信息）。"""
    u = int(uid or 0)
    c = _conn()
    try:
        snaps = _rows(c, "SELECT * FROM career_snapshot WHERE COALESCE(user_id,0)=? ORDER BY ts",
                      (u,))
        applies = _rows(c, "SELECT * FROM apply_log WHERE COALESCE(user_id,0)=? ORDER BY ts", (u,))
        events = _rows(c, "SELECT * FROM apply_event WHERE COALESCE(user_id,0)=? "
                          "ORDER BY apply_id, occurred_at", (u,))
        ivs = _rows(c, "SELECT * FROM interview_session WHERE COALESCE(user_id,0)=? "
                       "ORDER BY started_at", (u,))
        sids = [int(r["id"]) for r in ivs]
        turns = []
        if sids:
            q = ",".join("?" * len(sids))
            turns = _rows(c, f"SELECT * FROM interview_turn WHERE session_id IN ({q}) "
                             "ORDER BY session_id, seq", sids)
    finally:
        c.close()
    return {
        "type": PACK_TYPE,
        "version": PACK_VERSION,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_hint": "",            # 由页面层填显示用账号，不参与合并判断
        "career_snapshot": snaps,
        "apply_log": applies,
        "apply_event": events,
        "interview_session": ivs,
        "interview_turn": turns,
    }


def export_json(uid: int, account_hint: str = "") -> bytes:
    pack = export(uid)
    pack["account_hint"] = str(account_hint or "")
    return json.dumps(pack, ensure_ascii=False, indent=1).encode("utf-8")


# ================================================================ 导入
def _strip(row: dict, drop: tuple[str, ...]) -> dict:
    return {k: v for k, v in row.items() if k not in drop}


def import_pack(uid: int, payload: dict) -> dict:
    """把同步包合并进当前账号（uid 为当前登录账号的 id）。幂等，返回合并统计。"""
    u = int(uid or 0)
    if u <= 0:
        return {"ok": False, "msg": "请先登录再导入", "added": {}, "skipped": 0}
    if not isinstance(payload, dict) or payload.get("type") != PACK_TYPE:
        return {"ok": False, "msg": "这不是职航罗盘的同步包文件（type 不对）", "added": {},
                "skipped": 0}

    snaps = payload.get("career_snapshot") or []
    applies = payload.get("apply_log") or []
    events = payload.get("apply_event") or []
    ivs = payload.get("interview_session") or []
    turns = payload.get("interview_turn") or []

    added = {"快照": 0, "投递": 0, "事件": 0, "面试会话": 0, "面试对话": 0}
    skipped = 0
    c = _conn()
    try:
        # ---- ① 成长档案快照：按 (ts, family, note) 判重
        old = {(r["ts"], r["family"], r["note"] or "")
               for r in _rows(c, "SELECT ts, family, note FROM career_snapshot "
                                 "WHERE COALESCE(user_id,0)=?", (u,))}
        for r in snaps:
            s = _strip(r, ("id", "user_id"))
            key = (s.get("ts"), s.get("family") or "", s.get("note") or "")
            if key in old:
                skipped += 1
                continue
            c.execute("INSERT INTO career_snapshot(user_id,student,major,major_code,family,"
                      "have_json,n_held,match,n_gap,gap_json,note,ts,source) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (u, s.get("student") or "同学", s.get("major") or "",
                       s.get("major_code") or "", s.get("family") or "",
                       s.get("have_json") or "[]", s.get("n_held") or 0,
                       s.get("match") or 0, s.get("n_gap") or 0,
                       s.get("gap_json") or "[]", s.get("note") or "",
                       s.get("ts") or "", s.get("source") or "定位"))
            added["快照"] += 1
            old.add(key)

        # ---- ② 投递事实：按 (ts, title) 判重；旧 id → 新 id 供事件挂靠
        aid_map: dict[int, int] = {}
        old_ap = {(r["ts"], r["title"]) for r in _rows(c, "SELECT ts, title FROM apply_log "
                                                          "WHERE COALESCE(user_id,0)=?", (u,))}
        for r in applies:
            s = _strip(r, ("id", "user_id"))
            key = (s.get("ts"), s.get("title") or "")
            if key in old_ap:
                # 已有同一条投递：把旧 id 映射到现有行，事件照常判重后挂上来
                row = c.execute("SELECT id FROM apply_log WHERE COALESCE(user_id,0)=? "
                                "AND ts=? AND title=?", (u, key[0], key[1])).fetchone()
                if row:
                    aid_map[int(r["id"])] = int(row[0])
                skipped += 1
                continue
            cur = c.execute("INSERT INTO apply_log(user_id,student,title,company,city,status,"
                            "note,ts,jd_id,match_rate,source,url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (u, s.get("student") or "同学", s.get("title") or "",
                             s.get("company") or "", s.get("city") or "",
                             s.get("status") or "已投递", s.get("note") or "",
                             s.get("ts") or "", s.get("jd_id"), s.get("match_rate"),
                             s.get("source") or "补记", s.get("url") or ""))
            new_id = int(cur.lastrowid)
            aid_map[int(r["id"])] = new_id
            added["投递"] += 1
            old_ap.add(key)

        # ---- ③ 投递事件：按 (apply_id 新 id, kind, occurred_at) 判重
        old_ev = {(r["apply_id"], r["kind"], r["occurred_at"])
                  for r in _rows(c, "SELECT apply_id, kind, occurred_at FROM apply_event "
                                    "WHERE COALESCE(user_id,0)=?", (u,))}
        for r in events:
            s = _strip(r, ("id", "user_id"))
            old_aid = int(s.get("apply_id") or 0)
            new_aid = aid_map.get(old_aid)
            if not new_aid:
                skipped += 1        # 对不上本地投递（比如包被手工裁剪过），跳过
                continue
            key = (new_aid, s.get("kind") or "", s.get("occurred_at") or "")
            if key in old_ev:
                skipped += 1
                continue
            c.execute("INSERT INTO apply_event(user_id,apply_id,kind,occurred_at,evidence,"
                      "auto,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (u, new_aid, s.get("kind") or "", s.get("occurred_at") or "",
                       s.get("evidence") or "", int(s.get("auto") or 0),
                       s.get("note") or "", s.get("created_at") or ""))
            added["事件"] += 1
            old_ev.add(key)

        # ---- ④ 面试会话：按 (started_at) 判重；旧 sid → 新 sid
        sid_map: dict[int, int] = {}
        old_iv = {r["started_at"] for r in _rows(c, "SELECT started_at FROM interview_session "
                                                   "WHERE COALESCE(user_id,0)=?", (u,))}
        for r in ivs:
            s = _strip(r, ("id", "user_id"))
            key = s.get("started_at") or ""
            if key in old_iv:
                row = c.execute("SELECT id FROM interview_session WHERE COALESCE(user_id,0)=? "
                                "AND started_at=?", (u, key)).fetchone()
                if row:
                    sid_map[int(r["id"])] = int(row[0])
                skipped += 1
                continue
            cur = c.execute("INSERT INTO interview_session(user_id,student,family,persona,mode,"
                            "n_turns,score,level,report_md,state_json,started_at,ended_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (u, s.get("student") or "同学", s.get("family") or "",
                             s.get("persona") or "", s.get("mode") or "rules",
                             s.get("n_turns") or 0, s.get("score") or 0,
                             s.get("level") or "", s.get("report_md") or "",
                             s.get("state_json") or "{}", key, s.get("ended_at") or ""))
            new_sid = int(cur.lastrowid)
            sid_map[int(r["id"])] = new_sid
            # state_json 里存着旧会话 sid，改成新 id，防止续聊/回放对不上
            try:
                st_json = json.loads(s.get("state_json") or "{}")
                if isinstance(st_json, dict) and st_json.get("sid"):
                    st_json["sid"] = new_sid
                    c.execute("UPDATE interview_session SET state_json=? WHERE id=?",
                              (json.dumps(st_json, ensure_ascii=False), new_sid))
            except (ValueError, TypeError):
                pass
            added["面试会话"] += 1
            old_iv.add(key)

        # ---- ⑤ 面试逐轮对话：按旧 session_id 映射，按 (新 sid, seq) 判重
        for r in turns:
            old_sid = int(r.get("session_id") or 0)
            new_sid = sid_map.get(old_sid)
            if not new_sid:
                skipped += 1
                continue
            dup = c.execute("SELECT 1 FROM interview_turn WHERE session_id=? AND seq=? "
                            "LIMIT 1", (new_sid, r.get("seq") or 0)).fetchone()
            if dup:
                skipped += 1
                continue
            c.execute("INSERT INTO interview_turn(session_id,seq,role,kind,content,score,"
                      "dims_json,ts) VALUES(?,?,?,?,?,?,?,?)",
                      (new_sid, r.get("seq") or 0, r.get("role") or "", r.get("kind") or "",
                       r.get("content") or "", r.get("score") or 0,
                       r.get("dims_json") or "{}", r.get("ts") or ""))
            added["面试对话"] += 1

        c.commit()
    except sqlite3.Error as e:
        c.rollback()
        return {"ok": False, "msg": f"导入失败：{e}", "added": {}, "skipped": skipped}
    finally:
        c.close()

    n = sum(added.values())
    return {"ok": True, "added": added, "skipped": skipped,
            "msg": f"导入完成：新增 {n} 条（" +
                   "、".join(f"{k} {v}" for k, v in added.items()) +
                   f"），跳过重复 {skipped} 条"}
