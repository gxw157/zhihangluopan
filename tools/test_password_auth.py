"""密码登录专项测试（函数级，不跑 UI）：

1. 注册即设密码，无需验证码；手机号全库唯一，重复注册被拒
2. PBKDF2 校验：错密码拒绝、对密码放行、库里不落明文
3. 老账号（无密码）密码登录被拒 → 验证码绑定后可登录
4. 已登录改密码必须验原密码
5. 演示账号自动补默认密码，密码登录通道可用
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth as AU  # noqa: E402

PHONES = ["13900002001", "13900002002", "13900002003"]
_passed = 0


def ok(cond: bool, msg: str) -> None:
    global _passed
    assert cond, f"断言失败：{msg}"
    _passed += 1
    print(f"  ✓ {msg}")


def fresh(phone: str) -> None:
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


def main() -> None:
    import atexit
    for p in PHONES:
        fresh(p)
        atexit.register(fresh, p)
    fresh("张三同学")      # 固定中文账号名：上一次跑完可能还在，先清掉才能重复跑

    print("\n[1] 注册即设密码，无需验证码")
    r = AU.register_password(PHONES[0], "abc12345", "密码甲", "人工智能技术应用")
    ok(r.get("ok"), "注册成功")
    ok(bool(r.get("token")), "注册即登录，发了会话 token")
    c = sqlite3.connect(AU.DB)
    row = c.execute("SELECT password_hash, password_salt FROM users WHERE account=?",
                    (PHONES[0],)).fetchone()
    c.close()
    ok(bool(row[0]) and bool(row[1]), "库里有 password_hash 与 salt")
    ok(PHONES[0].encode() not in (row[0] or "").encode() and "abc12345" not in (row[0] or ""),
       "库里没有明文密码")

    print("\n[2] 账号唯一：重复注册被拒；非法账号名被拒")
    r = AU.register_password(PHONES[0], "other-pass", "密码甲二号")
    ok(not r.get("ok") and "已被注册" in r.get("msg", ""), f"重复账号被拒：{r.get('msg')}")

    r = AU.register_password("ab", "abc12345")
    ok(not r.get("ok") and "3–24 位" in r.get("msg", ""), "过短账号名被拒")

    r = AU.register_password("张三同学", "abc12345", "张三", "人工智能技术应用")
    ok(r.get("ok"), "中文账号名注册成功（无需手机号、无需验证码）")
    ok(AU.login_with_password("张三同学", "abc12345").get("ok"), "中文账号名可密码登录")

    r = AU.register_password(PHONES[1], "123")
    ok(not r.get("ok") and "6 位" in r.get("msg", ""), "弱密码（<6 位）被拒")

    print("\n[3] 密码登录：错密码拒、对密码放行、未注册拒")
    r = AU.login_with_password(PHONES[0], "wrong-pass")
    ok(not r.get("ok") and "账号或密码不对" in r.get("msg", ""), "错密码被拒")
    r = AU.login_with_password("13900009999", "abc12345")
    ok(not r.get("ok") and "还没注册" in r.get("msg", ""), "未注册账号被拒")
    r = AU.login_with_password(PHONES[0], "abc12345")
    ok(r.get("ok") and r.get("token"), "对密码登录成功")
    ok(AU.check_password("abc12345", row[0], row[1]), "PBKDF2 校验函数正确")
    ok(not AU.check_password("abc12346", row[0], row[1]), "PBKDF2 拒绝错密码")

    print("\n[4] 老账号（无密码）→ 拒绝 → 验证码绑定 → 可登录")
    # 造一个「验证码时代」的无密码账号
    c = sqlite3.connect(AU.DB)
    c.execute("INSERT INTO users(account,nickname,major,created_at,last_login,login_count) "
              "VALUES(?,?,?,?,?,1)", (PHONES[2], "老账号丙", "软件技术",
                                      AU._fmt(AU._now()), AU._fmt(AU._now())))
    c.commit()
    c.close()
    r = AU.login_with_password(PHONES[2], "whatever1")
    ok(not r.get("ok") and "还没有设置密码" in r.get("msg", ""), "无密码账号密码登录被拒")
    # 短信只走真发：这里直接写一条验证码记录，模拟"已被真实下发"的码
    _c = AU._conn()
    try:
        _now = AU._now()
        _c.execute("INSERT INTO sms_code(phone,code,purpose,created_at,expire_at,used,remote) "
                   "VALUES(?,?,?,?,?,0,0)", (PHONES[2], "135790", "auth", _now, _now + 300))
        _c.commit()
    finally:
        _c.close()
    r = AU.bind_password_by_code(PHONES[2], "135790", "old-bind-6")
    ok(r.get("ok"), f"验证码绑定密码：{r.get('msg')}")
    r = AU.bind_password_by_code(PHONES[2], "000000", "x2y3z4")
    ok(not r.get("ok"), "错验证码不能绑定")
    r = AU.login_with_password(PHONES[2], "old-bind-6")
    ok(r.get("ok"), "绑定后密码登录成功")

    print("\n[5] 已登录改密码必须验原密码")
    uid0 = int(AU.user_by_phone(PHONES[0])["id"])
    r = AU.set_password(uid0, "new-pass-99", old_password="bad-old")
    ok(not r.get("ok") and "原密码不对" in r.get("msg", ""), "旧密码错，改密被拒")
    r = AU.set_password(uid0, "new-pass-99", old_password="abc12345")
    ok(r.get("ok"), "旧密码对，改密成功")
    r = AU.login_with_password(PHONES[0], "new-pass-99")
    ok(r.get("ok"), "新密码可登录")
    r = AU.login_with_password(PHONES[0], "abc12345")
    ok(not r.get("ok"), "旧密码已失效")

    print("\n[6] 演示账号自动补默认密码")
    AU.ensure_demo_users()
    ok(AU.has_password("13800000001"), "林小雨已支持密码登录")
    r = AU.login_with_password("13800000001", AU.DEMO_PW)
    ok(r.get("ok"), f"演示账号用默认密码 {AU.DEMO_PW} 登录成功")
    r = AU.login_with_password("13800000001", "demo123456 ")
    ok(not r.get("ok"), "密码尾带空格不算通过（不做静默 trim）")

    print(f"\n全部通过（{_passed} 条断言）")


if __name__ == "__main__":
    main()
