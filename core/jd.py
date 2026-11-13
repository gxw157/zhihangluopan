"""JD 透视镜：把学生粘贴的一条招聘 JD 解析成标准技能 + 岗位族猜测。

口径说明：
- 技能识别复用 core/skills.py 的词典别名表（与平台采集标注同一条词典），
  中文别名子串匹配、拉丁别名词边界匹配，识别结果都是词典标准名，
  所以能直接和学生档案（③ 的已会技能）、岗位需求榜对得上；
- 岗位族猜测复用 analyze.family_of：JD 第一行通常是职位名，先按它判，
  判不出再用全文前 80 字兜底；学生可在页面上手动改。
"""
from __future__ import annotations

import re

from core import analyze as A
from core import skills as SK


def extract_from_text(text: str) -> dict:
    """解析一条 JD 文本。

    返回 {ok, counts, skills, family_guess, n_terms}
    - counts: {标准技能: 出现次数}
    - skills: 按出现次数降序的标准技能列表
    - family_guess: 猜测的目标岗位族（学生可改）
    """
    if not str(text or "").strip():
        return {"ok": False, "msg": "JD 文本为空"}
    counts = SK.scan_text(text)
    skills = sorted(counts, key=lambda s: (-counts[s], s))
    head = re.split(r"[\n，,。；;｜|]", text.strip())[0]
    fam = A.family_of(head)
    if fam == "其他":
        fam = A.family_of(text[:80])
    return {"ok": True, "counts": counts, "skills": skills,
            "family_guess": fam, "n_terms": len(skills)}


def interview_questions(family: str, top: int = 5) -> list[str]:
    """按岗位族高频技能生成模拟面试题（规则模板，不依赖大模型）。"""
    dem = A_skills_demand(family, top + 2)
    qs = []
    for i, s in enumerate(dem[:top]):
        tpl = TEMPLATES[i % len(TEMPLATES)]
        qs.append(tpl.format(skill=s))
    return qs


def A_skills_demand(family: str, top: int) -> list[str]:
    from core import pathway as PW
    dem = PW.demand_of_family(family, top)
    return dem["skill"].tolist() if not dem.empty else []


TEMPLATES = [
    "请结合一个具体项目或课程作业，讲讲你使用「{skill}」完成过的一件事（背景—你做了什么—结果）。",
    "面试官追问：你刚才提到「{skill}」，如果数据是脏的、需求是变的，你的处理步骤是什么？",
    "「{skill}」里你觉得最容易出错的地方是什么？你在项目里怎么发现和避免的？",
    "如果让你向非技术的面试官解释你用「{skill}」做的东西，你会怎么讲？",
    "关于「{skill}」，你最近一次主动学习的新知识是什么？在哪用上了？",
]
