"""本地模拟短信网关：验证「配置 → 真发」这条链路真的通，不需要短信服务商。

用法：
    .venv/Scripts/python tools/mock_sms_gateway.py 8799
    # 然后 config/sms.json 里 provider=webhook、url=http://127.0.0.1:8799/send
    # 首页点「发送验证码」，这里会打印收到的手机号与验证码

收到的每一条都会追加到 data/exports/sms_outbox.log（演示时可当"短信收件箱"看）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTBOX = ROOT / "data" / "exports" / "sms_outbox.log"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            data = json.loads(raw or "{}")
        except Exception:
            data = {"raw": raw}
        line = (f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
                f"phone={data.get('phone', '?')} code={data.get('code', '?')} "
                f"tpl={data.get('tpl', '')} sign={data.get('sign', '')}")
        print(line, flush=True)
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        body = json.dumps({"ok": True, "msg": "accepted"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        body = b'{"ok":true,"msg":"mock sms gateway"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"模拟短信网关已启动：http://127.0.0.1:{port}/send（Ctrl+C 停止）", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
