# -*- coding: utf-8 -*-
"""方案 C 拆分脚本：从 app_all.py 抽出 CSS 与工程后台，生成 core/theme.py、core/admin_ui.py。

先备份 app_all.py 到 .tmp/，再按行号锚点校验后切割。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app_all.py"
BAK = ROOT / ".tmp" / "app_all.py.bak_split"

lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
BAK.parent.mkdir(exist_ok=True)
BAK.write_text("".join(lines), encoding="utf-8")
print(f"备份 -> {BAK} ({len(lines)} 行)")


def seg(a: int, b: int) -> list[str]:
    """取 1-based 闭区间 [a, b] 的行。"""
    return lines[a - 1:b]


def assert_line(no: int, expect: str) -> None:
    actual = lines[no - 1].rstrip("\n")
    assert actual.strip() == expect.strip(), f"行 {no} 锚点不符:\n  期望: {expect!r}\n  实际: {actual!r}"


# ---------- 锚点校验 ----------
assert_line(71, 'st.markdown("""')
assert_line(72, "<style>")
assert_line(395, "</style>")
assert_line(396, '""", unsafe_allow_html=True)')
assert_line(709, "# ================================================================ MySQL 配置")
assert_line(985, "    threading.Thread(target=run_crawl, args=(cfg, job), daemon=True).start()")
assert_line(1057, 'def kpi(col, label, value, sub=""):')
assert_line(1072, "def hint(msg: str) -> None:")
assert_line(1077, "def sqlite_total() -> int:")
assert_line(1086, "        c.close()")
assert_line(1173, "def write_ledger(major: str | None = None) -> Path:")
assert_line(1224, "    return out")
assert_line(1228, "@st.fragment(run_every=2.0)")
assert_line(1258, '        st.rerun(scope="app")')
assert_line(1262, 'cfg = st.session_state.get("db_cfg", dict(DEFAULT_DB))')
assert_line(1277, "        mysql_err = str(e)")
assert_line(1279, "ov = c_overview(db_ver())")
assert_line(1312, "    if mysql_ok:")
assert_line(1327, "        st.rerun()")
assert_line(2939, "# ---------------------------------------------------------------- ⑧ 工程后台")
assert_line(2941, '    e1, e2, e3, e4 = st.tabs(["采集入库", "技能标注", "数据规范与台账", "账号与登录"])')
assert_line(3376, "        #st.caption(f\"验证码规则：{_rule} · 5 分钟有效 · 60 秒重发冷却 · 同一号码每小时最多 10 条 · 用后即废。\")")
print("锚点全部校验通过")

# ---------- 1. core/theme.py ----------
css_body = "".join(seg(72, 395))
theme = (
    '"""全站主题 CSS：学生端 app_all.py 与工程后台 app_admin.py 共用同一份。"""\n\n'
    "THEME_CSS = r'''"
    + css_body.replace("'''", "\\'\\'\\'") + "'''\n"
)
(ROOT / "core" / "theme.py").write_text(theme, encoding="utf-8")
print(f"core/theme.py 写入完成（{css_body.count(chr(10))} 行 CSS）")

# ---------- 2. core/admin_ui.py ----------
header = '''"""职航罗盘 · 工程后台（方案 C 独立入口的渲染层）

学生端 app_all.py 不再加载本模块：采集引擎、MySQL 直连、账号台账全部收在这里，
只由 app_admin.py（独立 streamlit 入口）调用。开发者名单在 config/admin.json。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import pymysql
except ImportError:            # 没装驱动时页面照样能开，只是采集不可用
    pymysql = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import auth as AU  # noqa: E402
from core import crawl as ZP  # noqa: E402
from core import majors as MJ  # noqa: E402
from core import skills as SK  # noqa: E402
from core import sms as SMS  # noqa: E402
from core import syncpack as SP  # noqa: E402

SQLITE_DB = ROOT / "data" / "jobs.db"


'''
engine = "".join(seg(709, 985)) + "\n\n\n"
tools = (
    "".join(seg(1057, 1059)) + "\n\n\n"          # kpi
    + "".join(seg(1072, 1074)) + "\n\n\n"        # hint
    + "".join(seg(1077, 1086)) + "\n\n\n"        # sqlite_total
    + '''def clear_analysis_cache() -> None:
    """后台页不缓存分析结果（KPI 每轮即时读库），保留接口兼容原调用点。"""


'''
    + "".join(seg(1173, 1224)) + "\n\n\n"        # write_ledger
    + "# ================================================================ 采集进度面板\n"
    + "".join(seg(1228, 1258)) + "\n\n\n"        # panel
)
aux = '''# ================================================================ MySQL 状态与开发者名单
def mysql_status() -> dict:
    """连主库、数条数。返回 {cfg, ok, err, n}，失败不抛错只记原因。"""
    cfg = st.session_state.get("db_cfg", dict(DEFAULT_DB))
    ok, err, n = False, "", 0
    if pymysql is None:
        err = "未安装 MySQL 驱动（可选功能）"
    else:
        try:
            init_db(cfg)
            cn = connect(cfg)
            with cn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM jobs")
                n = int(cur.fetchone()[0])
            cn.close()
            ok = True
        except Exception as e:
            err = str(e)
    return {"cfg": cfg, "ok": ok, "err": err, "n": n}


def load_admins() -> list[str]:
    """开发者账号名单：config/admin.json 的 admins 数组。"""
    f = ROOT / "config" / "admin.json"
    try:
        return [str(x) for x in (json.loads(f.read_text(encoding="utf-8")).get("admins") or [])]
    except Exception:
        return []


def is_admin(account: str) -> bool:
    return str(account) in load_admins()


# ================================================================ 工程后台（四个 tab）
def render_admin_screen(uid: int, account: dict) -> None:
    """工程后台全部界面。uid/account 是当前登录的开发者（用于同步包导出导入）。"""
    my = mysql_status()
    cfg = my["cfg"]
    mysql_ok, mysql_err, mysql_n = my["ok"], my["err"], my["n"]
    ov = A.overview()
    major_name = MJ.default_name()
    UID, ACCOUNT = int(uid), account
'''
body = "".join(seg(2941, 3376)) + "\n"
admin_ui = header + engine + tools + aux + body
(ROOT / "core" / "admin_ui.py").write_text(admin_ui, encoding="utf-8")
print(f"core/admin_ui.py 写入完成（{admin_ui.count(chr(10))} 行）")

