r"""推送到 GitHub / Streamlit Community Cloud 之前清理 data/jobs.db。

云端容器是"一次性"的：每次重启都会回滚到仓库里的 data/jobs.db，
所以推送前必须把不该公开的行清掉：

    1. users 表只保留 3 个演示账号（13800000001/2/3），其余注册用户数据全删
       （真实学生的注册信息不应公开发布到公有仓库）；
    2. 清空登录 token 列（登录会话不带到云端）；
    3. VACUUM 压缩体积。

用法：
    python tools/export_cloud_db.py

自动先备份到 data/_bak_jobs_before_cloud_时间戳.db。注意：本脚本直接改
data/jobs.db 本体，跑完再 git add data/jobs.db 提交快照。
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jobs.db"
DEMO_ACCOUNTS = ("13800000001", "13800000002", "13800000003")


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"找不到 {DB}")
    bak = ROOT / "data" / f"_bak_jobs_before_cloud_{time.strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB, bak)

    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("pragma table_info(users)")]
    before = con.execute("select count(*) from users").fetchone()[0]
    ph = ",".join("?" * len(DEMO_ACCOUNTS))
    con.execute(f"delete from users where account not in ({ph})", DEMO_ACCOUNTS)
    for c in cols:
        if "token" in c.lower():
            con.execute(f"update users set {c}=''")
    con.commit()
    con.execute("vacuum")
    after = con.execute("select count(*) from users").fetchone()[0]
    tables = {t: con.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("jobs", "job_skill", "apply_log", "career_snapshot")}
    con.close()

    print(f"备份: {bak}")
    print(f"users: {before} -> {after}（保留演示账号 {', '.join(DEMO_ACCOUNTS)}）")
    print("其余表行数:", tables)
    print("数据库已就绪，可以 git add data/jobs.db 提交")


if __name__ == "__main__":
    main()
