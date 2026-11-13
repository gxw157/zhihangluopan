"""演示账号数据自动播种：换一台电脑登录同一个演示账号，档案数据自动补齐、保持一致。

背景：业务数据全部存在本机 data/jobs.db（SQLite）。把项目拷到另一台电脑（或只用
干净库启动）时，users 表会由 ensure_demo_users() 重建三个演示账号，但成长档案
（career_snapshot）和投递记录（apply_log / apply_event）是空的——同一账号在
不同电脑上看到的数据不一样。

本模块把演示剧本数据（与 tools/seed_demo.py、参赛逐字稿口径完全一致）内置成
「种子」，登录演示账号时自动检查：该账号的档案 / 投递为空就按固定剧本补齐。
幂等：有数据就一个字都不动，绝不重复写入、不覆盖现场新产生的真实记录。

    - 林小雨（13800000001）：4 次定位快照（命中率爬升）+ 4 投 2 约面 = 50%
    - 陈子昂（13800000002）：3 次定位快照 + 1 条已面试投递
    - 周乐（13800000003）：3 次定位快照

真实注册的账号不走本模块（播种只认 DEMO_USERS 白名单）。
模拟面试记录是现场生成的（演示模式不落库），不参与播种。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402

# ---------------------------------------------------------------- 剧本数据
# 跨学期定位快照（与 tools/seed_demo.py 同一份剧本；逐字稿引用的命中率数字出自这里）
DEMO_STEPS = {
    "13800000001": dict(name="林小雨", major="人工智能技术应用", family="数据分析",
                        steps=[("2026-03-12 10:00:00", ["Python"],
                                "大一上·第一次定位：先看清方向"),
                               ("2026-05-20 15:30:00", ["Python", "Excel", "SQL"],
                                "大一下·学完数据库基础"),
                               ("2026-09-18 09:20:00", ["Python", "Excel", "SQL", "数据分析"],
                                "大二上·课程项目做了一次完整的漏斗分析"),
                               ("2026-11-02 16:40:00", ["Python", "Excel", "SQL", "数据分析",
                                                        "数据挖掘", "BI工具"],
                                "现在·准备投实习")]),
    "13800000002": dict(name="陈子昂", major="大数据技术", family="数据开发",
                        steps=[("2026-04-08 14:10:00", ["Python", "SQL"],
                                "大一下·刚学完数据库"),
                               ("2026-07-01 11:00:00", ["Python", "SQL", "Java"],
                                "暑假·自己搭了个小集群"),
                               ("2026-10-20 19:30:00", ["Python", "SQL", "Java", "Spark",
                                                        "Flink", "数据仓库"],
                                "现在·课程设计做了数仓分层")]),
    "13800000003": dict(name="周乐", major="软件技术", family="后端",
                        steps=[("2026-05-06 09:40:00", ["Java"],
                                "大一下·刚入门 Java"),
                               ("2026-08-12 20:15:00", ["Java", "MySQL", "Git"],
                                "暑假·写完第一个 CRUD 项目"),
                               ("2026-10-28 10:05:00", ["Java", "MySQL", "Git", "Spring Boot",
                                                        "Redis", "Linux"],
                                "现在·准备投后端实习")]),
}

# 演示投递剧本（账号, 标题, 公司, 城市, 当时状态, 投递时间）——
# 林小雨 4 投 2 约面 = 50%，与逐字稿口径一致；事件由 apply.legacy_import 按
# 状态自动回填（applied / interview_invite / interview_done）。
DEMO_APPLIES = [
    ("13800000001", "数据分析实习生", "郑州某科技有限公司", "郑州", "已约面",
     "2026-11-04 21:31:21"),
    ("13800000001", "数据运营实习生", "北京某电商公司", "北京", "已投递",
     "2026-11-04 21:31:21"),
    ("13800000001", "数据分析", "", "郑州", "已投递", "2026-11-05 14:24:25"),
    ("13800000001", "大模型", "", "郑州", "已约面", "2026-11-05 14:24:33"),
    ("13800000002", "大数据开发实习生", "深圳某数据科技", "深圳", "已面试",
     "2026-11-04 21:31:21"),
]

DEMO_ACCOUNTS = {p for p in DEMO_STEPS}


def _count(c: sqlite3.Connection, table: str, uid: int) -> int:
    return int(c.execute(f"SELECT COUNT(*) FROM {table} WHERE COALESCE(user_id,0)=?",
                         (uid,)).fetchone()[0])


def seed_demo_account(user: dict) -> dict:
    """给一个演示账号补齐剧本数据（幂等：对应表非空就跳过该域）。

    user 是 auth 返回的用户字典（至少含 id / account / nickname / major）。
    返回 {"ok": bool, "msg": str, "snapshots": int, "applies": int}
    snapshots/applies 是本次新写入的条数（0 = 本来就有数据，没动）。
    """
    acc = str((user or {}).get("account") or "")
    uid = int((user or {}).get("id") or 0)
    if acc not in DEMO_ACCOUNTS or uid <= 0:
        return {"ok": False, "msg": "不是演示账号，跳过播种", "snapshots": 0, "applies": 0}
    spec = DEMO_STEPS[acc]
    name = str(user.get("nickname") or spec["name"])
    n_snap = n_app = 0

    c = sqlite3.connect(A.DB)
    try:
        # 新库可能还没建这两张表：查不到就当 0 条（写入时由各自模块负责建表）
        try:
            has_snap = _count(c, "career_snapshot", uid)
        except sqlite3.Error:
            has_snap = 0
        try:
            has_app = _count(c, "apply_log", uid)
        except sqlite3.Error:
            has_app = 0
        need_snap, need_app = has_snap == 0, has_app == 0
    finally:
        c.close()

    # ① 成长档案：按剧本逐次定位（数据由平台真实计算，只是把时间补录到过去）
    if need_snap:
        for ts, have, note in spec["steps"]:
            lp = PW.build_path(have, spec["family"], top=12, major=spec["major"])
            if not lp.get("ok"):
                continue
            PF.save_snapshot(name, lp, have, note, ts=ts, uid=uid)
            n_snap += 1

    # ② 投递记录：写事实 + 按状态回填事件流水（状态推导口径与现网一致）
    if need_app:
        from core import apply as AP  # 延迟导入，避免模块加载顺序问题
        for account, title, company, city, status, ts in DEMO_APPLIES:
            if account != acc:
                continue
            AP.legacy_import(uid, name, title, company=company, city=city,
                             status=status, note="", ts=ts)
            n_app += 1

    if n_snap or n_app:
        return {"ok": True, "msg": f"演示档案已自动补齐（快照 {n_snap} 条、投递 {n_app} 条）",
                "snapshots": n_snap, "applies": n_app}
    return {"ok": True, "msg": "演示账号已有数据，未改动", "snapshots": 0, "applies": 0}
