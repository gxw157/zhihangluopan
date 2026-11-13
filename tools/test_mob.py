"""Mob 通道自测：本地起一个假的 Mob 接口，验证「发码 → 远程验码 → 一次性」全链路。

真的 Mob 需要企业签名 + IP 白名单，没法自动化跑；这里用等价协议把逻辑跑通：
    POST /sms/sendmsg   {"status": 200}
    POST /sms/verify    {"status": 200 | 468 | 491 ...}

跑法：./.venv/Scripts/python.exe tools/test_mob.py
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth as AU  # noqa: E402
from core import sms as SMS  # noqa: E402

PHONE = "13700007777"
STATE = {"send": 200, "verify": 200, "hits": []}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        STATE["hits"].append((self.path, form))
        if self.path.startswith("/sms/send"):
            code = STATE["send"]
        else:
            code = STATE["verify"]
        body = json.dumps({"status": code}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 静音
        pass


def clean() -> None:
    c = AU._conn()
    try:
        c.execute("DELETE FROM sms_code WHERE phone=?", (PHONE,))
        c.execute("DELETE FROM users WHERE account=?", (PHONE,))
        c.commit()
    finally:
        c.close()


def main() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    old_api = SMS.MOB_API
    SMS.MOB_API = base

    backup = SMS.CFG.read_text("utf-8") if SMS.CFG.exists() else None
    clean()
    try:
        # 1. 没配 = 拒绝发送，不是远程校验
        if SMS.CFG.exists():
            SMS.CFG.unlink()
        assert not SMS.ready(), "没配置不该 ready"
        assert not SMS.remote_verify(), "没配置不该是远程校验"
        r = AU.send_code(PHONE)
        assert not r["ok"] and not r.get("code"), r
        print("1. 未配置 → 拒绝发送、不回显  ✓")
        clean()

        # 2. 配 mob = 真实通道 + 远程校验
        SMS.save_cfg({"provider": "mob", "enabled": True,
                      "mob": {"appkey": "test_key", "appsecret": "test_secret", "zone": "86"}})
        assert SMS.ready()
        assert SMS.remote_verify(), "配了 mob 应该是远程校验"
        print("2. 配置 Mob → 自动切真实短信、走远程校验  ✓")

        # 3. 发送：平台不回显、库里不落明文
        r = AU.send_code(PHONE)
        assert r["ok"] and not r["demo"], r
        assert r["code"] == "", "Mob 通道不能回显验证码"
        path, form = STATE["hits"][-1]
        assert path.startswith("/sms/send"), path
        assert form.get("appkey") == "test_key" and form.get("phone") == PHONE, form
        c = AU._conn()
        try:
            row = c.execute("SELECT code, remote FROM sms_code WHERE phone=? ORDER BY id DESC",
                            (PHONE,)).fetchone()
        finally:
            c.close()
        assert row[0] == "" and int(row[1]) == 1, f"库里不该存明文：{row}"
        print("3. 发送成功：页面不回显、库里 code 为空、remote=1  ✓")

        # 4. 发错码：Mob 说 468
        STATE["verify"] = 468
        ok, msg = AU.verify_code(PHONE, "1234")
        assert not ok and "验证码错误" in msg, msg
        print("4. 错码 → Mob 返回 468 →", msg, " ✓")

        # 5. 发对码：Mob 说 200，且一次性
        STATE["verify"] = 200
        ok, msg = AU.verify_code(PHONE, "1234")
        assert ok, msg
        ok2, msg2 = AU.verify_code(PHONE, "1234")
        assert not ok2 and "已用过" in msg2, msg2
        print("5. 对码通过，第二次判已用  ✓")

        # 6. 发送失败：错误码翻成人话，且不留垃圾记录
        clean()
        STATE["send"] = 469
        r = AU.send_code(PHONE)
        assert not r["ok"] and "http-api" in r["msg"], r["msg"]
        print("6. 469 →", r["msg"][:46], "…  ✓")
        c = AU._conn()
        try:
            n = c.execute("SELECT COUNT(*) FROM sms_code WHERE phone=?", (PHONE,)).fetchone()[0]
        finally:
            c.close()
        assert n == 0, "失败应删掉这条记录，允许立刻重试"
        print("   失败不留记录，用户可直接重试  ✓")

        # 7. 服务端验证开关没开 = 474
        STATE["send"] = 474
        r = SMS.send_test(PHONE)
        assert not r["ok"] and "服务端验证" in r["msg"], r["msg"]
        print("7. 474 →", r["msg"][:40], "…  ✓")

        # 8. 关掉开关 → 不再就绪
        cfg = SMS.load_cfg()
        cfg["enabled"] = False
        SMS.save_cfg(cfg)
        assert not SMS.ready() and not SMS.remote_verify()
        print("8. 手动关闭 → 不再就绪、拒绝发送  ✓")

        print("\n全部通过（Mob 通道与本地通道并存，互不影响）")
    finally:
        SMS.MOB_API = old_api
        if backup is None:
            if SMS.CFG.exists():
                SMS.CFG.unlink()
        else:
            SMS.save_cfg(json.loads(backup))
        clean()
        srv.shutdown()


if __name__ == "__main__":
    main()
