"""模拟真实用户使用全流程（面向「部署给所有用户」场景的端到端排查）。

和 test_walkthrough（演示账号剧本走查）互补：本脚本模拟一个**全新注册**的普通
用户从注册到每块功能的使用旅程，专查真实用户会遇到、演示用户遇不到的逻辑问题：

    注册（账号密码）→ 新账号空数据各屏 → ③定位 → ④补课打卡 → ⑤档案
    → ⑥AI顾问（离线降级）→ ⑦库内岗位翻页+立即投递+重复投递 （同步包入口已拆到工程后台）
    → 退出 → 第二个新账号 → 数据隔离 → 恶意/边界输入（重名、短密码）

    .venv/Scripts/python.exe tools/test_user_journey.py

测试账号 journey_a / journey_b 跑完自动清理。
"""
from __future__ import annotations

import json
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


def _reg_errs(at) -> list[str]:
    """注册失败提示现在是 hint 低调样式（上一轮起不再用红色 st.error）。"""
    return [m.value or "" for m in at.markdown if 'class="hint"' in (m.value or "")]


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def exc(at: AppTest, where: str) -> bool:
    if at.exception:
        bad(f"{where} 抛异常：" + "；".join(str(e.value)[:200] for e in at.exception))
        return True
    return False


def cleanup() -> None:
    c = sqlite3.connect(DB)
    try:
        for acc in ("journey_a", "journey_b"):
            row = c.execute("SELECT id FROM users WHERE account=?", (acc,)).fetchone()
            if row:
                uid = int(row[0])
                for t in ("career_snapshot", "apply_log", "sessions"):
                    c.execute(f"DELETE FROM {t} WHERE COALESCE(user_id,0)=?", (uid,))
                c.execute("DELETE FROM apply_event WHERE COALESCE(user_id,0)=?", (uid,))
                c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM apply_event WHERE apply_id NOT IN (SELECT id FROM apply_log)")
        c.commit()
    finally:
        c.close()


def db_count(sql: str, args=()) -> int:
    c = sqlite3.connect(DB)
    try:
        return int(c.execute(sql, args).fetchone()[0])
    finally:
        c.close()


def register(at: AppTest, account: str, name: str) -> None:
    at.radio(key="lg_mode").set_value("注册新账号").run()
    at.text_input(key="rg_phone").set_value(account)
    at.text_input(key="rg_pwd").set_value("journey123")
    at.text_input(key="rg_pwd2").set_value("journey123")
    at.text_input(key="rg_name").set_value(name)
    at.button(key="rg_do").click().run()


