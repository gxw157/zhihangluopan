"""投递自动化专项测试：幂等 / 状态推导 / 14 天超时 / 迟到信号回滚 / 账号隔离 / 截图 OCR。

跑法：.venv/Scripts/python.exe tools/test_apply_auto.py
自清理：用 uid 998/999 当隔离沙箱，跑完连事件带投递一起删干净，绝不碰演示账号。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import apply as AP  # noqa: E402

UID_A, UID_B = 998, 999
PASS = 0
FAIL = 0


def ok(cond, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")


def purge() -> None:
    c = sqlite3.connect(AP.DB)
    try:
        ids = [r[0] for r in c.execute(
            "SELECT id FROM apply_log WHERE user_id IN (?,?)", (UID_A, UID_B))]
        for aid in ids:
            c.execute("DELETE FROM apply_event WHERE apply_id=?", (aid,))
        c.execute("DELETE FROM apply_log WHERE user_id IN (?,?)", (UID_A, UID_B))
        c.commit()
    finally:
        c.close()


def main() -> None:
    purge()
    print("\n[1] 投递幂等：同账号同岗位只记一次")
    r1 = AP.log_apply(UID_A, "测试甲", "ZP0001", "数据分析实习生",
                      "郑州云图数据科技有限公司", "郑州", 0.62, source="JD体检")
    r2 = AP.log_apply(UID_A, "测试甲", "ZP0001", "数据分析实习生",
                      "郑州云图数据科技有限公司", "郑州", 0.62, source="JD体检")
    ok(r1.get("ok") and not r1.get("dup"), f"首次写入 id={r1.get('id')}")
    ok(r2.get("ok") and r2.get("dup"), "重复点被拦住（不新增记录）")
    ok(AP.stats(UID_A)["n"] == 1, f"已投递仍为 1 条（实际 {AP.stats(UID_A)['n']}）")
    ok(AP.stats(UID_A)["pending"] == 1, "状态推导为「已投递」（在流程中）")

    print("\n[2] 账号隔离：乙看不到甲的任何投递")
    ok(AP.stats(UID_B)["n"] == 0, "乙的已投递 = 0")
    ok(AP.board(UID_B).empty, "乙的流水为空")
    ok(AP.add_event(UID_B, r1["id"], "offer").get("ok") is False,
       "乙不能往甲的投递上挂事件（越权被拒）")
    ok(AP.delete_apply(UID_B, r1["id"]) == 0, "乙删不掉甲的投递")

    print("\n[3] 状态机优先级：offer > 拒信 > 面试 > 约面 > 投递")
    AP.add_event(UID_A, r1["id"], "interview_invite", "2026-11-08 10:00", "截图OCR")
    ok(AP.stats(UID_A)["rows"].iloc[0]["状态"] == "已约面", "邀请 → 已约面")
    ok(AP.stats(UID_A)["interview"] == 1 and AP.stats(UID_A)["rate"] == 1.0,
       "转化率自动变 100%")
    AP.add_event(UID_A, r1["id"], "interview_done", "2026-11-12 15:00", "截图OCR")
    ok(AP.stats(UID_A)["rows"].iloc[0]["状态"] == "已面试", "面试完成 → 已面试")
    AP.add_event(UID_A, r1["id"], "offer", "2026-11-15 09:00", "截图OCR")
    ok(AP.stats(UID_A)["rows"].iloc[0]["状态"] == "已录用", "offer → 已录用")
    ok(AP.stats(UID_A)["offer"] == 1, "已录用计数 = 1")

    print("\n[4] 14 天超时规则：纯自动判「无回音」")
    old_ts = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    aid_old = AP.legacy_import(UID_B, "测试乙", "数据运营实习生",
                               "北京某电商公司", "北京", "已投递", "", old_ts)
    ok(AP.stats(UID_B)["rows"].iloc[0]["状态"] == "无回音",
       f"20 天前的投递自动判无回音（{AP.stats(UID_B)['rows'].iloc[0]['状态']}）")
    n1 = AP.timeout_sweep(UID_B)
    n2 = AP.timeout_sweep(UID_B)
    ok(n1 >= 1 and n2 == 0, f"补 silent 事件 {n1} 条，再跑一次 0 条（幂等）")

    print("\n[5] 迟到信号自动回滚：无回音 → 已约面")
    AP.add_event(UID_B, aid_old, "interview_invite",
                 datetime.now().strftime("%Y-%m-%d 10:00"), "邮件:IMAP")
    st = AP.stats(UID_B)["rows"].iloc[0]
    ok(st["状态"] == "已约面", f"第 21 天收到邀请 → 状态翻回（{st['状态']}）")
    ok("满 14 天" not in st["依据"] or "面试邀请" in st["依据"], f"依据含邀请记录：{st['依据']}")

    print("\n[6] 通知解析（截图/邮件共用规则）")
    txt = ("面试邀请\n郑州云图数据科技有限公司\n您好，您的简历已通过筛选，"
           "请于 11月15日 14:00 到郑州市金水区农业路 12 号参加面试。")
    p = AP.parse_notice(txt)
    ok(p["ok"] and p["kind"] == "interview_invite", f"识别为面试邀请（{p['kind']}）")
    ok("云图数据" in p["company"], f"提公司名：{p['company']}")
    ok(p["when"].startswith(f"{datetime.now().year}-11-15"), f"提时间：{p['when']}")
    ok(AP.parse_notice("恭喜您通过面试，现发录用通知，请于 12月1日入职")["kind"] == "offer",
       "录用通知识别为 offer")
    ok(AP.parse_notice("很遗憾，本岗位暂不合适")["kind"] == "rejected", "拒信识别为 rejected")
    ok(AP.parse_notice("今天天气不错")["ok"] is False, "无关文本不乱判")

    print("\n[7] 截图 OCR：拖一张约面通知，自动挂到对应投递")
    okv, err = AP.ocr_available()
    if not okv:
        print(f"  - 跳过：本机没有 OCR 引擎（{err}）")
    else:
        from PIL import Image, ImageDraw, ImageFont
        import io
        img = Image.new("RGB", (900, 360), "white")
        d = ImageDraw.Draw(img)
        f1 = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 34)
        f2 = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
        y = 30
        for t, f in (("面试邀请", f1), ("郑州云图数据科技有限公司", f2),
                     ("请于 11月15日 14:00 参加面试，地点：金水区农业路12号", f2)):
            d.text((40, y), t, font=f, fill="black")
            y += 60
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        o = AP.ocr_image(buf.getvalue())
        ok(o.get("ok"), f"OCR 出字（{len(o.get('lines', []))} 行）")
        ok("面试" in o["text"], f"识别到「面试」字样：{o['text'][:40]!r}")
        ing = AP.ingest_notice(UID_A, o["text"], "截图OCR")
        ok(ing.get("ok"), f"识别类型：{ing.get('kind_label')}")
        ok(ing.get("applied_id") == r1["id"],
           f"自动挂到「数据分析实习生」（applied_id={ing.get('applied_id')}）")

    print("\n[8] 删除级联：删投递连带删事件")
    before = AP.stats(UID_B)["n"]
    AP.delete_apply(UID_B, aid_old)
    c = sqlite3.connect(AP.DB)
    left = c.execute("SELECT COUNT(*) FROM apply_event WHERE apply_id=?", (aid_old,)).fetchone()[0]
    c.close()
    ok(AP.stats(UID_B)["n"] == before - 1, "投递已删")
    ok(left == 0, "事件一并清掉，不留孤儿")

    purge()
    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
