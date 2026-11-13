"""账号门禁冒烟测试：首页 → 注册 → 进工作台 → 数据隔离 → 退出登录。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

from core import auth as AU  # noqa: E402

PHONE_A = "13900001001"
PHONE_B = "13900001002"
PHONE_C = "13900001003"


def fresh_phone(phone: str) -> None:
    """清掉测试号码，保证可重复运行。"""
    import sqlite3
    c = sqlite3.connect(AU.DB)
    row = c.execute("SELECT id FROM users WHERE account=?", (phone,)).fetchone()
    if row:
        uid = int(row[0])
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid,))
        c.execute("DELETE FROM apply_log WHERE COALESCE(user_id,0)=?", (uid,))
    c.execute("DELETE FROM sms_code WHERE phone=?", (phone,))
    c.commit()
    c.close()


def deliver_code(phone: str, code: str = "246810") -> str:
    """短信只走真发：测试里直接写一条验证码记录，模拟「已被真实下发」。"""
    import sqlite3
    c = sqlite3.connect(AU.DB)
    now = AU._now()
    c.execute("DELETE FROM sms_code WHERE phone=?", (phone,))
    c.execute("INSERT INTO sms_code(phone,code,purpose,created_at,expire_at,used,remote) "
              "VALUES(?,?,?,?,?,0,0)", (phone, code, "auth", now, now + 300))
    c.commit()
    c.close()
    return code


def show(at: AppTest, tag: str) -> None:
    print(f"--- {tag}: exception={len(at.exception)}")
    for e in at.exception:
        print("   EXC:", e.value)
    print("   text:", [m.value[:60].replace("\n", " ") for m in at.markdown
                       if not m.value.startswith("<")][:4])


def signup(at: AppTest, phone: str, name: str, major: str = "人工智能技术应用",
           password: str = "abc12345") -> None:
    """注册：只有「账号密码」一条通道（短信验证码入口已按要求关闭并注释）。"""
    at.radio(key="lg_mode").set_value("注册新账号").run()
    at.text_input(key="rg_phone").set_value(phone).run()
    at.text_input(key="rg_pwd").set_value(password).run()
    at.text_input(key="rg_pwd2").set_value(password).run()
    at.text_input(key="rg_name").set_value(name).run()
    at.selectbox(key="rg_major").set_value(major).run()
    at.button(key="rg_do").click().run()


def login_pw(at: AppTest, phone: str, password: str) -> None:
    """账号密码登录。"""
    at.radio(key="lg_mode").set_value("登录").run()
    at.text_input(key="lg_phone").set_value(phone).run()
    at.text_input(key="lg_pwd").set_value(password).run()
    at.button(key="lg_do").click().run()
    if at.session_state.get("user") is None:
        print("   登录错误提示：", [e.value for e in at.error])


def login_by_code_api(phone: str) -> dict:
    """验证码登录：页面入口已关（代码注释保留），这里直接验证后端通道没坏。"""
    import sqlite3
    c = sqlite3.connect(AU.DB)
    c.execute("DELETE FROM sms_code WHERE phone=?", (phone,))
    c.commit()
    c.close()
    return AU.login_with_code(phone, deliver_code(phone))


def main() -> None:
    for p in (PHONE_A, PHONE_B, PHONE_C):
        fresh_phone(p)
    # 断言失败也要清：否则会留下「测试甲/测试乙」账号和一条冒烟快照，污染演示档案
    import atexit
    for _p in (PHONE_A, PHONE_B, PHONE_C):
        atexit.register(fresh_phone, _p)

    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=180)
    at.run()
    show(at, "未登录首页")
    assert not at.exception, "首页报错"
    assert any("让每个学生" in m.value for m in at.markdown), "首页 headline 缺失"
    assert at.session_state.get("user") is None, "未登录却有 user"

    signup(at, PHONE_A, "测试甲")
    show(at, "注册后")
    assert not at.exception, "注册流程报错"
    assert at.session_state.get("user"), "注册后没有登录态"
    print("   登录账号：", at.session_state["user"]["account"])

    # 存档一条成长档案，再换账号验证看不到
    from core import pathway as PW
    from core import profile as PF
    uid_a = int(at.session_state["user"]["id"])
    lp = PW.build_path(["Python"], "数据分析", top=8, major="人工智能技术应用")
    PF.save_snapshot("测试甲", lp, ["Python"], "冒烟测试", uid=uid_a)
    print("   甲的快照数：", len(PF.list_snapshots("测试甲", uid_a)))

    at.button(key="logout_btn").click().run()
    show(at, "退出后")
    assert at.session_state.get("user") is None, "退出后仍有登录态"

    # 验证码登录入口已关闭：页面上没有切换控件（后端通道仍可用，单独验一下）
    assert not any((r.key or "") == "lg_sub" for r in at.radio), "页面仍残留「登录方式」切换"
    _api = login_by_code_api(PHONE_A)
    assert _api.get("ok"), f"后端验证码登录通道失效：{_api}"
    print("   验证码登录（仅后端，页面入口已关）：", _api.get("user", {}).get("account"))
    login_pw(at, PHONE_A, "abc12345")
    print("   甲重新登录：", at.session_state.get("user", {}).get("account"))
    assert at.session_state.get("user"), "重新登录失败"
    print("   甲看到的快照：", len(PF.list_snapshots("测试甲", uid_a)))

    at.button(key="logout_btn").click().run()
    login_pw(at, PHONE_A, "abc12345")
    assert at.session_state.get("user"), "密码登录失败"
    print("   甲密码登录：", at.session_state.get("user", {}).get("account"))

    at.button(key="logout_btn").click().run()
    login_pw(at, PHONE_A, "wrong-password")
    assert at.session_state.get("user") is None, "错密码竟然登录成功"
    _h = [m.value or "" for m in at.markdown if 'class="hint"' in (m.value or "")]
    assert any("账号或密码不对" in h for h in _h), f"错密码没有低调提示：{_h[-2:]}"
    assert not [e.value for e in at.error], "错密码还在弹红色错误框"
    print("   错密码被拒（hint 低调提示）：",
          [h for h in _h if "账号或密码不对" in h][:1])

    signup(at, PHONE_B, "测试乙")
    print("   乙登录：", at.session_state.get("user", {}).get("account"))
    uid_b = int(at.session_state["user"]["id"])
    assert uid_b != uid_a, "两个账号 id 相同"
    print("   乙的快照数（应为 0）：", len(PF.list_snapshots("测试甲", uid_b)))
    assert len(PF.list_snapshots("测试甲", uid_b)) == 0, "数据串号了"

    # 验证码注册：页面入口已关（后端 register 仍在，验一下别被注释改坏）
    at.button(key="logout_btn").click().run()
    assert not any((r.key or "") == "rg_sub" for r in at.radio), "页面仍残留「注册方式」切换"
    from core import auth as _A
    _reg = _A.register(PHONE_C, deliver_code(PHONE_C), "测试丙", "人工智能技术应用")
    assert _reg.get("ok"), f"后端验证码注册通道失效：{_reg}"
    print("   验证码注册（仅后端，页面入口已关）：", _reg.get("user", {}).get("account"))

    # 演示账号一键进入（上一个账号已在上面退出，这里直接注入会话）
    login_demo(at, 0)
    show(at, "演示账号")
    print("   演示账号：", at.session_state.get("user", {}).get("nickname"))
    assert at.session_state.get("user", {}).get("account") == "13800000001"

    # 演示账号登录后，成长档案应读到自己账号下的记录（条数随演示/真实使用会变，
    # 不能写死 4：断言的是"读得到 + 只读到自己的"，不是某个固定条数）
    at.radio(key="screen").set_value("⑤ 成长档案").run()
    show(at, "⑤ 成长档案")
    assert not at.exception, "成长档案屏报错"
    _uid = int(at.session_state["user"]["id"])
    _snaps = PF.list_snapshots("林小雨", _uid)
    print("   林小雨快照数：", len(_snaps))
    assert len(_snaps) >= 1, "演示账号档案没读到"
    _other = PF.list_snapshots("林小雨", _uid + 1)
    assert len(_other) == 0 or set(_other["id"]).isdisjoint(set(_snaps["id"])), "档案串到别的账号"

    # 开发者视图由身份自动决定：演示一号在 admins 名单里 → 导航应含 ⑧
    _screens = at.radio(key="screen").options
    assert any("⑧" in s for s in _screens), "名单内账号没拿到 ⑧ 工程后台"
    print(f"   演示一号（开发者）导航（应 8 屏含⑧）：{_screens}")
    # 对照：名单外学生账号（演示二号）不应有 ⑧
    at.button(key="logout_btn").click().run()
    login_demo(at, 1)
    _screens2 = at.radio(key="screen").options
    assert not any("⑧" in s for s in _screens2), "学生账号导航出现了 ⑧"
    print(f"   演示二号（学生）导航（应 7 屏无⑧）：{_screens2}")
    print("\n全部通过")


if __name__ == "__main__":
    main()
