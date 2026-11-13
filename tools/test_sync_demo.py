"""测试：演示账号自动播种（core/demo_seed.py）+ 账号数据同步包（core/syncpack.py）。

    .venv/Scripts/python tools/test_sync_demo.py

测试用临时账号挂在真实库上，结束后 atexit 自动清理（用户 + 全部业务行）。
"""
from __future__ import annotations

import atexit
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import auth as AU  # noqa: E402
from core import demo_seed as DSD  # noqa: E402
from core import profile as PF  # noqa: E402
from core import syncpack as SP  # noqa: E402

PASS, FAIL = 0, 0
# 记录原始剧本规模（后面测试会往 DEMO_APPLIES 里追加测试条目，别污染断言）
N_DEMO_APPLIES = len(DSD.DEMO_APPLIES)
DEMO_APPLY_ACCOUNTS = {a for a, *_ in DSD.DEMO_APPLIES}


def ok(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")


def _uid_of(account: str) -> int:
    c = sqlite3.connect(A.DB)
    try:
        row = c.execute("SELECT id FROM users WHERE account=?", (account,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        c.close()


def _clean(account: str) -> None:
    uid = _uid_of(account)
    c = sqlite3.connect(A.DB)
    try:
        for t in ("career_snapshot", "apply_log", "apply_event",
                  "interview_session", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE COALESCE(user_id,0)=?", (uid,))
        c.execute("DELETE FROM interview_turn WHERE session_id NOT IN "
                  "(SELECT id FROM interview_session)")
        c.execute("DELETE FROM users WHERE account=?", (account,))
        c.commit()
    finally:
        c.close()


TEST_A, TEST_B = "__sync_t_a__", "__sync_t_b__"
atexit.register(lambda: (_clean(TEST_A), _clean(TEST_B)))
_clean(TEST_A)
_clean(TEST_B)

# ================================================================ 1. 演示播种
print("\n== 1. 演示账号自动播种 ==")
# 借一个假演示账号测「空 → 播种」路径（真实演示账号本机已有数据，动不得）
DSD.DEMO_STEPS[TEST_A] = dict(name="测试播种", major="人工智能技术应用", family="数据分析",
                              steps=[("2026-06-01 09:00:00", ["Python", "SQL"], "测试快照一"),
                                     ("2026-07-01 09:00:00", ["Python", "SQL", "Excel"],
                                      "测试快照二")])
DSD.DEMO_ACCOUNTS.add(TEST_A)
# 顺便给假演示账号配 2 条投递剧本（一条已约面→事件回填 2 条）
DSD.DEMO_APPLIES.append((TEST_A, "测试岗一", "测试公司", "郑州", "已约面", "2026-06-15 10:00:00"))
DSD.DEMO_APPLIES.append((TEST_A, "测试岗二", "", "郑州", "已投递", "2026-06-20 10:00:00"))
r = AU.register_password(TEST_A, "test123456", "测试播种", "人工智能技术应用")
ok(r.get("ok"), f"注册测试演示账号 {TEST_A}")
uid_a = int(r["user"]["id"])

r1 = DSD.seed_demo_account(r["user"])
ok(r1.get("ok") and r1.get("snapshots") == 2, f"首次播种：写入 2 条快照（实际 {r1.get('snapshots')}）")
ok(r1.get("applies") == 2, f"首次播种：写入 2 条投递（实际 {r1.get('applies')}）")
n_ev = 0
c = sqlite3.connect(A.DB)
try:
    n_ev = int(c.execute("SELECT COUNT(*) FROM apply_event WHERE COALESCE(user_id,0)=?",
                         (uid_a,)).fetchone()[0])
finally:
    c.close()
ok(n_ev >= 2, f"投递事件已回填（{n_ev} 条）")

r2 = DSD.seed_demo_account(r["user"])
ok(r2.get("snapshots") == 0 and r2.get("applies") == 0, "第二次播种：幂等，一条不写")

r3 = DSD.seed_demo_account({"id": uid_a, "account": "not_demo", "nickname": "x"})
ok(not r3.get("ok"), "非演示账号：拒绝播种")

# ================================================================ 2. 同步包
print("\n== 2. 账号数据同步包（导出 → 导入 → 幂等） ==")
# 给 A 再补一条面试会话 + 逐轮对话，凑齐五类数据
c = sqlite3.connect(A.DB)
try:
    cur = c.execute("INSERT INTO interview_session(user_id,student,family,persona,mode,n_turns,"
                    "score,level,report_md,state_json,started_at,ended_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uid_a, "测试播种", "数据分析", "温和型 HR", "rules", 1, 45.0, "需要重练",
                     "# 报告", '{"sid": 999, "student": "测试播种"}',
                     "2026-07-02 10:00:00", "2026-07-02 10:05:00"))
    sid = int(cur.lastrowid)
    c.execute("INSERT INTO interview_turn(session_id,seq,role,kind,content,score,dims_json,ts) "
              "VALUES(?,?,?,?,?,?,?,?)",
              (sid, 0, "ai", "ask", "测试问题", 0, "{}", "2026-07-02 10:00:00"))
    c.execute("INSERT INTO interview_turn(session_id,seq,role,kind,content,score,dims_json,ts) "
              "VALUES(?,?,?,?,?,?,?,?)",
              (sid, 1, "me", "answer", "测试回答", 45, "{}", "2026-07-02 10:01:00"))
    c.commit()
finally:
    c.close()

raw = SP.export_json(uid_a, TEST_A)
pack = __import__("json").loads(raw.decode("utf-8"))
ok(pack.get("type") == SP.PACK_TYPE, "导出：同步包 type 正确")
ok(len(pack.get("career_snapshot", [])) == 2, "导出：2 条快照")
ok(len(pack.get("apply_log", [])) == 2, "导出：2 条投递")
ok(len(pack.get("apply_event", [])) == n_ev, f"导出：{n_ev} 条事件")
ok(len(pack.get("interview_session", [])) == 1, "导出：1 条面试会话")
ok(len(pack.get("interview_turn", [])) == 2, "导出：2 条面试对话")

r_bad = SP.import_pack(uid_a, {"type": "别的"})
ok(not r_bad.get("ok"), "导入：非同步包文件被拒绝")

# 注册 B 账号（模拟另一台电脑上的同一个逻辑：数据从零开始）
r = AU.register_password(TEST_B, "test123456", "测试同步", "人工智能技术应用")
uid_b = int(r["user"]["id"])

r1 = SP.import_pack(uid_b, pack)
ok(r1.get("ok"), f"首次导入成功：{r1.get('msg')}")
ok(r1.get("added", {}).get("快照") == 2 and r1.get("added", {}).get("投递") == 2
   and r1.get("added", {}).get("事件") == n_ev
   and r1.get("added", {}).get("面试会话") == 1 and r1.get("added", {}).get("面试对话") == 2,
   f"首次导入：五类数据全进来了 {r1.get('added')}")

# B 账号的数据应该和 A 完全一致（逐字段比对，去掉 id/user_id）
c = sqlite3.connect(A.DB)
c.row_factory = sqlite3.Row
try:
    for t, ord_col, skip in (("career_snapshot", "ts", ()),
                             ("apply_log", "ts", ()),
                             ("interview_session", "started_at", ("state_json",))):
        # state_json 里的 sid 是库内自增 id，导入时合法重映射，不参与比对
        cols = [r[1] for r in c.execute(f"pragma table_info({t})")
                if r[1] not in ("id", "user_id", *skip)]
        ra = c.execute(f"SELECT {','.join(cols)} FROM {t} WHERE COALESCE(user_id,0)=? "
                       f"ORDER BY {ord_col}", (uid_a,)).fetchall()
        rb = c.execute(f"SELECT {','.join(cols)} FROM {t} WHERE COALESCE(user_id,0)=? "
                       f"ORDER BY {ord_col}", (uid_b,)).fetchall()
        ok([tuple(r) for r in ra] == [tuple(r) for r in rb], f"{t} 两账号逐字段一致")
finally:
    c.close()

# 面试 state_json 的 sid 已改成本库新 id
c = sqlite3.connect(A.DB)
try:
    row = c.execute("SELECT state_json FROM interview_session WHERE COALESCE(user_id,0)=?",
                    (uid_b,)).fetchone()
    sj = __import__("json").loads(row[0])
    ok(sj.get("sid") not in (999, sid), f"state_json.sid 已重映射（{sj.get('sid')}）")
finally:
    c.close()

r2 = SP.import_pack(uid_b, pack)
ok(r2.get("ok") and sum(r2.get("added", {}).values()) == 0,
   f"重复导入：幂等，0 条新增（跳过 {r2.get('skipped')}）")

# ================================================================ 3. tools/seed_demo 引用检查
print("\n== 3. 剧本数据单一来源 ==")
ok(N_DEMO_APPLIES == 5, "演示投递剧本 5 条（林小雨 4 投 2 约面口径）")
ok(DEMO_APPLY_ACCOUNTS == {"13800000001", "13800000002"},
   "投递剧本只挂 01/02 两个演示账号")
import tools.seed_demo as SD  # noqa: E402
ok(SD.DEMO_APPLY == DSD.DEMO_APPLIES, "tools/seed_demo 与 core/demo_seed 同一份剧本")

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
