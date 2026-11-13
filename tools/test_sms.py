"""短信网关自测：未配置拒绝发送 → 配 webhook 后真发 → 验证码可校验 → 还原配置。

    .venv/Scripts/python tools/test_sms.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core import auth as AU  # noqa: E402
from core import sms as SMS  # noqa: E402
from mock_sms_gateway import Handler  # noqa: E402

PHONE = "13900003001"
PORT = 8799


def clean(phone: str) -> None:
    c = sqlite3.connect(AU.DB)
    r = c.execute("SELECT id FROM users WHERE account=?", (phone,)).fetchone()
    if r:
        uid = r[0]
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    c.execute("DELETE FROM sms_code WHERE phone=?", (phone,))
    c.commit()
    c.close()


def main() -> None:
    backup = SMS.CFG.read_text("utf-8") if SMS.CFG.exists() else None
    clean(PHONE)
    try:
        # 0. 阿里云 RPC 签名对官方示例（ECS DescribeRegions / secret=testsecret）
        p = {
            "AccessKeyId": "testid", "Action": "DescribeRegions", "Format": "XML",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": "3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf",
            "SignatureVersion": "1.0", "Timestamp": "2016-02-23T12:46:24Z",
            "Version": "2014-05-26",
        }
        sig = SMS._aliyun_sign(p, "testsecret")
        print("0. 阿里云签名:", sig)
        assert sig == "OLeaidS1JvxuMvnyHOwuJ+uX5qY=", "阿里云签名算法与官方示例不一致"
        assert SMS._pct("a b*c~d") == "a%20b%2Ac~d", "RPC 编码不符合 RFC3986"

        # 1. 未配置 = 拒绝发送，不回显验证码
        if SMS.CFG.exists():
            SMS.CFG.unlink()
        st0 = SMS.status()
        print("1. 未配置:", st0["mode"], "|", st0["tip"])
        assert not st0["ready"], "空配置却判为就绪"
        r = AU.send_code(PHONE)
        print("   发码:", {k: v for k, v in r.items()})
        assert not r["ok"] and not r["demo"] and not r.get("code"), "未配置却发出验证码"
        assert "网关" in r["msg"], f"提示没引导去配网关：{r['msg']}"

        # 2. 配 webhook（指向本地模拟网关）→ 自动切真实短信
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.5)
        SMS.save_cfg({"provider": "webhook", "enabled": True,
                      "webhook": {"url": f"http://127.0.0.1:{PORT}/send",
                                  "token": "", "template": "career_compass",
                                  "sign": "职航罗盘"}})
        st1 = SMS.status()
        print("2. 配好后:", st1["mode"], "|", st1["provider_label"], "| ready =", st1["ready"])
        assert st1["ready"] and st1["mode"] == "真实短信", "配置齐全却没切真实短信"

        clean(PHONE)      # 清掉限流记录，避免冷却
        r2 = AU.send_code(PHONE)
        print("   发码:", {k: v for k, v in r2.items()})
        assert r2["ok"] and not r2["demo"], "没走真实短信"
        assert not r2["code"], "真实短信不该在页面回显验证码"

        # 网关收件箱
        log = ROOT / "data" / "exports" / "sms_outbox.log"
        last = log.read_text("utf-8").strip().splitlines()[-1] if log.exists() else ""
        print("   网关收到:", last)
        assert PHONE in last, "网关没收到请求"

        # 3. 真实验证码能通过校验
        code = last.split("code=")[1].split()[0]
        ok, msg = AU.verify_code(PHONE, code)
        print("3. 校验验证码:", ok, msg)
        assert ok, f"真发出去的验证码校验失败：{msg}"

        # 4. 配置缺项 → 拒绝发送
        SMS.save_cfg({"provider": "aliyun", "enabled": True,
                      "aliyun": {"access_key_id": "LTAI_test"}})
        st2 = SMS.status()
        print("4. 缺项配置:", st2["mode"], "| 缺:", "、".join(st2["missing"]))
        assert not st2["ready"] and st2["mode"] == "未配置", "缺项却判为就绪"

        # 5. 关闭开关 → 也不再发送
        SMS.save_cfg({"provider": "webhook", "enabled": False,
                      "webhook": {"url": f"http://127.0.0.1:{PORT}/send"}})
        st3 = SMS.status()
        print("5. 关闭开关:", st3["mode"])
        assert st3["mode"] == "未配置"

        srv.shutdown()
        print("\n短信网关自测全部通过")
    finally:
        if backup is None:
            if SMS.CFG.exists():
                SMS.CFG.unlink()
        else:
            SMS.CFG.write_text(backup, "utf-8")
        clean(PHONE)
        print("配置已还原：", "无（未配置）" if backup is None else "原 config/sms.json")


if __name__ == "__main__":
    main()