# ---------- 3. 重写 app_all.py ----------
doc_new = '''"""职航罗盘 · 学生职业规划大数据平台（学生端七屏）

    市场在要什么（① 市场全景）→ 专业学什么（② 方向画像）
        → 我差在哪里（③ 我的定位 → ④ 差距路径）→ 我接下来做什么（⑤ 成长档案 → ⑥ AI 顾问）
    ⑦ 求职实战：JD 透视镜 → 简历技能段 → 模拟面试 → 投递行动清单，学生动线的最后一步。
屏幕上的每一个数字，都要能变成学生今天就能做的一个动作。

工程能力（采集入库 / 技能标注 / 数据规范 / 账号台账）已按方案 C 拆到独立入口：
    app_admin.py + core/admin_ui.py，只有 config/admin.json 名单里的开发者账号能进；
    学生端不加载任何后台代码，导航只有 ①–⑦ 七屏。

双引擎智能体：
    平台引擎（analyze / pathway / agent）算得准——每个数字可复算、可追溯；
    Coze 引擎（core/coze.py）聊得开——上下文注入式 RAG、对话式规划、规划书工作流；
    三级降级：Coze 在线 → OpenAI 兼容接口 → 离线规则兜底，赛场断网不冷场。

数据怎么流（一条数据流水线）：
    智联公开搜索页
        └─ 采集线程 ──► MySQL（主库：jobs / crawl_progress / crawl_log）
                   └──► SQLite（分析快照：data/jobs.db，含成长档案 career_snapshot）

启动：
    学生端：双击 启动_职航罗盘.bat    （.venv\\Scripts\\python -m streamlit run app_all.py）
    工程后台：双击 启动_工程后台.bat  （.venv\\Scripts\\python -m streamlit run app_admin.py）
"""
'''
# docstring = 行 1-21
out = [doc_new] + lines[21:]
# 行号此时全部平移 -0（docstring 仍 21 行）——不再使用行号，改用全文替换
text = "".join(out)

# CSS 调用替换
old_css_head = 'st.markdown("""\n<style>'
assert old_css_head in text, "CSS 头未找到"
# CSS 段：从 st.markdown("""\n<style> 到 </style>\n""", unsafe_allow_html=True)
start = text.index(old_css_head)
end_marker = "</style>\n\"\"\", unsafe_allow_html=True)"
end = text.index(end_marker) + len(end_marker)
text = text[:start] + "st.markdown(THEME_CSS, unsafe_allow_html=True)" + text[end:]

# import theme
text = text.replace(
    "from core import weekly as WK  # noqa: E402",
    "from core import weekly as WK  # noqa: E402\nfrom core.theme import THEME_CSS  # noqa: E402",
    1)

# SCREENS 七屏
old_screens = '''SCREENS = ["① 市场全景", "② 方向画像", "③ 我的定位", "④ 差距路径",
           "⑤ 成长档案", "⑥ AI 顾问", "⑦ 求职实战", "⑧ 工程后台"]
demo_mode = bool(st.session_state.get("demo_mode"))
shown = [x for x in SCREENS if not (demo_mode and x.startswith("⑧"))]'''
new_screens = '''SCREENS = ["① 市场全景", "② 方向画像", "③ 我的定位", "④ 差距路径",
           "⑤ 成长档案", "⑥ AI 顾问", "⑦ 求职实战"]
demo_mode = bool(st.session_state.get("demo_mode"))
shown = list(SCREENS)'''
assert old_screens in text, "SCREENS 块未找到"
text = text.replace(old_screens, new_screens, 1)

# 删除各区间（在 docstring/CSS/SCREENS 替换后的新文本上，按唯一锚点切片）
def cut(text: str, start_anchor: str, end_anchor: str, keep_end: bool = True) -> str:
    s = text.index(start_anchor)
    e = text.index(end_anchor, s)
    return text[:s] + (text[e:] if keep_end else text[e + len(end_anchor):])

# 采集引擎区：从 "# ==== MySQL 配置" 到 "# ==== 缓存与分析"
text = cut(text,
           "# ================================================================ MySQL 配置",
           "# ================================================================ 缓存与分析")
# sqlite_total：从 "def sqlite_total" 到 "# ==== 导出"
text = cut(text, "def sqlite_total() -> int:", "# ================================================================ 导出")
# write_ledger + panel：从 "def write_ledger" 到 "# ==== 侧边栏"
text = cut(text, "def write_ledger(major: str | None = None) -> Path:",
           "# ================================================================ 侧边栏")
# 侧栏 MySQL/快照块 + 刷新统计：从 "    if mysql_ok:" 到 "# ==== 当前定位的有效性"
text = cut(text, "    if mysql_ok:", "# ================================================================ 当前定位的有效性")
# ⑧ 段：从 "# ---- ⑧ 工程后台" 到 "# ==== 页脚"
text = cut(text, "# ---------------------------------------------------------------- ⑧ 工程后台",
           "# ================================================================ 页脚（登录后各屏底部统一展示）")

SRC.write_text(text, encoding="utf-8")
print(f"app_all.py 重写完成（{text.count(chr(10))} 行）")
