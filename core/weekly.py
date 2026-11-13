"""周任务卡与成长周报：把"十二周补课表"落到"这周干什么"。

- task_card：从学习路径的缺口里取本周主攻技能，给出学哪门课、练什么、交什么、
  以及补完之后命中率会到多少——全部用平台已算好的数字，不引入新口径；
- weekly_report：读成长档案的两次快照，生成"你比上次强在哪 + 下周做什么"。
"""
from __future__ import annotations

from datetime import datetime

from core import profile as PF


def task_card(lp: dict, week: int = 1) -> dict:
    """生成第 N 周任务卡。lp 是 pathway.build_path 的结果。"""
    if not lp or not lp.get("ok") or len(lp.get("gap", [])) == 0:
        return {"ok": False, "msg": "没有待补技能——先做一次定位，或换个目标岗位族"}
    gap = lp["gap"]
    row = gap.iloc[min(max(week - 1, 0), len(gap) - 1)]
    total = float(lp["table"]["岗位数"].sum())
    held = float(lp["table"].loc[lp["table"]["已掌握"], "岗位数"].sum())
    after = min((held + float(row["岗位数"])) / total, 1.0) if total else lp["match"]
    course = str(row["相关课程"])
    has_course = course and course != "本专业暂无对应课程"
    plan = {
        "ok": True, "week": week, "skill": row["技能"], "n_jobs": int(row["岗位数"]),
        "share": float(row["占比"]), "course": course if has_course else "",
        "cover": float(row["课程覆盖"]), "match_now": float(lp["match"]),
        "match_after": float(after), "n_gap": int(len(gap)),
    }
    plan["steps"] = [
        ("学", f"《{course}》里对应「{row['技能']}」的章节，先看一遍、跟着做一遍"
         if has_course else
         f"找 1+X 证书对应模块或一门在线课，把「{row['技能']}」的基础过一遍"),
        ("练", f"用真实数据做一个最小练习：能跑通、能解释每一步为什么这么做"),
        ("交", f"产出一个可展示的成果（脚本 / 图表 / 一页说明），写进简历的「项目」段"),
        ("验", f"回来重新勾选技能，命中率应从 {lp['match']:.0%} 升到约 {after:.0%}"),
    ]
    return plan


def task_markdown(plan: dict) -> str:
    if not plan.get("ok"):
        return plan.get("msg", "")
    L = [f"### 第 {plan['week']} 周任务卡 · {plan['skill']}", "",
         f"> 目标岗位里有 **{plan['n_jobs']} 条**要求这项技能（占 {plan['share']:.0%}）；"
         f"它是你当前 {plan['n_gap']} 项缺口里最该先动的一项。", ""]
    for tag, text in plan["steps"]:
        L.append(f"- **{tag}**：{text}")
    L += ["", f"本周完成后的预期：命中率 **{plan['match_now']:.0%} → {plan['match_after']:.0%}**"
              "（按「多掌握一项岗位要求」直接推算，回来重新定位即可验证）。"]
    return "\n".join(L)


def weekly_report(student: str, uid: int | None = None) -> dict:
    """成长周报：基于快照对比生成。uid 为登录账号，按账号取自己的快照。"""
    cmp_ = PF.compare(student, uid)
    hist = PF.history(student, uid)
    if not cmp_.get("ok"):
        return {"ok": False, "msg": cmp_.get("msg", "快照不足")}
    prev, now = cmp_["prev"], cmp_["now"]
    delta = cmp_["d_match"]
    _days_txt = ("两次记录在同一天" if cmp_["days"] == 0
                 else f"距上次记录 {cmp_['days']} 天")
    L = [f"### 本周成长周报 · {student}", "",
         f"**一句话**：命中率 {prev['match']:.0%} → {now['match']:.0%}"
         f"（{'↑' if delta >= 0 else '↓'}{abs(delta):.0%}），"
         f"缺口 {prev['n_gap']} → {now['n_gap']} 项，{_days_txt}。", ""]
    if cmp_["fixed"]:
        L.append(f"- **补上的**：{'、'.join(cmp_['fixed'][:8])}")
    if cmp_["new_gap"]:
        L.append(f"- **新出现的**：{'、'.join(cmp_['new_gap'][:8])}（目标变了或岗位要求变了，属于正常）")
    if len(hist) >= 2:
        first, last = hist.iloc[0], hist.iloc[-1]
        L.append(f"- **整条曲线**：从 {first['match']:.0%} 到 {last['match']:.0%}，共 {len(hist)} 次记录")
    L += ["", "**下周建议**：把「④ 差距路径」的第一项拆成两半，前半周学、后半周做作品；"
              "做完回来重新定位一次，让这条曲线继续往上走。"]
    return {"ok": True, "text": "\n".join(L), "delta": delta,
            "fixed": cmp_["fixed"], "new_gap": cmp_["new_gap"],
            "ts": datetime.now().strftime("%Y-%m-%d")}
