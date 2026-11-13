"""AI 事实校验：把生成文本里的数字，与平台算出来的数字逐个核对。

为什么需要：大模型负责"把数字组织成话"，但它可能改写、四舍五入错、甚至编一个更
好看的数。这里在生成之后加一道闸——文本里出现的百分比 / 岗位条数，必须能在平台
侧算出的允许值里找到，否则标为"待核"。答辩时可以直接演示这道闸。

用法：
    facts = collect(lp=lp, cov=cov, ov=ov)
    r = check(plan_text, facts)      # r["issues"] 为空 = 全部核对通过
"""
from __future__ import annotations

import re

PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
COUNT = re.compile(r"(\d{2,5})\s*(条|门|项|个)")
YEAR = re.compile(r"^(19|20)\d{2}$")


def collect(lp: dict | None = None, cov: dict | None = None,
            ov: dict | None = None, extra: list[float] | None = None) -> dict:
    """汇总平台侧所有可核对的数字。

    返回 {"pct": {允许的百分比}, "count": {允许的条数}, "labels": {...}}
    百分比按 0~100 存；条数按整数存。
    """
    # 平台固定阈值也算"可核对"：70% 可投实习线、0.6/0.4 权重、红橙分位 70%/50%
    pct: set[float] = {0.0, 100.0, 70.0, 60.0, 40.0, 50.0, 30.0}
    cnt: set[int] = set()
    labels: dict[str, str] = {}

    if lp and lp.get("ok"):
        pct.add(round(float(lp["match"]) * 100, 1))
        cnt.add(int(lp.get("n_family", 0)))
        cnt.add(int(len(lp.get("gap", []))))
        if "table" in lp:
            cnt.update({int(x) for x in lp["table"]["岗位数"].head(20).tolist()})
        labels["命中率"] = f"{lp['match']:.1%}"
        if "table" in lp and len(lp["table"]):
            for r in lp["table"].head(20).itertuples():
                pct.add(round(float(r.占比) * 100, 1))
    if cov and cov.get("ok"):
        pct.add(round(float(cov["coverage"]) * 100, 1))
        cnt.update({int(cov.get("n_courses", 0)), int(cov.get("n_links", 0)),
                    int(cov.get("red", 0)), int(cov.get("orange", 0)),
                    int(cov.get("green", 0))})
        labels["课程覆盖率"] = f"{cov['coverage']:.1%}"
    if ov:
        cnt.update({int(ov.get("n", 0)), int(ov.get("cities", 0)),
                    int(ov.get("companies", 0)), int(ov.get("skills", 0))})
        pct.add(round(float(ov.get("salary_rate", 0)) * 100, 1))
    if extra:
        for v in extra:
            pct.add(round(float(v), 1))

    pct = {p for p in pct if 0 <= p <= 100}
    cnt = {c for c in cnt if c > 0}
    return {"pct": pct, "count": cnt, "labels": labels}


def check(text: str, facts: dict, tol: float = 1.0) -> dict:
    """核对文本中的数字。

    tol：百分比允许的误差（百分点）。四舍五入到整数的写法也算通过。
    返回 {ok, checked, issues, note}
    """
    if not text:
        return {"ok": True, "checked": 0, "issues": [], "note": ""}
    pct_ok, cnt_ok = facts.get("pct", set()), facts.get("count", set())
    issues: list[tuple[str, str]] = []
    checked = 0

    for m in PCT.finditer(text):
        val = float(m.group(1))
        checked += 1
        if not any(abs(val - p) <= tol for p in pct_ok):
            issues.append((m.group(0), "平台侧没有这个比例"))
    for m in COUNT.finditer(text):
        num = int(m.group(1))
        if YEAR.match(m.group(1)):
            continue
        checked += 1
        if not any(abs(num - c) <= 1 for c in cnt_ok):
            issues.append((m.group(0), "平台侧没有这个条数"))

    n = len(issues)
    note = ("全部数字与平台计算一致" if n == 0 else
            f"{n} 处数字在平台侧找不到对应值，可能被模型改写，建议点开原始数据核对")
    return {"ok": n == 0, "checked": checked, "issues": issues[:6], "note": note}


def badge(text: str, facts: dict) -> tuple[str, str]:
    """给页面用的简洁结论：(等级, 文案)。等级 ok / warn / none。"""
    r = check(text, facts)
    if r["checked"] == 0:
        return "none", "这段文字里没有需要核对的数字"
    if r["ok"]:
        return "ok", f"事实校验通过：{r['checked']} 处数字均与平台计算一致"
    return "warn", f"事实校验：{r['checked']} 处数字中 {len(r['issues'])} 处待核（{r['note']}）"
