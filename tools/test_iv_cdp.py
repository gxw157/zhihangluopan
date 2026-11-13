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

PORT = 9231
BASE = "http://127.0.0.1:8532/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = ROOT / "data" / "exports"
OUT.mkdir(parents=True, exist_ok=True)


def cdp(ws, _id, method, params=None):
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            return msg.get("result", {})


def js(ws, expr):
    return cdp(ws, 100, "Runtime.evaluate",
               {"expression": expr, "returnByValue": True}).get("result", {}).get("value", "")


def shot(ws, name):
    r = cdp(ws, 200, "Page.captureScreenshot", {"format": "png"})
    (OUT / name).write_bytes(base64.b64decode(r["data"]))
    print("  截图:", name)


def wait(ws, expr, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = js(ws, expr)
        if v and v != "false":
            return v
        time.sleep(1.2)
    return ""


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
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60)
    cdp(ws, 1, "Page.enable")
    return ws


def main():
    users = AU.list_users(10)
    demo = next(u for u in users if u["phone"] == "13800000001")
    token = AU.create_session(int(demo["id"]))

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", "--window-size=1500,1500",
         "--user-data-dir=" + str(ROOT / ".tmp" / "chrome_iv"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    try:
        ws = new_page(f"{BASE}?t={token}")
        assert wait(ws, "!!document.querySelector('.hero h1')"), "登录态没恢复"
        print("1. 登录态 OK")

        assert wait(ws, "document.querySelectorAll('input[type=radio]').length>=8"), "导航没渲染"
        v = js(ws, """(() => {
          const i=document.querySelector('input[type="radio"][value="6"]');
          if(!i) return 'no';
          i.closest('label').click();
          return 'ok';
        })()""")
        print("2. 切屏:", v)
        assert wait(ws, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('开始面试'))"), "没到⑦"
        time.sleep(1.5)
        shot(ws, "iv_1_entry.png")

        print("   数字人卡片:", js(ws, "document.querySelectorAll('.ivcard').length"),
              "SVG 宽:", js(ws, "(()=>{const s=document.querySelector('.ivcard svg');return s?Math.round(s.getBoundingClientRect().width):0})()"))
        print("   头像高度:", js(ws, "(()=>{const s=document.querySelector('.ivcard svg');return s?Math.round(s.getBoundingClientRect().height):0})()"))

        js(ws, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('开始面试')).click()")
        assert wait(ws, "!!document.querySelector('.ivstate')"), "面试没开始"
        time.sleep(2.5)
        js(ws, "document.querySelector('.ivcard').scrollIntoView({block:'start'})")
        time.sleep(1.2)
        shot(ws, "iv_2_asking.png")
        print("3. 面试已开始 · 状态:", js(ws, "document.querySelector('.ivstate').textContent"))
        print("   进度条:", js(ws, "document.querySelectorAll('.ivrow').length"), "行")
        print("   对话气泡:", js(ws, "document.querySelectorAll('[data-testid=\"stChatMessage\"]').length"))
        print("   音频元素:", js(ws, "document.querySelectorAll('audio').length"),
              "| 有声源:", js(ws, "[...document.querySelectorAll('audio')].some(a=>a.src)"))

        # 提交一句，看追问与状态变化
        js(ws, """(() => {
          const ta=document.querySelector('textarea[aria-label="你的回答"]');
          if(!ta) return 'no';
          const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          setter.call(ta,'我做过数据清洗。');
          ta.dispatchEvent(new Event('input',{bubbles:true}));
          return 'ok';
        })()""")
        time.sleep(0.8)
        js(ws, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('提交回答')).click()")
        time.sleep(3.5)
        js(ws, "document.querySelector('.ivcard').scrollIntoView({block:'start'})")
        time.sleep(1.2)
        shot(ws, "iv_3_probe.png")
        print("4. 提交后状态:", js(ws, "document.querySelector('.ivstate') ? document.querySelector('.ivstate').textContent : ''"))
        print("   气泡数:", js(ws, "document.querySelectorAll('[data-testid=\"stChatMessage\"]').length"))

        # 自由交流：展开 expander → 输入问题 → 发送 → 面试官回答（不影响进度）
        js(ws, "[...document.querySelectorAll('[data-testid=\"stExpander\"] summary, details summary')]"
               ".find(s=>s.textContent.includes('想跟面试官聊两句'))?.click()")
        time.sleep(1.5)
        js(ws, """(() => {
          const inp=document.querySelector('input[aria-label="问面试官"]');
          if(!inp) return 'no';
          const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          setter.call(inp,'这题能给个提示吗？');
          inp.dispatchEvent(new Event('input',{bubbles:true}));
          return 'ok';
        })()""")
        time.sleep(0.6)
        _r = js(ws, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('发送'))?.click() ?? 'no'")
        _ok = wait(ws, "[...document.querySelectorAll('[data-testid=\"stChatMessage\"]')]"
                       ".some(m=>m.textContent.includes('提示'))", 30)
        time.sleep(1)
        print("5. 自由对话:", "面试官已回应" if _ok else f"未响应({_r})",
              "· 气泡数:", js(ws, "document.querySelectorAll('[data-testid=\"stChatMessage\"]').length"),
              "· 进度不变:", js(ws, "document.querySelector('.ivrow span:nth-child(3)')?.textContent"))
        js(ws, "document.querySelector('.ivcard').scrollIntoView({block:'start'})")
        time.sleep(1.2)
        shot(ws, "iv_3b_freechat.png")

        # 放弃本场 → 演示按钮一键跑完 → 看报告页
        js(ws, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('放弃本场')).click()")
        time.sleep(3)
        assert wait(ws, "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('演示一场'))"), "没回到入口"
        js(ws, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('演示一场')).click()")
        assert wait(ws, "!!document.querySelector('.ivsum')"), "演示场没出报告"
        time.sleep(2)
        js(ws, "document.querySelector('.ivsum').scrollIntoView({block:'start'})")
        time.sleep(1.2)
        shot(ws, "iv_4_report.png")
        print("5. 演示场报告 · 状态:", js(ws, "document.querySelector('.ivstate').textContent"))
        print("   总分卡:", js(ws, "document.querySelector('.ivsum .sc') ? document.querySelector('.ivsum .sc').textContent : ''"))
        ws.close()
    finally:
        chrome.terminate()
        try:
            chrome.wait(6)
        except Exception:
            chrome.kill()
        AU.drop_session(token)


if __name__ == "__main__":
    main()
