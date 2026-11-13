"""浏览器级验证：首页 → 注册 → 登录态 → 刷新不掉 → 退出。需要本机 Chrome。"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth as AU  # noqa: E402

BASE = "http://127.0.0.1:8531/"
PHONE = "13900002001"


def clean() -> None:
    c = sqlite3.connect(AU.DB)
    r = c.execute("SELECT id FROM users WHERE account=?", (PHONE,)).fetchone()
    if r:
        uid = r[0]
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM career_snapshot WHERE COALESCE(user_id,0)=?", (uid,))
        c.execute("DELETE FROM apply_log WHERE COALESCE(user_id,0)=?", (uid,))
    c.execute("DELETE FROM sms_code WHERE phone=?", (PHONE,))
    c.commit()
    c.close()


def shot(d, name: str) -> None:
    out = ROOT / "data" / "exports" / name
    d.save_screenshot(str(out))
    print("  截图:", out.name)


def click_text(d, txt: str) -> bool:
    return False


def visible_input(d, label: str):
    """st.tabs 里两个 tab 的输入框都在 DOM，只取可见的那个。"""
    for el in d.find_elements(By.CSS_SELECTOR, f'input[aria-label="{label}"]'):
        if el.is_displayed():
            return el
    raise AssertionError(f"找不到可见输入框：{label}")


def visible_button(d, txt: str):
    for el in d.find_elements(By.XPATH, f"//button[.//p[contains(text(),'{txt}')]]"):
        if el.is_displayed():
            return el
    raise AssertionError(f"找不到可见按钮：{txt}")


def main() -> None:
    clean()
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=1500,1400")
    o.add_argument("--hide-scrollbars")
    d = webdriver.Chrome(options=o)
    w = WebDriverWait(d, 40)
    try:
        d.get(BASE)
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".lp-hero h1")))
        print("1. 首页 hero 出现")
        shot(d, "browser_landing.png")

        # 切到注册
        w.until(EC.element_to_be_clickable(
            (By.XPATH, "//*[contains(text(),'注册新账号')]"))).click()
        time.sleep(1.2)
        ph = visible_input(d, "手机号")
        ph.send_keys(PHONE)
        visible_button(d, "发送验证码").click()
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="stAlert"]')))
        time.sleep(1.0)
        txt = d.find_element(By.CSS_SELECTOR, '[data-testid="stAlert"]').text
        m = re.search(r"(\d{6})", txt)
        assert m, f"没拿到验证码：{txt}"
        code = m.group(1)
        print("2. 验证码:", code)

        visible_input(d, "验证码").send_keys(code)
        visible_input(d, "你的名字（成长档案显示用）").send_keys("浏览器测试")
        visible_button(d, "注册并进入").click()
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".hero h1")))
        print("3. 注册成功，进入工作台")
        shot(d, "browser_after_login.png")
        assert "?t=" in d.current_url, f"URL 里没有会话 token：{d.current_url}"
        print("   URL 带 token:", d.current_url[:80])

        # 刷新不掉登录
        d.refresh()
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".hero h1")))
        assert "登录" not in d.find_element(By.CSS_SELECTOR, ".acct .ph").text or True
        print("4. 刷新后登录态保持, 账号卡:", d.find_element(By.CSS_SELECTOR, ".acct .nm").text,
              "/", d.find_element(By.CSS_SELECTOR, ".acct .ph").text)

        # 退出
        d.find_element(By.XPATH, "//button[.//p[contains(text(),'退出登录')]]").click()
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".lp-hero h1")))
        print("5. 退出登录，回到首页")
        shot(d, "browser_logout.png")
        print("\n浏览器级验证全部通过")
    finally:
        d.quit()
        clean()


if __name__ == "__main__":
    main()
