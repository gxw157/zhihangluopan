"""④补课清单勾选提交 → ⑤成长档案识别 → 成长曲线橙点 的专项回归。

跑法：.venv/Scripts/python.exe tools/test_checkin.py
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
    PF._conn().close()                      # 触发建表/补 source 列
    c = sqlite3.connect(DB)
    cols = [r[1] for r in c.execute("PRAGMA table_info(career_snapshot)").fetchall()]
    check("source" in cols, "career_snapshot 已自动补 source 列")
    base = c.execute("SELECT COALESCE(MAX(id),0) FROM career_snapshot").fetchone()[0]
    c.close()

    print("\n— A. 逻辑层：source 落库 / compare 来源 / history 带来源")
    lp = PW.build_path(["Python"], "数据分析", 10, major="计算机应用技术")
    check(lp.get("ok"), f"build_path 正常（match={lp.get('match', 0):.0%}）")
    uid_t = 993001
    s1 = PF.save_snapshot("勾选测试同学", lp, ["Python"], "第一次定位",
                          ts="2026-11-01 10:00:00", uid=uid_t)
    lp2 = PW.build_path(["Python", "SQL", "Excel"], "数据分析", 10, major="计算机应用技术")
    s2 = PF.save_snapshot("勾选测试同学", lp2, ["Python", "SQL", "Excel"],
                          "④补课清单提交补齐：SQL、Excel",
                          ts="2026-11-05 10:00:00", uid=uid_t, source="补课勾选")
    check(s1 > 0 and s2 > 0, f"两份快照落库 id={s1},{s2}")
    c = sqlite3.connect(DB)
    src1 = c.execute("SELECT source FROM career_snapshot WHERE id=?", (s1,)).fetchone()[0]
    src2 = c.execute("SELECT source FROM career_snapshot WHERE id=?", (s2,)).fetchone()[0]
    c.close()
    check(src1 == "定位" and src2 == "补课勾选", f"source 值：{src1} / {src2}")
    cmp_ = PF.compare("勾选测试同学", uid_t)
    check(cmp_.get("ok") and cmp_.get("src_now") == "补课勾选", "compare 识别最新快照来源=补课勾选")
    check(cmp_.get("fixed_src") == "④补课清单提交", "compare 给已补齐技能打上清单提交来源")
    check("最近一次记录" in cmp_["headline"] and "比上一次" in cmp_["headline"],
          "headline 是「最近一次记录比上一次」的历史口径")
    check("你正在变强" not in cmp_["headline"], "headline 不再冒充刚发生的事（无『你正在变强』）")
    check("④补课清单提交" in cmp_["headline"], f"headline 含来源：…{cmp_['headline'][40:80]}…")
    hist = PF.history("勾选测试同学", uid_t)
    check("source" in hist.columns and set(hist["source"]) == {"定位", "补课勾选"},
          "history 带出 source 列")
    snaps = PF.list_snapshots("勾选测试同学", uid_t)
    check("来源" in snaps.columns, "定位记录表带「来源」列")
    md = PF.export_markdown("勾选测试同学", uid_t)
    check("来源" in md, "导出 Markdown 表格含来源列")

    print("\n— B. 曲线：补课勾选点画橙色")
    from core import viz
    svg = viz.growth_curve(hist)
    check("#ea580c" in svg, "曲线含橙点（#ea580c）")
    check("补课清单勾选提交" in svg, "橙点悬浮提示注明来源")

    print("\n— C. 页面层：④勾选提交全流程（AppTest）")
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    exc(at, "首页")
    login_demo(at, 0)
    exc(at, "登录")
    c = sqlite3.connect(DB)
    uid = c.execute("SELECT id FROM users WHERE account='13800000001'").fetchone()[0]
    c.close()

    at.radio(key="screen").set_value("③ 我的定位").run()
    exc(at, "③屏")
    ms = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    ms.set_value(["Python", "Excel"]).run()
    [b for b in at.button if b.label == "📐 生成我的定位"][0].click().run()
    exc(at, "生成定位")
    lp1 = at.session_state.get("lp") or {}
    check(lp1.get("ok"), f"定位生成，命中率 {lp1.get('match', 0):.0%}")
    [b for b in at.button if "存入成长档案" in (b.label or "")][0].click().run()
    exc(at, "存快照1")

    at.radio(key="screen").set_value("④ 差距路径").run()
    exc(at, "④屏")
    gap_skills = list((at.session_state.get("lp") or {}).get("gap", {}).get("技能", []))
    check(len(gap_skills) > 0, f"补课清单 {len(gap_skills)} 项")
    _cb = {x.key: x for x in at.checkbox if (x.key or "").startswith("done_")}
    check(len(_cb) == len(gap_skills), f"清单勾选框 {len(_cb)} 个 = 缺口数")
    pick = gap_skills[:2]
    for sk in pick:
        _cb[f"done_{sk}"].check()
    at.run()
    exc(at, "勾选")
    [ti for ti in at.text_input if ti.key == "done_evidence"][0].set_value("蓝桥杯省赛二等奖")
    [b for b in at.button if "提交补课结果" in (b.label or "")][0].click().run()
    exc(at, "提交")

    _mds4 = " ".join((m.value or "") for m in at.markdown)
    _succ = [s.value or "" for s in at.success]
    check(not any("已补齐" in s for s in _succ) and "已补齐" not in _mds4,
          "提交后不再弹「🎉 已补齐…」提示（按要求删除）")
    # 提交后按钮变灰写「已提交」（不再是可点的「提交补课结果」）
    _btns = {(b.key or ""): b for b in at.button}
    check("checkin_done_btn" in _btns and (_btns["checkin_done_btn"].label or "") == "已提交"
          and _btns["checkin_done_btn"].disabled is True,
          "提交后按钮变灰、文字为「已提交」")
    check("checkin_btn" not in _btns, "可点的「提交补课结果」按钮已收起")

    _have = at.session_state.get("have_last", [])
    check(all(sk in _have for sk in pick), f"勾选技能并入定位 {pick}")
    lp2 = at.session_state.get("lp") or {}
    check(lp2.get("ok") and lp2["match"] >= lp1["match"],
          f"命中率 {lp1['match']:.0%} → {lp2.get('match', 0):.0%} 未下降")
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT source, note, n_gap FROM career_snapshot "
                     "WHERE COALESCE(user_id,0)=? AND id>? ORDER BY id",
                     (uid, base)).fetchall()
    c.close()
    check(len(rows) == 2, f"本流程共存 2 份快照（实际 {len(rows)}）")
    check(rows[-1][0] == "补课勾选", "新快照来源=补课勾选")
    check("佐证：蓝桥杯省赛二等奖" in rows[-1][1], f"佐证写进备注：{rows[-1][1]}")
    cmp2 = PF.compare(at.session_state.get("student_name", ""), uid)
    if cmp2.get("ok"):
        check(cmp2.get("src_now") == "补课勾选", "⑤档案 compare 识别到补课勾选快照")
        check(all(sk in cmp2.get("fixed", []) for sk in pick),
              f"已补齐列表含勾选项：{cmp2.get('fixed', [])}")
    else:
        check(False, "⑤档案 compare 不可用")

    at.radio(key="screen").set_value("⑤ 成长档案").run()
    exc(at, "⑤屏")
    svg5 = ""
    for el in at.markdown:
        v = el.value or ""
        if "svg" in v:
            svg5 += v
    check("#ea580c" in svg5, "⑤屏成长曲线渲染出橙点")
    _mds = [m.value or "" for m in at.markdown]
    check(any("当前命中率" in m for m in _mds), "⑤屏顶部有「当前命中率」状态卡")
    check(any('class="grow"' in m for m in _mds), "本次会话刚提交 → 用「刚补齐」庆祝口径")
    # 模拟"再次进来"：不是本次会话提交的那份快照，必须降级为历史口径
    at.session_state["last_checkin_sid"] = 0
    at.run()
    _mds2 = [m.value or "" for m in at.markdown]
    check(any('class="hist"' in m for m in _mds2), "再次进入⑤改用「最近一次变化（历史记录）」卡")
    check(not any("刚补齐" in m for m in _mds2), "历史口径不再写「刚补齐」，不冒充当前状态")

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
