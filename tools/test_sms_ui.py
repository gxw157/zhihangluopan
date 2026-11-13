"""短信入口已关闭的回归：登录/注册页与工程后台都不再出现验证码相关控件。

背景：短信网关没接好，按要求把「手机验证码登录/注册」和后台「短信通道」整段注释掉了
（代码没删，注释保留，日后解开即可恢复）。这个测试盯住「界面上确实看不见」这件事，
防止以后有人顺手又加回来；后端通道（core/auth、core/sms）本身仍可用，另见 test_auth。

跑法：.venv/Scripts/python.exe tools/test_sms_ui.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

BAD: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    BAD.append(msg)
    print(f"  ❌ {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def _keys(items, attr: str = "key") -> set[str]:
    return {(getattr(x, attr, "") or "") for x in items}


def main() -> None:
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=180)
    at.run()
    check(not at.exception, "首页无异常")

    print("— A. 登录页：只剩账号密码")
    at.radio(key="lg_mode").set_value("登录").run()
    check(not ({"lg_sub"} & _keys(at.radio)), "没有「登录方式」切换（短信入口已注释）")
    check(not ({"lg_code"} & _keys(at.text_input)), "没有验证码输入框")
    check(not ({"lg_send"} & _keys(at.button)), "没有「发送验证码」按钮")
    check(bool({"lg_phone"} & _keys(at.text_input)), "账号输入框在")
    check(bool({"lg_pwd"} & _keys(at.text_input)), "密码输入框在")
    check(bool({"lg_do"} & _keys(at.button)), "「登 录」按钮在")

    print("\n— B. 注册页：只剩账号密码")
    at.radio(key="lg_mode").set_value("注册新账号").run()
    check(not ({"rg_sub"} & _keys(at.radio)), "没有「注册方式」切换（短信入口已注释）")
    check(not ({"rg_code"} & _keys(at.text_input)), "没有验证码输入框")
    check(not ({"rg_send"} & _keys(at.button)), "没有「发送验证码」按钮")
    check(bool({"rg_phone", "rg_pwd", "rg_pwd2", "rg_name"} & _keys(at.text_input)),
          "账号 / 密码 / 确认密码 / 姓名 四个输入框都在")
    check(bool({"rg_major"} & _keys(at.selectbox)), "专业下拉在")

    print("\n— C. 工程后台：短信通道配置区不可见")
    at.radio(key="lg_mode").set_value("登录").run()
    login_demo(at, 0)      # 林小雨：开发者名单内，带 ⑧ 工程后台
    at.radio(key="screen").set_value("⑧ 工程后台").run()
    check(not at.exception, "工程后台无异常")
    _body = " ".join((m.value or "") for m in at.markdown)
    check("短信通道" not in _body, "后台不再出现「短信通道」")
    check("配置短信网关" not in _body, "后台不再出现「配置短信网关」")
    check("发一条测试短信" not in " ".join((b.label or "") for b in at.button),
          "后台不再有「发一条测试短信」按钮")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
