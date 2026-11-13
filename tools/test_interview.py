"""模拟面试（数字人陪练）的专项回归：状态机、评分、追问、报告、账号隔离。

跑法：.venv/Scripts/python.exe tools/test_interview.py
不碰页面，纯逻辑；页面渲染由 tools/test_walkthrough.py 第 9 步覆盖。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import interview as IV  # noqa: E402
from core import profile as PF  # noqa: E402

DB = ROOT / "data" / "jobs.db"
UID_A, UID_B = 991001, 991002
BAD: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    BAD.append(msg)
    print(f"  ❌ {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def cleanup() -> None:
    PF._conn().close()          # 先触发建表，老库第一次跑也不会 no such table
    c = sqlite3.connect(DB)
    for uid in (UID_A, UID_B):
        for sid, in c.execute("SELECT id FROM interview_session WHERE COALESCE(user_id,0)=?",
                              (uid,)).fetchall():
            c.execute("DELETE FROM interview_turn WHERE session_id=?", (sid,))
        c.execute("DELETE FROM interview_session WHERE COALESCE(user_id,0)=?", (uid,))
    c.commit()
    c.close()


def run_full(persona: str = "温和型 HR", n: int = 3) -> dict:
    qs = IV.build_questions(["数据分析", "SQL", "Python"], n)
    st = IV.new_state("测试同学", "数据分析", qs, persona)
    for _ in range(14):
        if st["stage"] == "report":
            break
        if st["stage"] == "closing":
            IV.skip_closing(st)
            break
        IV.answer(st, IV.demo_answer(IV.cur_q(st)["skill"], st["stage"] == "probe"))
    IV.finish(st)
    return st


def main() -> None:
    cleanup()

    print("\n— 1. 出题与开局")
    qs = IV.build_questions(["Python", "SQL", "Python", "", "Excel"], 5)
    check(len(qs) == 3, f"重复/空技能被去掉，实得 {len(qs)} 题")
    st = IV.new_state("张三", "数据分析", qs, "技术主管")
    check(len(st["turns"]) == 2 and st["turns"][0]["kind"] == "open",
          "开局有开场白 + 第一题")
    check(st["stage"] == "ask" and st["idx"] == 0, "初始状态为第 1 题")
    check(IV.progress(st) == (1, len(qs)), f"进度显示 {IV.progress(st)}")
    check("AI 模拟" in IV.avatar_html("技术主管", "talk"), "数字人卡片标注「AI 模拟·非真人」")

    print("\n— 2. 评分能区分好坏答案")
    good = IV.judge("在课程设计里我用 Python 清洗了 3000 条数据，先做去重再补缺失，"
                    "最后准确率提升了 12%，报告拿了优秀。", "Python")
    empty = IV.judge("不知道。", "Python")
    check(good["score"] > empty["score"], f"好答案 {good['score']} 分 > 敷衍 {empty['score']} 分")
    check(good["dims"]["具体"] == 5, "有数字 → 具体维度满分")
    check(empty["score"] <= 20, "「不知道」得分被压到 20 以内")
    short = IV.judge("做过。", "SQL")
    check(short["score"] <= 30, f"一句话答案得分 {short['score']}，不会虚高")

    print("\n— 3. 追问：该追的追、每题只追一次")
    need = IV.judge("我在项目里做过数据清洗。", "SQL")
    check(need["probe"] is not None, "没数字 → 触发追问")
    fine = IV.judge("在实训里我用 SQL 从 MySQL 拉了 2 万条订单明细，写了 3 个视图，"
                    "把对账时间从 3 小时压到 20 分钟。", "SQL")
    check(fine["probe"] is None, "要素齐全 → 不追问，直接下一题")

    st2 = IV.new_state("李四", "数据分析", IV.build_questions(["SQL", "Excel"], 2))
    IV.answer(st2, "我做过。")           # 触发追问
    check(st2["stage"] == "probe", "进入追问阶段")
    IV.answer(st2, "在实训里用 SQL 处理了 5000 条数据，最后对账时间缩短一半。")
    check(st2["stage"] == "ask" and st2["idx"] == 1, "追问后进入第 2 题（不再追）")
    n_probe = sum(1 for t in st2["turns"] if t["kind"] == "probe")
    check(n_probe == 1, f"第 1 题只追问了 {n_probe} 次")

    print("\n— 4. 完整一场：5 题走完 → 收尾 → 报告")
    full = run_full(n=3)
    check(full["stage"] == "report", "状态机走到 report")
    check(len(full["scores"]) == 3, f"记录 {len(full['scores'])} 题")
    check(60 <= IV.overall(full)["score"] <= 95,
          f"示范答案总分 {IV.overall(full)['score']}，落在合理区间")
    rep = full["report"]
    for kw in ("总评", "逐题复盘", "改一版可以这样说", "训练反馈", "不是录用预测"):
        check(kw in rep, f"报告包含「{kw}」")
    check("AI 模拟，非真人" in rep, "报告标注 AI 模拟、非真人")
    check(full["ended_at"] != "", "结束时间已记录")

    print("\n— 5. 主动提问收尾")
    st3 = run_full(n=2)
    check(st3["stage"] == "report", "不提问也能正常结束")

    print("\n— 6. 序列化往返（刷新页面续面 / 落库都靠它）")
    s = IV.to_json(full)
    back = IV.from_json(s)
    check(back["stage"] == "report" and len(back["scores"]) == len(full["scores"]),
          "state 可无损序列化")

    print("\n— 7. 落库 + 账号隔离")
    sid = PF.save_interview("测试同学", full, UID_A)
    check(sid > 0, f"落库成功，session id={sid}")
    df_a = PF.list_interviews("测试同学", UID_A)
    check(len(df_a) == 1, f"A 账号能看到 {len(df_a)} 条记录")
    df_b = PF.list_interviews("测试同学", UID_B)
    check(df_b.empty, "B 账号看不到 A 的记录（隔离生效）")
    rec = PF.load_interview(sid, UID_A)
    check(rec["ok"] and "训练反馈" in rec["report"], "A 能读回完整报告")
    check(not PF.load_interview(sid, UID_B)["ok"], "B 读 A 的 session 被拒绝")
    c = sqlite3.connect(DB)
    n_turn = c.execute("SELECT COUNT(*) FROM interview_turn WHERE session_id=?",
                       (sid,)).fetchone()[0]
    c.close()
    check(n_turn >= 6, f"对话轮次落库 {n_turn} 条")

    # 断点续面：同一场再存一次必须是 UPDATE，不能新增一条
    PF.save_interview("测试同学", full, UID_A)
    check(len(PF.list_interviews("测试同学", UID_A)) == 1, "重复保存是更新，不会产生重复记录")

    print("\n— 8. 空输入与异常保护")
    st4 = IV.new_state("王五", "全部", IV.build_questions(["Excel"], 1))
    IV.answer(st4, "")
    check(0 <= st4["scores"][0]["score"] <= 20, "空答案不崩，给低分")
    IV.finish(st4)
    check("0 分" in st4["report"] or "分" in st4["report"], "空场也能出报告")

    cleanup()
    print("\n" + "=" * 60)
    if BAD:
        print(f"❌ 有 {len(BAD)} 项不通过：")
        for b in BAD:
            print("   ·", b)
        sys.exit(1)
    print("✅ 模拟面试全部通过（测试数据已清理）")


if __name__ == "__main__":
    main()
