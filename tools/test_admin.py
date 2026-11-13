# -*- coding: utf-8 -*-
"""⑧ 工程后台（内嵌版）冒烟测试：

工程后台的独立入口（app_admin.py / 启动_工程后台.bat）已下线，
后台能力全部内嵌在 app_all.py 的 ⑧ 屏，由 config/admin.json 名单自动显隐：

1. 名单加载与 is_admin 判定；
2. 名单内账号登录 → 导航多出 ⑧ 工程后台，采集按钮存在；
3. 名单外账号登录 → 只有学生端七屏，不见 ⑧。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

from core.admin_ui import is_admin, load_admins  # noqa: E402

PROBLEMS: list[str] = []


def ok(m: str) -> None:
    print("  ✅", m)


def bad(m: str) -> None:
    PROBLEMS.append(m)
    print("  ❌", m)


def step(m: str) -> None:
    print(f"\n— {m}")


step("1. 开发者名单加载与 is_admin 判定")
admins = load_admins()
if admins and "13800000001" in admins:
    ok(f"名单加载正常：{admins}")
else:
    bad(f"名单异常：{admins}")
if is_admin("13800000001") and not is_admin("13800000002"):
    ok("is_admin：名单内 True / 名单外 False")
else:
    bad("is_admin 判定异常")

step("2. 名单内账号登录 → 学生端导航多出 ⑧ 工程后台")
at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=300)
at.run()
login_demo(at, 0)          # 13800000001，在名单里
at.run()
opts = list(at.radio(key="screen").options)
if "⑧ 工程后台" in opts:
    ok(f"开发者导航含 ⑧（共 {len(opts)} 屏）")
else:
    bad(f"开发者导航缺 ⑧：{opts}")
at.radio(key="screen").set_value("⑧ 工程后台").run()
if at.exception:
    bad(f"⑧ 渲染异常：{[e.value for e in at.exception][:1]}")
elif any("开始 / 继续采集" in (b.label or "") for b in at.button):
    ok("⑧ 采集引擎已挂载（开始按钮存在）")
else:
    bad("⑧ 缺少开始按钮")

step("3. 名单外账号登录 → 只有学生端七屏")
at2 = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=300)
at2.run()
login_demo(at2, 1)         # 13800000002，不在名单里
at2.run()
opts2 = list(at2.radio(key="screen").options)
if "⑧ 工程后台" not in opts2 and len(opts2) == 7:
    ok(f"学生账号只见七屏：{opts2}")
else:
    bad(f"名单外账号导航异常：{opts2}")

print()
if PROBLEMS:
    print("存在问题：")
    for p in PROBLEMS:
        print("  -", p)
    sys.exit(1)
print("🎉 工程后台（内嵌⑧）冒烟测试全部通过")
