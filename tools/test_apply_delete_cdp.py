"""⑦投递记录：左列勾选框多选 → 批量删除 的真浏览器验收（CDP）。

跑法：先起服务（8545），再 .venv/Scripts/python.exe tools/test_apply_delete_cdp.py
截图落在 data/exports/appdel_*.png；自建 3 条临时投递，跑完清理。
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
from core import apply as AP  # noqa: E402
from core import auth as AU  # noqa: E402

PORT = 9245
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
        if v and v != "false":
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


def click_at(ws, x, y):
    for t in ("mousePressed", "mouseReleased"):
        cdp(ws, 300, "Input.dispatchMouseEvent",
            {"type": t, "x": float(x), "y": float(y), "button": "left", "clickCount": 1})
        time.sleep(0.12)


def nav(ws, idx):
    js(ws, f"""(() => {{
      const i=document.querySelector('input[type="radio"][value="{idx}"]');
      if(!i) return 'no'; i.closest('label').click(); return 'ok';
    }})()""")


def tbl_pos(ws, row_i):
    """投递记录表第 row_i 行（0 基）左侧勾选框坐标（首行 +40，行距 35）。

    每次都重新把表滚进视口再量坐标：Streamlit 重渲染会改变页面滚动位置。
    """
    js(ws, """(()=>{const els=[...document.querySelectorAll('[data-testid="stDataFrame"]')];
              els[els.length-1].scrollIntoView({block:'center'}); return 'ok'})()""")
    time.sleep(1.2)
    r = js(ws, """(()=>{const els=[...document.querySelectorAll('[data-testid="stDataFrame"]')];
                   const b=els[els.length-1].querySelector('canvas').getBoundingClientRect();
                   return {l:Math.round(b.left+25), t:Math.round(b.top),
                           b:Math.round(b.bottom)};})()""")
    if not isinstance(r, dict):
        return None
    y = r["t"] + 40 + 35 * row_i
    return (r["l"], y) if y <= r["b"] - 6 else None


def main():
    demo = next(u for u in AU.list_users(200) if u["account"] == "13800000001")
    uid = int(demo["id"])
    token = AU.create_session(uid)
    stu = demo["nickname"]

    print("0. 造 3 条临时投递（跑完删除）")
    ids = [AP.legacy_import(uid, stu, f"CDP验收岗{'ABC'[i]}", "测试公司", "郑州",
                            "已投递", "CDP批量删除验收", ts=f"2026-11-12 08:0{i}:00")
           for i in range(3)]
    n0 = len(AP.stats(uid)["rows"])
    print(f"   投递 {n0} 条，新增 {ids}")

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1700",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_appdel"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        assert wait(ws, "document.querySelectorAll('input[type=radio]').length>=8"), "导航没渲染"
        print("1. 登录 OK")

        nav(ws, 6)          # ⑦ 求职实战
        time.sleep(1.5)
        nav(ws, 6)
        wait(ws, "document.body.innerText.includes('投递记录')", 90)
        time.sleep(2.0)
        js(ws, """(()=>{const h=[...document.querySelectorAll('h4,h3')]
                   .find(e=>e.textContent.includes('投递记录'));
                   if(h) h.scrollIntoView({block:'start'}); return 'ok'})()""")
        time.sleep(1.0)
        shot(ws, "appdel_1_table.png")

        check(not bool(js(ws, "document.body.innerText.includes('勾最左一列')")),
              "表下不再有「勾最左一列…不可恢复」说明")
        check(not bool(js(ws, "document.body.innerText.includes('删除某条')")),
              "底部「删除某条」下拉已移除")

        # 勾两行（最左列复选框）：每勾一行都等按钮条数刷新，再勾下一行
        p0 = tbl_pos(ws, 0)
        assert p0, "取不到表格坐标"
        click_at(ws, *p0)
        wait(ws, "document.body.innerText.includes('删除选中 1 条')", 40)
        p1 = tbl_pos(ws, 1)
        assert p1, "取不到第二行坐标"
        click_at(ws, *p1)
        wait(ws, "document.body.innerText.includes('删除选中 2 条')", 40)
        time.sleep(1.0)
        shot(ws, "appdel_2_picked.png")
        check(bool(js(ws, "document.body.innerText.includes('删除选中 2 条')")),
              "勾两行 → 出现「🗑 删除选中 2 条」")

        print("2. 点一次删掉这两条")
        _bd = AP.stats(uid)["rows"]
        target = [int(_bd["id"].iloc[0]), int(_bd["id"].iloc[1])]
        js(ws, """(()=>{const b=[...document.querySelectorAll('button')]
                   .find(x=>x.textContent.includes('删除选中')); if(b) b.click(); return 'ok'})()""")
        # 删完 Streamlit 会重跑整页，等等按钮收起（最多 30s）
        wait(ws, """![...document.querySelectorAll('button')]
              .some(b=>b.textContent.includes('删除选中'))""", 30)
        time.sleep(1.0)
        after = AP.stats(uid)["rows"]
        check(len(after) == n0 - 2, f"投递 {n0} → {len(after)} 条")
        check(all(i not in list(after["id"]) for i in target), "勾选的两条已从库中删除")
        check(not bool(js(ws, """[...document.querySelectorAll('button')]
              .some(b=>b.textContent.includes('删除选中'))""")),
              "删完勾选清空，按钮收起")
        shot(ws, "appdel_3_after.png")
    finally:
        chrome.terminate()
        for i in ids:
            AP.delete_apply(uid, i)
        print("   🧹 已清理临时投递与浏览器")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
