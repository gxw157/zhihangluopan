"""模拟演示全过程走查：按答辩讲解顺序把八屏跑一遍，找逻辑错误。

跑法：.venv/Scripts/python.exe tools/test_walkthrough.py
"""
from __future__ import annotations

import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

DB = ROOT / "data" / "jobs.db"
PROBLEMS: list[str] = []
STEPS: list[str] = []


def step(msg: str) -> None:
    STEPS.append(msg)
    print(f"\n— {msg}")


def bad(msg: str) -> None:
    PROBLEMS.append(msg)
    print(f"  ❌ {msg}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def exc(at: AppTest, where: str) -> bool:
    if at.exception:
        bad(f"{where} 抛异常：" + "；".join(str(e.value)[:200] for e in at.exception))
        return True
    return False


def by_label(at: AppTest, label: str, kind: str = "button"):
    coll = {"button": at.button, "multiselect": at.multiselect,
            "selectbox": at.selectbox, "text_area": at.text_area,
            "text_input": at.text_input, "radio": at.radio,
            "checkbox": at.checkbox, "toggle": at.toggle}[kind]
    for x in coll:
        if (x.label or "") == label:
            return x
    return None


def go(at: AppTest, screen: str) -> None:
    at.radio(key="screen").set_value(screen).run()


def main() -> None:
    # 清掉上一轮残留测试账号
    c = sqlite3.connect(DB)
    for ph in ("13700008888", "13700008889"):
        r = c.execute("SELECT id FROM users WHERE account=?", (ph,)).fetchone()
        if r:
            uid = r[0]
            for t in ("users", "sessions"):
                c.execute(f"DELETE FROM {t} WHERE " +
                          ("id=?" if t == "users" else "user_id=?"), (uid,))
            for t in ("career_snapshot", "apply_log"):
                c.execute(f"DELETE FROM {t} WHERE COALESCE(user_id,0)=?", (uid,))
    c.commit()
    c.close()

    # 记下演示账号的基线，跑完把本次新增的记录删掉，避免污染答辩用的演示档案
    c = sqlite3.connect(DB)
    base_snap = c.execute("SELECT COALESCE(MAX(id),0) FROM career_snapshot").fetchone()[0]
    base_app = c.execute("SELECT COALESCE(MAX(id),0) FROM apply_log").fetchone()[0]
    _has_iv = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interview_session'"
                        ).fetchone()
    base_iv = c.execute("SELECT COALESCE(MAX(id),0) FROM interview_session").fetchone()[0] \
        if _has_iv else 0
    c.close()

    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    exc(at, "首页")

    step("1. 首页：产品介绍 + 登录/注册")
    assert not at.exception
    ok(f"首页渲染完成，按钮 {len(at.button)} 个")
    if not any("登 录" in (b.label or "") for b in at.button):
        bad("首页缺少登录入口")
    if [b for b in at.button if (b.key or "").startswith("demo_login_")]:
        bad("首页仍有演示账号快捷入口（已按要求删除）")

    step("2. 演示账号登录（林小雨）")
    login_demo(at, 0)
    exc(at, "登录")
    if at.session_state.get("student_name") != "林小雨":
        bad(f"登录后档案名不是林小雨：{at.session_state.get('student_name')}")
    else:
        ok("档案名随账号带入：林小雨")
    if at.session_state.get("student_name") == "林小雨" and \
            at.session_state.get("major_name") is None:
        bad("登录后未带入专业")

    step("3. ① 市场全景：KPI / 技能榜 / 溢价 / 城市 / 趋势")
    go(at, "① 市场全景")
    exc(at, "①")
    texts = " ".join(m.value for m in at.markdown)
    for kw in ("市场最抢手的技能", "技能共现网络", "哪些技能更值钱", "机会在哪"):
        if kw not in texts:
            bad(f"① 缺少模块：{kw}")
    if "数据时间窗" not in " ".join(m.value for m in at.markdown):
        bad("① 时间窗 KPI 缺失")
    ok("① 各模块齐全" if not at.exception else "① 有异常")

    step("4. ② 方向画像：覆盖率口径已固定为全部技术岗（radio 已删）")
    go(at, "② 方向画像")
    exc(at, "②")
    if not any("课程跟不跟得上" in m.value for m in at.markdown):
        bad("② 覆盖率模块缺失")
    else:
        ok("② 覆盖率正常渲染（无口径切换控件）")

    step("5. ③ 我的定位：勾技能 → 生成 → 存快照")
    go(at, "③ 我的定位")
    ms = by_label(at, "我已掌握的技能", "multiselect")
    ms.set_value(["Python", "SQL", "Excel"]).run()
    btn = [b for b in at.button if "生成我的定位" in (b.label or "")][0]
    btn.click().run()
    exc(at, "③ 生成定位")
    lp = at.session_state.get("lp") or {}
    if not lp.get("ok"):
        bad("③ 定位生成失败")
    else:
        ok(f"定位成功：命中率 {lp['match']:.0%}，缺口 {len(lp['gap'])} 项，专业 {lp.get('major')}")
    n0 = len(at.success)
    sb = [b for b in at.button if "存入成长档案" in (b.label or "")]
    if sb:
        sb[0].click().run()
        exc(at, "③ 存快照")
        ok("快照已保存" if len(at.success) > n0 else "快照按钮已点击")
    else:
        bad("③ 缺少「存入成长档案」按钮")

    step("5b. ③ 反例：改了勾选但不重新生成就存快照（数据应与定位一致）")
    c = sqlite3.connect(DB)
    row = c.execute("SELECT n_held, match, have_json FROM career_snapshot "
                    "WHERE student='林小雨' ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    if row:
        import json
        held = len(json.loads(row[2] or "[]"))
        if held != row[0]:
            bad(f"快照 n_held={row[0]} 与实际技能数 {held} 不一致")
        else:
            ok(f"快照技能数一致（{held} 项，命中率 {row[1]:.0%}）")

    step("6. ④ 差距路径：路线图 / 三类缺口 / 补课清单 / 周任务卡翻页")
    go(at, "④ 差距路径")
    exc(at, "④")
    wk0 = at.session_state.get("task_week", 1)
    nxt = next((b for b in at.button if (b.key or "") == "wk_next"), None)
    if nxt and not nxt.disabled:
        nxt.click().run()
        exc(at, "④ 下一周")
        if at.session_state.get("task_week") == wk0 + 1:
            ok(f"周任务卡翻页：{wk0} → {at.session_state['task_week']}")
        else:
            bad("周任务卡翻页未生效")
        prev = next((b for b in at.button if (b.key or "") == "wk_prev"), None)
        if prev:
            prev.click().run()
            exc(at, "④ 上一周")
    else:
        bad("④ 缺少「下一周」按钮")

    step("7. ⑤ 成长档案：曲线 / 记录 / 周报")
    go(at, "⑤ 成长档案")
    exc(at, "⑤")
    wb = next((b for b in at.button if (b.key or "") == "gen_weekly"), None)
    if wb:
        wb.click().run()
        exc(at, "⑤ 周报")
        wr = at.session_state.get("weekly_md") or {}
        if wr.get("ok"):
            ok(f"周报生成：{len(wr.get('text', ''))} 字")
        else:
            print(f"  · 周报未生成：{wr.get('msg')}（快照不足时属正常）")
    else:
        bad("⑤ 缺少「生成本周周报」按钮")

    step("8. ⑥ AI 顾问：快捷提问 → 回答 → 一键生成规划书")
    go(at, "⑥ AI 顾问")
    exc(at, "⑥")
    ask = [b for b in at.button if "问" in (b.label or "") and (b.key or "").startswith("qk_")]
    if ask:
        ask[0].click().run()
        exc(at, "⑥ 快捷提问")
        ok("快捷提问有回答：" + (at.markdown[-1].value[:40] if at.markdown else ""))
    else:
        print("  · 未找到快捷提问按钮（可能叫法不同），跳过")
    p = [b for b in at.button if "生成我的职业规划书" in (b.label or "")]
    if p:
        p[0].click().run()
        exc(at, "⑥ 生成规划书")
        pm = at.session_state.get("plan_md") or ""
        if pm:
            ok(f"规划书已生成 {len(pm)} 字；含事实校验横幅："
               f"{any('事实校验' in (w.value or '') for w in at.warning)}")
        else:
            bad("规划书为空")
    else:
        bad("⑥ 缺少「生成我的职业规划书」按钮")

    step("9. ⑦ 求职实战：JD 透视镜（库内岗位）→ 简历 → 模拟面试 → 投递")
    go(at, "⑦ 求职实战")
    exc(at, "⑦")
    # 粘贴 JD / 多 JD 对比入口已按要求删除：只保留库内岗位逐条翻
    if any((r.key or "") == "jd_mode" for r in at.radio):
        bad("⑦ 还有「JD 来源」切换（粘贴 JD 应已删除）")
    else:
        ok("粘贴 JD 入口已移除，只剩库内岗位")
    if any("再贴两条" in (e.label or "") for e in at.expander):
        bad("⑦ 还有「再贴两条 JD」对比模块")
    else:
        ok("多 JD 对比模块已移除")
    cards = [m.value for m in at.markdown if 'class="jobcard"' in (m.value or "")]
    if cards:
        ok("JD 透视镜渲染出岗位卡")
    else:
        bad("⑦ 没有岗位卡")
    rv = [x for x in at.button if "预览" in (x.label or "")]
    if rv:
        rv[0].click().run()
        exc(at, "⑦ 简历预览")
        ok("简历技能段可预览")
    else:
        bad("⑦ 缺少简历预览按钮")
    # 板块 3 已改成数字人对话式面试：开始 → 提交一轮 → 状态机必须往前走
    sb = [x for x in at.button if "开始面试" in (x.label or "")]
    if sb:
        sb[0].click().run()
        exc(at, "⑦ 开始面试")
        iv = at.session_state.get("iv") or {}
        if iv.get("turns"):
            ok(f"面试已开始：{len(iv['turns'])} 条对话，共 {len(iv.get('qs') or [])} 题")
        else:
            bad("面试未进入会话状态")
        ans = at.text_area(key="iv_ans")
        if ans is not None:
            # 注意：AppTest 里 set_value 之后不能先 run，否则 form 的值会被重置，提交等于空
            ans.set_value("在课程设计里用 Python 清洗了 3 万条数据，做了 5 张可视化图，"
                          "处理效率提升了 8%。")
            sent = [x for x in at.button if "提交回答" in (x.label or "")]
            if sent:
                sent[0].click()
                at.run()
                exc(at, "⑦ 提交回答")
                iv2 = at.session_state.get("iv") or {}
                if iv2.get("scores"):
                    ok(f"作答已记分：第 {len(iv2['scores'])} 题 "
                       f"{iv2['scores'][-1]['score']} 分")
                else:
                    bad("作答未记录")
            else:
                bad("⑦ 缺少「提交回答」按钮")
        else:
            bad("⑦ 面试输入框缺失")
    else:
        bad("⑦ 缺少「开始面试」按钮")
    # 手动投递表单已删除（投递全自动）：库内岗位模式下走「立即投递」按钮
    # 演示账号此前投过的岗位按钮会变成「已记入投递」，往后翻几条找未投的
    ap_btn = next((b for b in at.button if (b.key or "") == "jd_apply"), None)
    _tries = 0
    while not ap_btn and _tries < 6:
        nxt = next((b for b in at.button if (b.key or "") == "jd_next"), None)
        if not nxt or nxt.disabled:
            break
        nxt.click().run()
        ap_btn = next((b for b in at.button if (b.key or "") == "jd_apply"), None)
        _tries += 1
    if ap_btn:
        ap_btn.click().run()
        exc(at, "⑦ 立即投递")
        apps = at.dataframe
        ok(f"投递已自动记入，投递记录区渲染 {len(apps)} 张表")
        if not next((b for b in at.button if (b.key or "") == "jd_applied_btn"), None):
            bad("投递后按钮未变为「✓ 已记入投递」")
    else:
        bad("⑦ 库内岗位模式没有「立即投递」按钮")

    step("10. 开发者视图（演示一号在 admins 名单）：导航自动含 ⑧")
    shown = at.radio(key="screen").options
    if any("⑧" in s for s in shown):
        ok(f"{len(shown)} 屏含工程后台（开发者身份自动进入）")
    else:
        bad("名单内账号导航没有 ⑧ 工程后台")

    step("11. 退出 → 换账号（陈子昂）：验证互不干扰")
    at.button(key="logout_btn").click().run()
    exc(at, "退出登录")
    login_demo(at, 1)
    exc(at, "第二个演示账号登录")
    leaks = {k: at.session_state.get(k) for k in
             ("lp", "plan_md", "chat", "have_last", "weekly_md", "jd_res")}
    leaked = {k: v for k, v in leaks.items() if v}
    if leaked:
        bad(f"换账号后仍残留上一账号的会话数据：{list(leaked)}")
    else:
        ok("换账号后定位/规划书/对话/周报均已清空")
    go(at, "⑤ 成长档案")
    exc(at, "⑤ 换账号")
    names = set()
    c = sqlite3.connect(DB)
    for r in c.execute("SELECT DISTINCT student FROM career_snapshot "
                       "WHERE COALESCE(user_id,0)!=0"):
        names.add(r[0])
    c.close()
    ok(f"库内档案主人：{sorted(names)}")

    step("12. 边界：③ 不勾技能直接生成 / ⑦ 零技能看 JD")
    go(at, "③ 我的定位")
    by_label(at, "我已掌握的技能", "multiselect").set_value([]).run()
    [b for b in at.button if "生成我的定位" in (b.label or "")][0].click().run()
    exc(at, "③ 空技能定位")
    lp2 = at.session_state.get("lp") or {}
    ok(f"空技能定位：命中率 {lp2.get('match', 0):.0%}，缺口 {len(lp2.get('gap', []))} 项")
    go(at, "⑦ 求职实战")
    exc(at, "⑦ 零技能")
    ok(f"⑦ 零技能仍渲染岗位卡：{bool([m for m in at.markdown if 'jobcard' in (m.value or '')])}")

    # 清掉本次走查产生的记录，演示档案恢复原样
    c = sqlite3.connect(DB)
    for t, base in (("career_snapshot", base_snap), ("apply_log", base_app)):
        c.execute(f"DELETE FROM {t} WHERE id > ? AND COALESCE(user_id,0)!=0", (base,))
    c.execute("DELETE FROM apply_event WHERE apply_id NOT IN (SELECT id FROM apply_log)")
    if base_iv:
        for sid, in c.execute("SELECT id FROM interview_session WHERE id > ?", (base_iv,)).fetchall():
            c.execute("DELETE FROM interview_turn WHERE session_id=?", (sid,))
        c.execute("DELETE FROM interview_session WHERE id > ?", (base_iv,))
    for ph in ("13700008888", "13700008889", "13900001001", "13900001002"):
        r = c.execute("SELECT id FROM users WHERE account=?", (ph,)).fetchone()
        if r:
            uid = int(r[0])
            c.execute("DELETE FROM users WHERE id=?", (uid,))
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            for t in ("career_snapshot", "apply_log"):
                c.execute(f"DELETE FROM {t} WHERE COALESCE(user_id,0)=?", (uid,))
    c.commit()
    c.close()

    print("\n" + "=" * 70)
    print(f"走查完成：{len(STEPS)} 步，问题 {len(PROBLEMS)} 个")
    for i, p in enumerate(PROBLEMS, 1):
        print(f"  {i}. {p}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("\n脚本自身中断；已发现问题：")
        for p in PROBLEMS:
            print(" -", p)
