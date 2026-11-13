"""数据体检与清理：只处理"任何账号都看不到"的遗留记录。

默认**只看不动**：
    .venv/Scripts/python.exe tools/cleanup_data.py

确认无误后再动手（二选一）：
    .venv/Scripts/python.exe tools/cleanup_data.py --apply        # 删孤儿（user_id 查不到账号）
    .venv/Scripts/python.exe tools/cleanup_data.py --ids 79,94,95 # 删指定快照 id

孤儿 = 早期未登录时代（user_id 为空/0）或账号已被删除的记录。
登录后所有查询都用 COALESCE(user_id,0)=登录uid，这些记录谁都看不到，
留着只会污染 ⑧ 的账号统计和"历史记录次数"。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "jobs.db"
TABLES = ("career_snapshot", "apply_log", "interview_session")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def orphans(c: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """user_id 为空/0，或指向 users 表里不存在的账号。"""
    out: dict[str, list[sqlite3.Row]] = {}
    uids = {int(r[0]) for r in c.execute("SELECT id FROM users")}
    for t in TABLES:
        rows = []
        for r in c.execute(f"SELECT * FROM {t} ORDER BY id"):
            u = r["user_id"] if "user_id" in r.keys() else None
            if u is None or int(u) not in uids:
                rows.append(r)
        out[t] = rows
    return out


def main() -> None:
    apply_orphans = "--apply" in sys.argv
    ids = []
    if "--ids" in sys.argv:
        raw = sys.argv[sys.argv.index("--ids") + 1] if len(sys.argv) > sys.argv.index("--ids") + 1 else ""
        ids = [int(x) for x in raw.replace("，", ",").split(",") if x.strip().isdigit()]

    c = conn()
    print("=" * 62)
    print("一、账号分布（八屏里每个账号只能看到自己 uid 的行）")
    for t in TABLES:
        rows = c.execute(f"SELECT COALESCE(user_id,0) u, COUNT(*) n FROM {t} "
                         f"GROUP BY 1 ORDER BY 1").fetchall()
        detail = "、".join(f"uid{u}:{n}" for u, n in rows) or "空"
        print(f"  {t:<18} {detail}")
    print("  演示账号：" + "、".join(
        f"{r['nickname']}({r['phone']})" for r in c.execute("SELECT phone,nickname FROM users")))

    orp = orphans(c)
    total = sum(len(v) for v in orp.values())
    print("\n二、孤儿记录（user_id 为空/0 或账号已不存在 → 任何账号都看不到）")
    if not total:
        print("  没有，干净。")
    for t, rows in orp.items():
        if not rows:
            continue
        print(f"  {t}: {len(rows)} 条  id={[r['id'] for r in rows][:12]}"
              f"{' …' if len(rows) > 12 else ''}")
        for r in rows[:3]:
            nm = r["student"] if "student" in r.keys() else ""
            ts = r["ts"] if "ts" in r.keys() else ""
            print(f"      · id={r['id']} {nm} {ts}")

    print("\n三、演示账号的近期记录（不会自动删，需要你自己确认）")
    for u in c.execute("SELECT id,nickname,phone FROM users ORDER BY id"):
        n = c.execute("SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)=?",
                      (u["id"],)).fetchone()[0]
        last = c.execute("SELECT id,ts,source,note FROM career_snapshot "
                         "WHERE COALESCE(user_id,0)=? ORDER BY id DESC LIMIT 3",
                         (u["id"],)).fetchall()
        print(f"  {u['nickname']}（{u['phone']}）快照 {n} 条")
        for r in last:
            print(f"      · id={r['id']} {r['ts']} {r['source']} {r['note'] or '（无备注）'}")

    if not (apply_orphans or ids):
        print("\n以上只是体检。确认要删，再带参数运行：")
        print("  --apply        删除所有孤儿记录")
        print("  --ids 79,94,95 删除指定快照 id（⑤ 页面也能逐条点选删除）")
        c.close()
        return

    # ---- 真正动手（用户已显式带参数）
    n = 0
    if apply_orphans:
        for t, rows in orp.items():
            for r in rows:
                c.execute(f"DELETE FROM {t} WHERE id=?", (r["id"],))
                if t == "interview_session":
                    c.execute("DELETE FROM interview_turn WHERE session_id=?", (r["id"],))
                n += 1
    for sid in ids:
        n += c.execute("DELETE FROM career_snapshot WHERE id=?", (sid,)).rowcount
    c.commit()
    c.close()
    print(f"\n已删除 {n} 条记录。")


if __name__ == "__main__":
    main()
