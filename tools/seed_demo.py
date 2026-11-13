"""生成 3 位演示学生的成长档案（可反复运行，先清空同账号数据再写入）。

用途：答辩现场直接切换学生，展示"跨学期命中率爬升 + 已补齐技能"，
不用现场从零勾技能。数据全部由平台真实计算（pathway.build_path），
只是把记录时间补录到过去几个月。

数据挂在演示账号上（13800000001/2/3），登录该手机号即可看到对应档案；
不同账号的数据按 user_id 隔离，互不干扰。

    .venv/Scripts/python tools/seed_demo.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import auth as AU  # noqa: E402
from core import demo_seed as DSD  # noqa: E402
from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402

DEMO = [dict(phone=p, **v) for p, v in DSD.DEMO_STEPS.items()]

# 剧本投递：（账号, 标题, 公司, 城市, 状态, 投递时间）——与 core/demo_seed.py 同一份
DEMO_APPLY = [(a, t, co, ci, st, ts) for a, t, co, ci, st, ts in DSD.DEMO_APPLIES]


def main() -> None:
    users = {u["phone"]: u for u in AU.ensure_demo_users()}
    PF.list_snapshots("__migrate__")      # 触发建表与 user_id 列迁移
    c = sqlite3.connect(A.DB)
    for d in DEMO:
        uid = int(users[d["phone"]]["id"])
        c.execute("DELETE FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid,))
        c.execute("DELETE FROM apply_log WHERE COALESCE(user_id,0)=?", (uid,))
    c.commit()
    c.close()

    n = 0
    for d in DEMO:
        u = users[d["phone"]]
        uid = int(u["id"])
        AU.update_user(uid, nickname=d["name"], major=d["major"])
        for ts, have, note in d["steps"]:
            lp = PW.build_path(have, d["family"], top=12, major=d["major"])
            if not lp.get("ok"):
                print("跳过", d["name"], ts, lp.get("msg"))
                continue
            PF.save_snapshot(d["name"], lp, have, note, ts=ts, uid=uid)
            n += 1
        last = PW.build_path(d["steps"][-1][1], d["family"], top=12, major=d["major"])
        print(f"{d['phone']} {d['name']}·{d['major']}·{d['family']}：{len(d['steps'])} 次定位，"
              f"最新命中率 {last['match']:.0%}，缺口 {len(last['gap'])} 项")

    from core import apply as AP
    for phone, title, company, city, status, ts in DEMO_APPLY:
        u = users[phone]
        AP.legacy_import(int(u["id"]), u["nickname"], title, company=company, city=city,
                         status=status, ts=ts)
    names = "、".join(f"{p}（{u['nickname']}）" for p, u in users.items())
    print(f"写入快照 {n} 条、投递记录 {len(DEMO_APPLY)} 条；演示账号：{names}")


if __name__ == "__main__":
    main()
