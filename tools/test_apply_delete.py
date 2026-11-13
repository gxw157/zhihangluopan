"""⑦求职实战 · 投递记录：左列勾选框多选 → 批量删除 的专项回归。

跑法：.venv/Scripts/python.exe tools/test_apply_delete.py
跑完自动清理本次新增投递，不污染答辩演示档案。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from core import apply as AP  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

BAD: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    BAD.append(msg)
    print(f"  ❌ {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def exc(at: AppTest, where: str) -> None:
    if at.exception:
        bad(f"{where} 抛异常：" + "；".join(str(e.value)[:200] for e in at.exception))


def main() -> None:
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    exc(at, "首页")
    login_demo(at, 0)
    exc(at, "登录")
    uid = int(at.session_state["user"]["id"])
    stu = at.session_state.get("student_name", "同学")

    # ---- 造 3 条投递（时间倒序：01 最新）
    ids = [AP.legacy_import(uid, stu, "删除测试岗A", "测试公司", "郑州", "已投递",
                            "批量删除回归", ts="2026-11-12 09:00:00"),
           AP.legacy_import(uid, stu, "删除测试岗B", "测试公司", "郑州", "已投递",
                            "批量删除回归", ts="2026-11-11 09:00:00"),
           AP.legacy_import(uid, stu, "删除测试岗C", "测试公司", "郑州", "已投递",
                            "批量删除回归", ts="2026-11-10 09:00:00")]
    check(all(ids), "3 条投递已落库")

    at.radio(key="screen").set_value("⑦ 求职实战").run()
    exc(at, "⑦屏")

    _bd = AP.stats(uid)["rows"]
    n0 = len(_bd)
    check(n0 >= 3, f"投递记录 {n0} 条")

    print("\n— A. 表左列勾选：可多选，底部不再有「删除某条」")
    check(not any((s.label or "") == "删除某条" for s in at.selectbox),
          "底部「删除某条」下拉已移除")
    # 预置选中前两行（等价于用户勾了最左一列的复选框）
    at.session_state["app_sel"] = {"selection": {"rows": [0, 1]}}
    at.run()
    exc(at, "预置勾选")
    _btn = [b for b in at.button if (b.key or "") == "del_app_btn"]
    check(len(_btn) == 1, "出现「删除选中」按钮")
    check("2 条" in (_btn[0].label if _btn else ""), f"按钮带条数：{_btn[0].label if _btn else '—'}")

    _target = [int(_bd["id"].iloc[0]), int(_bd["id"].iloc[1])]
    _keep = list(_bd["id"].iloc[2:])
    print("\n— B. 点一次删掉选中的两条")
    _btn[0].click().run()
    exc(at, "删除")
    _after = AP.stats(uid)["rows"]
    check(len(_after) == n0 - 2, f"记录数 {n0} → {len(_after)}")
    check(all(i not in list(_after["id"]) for i in _target), "选中的两条已从库中删除")
    check(list(_after["id"]) == _keep, "其余记录一条没动、顺序不变")

    _btn2 = [b for b in at.button if (b.key or "") == "del_app_btn"]
    check(not _btn2, "删完勾选自动清空，按钮收起")

    print("\n— 清理本次测试数据")
    for i in ids:
        AP.delete_apply(uid, i)
    print("  🧹 已清理 3 条测试投递")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
