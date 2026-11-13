"""⑤成长档案：勾选记录（可多选）→ 曲线高亮 → 批量删除 的真浏览器验收（CDP）。

跑法：先起服务（8547），再 .venv/Scripts/python.exe tools/test_snap_del_cdp.py
截图落在 data/exports/snap_*.png；用专用测试账号（13900003005）自建 6 条快照，\n跑完连账号一起删，全程不碰演示/真实数据。
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
from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402

import sqlite3  # noqa: E402

DB = ROOT / "data" / "jobs.db"
PORT = 9243
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


def click_text(ws, text, tag="button"):
    return js(ws, f"""[...document.querySelectorAll('{tag}')]
      .find(b=>b.textContent.includes('{text}'))?.click() ?? 'no'""")


def row_pos(ws, row_i):
    """记录表第 row_i 行（0 基）的屏幕坐标；超出可视区返回 None。

    表格高度上限 300px 且带内部滚动，行必须真的可见才点得到。
    """
    js(ws, """(()=>{const c=document.querySelector('[data-testid="stDataFrame"] canvas');
              if(!c) return 'no'; c.scrollIntoView({block:'center'}); return 'ok'})()""")
    time.sleep(0.8)
    # 注意：glide grid 只有行首复选框（left+25）能可靠选中，点数据区中部无效
    r = js(ws, """(()=>{const c=document.querySelector('[data-testid="stDataFrame"] canvas');
                   if(!c) return null; const b=c.getBoundingClientRect();
                   return {l:Math.round(b.left+25), t:Math.round(b.top), b:Math.round(b.bottom)};})()""")
    if not isinstance(r, dict):
        return None
    y = r["t"] + 52 + 35 * row_i
    return (r["l"], y) if y <= r["b"] - 6 else None


def grid_scroll_bottom(ws):
    """在记录表内部滚轮滚到真正的底部（scrollTop 不再变化为止）。

    滚轮坐标必须落在表格内部（.dvn-scroller 的中心），否则滚的是整页，
    表格停在顶部 → 后面的「末行」其实是中间的某一行。
    """
    for _ in range(14):
        pos = js(ws, """(()=>{const s=document.querySelector('.dvn-scroller');
                       if(!s) return null; const b=s.getBoundingClientRect();
                       return {x:Math.round(b.left+b.width/2),
                               y:Math.round(b.top+b.height/2)};})()""")
        if not isinstance(pos, dict):
            return
        before = js(ws, """(()=>{const s=document.querySelector('.dvn-scroller');
                           return s? s.scrollTop : -1})()""")
        cdp(ws, 300, "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": float(pos["x"]), "y": float(pos["y"]),
             "deltaX": 0, "deltaY": 900})      # deltaY 正值 = 向下滚
        time.sleep(0.6)
        after = js(ws, """(()=>{const s=document.querySelector('.dvn-scroller');
                          return s? s.scrollTop : -1})()""")
        if before == after:
            break


def bottom_row_pos(ws):
    """滚到底后，可视区最底下一行（= 最新一条记录）的复选框坐标。"""
    js(ws, """(()=>{const c=document.querySelector('[data-testid="stDataFrame"] canvas');
              if(!c) return 'no'; c.scrollIntoView({block:'center'}); return 'ok'})()""")
    time.sleep(0.8)
    r = js(ws, """(()=>{const c=document.querySelector('[data-testid="stDataFrame"] canvas');
                   if(!c) return null; const b=c.getBoundingClientRect();
                   return {l:Math.round(b.left+25), b:Math.round(b.bottom)};})()""")
    return (r["l"], r["b"] - 24) if isinstance(r, dict) else None


def fresh_account(acc: str) -> None:
    """清掉历史测试账号，保证可重复运行。"""
    c = sqlite3.connect(DB)
    row = c.execute("SELECT id FROM users WHERE account=?", (acc,)).fetchone()
    if row:
        uid = int(row[0])
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid,))
    c.commit()
    c.close()


def main():
    # 专用测试账号：档案里只有本测试造的几条记录，表格一屏放得下、行坐标固定，
    # 不会再因为表格内部滚动量不准而点错行（上次就因此误删了演示档案的残留记录）。
    acc = "13900003005"
    fresh_account(acc)
    import atexit
    atexit.register(fresh_account, acc)

    r = AU.register_password(acc, "test123456", "删档验收", "人工智能技术应用")
    assert r.get("ok"), f"测试账号注册失败：{r}"
    uid = int(r["user"]["id"])
    stu = "删档验收"
    token = AU.create_session(uid)

    print("0. 造 6 条快照（整张表一屏放得下，跑完连账号一起删）")
    lp = PW.build_path(["Python"], "数据分析", 10, major="人工智能技术应用")
    ids = [PF.save_snapshot(stu, lp, ["Python"], f"CDP验收记录{chr(65 + i)}",
                            ts=f"2026-01-0{i + 1} 09:00:00", uid=uid)
           for i in range(6)]
    n0 = len(PF.list_snapshots(stu, uid))
    print(f"   档案 {n0} 条：{ids}")

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1700",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_snap"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        assert wait(ws, "document.querySelectorAll('input[type=radio]').length>=7"), "导航没渲染"
        print("1. 登录 OK")

        nav(ws, 4)
        time.sleep(1.5)
        nav(ws, 4)
        wait(ws, "!!document.querySelector('.fig svg')", 60)
        wait(ws, "!!document.querySelector('[data-testid=\"stDataFrame\"] canvas')", 30)
        time.sleep(1.5)
        check(bool(js(ws, "!!document.querySelector('[data-testid=\"stDataFrame\"] canvas')")),
              "定位记录表渲染出可勾选的表格")
        check(not bool(js(ws, "!!document.querySelector('.pick')")),
              "没有「📌 已选中」卡片（已按多选删除重做）")
        check(not bool(js(ws, "document.body.innerText.includes('勾最左一列')")),
              "表下没有多余提示语句")

        # ---- 勾倒数第二行（第 5 行）→ 曲线高亮 + 按钮 1 条
        pos = row_pos(ws, 4)
        assert pos, "取不到第 5 行坐标（表格应一屏放得下）"
        click_at(ws, *pos)
        wait(ws, "document.body.innerText.includes('删除选中 1 条')", 40)
        time.sleep(1.2)
        check(bool(js(ws, "document.body.innerText.includes('删除选中 1 条')")),
              "勾一行 → 出现「🗑 删除选中 1 条」")
        check(int(js(ws, "document.querySelectorAll('.fig line[stroke-dasharray]').length") or 0) >= 1,
              "曲线上框出了选中的点（竖虚线）")
        check(int(js(ws, """document.querySelectorAll('.fig circle[r=\"12\"]').length""") or 0) == 1,
              "选中点有光环（r=12 只有 1 个）")
        shot(ws, "snap_1_pick.png")

        # ---- 再勾最后一行 → 按钮变 2 条
        pos2 = row_pos(ws, 5)
        assert pos2, "取不到末行坐标"
        click_at(ws, *pos2)
        wait(ws, "document.body.innerText.includes('删除选中 2 条')", 40)
        time.sleep(1.2)
        check(bool(js(ws, "document.body.innerText.includes('删除选中 2 条')")),
              "再勾一行 → 「🗑 删除选中 2 条」")
        shot(ws, "snap_2_confirm.png")

        # ---- 点批量删除
        click_text(ws, "删除选中 2 条")
        wait(ws, "!document.body.innerText.includes('删除选中')", 45)
        time.sleep(1.5)
        after = PF.list_snapshots(stu, uid)
        check(len(after) == n0 - 2, f"记录数 {n0} → {len(after)}")
        _left = set(int(x) for x in after["id"])
        check(not (_left & {int(ids[4]), int(ids[5])}),
              f"勾中的两条（第 5、6 行）都已删除，剩余 {sorted(_left)}")
        check(int(js(ws, """document.querySelectorAll('.fig circle[r=\"12\"]').length""") or 0) == 0,
              "曲线高亮同步消失")
        shot(ws, "snap_3_after_del.png")
    finally:
        chrome.terminate()
        fresh_account(acc)
        print("   🧹 测试账号与快照已清理（真实账号全程未触碰）")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
