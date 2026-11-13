"""专业广度验收（CDP）：36 个专业可搜可选、切到会计专业后②按财务方向算、⑦城市全量。

跑法：先起 8561 服务，再 .venv/Scripts/python.exe tools/test_major_breadth_cdp.py
截图：data/exports/mb_*.png
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

PORT = 9262
BASE = "http://127.0.0.1:8561/"
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
        if v and v != "false":
            return v
        time.sleep(1.0)
    return ""


def check(cond, msg):
    print(("   ✅ " if cond else "   ❌ ") + msg)
    if not cond:
        BAD.append(msg)


def click_at(ws, x, y):
    cdp(ws, 300, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": float(x), "y": float(y)})
    time.sleep(0.1)
    for t in ("mousePressed", "mouseReleased"):
        cdp(ws, 300, "Input.dispatchMouseEvent",
            {"type": t, "x": float(x), "y": float(y), "button": "left", "clickCount": 1})
        time.sleep(0.15)


def new_page(url):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t = None
    for _ in range(10):
        try:
            r = op.open(urllib.request.Request(
                f"http://127.0.0.1:{PORT}/json/new?{url}", method="PUT"))
            t = json.loads(r.read())
            break
        except Exception:
            time.sleep(1.5)
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=90)
    cdp(ws, 1, "Page.enable")
    return ws


def open_panel(ws, label):
    js(ws, f"""(()=>{{const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
              .find(e=>e.innerText.includes('{label}'));
              if(b) b.scrollIntoView({{block:'center'}}); return b?'ok':'no'}})()""")
    time.sleep(0.8)
    box = js(ws, f"""(()=>{{const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
              .find(e=>e.innerText.includes('{label}')); if(!b) return null;
              const c=b.getBoundingClientRect(); return {{x:Math.round(c.left+40),y:Math.round(c.top+14)}}}})()""")
    if not isinstance(box, dict):
        return False
    click_at(ws, box["x"], box["y"])
    time.sleep(1.3)
    return True


def panel_items(ws):
    return js(ws, """(()=>{const f=document.querySelector('.ss-panel');
      if(!f) return null; const p=f.closest('[data-testid="stPopoverBody"]');
      const bs=[...p.querySelectorAll('button')].map(e=>e.innerText.trim());
      return {n:bs.length, first:bs.slice(0,3), last:bs.slice(-2)}})()""")


def type_and_enter(ws, text):
    js(ws, """(()=>{const p=document.querySelector('.ss-panel')
              .closest('[data-testid="stPopoverBody"]');
              const i=p.querySelector('input'); i.focus(); i.select(); return 'ok'})()""")
    cdp(ws, 400, "Input.insertText", {"text": text})
    time.sleep(0.4)
    for t in ("char", "keyDown", "keyUp"):
        cdp(ws, 401, "Input.dispatchKeyEvent",
            {"type": t, "key": "Enter", "code": "Enter",
             "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
    time.sleep(2.0)


def click_first(ws):
    box = js(ws, """(()=>{const p=document.querySelector('.ss-panel')
              .closest('[data-testid="stPopoverBody"]');
              const b=p.querySelector('button'); const c=b.getBoundingClientRect();
              return {x:Math.round(c.left+c.width/2),y:Math.round(c.top+c.height/2)}})()""")
    if not isinstance(box, dict):
        return False
    click_at(ws, box["x"], box["y"])
    time.sleep(2.6)
    return True


def nav(ws, idx):
    js(ws, f"""(()=>{{const i=document.querySelector('input[type="radio"][value="{idx}"]');
              if(!i) return 'no'; i.closest('label').click(); return 'ok'}})()""")


def main():
    demo = next(u for u in AU.list_users(200) if u["account"] == "13800000001")
    token = AU.create_session(int(demo["id"]))

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1500",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_mb"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        wait(ws, "document.body.innerText.includes('我的专业')", 60)
        time.sleep(1.5)
        shot(ws, "mb_1_sidebar.png")

        print("1. 侧边栏专业面板：36 个专业按大类排")
        check(open_panel(ws, "我的专业"), "点开专业下拉")
        it = panel_items(ws)
        print("   ", it)
        check(isinstance(it, dict) and it["n"] >= 30, f"列出 {it and it['n']} 个专业")
        check(isinstance(it, dict) and "现代农业技术" in str(it["first"]),
              "首项是农林牧渔大类（按专业大类顺序排）")
        shot(ws, "mb_2_majors.png")

        print("2. 搜「会计」→ 选中大数据与会计")
        type_and_enter(ws, "会计")
        it2 = panel_items(ws)
        print("   ", it2)
        check(isinstance(it2, dict) and it2["n"] == 1 and "会计" in str(it2["first"]),
              "只剩会计相关专业")
        click_first(ws)
        trig = js(ws, """(()=>{const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
                   .find(e=>e.innerText.includes('我的专业')); return b?b.innerText.replace(/\\n/g,'|'):'-'})()""")
        check("会计" in str(trig), f"按钮显示新专业：{str(trig)[:30]}")
        chip = js(ws, """(()=>{const e=document.querySelector('.major-chip');return e?e.innerText.replace(/\\n/g,'|'):'-'})()""")
        print("   专业卡:", chip)
        check("财经商贸" in str(chip), "专业卡显示财经商贸大类")
        shot(ws, "mb_3_accounting.png")

        print("3. ② 方向画像：默认落在财务方向")
        nav(ws, 1)
        time.sleep(3)
        nav(ws, 1)
        wait(ws, "document.body.innerText.includes('方向画像')", 60)
        time.sleep(2.0)
        t2 = js(ws, "document.body.innerText")
        check("财务" in str(t2), "② 方向默认财务")
        check("加权覆盖率" in str(t2) or "样本太少" in str(t2), "② 覆盖率区块有结果或提示")
        shot(ws, "mb_4_screen2.png")

        print("4. ⑦ 城市下拉：库内全部城市")
        nav(ws, 6)
        time.sleep(3)
        nav(ws, 6)
        wait(ws, "document.body.innerText.includes('投递记录')", 90)
        time.sleep(1.5)
        check(open_panel(ws, "城市"), "点开城市下拉")
        it3 = panel_items(ws)
        print("   城市:", it3)
        check(isinstance(it3, dict) and it3["n"] >= 20, f"城市 {it3 and it3['n']} 个（不再只 15 个）")
        shot(ws, "mb_5_city.png")
    finally:
        chrome.terminate()

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
