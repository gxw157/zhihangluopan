"""搜索下拉的视觉验收（CDP）：点开面板 → 搜索框在列表顶部 → 过滤 → 选中 → 收起。

跑法：先起 8561 服务，再 .venv/Scripts/python.exe tools/test_search_cdp.py
截图：data/exports/ss_*.png
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

PORT = 9256
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
    for t in ("mousePressed", "mouseReleased"):
        cdp(ws, 300, "Input.dispatchMouseEvent",
            {"type": t, "x": float(x), "y": float(y), "button": "left", "clickCount": 1})
        time.sleep(0.15)


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


def open_panel(ws, label_prefix):
    """点开指定触发按钮，返回面板是否出现。"""
    r = js(ws, f"""(()=>{{
      const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
        .find(e=>e.innerText.includes('{label_prefix}'));
      if(!b) return 'no'; b.scrollIntoView({{block:'center'}}); return 'ok'}})()""")
    if r != "ok":
        return False
    time.sleep(0.8)
    box = js(ws, f"""(()=>{{
      const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
        .find(e=>e.innerText.includes('{label_prefix}'));
      const c=b.getBoundingClientRect(); return {{x:Math.round(c.left+40),y:Math.round(c.top+14)}}}})()""")
    if not isinstance(box, dict):
        return False
    click_at(ws, box["x"], box["y"])
    time.sleep(1.2)
    return True


def panel_info(ws):
    return js(ws, """(()=>{
      const flag=document.querySelector('.ss-panel');
      if(!flag) return null;
      const card=flag.closest('[data-testid="stPopoverBody"]')||flag.parentElement;
      const inp=card.querySelector('input');
      const btns=[...card.querySelectorAll('button')];
      const ir=inp?inp.getBoundingClientRect():null;
      const br=btns.length?btns[0].getBoundingClientRect():null;
      return {n:btns.length, hasInput:!!inp,
              inputTop: ir?Math.round(ir.top):null, firstBtnTop: br?Math.round(br.top):null,
              text: card.innerText.slice(0,60),
              w: Math.round(card.getBoundingClientRect().width)}})()""")


def main():
    demo = next(u for u in AU.list_users(200) if u["account"] == "13800000001")
    token = AU.create_session(int(demo["id"]))

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1400",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_ss"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        wait(ws, "document.body.innerText.includes('我的专业')", 60)
        time.sleep(1.5)
        shot(ws, "ss_1_trigger.png")

        print("1. 侧边栏「我的专业」面板")
        check(open_panel(ws, "我的专业"), "点开触发按钮")
        info = panel_info(ws)
        print("   面板:", info)
        check(isinstance(info, dict) and info.get("hasInput"), "面板里有搜索框")
        check(isinstance(info, dict) and info["inputTop"] < info["firstBtnTop"],
              "搜索框在选项列表上面")
        check(isinstance(info, dict) and info["n"] >= 8, f"列出 {info and info.get('n')} 个选项")
        shot(ws, "ss_2_panel.png")

        print("2. 面板内直接搜索「网络」")
        js(ws, """(()=>{const p=document.querySelector('.ss-panel').closest('[data-testid="stPopoverBody"]');
                   const i=p.querySelector('input'); i.focus(); i.select(); return 'ok'})()""")
        cdp(ws, 400, "Input.insertText", {"text": "网络"})
        time.sleep(0.4)
        for t in ("char", "keyDown", "keyUp"):   # 回车提交，触发过滤
            cdp(ws, 401, "Input.dispatchKeyEvent",
                {"type": t, "key": "Enter", "code": "Enter",
                 "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
        time.sleep(2.0)
        info2 = panel_info(ws)
        print("   过滤后:", info2)
        check(info2 and info2["n"] == 1 and "网络" in info2["text"], "只剩命中项")
        shot(ws, "ss_3_filtered.png")

        print("3. 点选项 → 写回 + 收起")
        box = js(ws, """(()=>{const p=document.querySelector('.ss-panel').closest('[data-testid="stPopoverBody"]');
                   const b=p.querySelector('button'); const c=b.getBoundingClientRect();
                   return {x:Math.round(c.left+30),y:Math.round(c.top+12)}})()""")
        click_at(ws, box["x"], box["y"])
        time.sleep(2.2)
        cur = js(ws, """(()=>{const b=[...document.querySelectorAll('button[data-testid="stPopoverButton"]')]
                   .find(e=>e.innerText.includes('我的专业')); return b?b.innerText:'-'})()""")
        print("   触发按钮:", cur)
        check("计算机网络技术" in str(cur), "按钮显示新选中的专业")
        check(not bool(js(ws, "!!document.querySelector('.ss-panel')")), "面板已收起")
        shot(ws, "ss_4_after.png")

        print("4. ⑦ 分栏里的「城市」下拉")
        nav = """(()=>{const i=document.querySelector('input[type="radio"][value="6"]');
                  if(!i) return 'no'; i.closest('label').click(); return 'ok'})()"""
        js(ws, nav)
        time.sleep(2.5)
        js(ws, nav)
        wait(ws, "document.body.innerText.includes('筛选岗位')||document.body.innerText.includes('投递记录')", 90)
        time.sleep(1.5)
        check(open_panel(ws, "城市"), "点开城市下拉")
        info3 = panel_info(ws)
        print("   面板:", info3)
        check(info3 and info3["hasInput"] and info3["n"] > 5, "城市面板有搜索框与选项")
        shot(ws, "ss_5_city.png")
    finally:
        chrome.terminate()

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
