"""真浏览器验收：本轮删掉的入口/模块确实不在页面上（CDP）。

跑法：先起服务（8546），再 .venv/Scripts/python.exe tools/test_ui_cleanup.py
截图落在 data/exports/clean_*.png。
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

ROOT = Path(r"D:/WorkBuddyP/outputs/zhihang-luopan")
sys.path.insert(0, str(ROOT))
from core import auth as AU  # noqa: E402

PORT = 9252
BASE = "http://127.0.0.1:8547/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = ROOT / "data" / "exports"
OUT.mkdir(parents=True, exist_ok=True)
BAD: list[str] = []


def cdp(ws, _id, method, params=None):
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            return msg.get("result", {})


def js(ws, expr):
    return cdp(ws, 100, "Runtime.evaluate", {"expression": expr, "returnByValue": True}
               ).get("result", {}).get("value", "")


def shot(ws, name):
    r = cdp(ws, 200, "Page.captureScreenshot", {"format": "png"})
    (OUT / name).write_bytes(base64.b64decode(r["data"]))
    print("   📸", name)


def wait(ws, expr, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = js(ws, expr)
        if v:
            return v
        time.sleep(1.0)
    return ""


def check(cond, msg):
    print(("   ✅ " if cond else "   ❌ ") + msg)
    if not cond:
        BAD.append(msg)


def new_page(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t = None
    for _ in range(10):
        try:
            r = opener.open(urllib.request.Request(
                f"http://127.0.0.1:{PORT}/json/new?{url}", method="PUT"))
            t = json.loads(r.read())
            break
        except Exception:
            time.sleep(1.5)
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=90)
    cdp(ws, 1, "Page.enable")
    return ws


def nav(ws, idx):
    js(ws, f"""(() => {{
      const i=document.querySelector('input[type="radio"][value="{idx}"]');
      if(!i) return 'no'; i.closest('label').click(); return 'ok';
    }})()""")


def text(ws):
    return js(ws, "document.body.innerText") or ""


def main():
    demo = next(u for u in AU.list_users(200) if u["account"] == "13800000001")
    token = AU.create_session(int(demo["id"]))

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1700",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_clean"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        # ---------- A. 未登录首页：折叠入口与演示账号快捷按钮都已删除
        ws = new_page(BASE)
        wait(ws, "!!document.querySelector('.lp-hero h1')")
        time.sleep(1.5)
        shot(ws, "clean_1_landing.png")
        t = text(ws)
        check("老账号绑定密码" not in t, "「老账号绑定密码」入口已删除")
        check("一键进入" not in t and "演示账号" not in t,
              "演示账号快捷入口已删除（连那一行按钮一起）")
        _btns = js(ws, """[...document.querySelectorAll('button')]
              .filter(b=>['林小雨','陈子昂','周乐'].includes(b.textContent.trim())).length""")
        check(int(_btns or 0) == 0, "首页不再有演示账号小按钮")
        _expand = js(ws, """[...document.querySelectorAll('[data-testid="stExpander"]')]
              .map(e=>e.innerText.split('\\n')[0]).join('|')""")
        check("老账号绑定密码" not in str(_expand), "登录卡内已无该折叠项")

        # ---------- B. ⑥ AI 顾问：三块配置/工作台已删除
        ws2 = new_page(f"{BASE}?t={token}")
        wait(ws2, "document.querySelectorAll('input[type=radio]').length>=8")
        nav(ws2, 5)
        time.sleep(2.0)
        nav(ws2, 5)
        time.sleep(2.5)
        t6 = text(ws2)
        shot(ws2, "clean_2_ai.png")
        for k in ("平台引擎工作台", "Coze 接入配置", "Dify 本地化部署"):
            check(k not in t6, f"⑥ 已无「{k}」")

        # ---------- C. ⑦ 求职实战：粘贴 JD / 多 JD / 行动清单 / 补记 全删
        nav(ws2, 6)
        time.sleep(2.5)
        nav(ws2, 6)
        wait(ws2, "document.body.innerText.includes('简历技能段生成器')", 90)
        time.sleep(2.0)
        shot(ws2, "clean_3_jd.png")
        t7 = text(ws2)
        check("粘贴 JD" not in t7, "⑦ 已无「粘贴 JD」")
        check("再贴两条 JD" not in t7, "⑦ 已无「再贴两条 JD」对比")
        check("本周投递行动清单" not in t7, "⑦ 已无「本周投递行动清单」")
        check("补记一条在别处投的岗" not in t7, "⑦ 已无「补记一条在别处投的岗」")
        check("第" in t7 and "条" in t7 and "立即投递" in t7 or "已记入投递" in t7,
              "⑦ 库内岗位卡 + 投递按钮仍在")
        check("简历技能段生成器" in t7 or "简历" in t7, "⑦ 简历模块仍在")
        check("条 · " not in t7 and "方向</div>" not in t7,
              "⑦ 岗位导航只剩「第 N / M 条」，不再挂「· XX方向」")

        # ---------- D. ⑤ 选中记录：不再有「按上一条重算」警告
        nav(ws2, 4)
        time.sleep(2.5)
        nav(ws2, 4)
        wait(ws2, "!!document.querySelector('[data-testid=\"stDataFrame\"] canvas')", 90)
        time.sleep(1.5)
        js(ws2, """(()=>{const els=[...document.querySelectorAll('[data-testid="stDataFrame"]')];
              els[els.length-1].scrollIntoView({block:'center'}); return 'ok'})()""")
        time.sleep(1.0)
        r = js(ws2, """(()=>{const els=[...document.querySelectorAll('[data-testid="stDataFrame"]')];
              const b=els[els.length-1].querySelector('canvas').getBoundingClientRect();
              return {l:Math.round(b.left+25), t:Math.round(b.top)};})()""")
        if isinstance(r, dict):
            for tt in ("mousePressed", "mouseReleased"):
                cdp(ws2, 300, "Input.dispatchMouseEvent",
                    {"type": tt, "x": float(r["l"]), "y": float(r["t"] + 40),
                     "button": "left", "clickCount": 1})
                time.sleep(0.15)
            time.sleep(1.0)
            wait(ws2, "document.body.innerText.includes('删除选中 1 条')", 30)
            time.sleep(1.0)
            shot(ws2, "clean_4_pick.png")
            _body = text(ws2)
            check(not bool(js(ws2, "!!document.querySelector('.pick')")),
                  "⑤ 不再有「📌 已选中」卡片")
            check("删除选中 1 条" in _body, "⑤ 勾一行 → 出现「🗑 删除选中 1 条」")
            check("勾最左一列" not in _body and "删除后不可恢复" not in _body,
                  "⑤ 没有多余提示语句")
    finally:
        chrome.terminate()
        print("   🧹 浏览器已关闭")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
