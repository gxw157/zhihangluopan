"""测试用演示账号登录助手。

页面上「演示账号」入口已按要求删除，测试不再点按钮，改为直接注入会话
（等价于 _enter 写入的那几个 key：user / _token / student_name / major_name）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import auth as AU  # noqa: E402


def login_demo(at, idx: int = 0) -> None:
    """以第 idx 个演示账号进入 AppTest（0=林小雨，1=陈子昂，2=周乐）。"""
    phone = AU.DEMO_USERS[idx][0]
    u = AU.user_by_account(phone)
    assert u, f"演示账号 {phone} 不存在"
    token = AU.create_session(int(u["id"]))
    at.session_state["user"] = u
    at.session_state["_token"] = token
    at.session_state["student_name"] = u.get("nickname") or "同学"
    if u.get("major"):
        at.session_state["major_name"] = u["major"]
    at.run()
