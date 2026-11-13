"""⑦ 库内岗位 JD 透视镜 + 投递自动化 的回归测试（AppTest）。

覆盖：逐条翻页 / 筛选重置游标 / 立即投递幂等 / 粘贴模式保留 / 换账号互不影响。
跑法：.venv/Scripts/python.exe tools/test_jd_pool.py
自清理：测试里投出去的记录跑完删掉，演示档案数字不变。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402
from core import apply as AP  # noqa: E402

DB = ROOT / "data" / "jobs.db"
PASS = 0
FAIL = 0


def ok(cond, msg) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")


def card(at):
    """取当前岗位卡的 (标题, 公司, 命中率)。"""
    for m in at.markdown:
        v = m.value or ""
        mo = re.search(r'jc-title">([^<]*)', v)
        if mo:
            co = re.search(r'jc-co">([^<]*)', v)
            hit = re.search(r'jc-hit"><b>(\d+)%', v)
            return (mo.group(1), co.group(1) if co else "", int(hit.group(1)) if hit else -1)
    return None


def kpi_num(at, name):
    """从自定义 KPI 卡里取数字（kpi() 是 HTML，不是 st.metric）。"""
    for m in at.markdown:
        v = m.value or ""
        mo = re.search(rf'class="k">{name}</div><div class="v">(\d+)', v)
        if mo:
            return int(mo.group(1))
    return None


def pool_text(at):
    for m in at.markdown:
        v = m.value or ""
        mo = re.search(r"第 <b>(\d+)</b> / (\d+) 条", v)
        if mo:
            return int(mo.group(1)), int(mo.group(2))
    return 0, 0


def main() -> None:
    AP.ensure_legacy()
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=300)
    at.run()
    login_demo(at, 0)
    uid = int(at.session_state["user"]["id"])
    n_before = AP.stats(uid)["n"]

    at.radio(key="screen").set_value("⑦ 求职实战").run()
    ok(not at.exception, f"⑦ 无异常：{[str(e.value)[:120] for e in at.exception]}")

    print("\n[1] 库内岗位：唯一模式 + 岗位卡 + 分页")
    ok(not any((r.key or "") == "jd_mode" for r in at.radio), "无「JD 来源」切换（只剩库内岗位）")
    c1 = card(at)
    ok(c1 is not None, f"岗位卡渲染：{c1}")
    ok(c1 and c1[0] and c1[1] and c1[1] != "—", "卡上有岗位名 + 公司名（来自库内真实数据）")
    idx1, total = pool_text(at)
    ok(idx1 == 1 and total > 100, f"分页文案 第 {idx1}/{total} 条")
    at.button(key="jd_next").click().run()
    c2 = card(at)
    _i2 = pool_text(at)[0]
    # 全库岗位里同名同公司的重复岗位不少（"兼职线上论文辅导"就有多条），
    # 用「序号前进 + 卡片仍在」判断翻页有效，重名时只作说明不算失败。
    _dup = c1 and c2 and (c2[0], c2[1]) == (c1[0], c1[1])
    ok(c2 is not None and _i2 == 2,
       f"下一岗翻到第 {_i2} 条：{c2[0] if c2 else '—'}"
       + ("（与上一条同名同公司，库内重复岗位）" if _dup else ""))
    ok(pool_text(at)[0] == 2, "序号走到第 2 条")
    at.button(key="jd_prev").click().run()
    ok(card(at) and card(at)[0] == c1[0], "上一岗能翻回来（顺序稳定，不重复不漏）")

    print("\n[2] 筛选：换方向 → 游标回第 1 条")
    at.session_state["jd_fam"] = "数据分析"   # 方向下拉已是搜索面板，直接写状态
    at.run()
    ok(pool_text(at)[0] == 1, "切方向后回第 1 条（不会停在上一个筛选的序号上）")
    ok(pool_text(at)[1] < total, f"数据分析方向只剩 {pool_text(at)[1]} 条")
    ok(not at.exception, "筛选过程无异常")

    print("\n[3] 立即投递：写库 + 按钮变已投 + 再点不重复")
    before = AP.stats(uid)["n"]
    # 演示账号此前投过的岗按钮会变成「已记入投递」，往后翻几条找未投的
    _tries = 0
    while not any((b.key or "") == "jd_apply" for b in at.button) and _tries < 8:
        _nxt = next((b for b in at.button if (b.key or "") == "jd_next"), None)
        if not _nxt or _nxt.disabled:
            break
        _nxt.click().run()
        _tries += 1
    at.button(key="jd_apply").click().run()
    ok(not at.exception, f"投递无异常：{[str(e.value)[:120] for e in at.exception]}")
    after = AP.stats(uid)["n"]
    ok(after == before + 1, f"已投递 {before} → {after}")
    ok(kpi_num(at, "已投递") == after, f"页面 KPI 同步为 {kpi_num(at, '已投递')}")
    ok(any(b.key == "jd_applied_btn" for b in at.button), "按钮变「✓ 已记入投递」（不可重复点）")
    row = AP.stats(uid)["rows"].iloc[0]
    ok(row["状态"] in ("已投递", "无回音"), f"新记录状态由推导得出：{row['状态']}")
    ok(str(row["依据"]).startswith(row["时间"][5:10]), f"依据列写明投递日期：{row['依据']}")

    print("\n[4] 粘贴 JD 入口已移除：只保留库内岗位")
    ok(not any((r.key or "") == "jd_mode" for r in at.radio), "没有「JD 来源」切换控件")
    ok(not any(t.key == "jd_text" for t in at.text_area), "没有 JD 粘贴框")
    ok(any((b.key or "") == "jd_next" for b in at.button), "库内岗位翻页控件仍在")

    print("\n[5] 换账号：投递/游标/筛选全部互不影响")
    at.button(key="logout_btn").click().run()
    login_demo(at, 1)
    uid2 = int(at.session_state["user"]["id"])
    ok(uid2 != uid, f"换成另一个账号（{uid} → {uid2}）")
    at.radio(key="screen").set_value("⑦ 求职实战").run()
    n2 = AP.stats(uid2)["n"]
    ok(kpi_num(at, "已投递") == n2,
       f"乙看到的是自己的 {n2} 条，不是甲的 {after} 条")
    ok("jd_cursor" not in at.session_state or at.session_state["jd_cursor"] == 0,
       "翻页游标已清（不会接着别人的位置往下翻）")
    ok(not any((r.key or "") == "jd_mode" for r in at.radio), "仍只有库内岗位一种模式")

    # 清掉本次测试投出去的那条（jd_id 非空、属于 uid）
    c = sqlite3.connect(DB)
    r = c.execute("SELECT id FROM apply_log WHERE user_id=? AND jd_id IS NOT NULL "
                  "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    c.close()
    if r:
        AP.delete_apply(uid, int(r[0]))
    ok(AP.stats(uid)["n"] == n_before, f"演示档案已还原（{AP.stats(uid)['n']} 条）")

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
