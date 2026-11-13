"""⑤成长档案：定位记录 / 成长曲线 选中某次记录并删除 的专项回归。

跑法：.venv/Scripts/python.exe tools/test_snap_delete.py
跑完自动清理本次新增快照，不污染答辩演示档案。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402
from core import viz  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

DB = ROOT / "data" / "jobs.db"
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
    PF._conn().close()
    c = sqlite3.connect(DB)
    base = c.execute("SELECT COALESCE(MAX(id),0) FROM career_snapshot").fetchone()[0]
    has_del = hasattr(PF, "delete_snapshot")
    c.close()
    check(has_del, "profile 提供 delete_snapshot")

    print("\n— A. 逻辑层：删除只影响目标记录，不影响别的账号")
    uid_t = 993002
    stu = "删除测试同学"
    lp_a = PW.build_path(["Python"], "数据分析", 10, major="计算机应用技术")
    lp_b = PW.build_path(["Python", "SQL"], "数据分析", 10, major="计算机应用技术")
    lp_c = PW.build_path(["Python", "SQL", "Excel"], "数据分析", 10, major="计算机应用技术")
    s1 = PF.save_snapshot(stu, lp_a, ["Python"], "第1次", ts="2026-11-01 10:00:00", uid=uid_t)
    s2 = PF.save_snapshot(stu, lp_b, ["Python", "SQL"], "④补课清单提交补齐：SQL",
                          ts="2026-11-02 10:00:00", uid=uid_t, source="补课勾选")
    s3 = PF.save_snapshot(stu, lp_c, ["Python", "SQL", "Excel"], "第3次",
                          ts="2026-11-03 10:00:00", uid=uid_t)
    check(len(PF.list_snapshots(stu, uid_t)) == 3, "3 条记录已落库")

    n = PF.delete_snapshot(s2, uid_t)
    left = PF.list_snapshots(stu, uid_t)
    check(n == 1 and len(left) == 3 - 1, f"删中间一条：影响 {n} 行，剩 {len(left)} 条")
    check(s2 not in list(left["id"]), "被删的 id 确实不在了")
    check(list(left["id"]) == [s1, s3], "其余记录顺序不变")

    check(PF.delete_snapshot(s1, 999999) == 0, "别的账号删不动（uid 不匹配 → 0 行）")
    check(PF.delete_snapshot(987654321, uid_t) == 0, "不存在的 id → 0 行")
    check(len(PF.list_snapshots(stu, uid_t)) == 2, "越权/无效删除后记录数不变")

    h = PF.history(stu, uid_t)
    check(len(h) == 2, f"曲线数据同步剩 {len(h)} 个点")
    cmp_ = PF.compare(stu, uid_t)
    check(cmp_.get("ok") and cmp_["t_now"].startswith("2026-11-03"),
          f"compare 以剩余最后两条为准（now={cmp_.get('t_now')}）")

    print("\n— B. 曲线：选中点高亮，未选中不画高亮")
    svg_sel = viz.growth_curve(h, 1)
    check('stroke-dasharray="5 5"' in svg_sel, "选中点画了竖虚线")
    check('r="12"' in svg_sel and "已选中" in svg_sel, "选中点有光环 + 悬浮提示标注已选中")
    svg_plain = viz.growth_curve(h)
    check('stroke-dasharray="5 5"' not in svg_plain, "不传 sel 时没有高亮")
    check("蓝点=定位" in svg_plain and "橙点=补课清单提交" in svg_plain, "图例保留")

    print("\n— C. 删到只剩一条：对比降级、曲线仍可画")
    PF.delete_snapshot(s3, uid_t)
    check(PF.compare(stu, uid_t).get("ok") is False, "只剩 1 条时 compare 返回 ok=False")
    check(len(viz.growth_curve(PF.history(stu, uid_t))) > 200, "单点曲线仍能渲染")
    PF.delete_snapshot(s1, uid_t)
    check(len(PF.list_snapshots(stu, uid_t)) == 0, "可以删空（档案回到空态）")

    print("\n— D. 页面层：⑤ 点选记录 → 确认删除（AppTest）")
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    exc(at, "首页")
    login_demo(at, 0)
    exc(at, "登录")
    c = sqlite3.connect(DB)
    uid = c.execute("SELECT id FROM users WHERE account='13800000001'").fetchone()[0]
    c.close()

    # 造两次新定位：两次都存入档案，供点选删除
    at.radio(key="screen").set_value("③ 我的定位").run()
    ms = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    ms.set_value(["Python"]).run()
    [b for b in at.button if b.label == "📐 生成我的定位"][0].click().run()
    [b for b in at.button if "存入成长档案" in (b.label or "")][0].click().run()
    exc(at, "存快照1")
    ms = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    ms.set_value(["Python", "Excel"]).run()
    [b for b in at.button if b.label == "📐 生成我的定位"][0].click().run()
    [b for b in at.button if "存入成长档案" in (b.label or "")][0].click().run()
    exc(at, "存快照2")

    stu_name = at.session_state.get("student_name", "")
    snaps = PF.list_snapshots(stu_name, uid)
    n0 = len(snaps)
    check(n0 >= 2, f"档案现有 {n0} 条记录")

    # 首次进 ⑤ 之前预置选中（widget 还没实例化，等价于"用户勾了最后两行"）
    at.session_state["snap_sel"] = {"selection": {"rows": [n0 - 2, n0 - 1]}}
    at.radio(key="screen").set_value("⑤ 成长档案").run()
    exc(at, "⑤屏")
    _mds = [m.value or "" for m in at.markdown]
    check(not any('class="pick"' in m for m in _mds),
          "不再有「📌 已选中」卡片（已按多选删除重做）")
    _svg = "".join(m for m in _mds if "svg" in m)
    check('stroke-dasharray="5 5"' in _svg, "曲线仍框出选中的那次记录")

    _btns = {b.key: b for b in at.button if (b.key or "").startswith("snap_del_btn")}
    check(len(_btns) == 1 and "删除选中 2 条" in (_btns["snap_del_btn"].label or ""),
          f"多选 2 行 → 出现批量删除按钮：{[b.label for b in at.button if (b.key or '').startswith('snap_del')]}")
    check(not any((x.key or "").startswith("delok_") for x in at.checkbox),
          "旧的单条确认框已移除")
    check(not any("勾最左一列" in m for m in _mds), "没有多余提示语句")

    _target = [int(snaps.iloc[-1]["id"]), int(snaps.iloc[-2]["id"])]
    _btns["snap_del_btn"].click().run()
    exc(at, "删除")

    _after = PF.list_snapshots(stu_name, uid)
    check(len(_after) == n0 - 2, f"记录数 {n0} → {len(_after)}")
    check(all(t not in list(_after["id"]) for t in _target), "选中的两条都从库中删除")
    _mds2 = [m.value or "" for m in at.markdown]
    check(not any((b.key or "").startswith("snap_del") for b in at.button),
          "删完勾选清空，批量删除按钮收起")
    _svg2 = "".join(m for m in _mds2 if "svg" in m)
    check('stroke-dasharray="5 5"' not in _svg2, "曲线上的高亮同步消失")
    check(any("当前命中率" in m for m in _mds2), "顶部状态卡仍按剩余记录渲染")

    print("\n— 清理本次测试数据")
    c = sqlite3.connect(DB)
    n1 = c.execute("DELETE FROM career_snapshot WHERE id>?", (base,)).rowcount
    n2 = c.execute("DELETE FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid_t,)).rowcount
    c.commit()
    c.close()
    print(f"  🧹 已删除测试快照 {n1 + n2} 条")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
