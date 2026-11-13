"""CDP 轻量浏览器验证：不依赖 chromedriver，直接连 Chrome 调试端口。

验证两件 AppTest 验证不了的事：
1. 首页真实渲染（.lp-hero 出现 + 截图）；
2. URL 带 ?t=<token> 时刷新/直开都能恢复登录态（query_params 会话）。

    .venv/Scripts/python tools/test_cdp.py
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth as AU  # noqa: E402

PORT = 9223
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8531/"
OUT = ROOT / "data" / "exports"


def cdp(ws: websocket.WebSocket, _id: int, method: str, params: dict | None = None):
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            return msg.get("result", {})


def eval_js(ws, expr: str) -> str:
    r = cdp(ws, 100, "Runtime.evaluate",
            {"expression": expr, "returnByValue": True})
    return r.get("result", {}).get("value", "")


def shot(ws, name: str) -> None:
    r = cdp(ws, 200, "Page.captureScreenshot", {"format": "png"})
    (OUT / name).write_bytes(base64.b64decode(r["data"]))
    print("  截图:", name)


def wait_expr(ws, expr: str, timeout: float = 45.0) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = eval_js(ws, expr)
        if v and v != "false":
            return v
        time.sleep(1.2)
    return ""


def new_page(url: str):
    """开一个新标签页并返回 websocket（绕系统代理，直连本机调试端口）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(10):                      # chrome 可能还没就绪
        try:
            r = opener.open(
                urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{url}", method="PUT"))
            t = json.loads(r.read())
            break
        except Exception:
            time.sleep(1.5)
    else:
        raise RuntimeError("Chrome 调试端口没就绪")
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=50)
    cdp(ws, 1, "Page.enable")
    return ws


def main() -> None:
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1400",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_profile"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        # 1. 首页渲染
        ws = new_page(BASE)
        v = wait_expr(ws, "!!document.querySelector('.lp-hero h1')")
        assert v, "首页 hero 没渲染出来"
        print("1. 首页渲染 OK ·", eval_js(ws, "document.querySelector('.lp-hero h1').textContent"))
        print("   注册账号数:", eval_js(
            ws, "document.querySelectorAll('.lp-hero .stat b')[3].textContent"))
        shot(ws, "cdp_landing.png")

        # 2. URL 带 token 直接恢复登录
        users = AU.list_users(10)
        demo = next(u for u in users if u["phone"] == "13800000001")
        token = AU.create_session(int(demo["id"]))
        ws2 = new_page(f"{BASE}?t={token}")
        v = wait_expr(ws2, "!!document.querySelector('.hero h1')")
        assert v, "带 token 打开没有恢复登录态"
        print("2. ?t= 恢复登录 OK ·", eval_js(ws2, "document.querySelector('.acct .nm').textContent"),
              "/", eval_js(ws2, "document.querySelector('.acct .ph').textContent"))
        # 档案名应该自动是账号昵称
        v2 = eval_js(ws2, "document.querySelector('input[aria-label=\"档案名（显示在成长档案上）\"]').value")
        print("   档案名输入框:", v2)
        shot(ws2, "cdp_logged_in.png")

        # 3. 退出登录回到首页
        wait_expr(ws2, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('退出登录'))")
        eval_js(ws2, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('退出登录')).click()")
        v = wait_expr(ws2, "!!document.querySelector('.lp-hero h1')", 30)
        assert v, "退出登录没回到首页"
        print("3. 退出登录 OK，回到首页")
        AU.drop_session(token)
        ws.close(); ws2.close()
        print("\nCDP 浏览器验证全部通过")
    finally:
        chrome.terminate()
        try:
            chrome.wait(5)
        except Exception:
            chrome.kill()


if __name__ == "__main__":
    main()