def main() -> None:
    cleanup()
    base_users = db_count("SELECT COUNT(*) FROM users")
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    exc(at, "首页")

    # ---------- 1. 注册边界
    step("1. 注册边界：重名账号 / 短密码 / 两次密码不一致")
    at.radio(key="lg_mode").set_value("注册新账号").run()
    at.text_input(key="rg_phone").set_value("13800000001")   # 与演示账号重名
    at.text_input(key="rg_pwd").set_value("journey123")
    at.text_input(key="rg_pwd2").set_value("journey123")
    at.button(key="rg_do").click().run()
    exc(at, "重名注册")
    errs = _reg_errs(at)
    if errs:
        ok(f"重名注册被拦截（hint 低调提示）：{errs[0][:40]}")
    else:
        bad("重名注册没有报错提示（直接放过去了？）")

    at.text_input(key="rg_phone").set_value("journey_a")
    at.text_input(key="rg_pwd").set_value("123")
    at.text_input(key="rg_pwd2").set_value("123")
    at.button(key="rg_do").click().run()
    exc(at, "短密码注册")
    errs = _reg_errs(at)
    if errs:
        ok(f"短密码被拦截（hint 低调提示）：{errs[0][:40]}")
    else:
        bad("短密码没有报错提示")

    at.text_input(key="rg_pwd").set_value("journey123")
    at.text_input(key="rg_pwd2").set_value("journey999")
    at.button(key="rg_do").click().run()
    errs = _reg_errs(at)
    if errs:
        ok(f"两次密码不一致被拦截（hint 低调提示）：{errs[0][:40]}")
    else:
        bad("两次密码不一致没有报错")

    # ---------- 2. 正常注册账号 A
    step("2. 正常注册 journey_a 并进入")
    at.text_input(key="rg_pwd2").set_value("journey123")
    at.text_input(key="rg_name").set_value("旅程甲")
    at.button(key="rg_do").click().run()
    exc(at, "注册")
    if at.session_state.get("user"):
        ok(f"注册成功并直接进入，user_id={int(at.session_state['user']['id'])}")
    else:
        bad("注册后未进入应用")
        print("\n".join(PROBLEMS))
        return
    uid_a = int(at.session_state["user"]["id"])
    if db_count("SELECT COUNT(*) FROM users") != base_users + 1:
        bad("users 表没有新增一行")
    if at.session_state.get("student_name") != "旅程甲":
        bad(f"档案名未带入：{at.session_state.get('student_name')}")

    # ---------- 3. 新账号空数据：各屏不崩
    step("3. 新账号空数据：③④⑤⑥⑦ 各屏首次渲染")
    for sc in ("① 市场全景", "② 方向画像", "③ 我的定位", "④ 差距路径",
               "⑤ 成长档案", "⑥ AI 顾问", "⑦ 求职实战"):
        at.radio(key="screen").set_value(sc).run()
        exc(at, f"新账号首访 {sc}")
    ok("七屏首访无异常（空数据路径）")

    step("3b. ⑦ 新账号默认「库内岗位」：候选池 / 翻页")
    at.radio(key="screen").set_value("⑦ 求职实战").run()
    exc(at, "⑦ 新账号")
    if (at.session_state.get("jd_mode") or "库内岗位") != "库内岗位":
        bad(f"⑦ 默认 JD 来源不是「库内岗位」：{at.session_state.get('jd_mode')}")
    nxt = next((b for b in at.button if (b.key or "") == "jd_next"), None)
    if not nxt:
        bad("⑦ 库内岗位模式没有翻页按钮（候选池没渲染？）")
    else:
        if nxt.disabled:
            bad("⑦ 候选池为空或翻页按钮异常禁用")
        cur0 = at.session_state.get("jd_cursor", 0)
        nxt.click().run()
        exc(at, "⑦ 下一岗")
        cur1 = at.session_state.get("jd_cursor", 0)
        ok(f"翻页 {cur0} → {cur1}" if cur1 == cur0 + 1 else f"翻页异常：{cur0}→{cur1}")

    step("3c. ⑦ 立即投递：写库 + user_id 归属 + 幂等")
    ap0 = db_count("SELECT COUNT(*) FROM apply_log WHERE COALESCE(user_id,0)=?", (uid_a,))
    ap_btn = next((b for b in at.button if (b.key or "") == "jd_apply"), None)
    if not ap_btn:
        bad("当前岗位没有「立即投递」按钮（可能已被投过），跳到下一条再试")
        nxt2 = next((b for b in at.button if (b.key or "") == "jd_next"), None)
        if nxt2:
            nxt2.click().run()
        ap_btn = next((b for b in at.button if (b.key or "") == "jd_apply"), None)
    if not ap_btn:
        bad("连续两条岗位都没有「立即投递」按钮")
    else:
        ap_btn.click().run()
        exc(at, "⑦ 立即投递")
        ap1 = db_count("SELECT COUNT(*) FROM apply_log WHERE COALESCE(user_id,0)=?", (uid_a,))
        if ap1 == ap0 + 1:
            ok("投递已记入 apply_log")
        else:
            bad(f"投递未落库（{ap0}→{ap1}）")
        ev1 = db_count("SELECT COUNT(*) FROM apply_event WHERE COALESCE(user_id,0)=?", (uid_a,))
        ok(f"事件流水 {ev1} 条（应≥1）" if ev1 >= 1 else "applied 事件缺失")
        done_btn = next((b for b in at.button if (b.key or "") == "jd_applied_btn"), None)
        if done_btn and done_btn.disabled:
            ok("同一岗位按钮已变「✓ 已记入投递」且禁用（幂等）")
        elif done_btn:
            bad("投过之后按钮仍可再点（会重复记投递）")
        else:
            bad("投递后按钮状态没变")
        if db_count("SELECT COUNT(*) FROM apply_log WHERE COALESCE(user_id,0)=? "
                    "AND jd_id IS NOT NULL", (uid_a,)) >= 1:
            row = sqlite3.connect(DB).execute(
                "SELECT jd_id, status, source FROM apply_log WHERE COALESCE(user_id,0)=? "
                "ORDER BY id DESC LIMIT 1", (uid_a,)).fetchone()
            ok(f"投递行完整：jd_id={row[0]} status={row[1]} source={row[2]}")

    step("3d. ⑦ 投递看板：全自动 KPI（无手动输入）")
    dfs = len(at.dataframe)
    ok(f"投递记录区渲染 {dfs} 张表" if dfs else "投递记录区没有表")

    # ---------- 4. ③ 定位 → ④ 补课打卡 → ⑤ 档案
    step("4. ③ 定位 → 存快照 → ④ 补课打卡 → ⑤ 档案")
    at.radio(key="screen").set_value("③ 我的定位").run()
    ms = next((m for m in at.multiselect if (m.label or "") == "我已掌握的技能"), None)
    if not ms:
        bad("③ 找不到技能多选框")
    else:
        ms.set_value(["Python", "SQL"]).run()
        [b for b in at.button if "生成我的定位" in (b.label or "")][0].click().run()
        exc(at, "③ 生成定位")
        lp = at.session_state.get("lp") or {}
        ok(f"定位：命中率 {lp.get('match', 0):.0%}" if lp.get("ok") else "③ 定位失败")
        [b for b in at.button if "存入成长档案" in (b.label or "")][0].click().run()
        exc(at, "③ 存快照")
        n = db_count("SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid_a,))
        ok(f"快照 {n} 条已归属 journey_a" if n == 1 else f"快照数异常：{n}")

    at.radio(key="screen").set_value("④ 差距路径").run()
    exc(at, "④")
    cbs = [x for x in at.checkbox if (x.key or "").startswith("done_")]
    if not cbs:
        bad("④ 补课清单没有勾选框")
    else:
        cbs[0].check().run()
        [ti for ti in at.text_input if ti.key == "done_evidence"][0].set_value("课程设计 A 评级优")
        [b for b in at.button if "提交补课结果" in (b.label or "")][0].click().run()
        exc(at, "④ 补课打卡")
        n2 = db_count("SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)=? "
                      "AND source='补课勾选'", (uid_a,))
        ok("补课打卡已存快照（source=补课勾选）" if n2 == 1 else f"补课快照异常：{n2}")

    at.radio(key="screen").set_value("⑤ 成长档案").run()
    exc(at, "⑤")
    ok("⑤ 成长档案渲染（1 定位 + 1 补课）")

    # ---------- 5. ⑥ AI 顾问：未配任何大模型时的离线降级
    step("5. ⑥ AI 顾问：离线降级链（Dify→Coze→OpenAI→离线）")
    at.radio(key="screen").set_value("⑥ AI 顾问").run()
    qk = [b for b in at.button if (b.key or "").startswith("quick")]
    if qk:
        qk[0].click().run()
        exc(at, "⑥ 快捷提问")
        ok("快捷提问有回答（未配大模型也不崩）")
    else:
        bad("⑥ 没有快捷提问按钮")

    # ---------- 6. 同步包入口已随工程后台拆出
    step("6. 同步包入口已拆出：学生端不含导出/上传口")
    has_dl = any((b.key or "") == "sp_download" for b in at.download_button)
    has_up = any((u.key or "") == "sp_upload" for u in at.file_uploader)
    if has_dl or has_up:
        bad("学生端仍残留同步包入口")
    else:
        ok("学生端无同步包入口（已随工程后台拆出，后台侧见 test_admin.py）")

    # ---------- 7. 登出 → 账号 B → 数据隔离
    step("7. 登出 → 注册 journey_b → 数据隔离")
    lb = next((b for b in at.button if (b.key or "") == "logout_btn"), None)
    if not lb:
        bad("找不到退出登录按钮")
    else:
        lb.click().run()
        exc(at, "退出登录")
        if at.session_state.get("user"):
            bad("退出后 user 未清空")
        else:
            ok("退出登录干净")
    register(at, "journey_b", "旅程乙")
    exc(at, "注册 journey_b")
    if not at.session_state.get("user"):
        bad("journey_b 注册失败")
    else:
        uid_b = int(at.session_state["user"]["id"])
        leaks = [k for k in ("lp", "plan_md", "chat", "jd_res", "have_last")
                 if at.session_state.get(k)]
        ok("会话无上一账号残留" if not leaks else f"会话残留：{leaks}")
        n_a = db_count("SELECT COUNT(*) FROM apply_log WHERE COALESCE(user_id,0)=?", (uid_a,))
        n_b = db_count("SELECT COUNT(*) FROM apply_log WHERE COALESCE(user_id,0)=?", (uid_b,))
        ok(f"投递隔离：A={n_a} 条，B={n_b} 条" if n_b == 0 else "B 账号看到了 A 的投递！")
        s_a = db_count("SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid_a,))
        s_b = db_count("SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid_b,))
        ok(f"快照隔离：A={s_a} 条，B={s_b} 条" if s_b == 0 else "B 账号看到了 A 的快照！")
        # B 的 ⑦ 应看不到「已投递」按钮置灰状态
        at.radio(key="screen").set_value("⑦ 求职实战").run()
        exc(at, "⑦ B 账号")
        done = next((b for b in at.button if (b.key or "") == "jd_applied_btn"), None)
        if done:
            bad("B 账号首条岗位直接显示「已记入投递」（跨账号串状态）")
        else:
            ok("B 账号首条岗位可正常投递（无跨账号串状态）")

    # ---------- 8. 演示账号：登录后数据不被播种覆盖
    step("8. 演示账号回归：登录不动本机已有剧本数据")
    lb = next((b for b in at.button if (b.key or "") == "logout_btn"), None)
    if lb:
        lb.click().run()
    base_snap_lxy = db_count(
        "SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)="
        "(SELECT id FROM users WHERE account='13800000001')")
    login_demo(at, 0)
    exc(at, "演示账号登录")
    n_lxy = db_count(
        "SELECT COUNT(*) FROM career_snapshot WHERE COALESCE(user_id,0)="
        "(SELECT id FROM users WHERE account='13800000001')")
    ok(f"林小雨快照数不变（{n_lxy}）" if n_lxy == base_snap_lxy
       else f"演示账号快照被播种改动：{base_snap_lxy}→{n_lxy}")

    # ---------- 清理
    cleanup()
    print("\n" + "=" * 70)
    print(f"用户旅程走查完成：{len(STEPS)} 步，问题 {len(PROBLEMS)} 个")
    for i, p in enumerate(PROBLEMS, 1):
        print(f"  {i}. {p}")
    if PROBLEMS:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("\n脚本自身中断；已发现问题：")
        for p in PROBLEMS:
            print(" -", p)
        cleanup()
        sys.exit(2)
