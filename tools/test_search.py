"""搜索下拉：方向 / 城市 / 目标岗位族 / 侧边栏我的专业，搜索框都长在选项列表顶部。

交互：点开「名称：当前值」按钮 → 面板第一行是搜索框，下面即时过滤（包含匹配、
忽略大小写），点一项立即选中并收起；写回的 session_state[key] 与旧 selectbox 一致。

跑法：.venv/Scripts/python.exe tools/test_search.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

BAD: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    BAD.append(msg)
    print(f"  ❌ {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def opt_btns(at: AppTest, key: str) -> list:
    """某下拉面板里当前列出的选项按钮（key 形如 major_name_o0…）。"""
    return sorted([b for b in at.button if (b.key or "").startswith(f"{key}_o")],
                  key=lambda b: b.key)


def labels(at: AppTest, key: str) -> list[str]:
    return [str(b.label) for b in opt_btns(at, key)]


def has_q(at: AppTest, key: str) -> bool:
    return any((t.key or "") == f"{key}_q" for t in at.text_input)


def main() -> None:
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=240)
    at.run()
    login_demo(at, 0)
    check(not at.exception, "登录后无异常")

    print("— A. 侧边栏「我的专业」：面板顶部是搜索框")
    n0 = len(labels(at, "major_name"))
    check(has_q(at, "major_name") and n0 > 1, f"面板有搜索框，列出 {n0} 个选项")
    at.text_input(key="major_name_q").set_value("软件").run()
    _o = labels(at, "major_name")
    check(len(_o) == 1 and "软件技术" in _o[0], f"搜「软件」→ 只剩 {_o}")
    opt_btns(at, "major_name")[0].click().run()
    check(at.session_state.get("major_name") == "软件技术", "点选项 → 值写回 major_name")
    check([t.value for t in at.text_input if t.key == "major_name_q"] == [""],
          "选完搜索框自动清空，下次打开回到全量")
    _n = int(at.session_state.get("major_name_pop_n") or 0)
    check(_n >= 1, "面板 key 已递增（下拉收起）")

    print("\n— B. ③「目标岗位族」")
    at.radio(key="screen").set_value("③ 我的定位").run()
    _o0 = labels(at, "fam_locate")
    check(has_q(at, "fam_locate") and len(_o0) > 1, f"有搜索框，原选项 {len(_o0)} 个")
    at.text_input(key="fam_locate_q").set_value("算法").run()
    _o = labels(at, "fam_locate")
    check(0 < len(_o) < len(_o0) and all("算法" in x for x in _o), f"搜「算法」→ {_o}")

    print("\n— C. ②「方向」")
    at.radio(key="screen").set_value("② 方向画像").run()
    _o0 = labels(at, "fam_portrait")
    check(has_q(at, "fam_portrait") and len(_o0) > 1, f"有搜索框，原选项 {len(_o0)} 个")
    at.text_input(key="fam_portrait_q").set_value("数据").run()
    _o = labels(at, "fam_portrait")
    check(0 < len(_o) < len(_o0) and all("数据" in x for x in _o), f"搜「数据」→ {_o}")

    print("\n— D. ⑦「方向 / 城市」")
    at.radio(key="screen").set_value("⑦ 求职实战").run()
    check(not at.exception, "⑦ 无异常")
    for k, kw in (("jd_fam", "数据"), ("jd_city", "郑州")):
        _all = labels(at, k)
        if not _all:
            bad(f"⑦ 没有 {k} 下拉")
            continue
        check(has_q(at, k), f"「{k}」有搜索框（原选项 {len(_all)} 个）")
        at.text_input(key=f"{k}_q").set_value(kw).run()
        _o = labels(at, k)
        check(0 < len(_o) < len(_all) and all(kw in x for x in _o),
              f"搜「{kw}」→ {_o[:5]}")
        at.text_input(key=f"{k}_q").set_value("").run()

    print("\n— E. 无命中时列表为空但不报错（提示换关键词）")
    at.text_input(key="jd_city_q").set_value("火星").run()
    check(not at.exception and labels(at, "jd_city") == [], "乱填关键词 → 无选项、无异常")
    check(any("没有匹配" in (c.value or "") for c in at.caption), "有「没有匹配」提示")
    at.text_input(key="jd_city_q").set_value("").run()
    check(len(labels(at, "jd_city")) > 1, "清空关键词 → 选项恢复全部")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
