"""面试反馈 / 职业规划书 新布局的真浏览器验收（CDP 截图 + 尺寸断言）。

跑法：先起服务（8542），再 .venv/Scripts/python.exe tools/test_doc_layout_cdp.py
截图落在 data/exports/doc_*.png
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

PORT = 9241
BASE = "http://127.0.0.1:8542/"
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
        time.sleep(1.2)
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


def click_btn(ws, text):
    return js(ws, f"""[...document.querySelectorAll('button')]
      .find(b=>b.textContent.includes('{text}'))?.click() ?? 'no'""")


def main():
    demo = next(u for u in AU.list_users(10) if u["phone"] == "13800000001")
    token = AU.create_session(int(demo["id"]))

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1600",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_doc"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        assert wait(ws, "document.querySelectorAll('input[type=radio]').length>=8"), "导航没渲染"
        print("1. 登录 OK")

        # ---- ⑤ 成长档案：历史变化口径（不是本次提交）
        nav(ws, 4)
        time.sleep(1.5)
        nav(ws, 4)
        wait(ws, "!!document.querySelector('.hist') || !!document.querySelector('.grow')", 60)
        time.sleep(1.5)
        check(bool(js(ws, "!!document.querySelector('.hist')")),
              "⑤屏用「最近一次变化（历史记录）」卡，不用刚补齐口径")
        check(not bool(js(ws, "document.body.innerText.includes('刚补齐')")),
              "⑤屏没有『刚补齐』字样")
        check(bool(js(ws, "document.body.innerText.includes('当前命中率')")),
              "⑤屏顶部有「当前命中率」状态卡")
        js(ws, "document.querySelector('.hist')?.scrollIntoView({block:'start'})")
        time.sleep(1.0)
        shot(ws, "doc_5_growth_hist.png")

        # ---- ⑥ 职业规划书
        nav(ws, 2)
        time.sleep(1.5)
        nav(ws, 2)
        assert wait(ws, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('生成我的定位'))"), "没到③"
        click_btn(ws, "生成我的定位")
        wait(ws, "!!document.querySelector('.kpi')", 60)
        print("2. ③ 定位已生成")
        nav(ws, 5)
        time.sleep(1.5)
        nav(ws, 5)
        assert wait(ws, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('生成我的职业规划书'))"), "没到⑥"
        time.sleep(1.2)
        click_btn(ws, "生成我的职业规划书")
        ok = wait(ws, "!!document.querySelector('.dochead')", 90)
        check(bool(ok), "规划书文档头渲染")
        time.sleep(1.5)
        n_sec = js(ws, "document.querySelectorAll('.sechead').length")
        check(int(n_sec or 0) >= 5, f"五节卡片渲染（{n_sec} 节）")
        check(bool(js(ws, "!!document.querySelector('.dochead .tag')")), "文档头带引擎标签")
        # 表格不横溢出、卡片高度正常
        tw = js(ws, "(()=>{const t=document.querySelector('.st-key-plansec3 table');"
                    "return t?Math.round(t.getBoundingClientRect().width):0})()")
        cw = js(ws, "(()=>{const c=document.querySelector('.st-key-plansec3');"
                    "return c?Math.round(c.getBoundingClientRect().width):0})()")
        check(int(tw or 0) <= int(cw or 1), f"表格不溢出卡片（表 {tw}px / 卡 {cw}px）")
        # 整行：规划书卡宽度应接近主内容区「内容宽」（减去容器内边距），不再被右栏压成 40%
        _main = int(js(ws, "(()=>{const m=document.querySelector('[data-testid=\"stMainBlockContainer\"]')"
                           "||document.querySelector('.block-container');if(!m)return 0;"
                           "const s=getComputedStyle(m),r=m.getBoundingClientRect();"
                           "return Math.round(r.width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight))})()") or 0)
        _card = int(js(ws, "(()=>{const c=document.querySelector('.st-key-plansec1');"
                           "return c?Math.round(c.getBoundingClientRect().width):0})()") or 0)
        check(_main and _card / _main > 0.95,
              f"规划书整行铺开（卡 {_card}px / 内容区 {_main}px = {_card / max(_main, 1):.0%}）")
        js(ws, "document.querySelector('.dochead').scrollIntoView({block:'start'})")
        time.sleep(1.2)
        shot(ws, "doc_1_plan_top.png")
        js(ws, "document.querySelector('.sechead')?.scrollIntoView({block:'start'})")
        time.sleep(1.0)
        shot(ws, "doc_2_plan_sections.png")
        sw = js(ws, "document.documentElement.scrollWidth")
        cw2 = js(ws, "document.documentElement.clientWidth")
        check(int(sw or 0) <= int(cw2 or 1) + 4, f"页面无横向滚动（{sw}/{cw2}）")

        # ---- ⑦ 面试反馈
        nav(ws, 6)
        time.sleep(1.5)
        nav(ws, 6)
        wait(ws, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('演示一场'))", 40)
        click_btn(ws, "演示一场（自动作答）")
        assert wait(ws, "!!document.querySelector('.ivhero')", 120), "报告没出来"
        time.sleep(2)
        check(js(ws, "document.querySelectorAll('.dimcard').length") == 4, "四维得分卡 4 张")
        check(bool(js(ws, "document.querySelector('.ivhero .sc')?.textContent")), "总分主卡有数字")
        _hw = int(js(ws, "(()=>{const h=document.querySelector('.ivhero');"
                          "return h?Math.round(h.getBoundingClientRect().width):0})()") or 0)
        _mw = int(js(ws, "(()=>{const m=document.querySelector('[data-testid=\"stMainBlockContainer\"]')"
                          "||document.querySelector('.block-container');if(!m)return 0;"
                          "const s=getComputedStyle(m),r=m.getBoundingClientRect();"
                          "return Math.round(r.width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight))})()") or 0)
        check(_mw and _hw / _mw > 0.95,
              f"反馈整行铺开（hero {_hw}px / 内容区 {_mw}px = {_hw / max(_mw, 1):.0%}）")
        js(ws, "document.querySelector('.ivhero').scrollIntoView({block:'start'})")
        time.sleep(1.0)
        shot(ws, "doc_3_iv_hero.png")
        # 切到逐题复盘
        js(ws, """(() => {
          const t=[...document.querySelectorAll('[role="tab"],button')]
            .find(b=>b.textContent.trim().startsWith('逐题复盘'));
          if(t){t.click();return 'ok'} return 'no';
        })()""")
        time.sleep(2)
        nq = js(ws, "document.querySelectorAll('.qhead').length")
        check(int(nq or 0) >= 1, f"逐题复盘拆成单题卡（{nq} 张）")
        js(ws, "document.querySelector('.qhead')?.scrollIntoView({block:'start'})")
        time.sleep(1.0)
        shot(ws, "doc_4_iv_questions.png")
        sw2 = js(ws, "document.documentElement.scrollWidth")
        check(int(sw2 or 0) <= int(cw2 or 1) + 4, f"⑦屏无横向滚动（{sw2}/{cw2}）")
        ws.close()
    finally:
        chrome.terminate()
        try:
            chrome.wait(6)
        except Exception:
            chrome.kill()
        AU.drop_session(token)

    print("\n" + ("❌ " + "；".join(BAD) if BAD else "🎉 布局验收通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
