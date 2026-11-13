"""AI 模拟面试官：数字人陪练的"大脑"。

一、这个模块负责什么
    一个纯 Python 的面试状态机：出题 → 学生答 → 判定 → 要不要追问 → 下一题 → 收尾 → 出报告。
    页面只负责画（数字人头像、对话气泡、输入框），逻辑全在这里，所以能脱离 UI 直接测。

二、为什么要有离线规则版
    赛场/教室断网是常态。在线大模型（core/coze.py）只是"让追问更像人"，
    没有它也必须是完整一场面试：出题、追问、评分、报告，一步不少。
    所以 judge() / probe_for() / report_md() 全是规则实现，不依赖任何网络。

三、评分口径（必须诚实）
    四维各 5 分，满分 20 折算 100：结构 / 具体 / 技术 / 落地。
    这是「训练反馈」，不是「录用预测」——报告里固定带这句声明，不能删。
    每一维都能指出学生原话里的证据，不做玄学打分。

四、状态怎么存
    state 是一个可 JSON 序列化的 dict，页面放 st.session_state，落库存 state_json，
    所以刷新页面能续面、换账号互不干扰（session 里带 user_id，查询时按它隔离）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from core import skills as SK

# ================================================================ 面试官人设
PERSONAS: dict[str, dict] = {
    "温和型 HR": {
        "name": "李敏",
        "title": "某数据科技 · 招聘主管",
        "style": "语气温和，先肯定再追问，关注你的表达和动机",
        "tag": "表达 / 动机",
        "open": ("我是李敏，做招聘六年了，今天由我跟你聊二十分钟。流程很简单："
                 "我围绕{topic}问你 {n} 个能力点，每题你用 3–5 句话回答就行，中间我可能追问一句；"
                 "最后给你一份书面反馈。不用紧张，讲你真实做过的事就好。"),
        "close": "好，我这边问完了，谢谢你的时间。",
    },
    "技术主管": {
        "name": "陈工",
        "title": "某互联网公司 · 数据组负责人",
        "style": "直接、抠细节，关注你到底动没动手",
        "tag": "技术细节",
        "open": ("我是陈工，带数据组。今天不看简历，只看你说不说得清楚自己做过什么。"
                 "{n} 个问题，围绕{topic}，每个问题我可能会往下追一层。"
                 "答不上来就直说，别绕——我判断的是思路，不是背答案。"),
        "close": "行，我问到这儿。",
    },
}

# 出题模板：和 core/jd.py 的口径一致（同一批岗位技能），但改成面试口语
TEMPLATES = [
    "先说说「{skill}」吧。你最近一次真正用它做事是什么场景？背景是什么，你具体做了什么，结果怎么样。",
    "简历上写了「{skill}」。如果现在给你一份真实需求，你从拿到需求到交付，大概会分几步走？",
    "「{skill}」这块，你踩过最大的坑是什么？后来怎么解决的。",
    "假设我是完全不懂技术的客户，你用「{skill}」做的东西，你会怎么跟我解释？",
    "「{skill}」你现在的水平，和半年前比进步在哪？最近主动学的是什么。",
]

# 追问库：key -> 话术。按优先级从上往下取第一个命中的，一次只问一句。
PROBES: list[tuple[str, str]] = [
    ("short", "先别急着下结论。把当时的情况讲清楚：什么场景、你负责哪一块、最后是什么结果。"),
    ("vague", "举个例子吧——具体哪个项目或课程设计？你动手做的是哪一步。"),
    ("we", "这块具体是你做的哪一部分？团队里你负责哪一段，别人负责哪一段。"),
    ("nodigit", "这个结果有量化吗？比如处理了多少条数据、准确率或效率提升了多少。"),
    ("shallow", "你刚才提到「{skill}」，它最容易踩的坑是什么？你是怎么绕过去的。"),
    ("why", "为什么用「{skill}」这个做法，而不是别的？当时有比较过吗。"),
]

LEVELS = [(85, "能上场"), (70, "不错，再打磨细节"), (50, "及格，缺说服力"), (0, "需要重练")]

DIM_NAMES = ["结构", "具体", "技术", "落地"]
DIM_DESC = {
    "结构": "有背景、有动作、有结果，听得出一条完整的事",
    "具体": "有数字（数据量、提升幅度、处理条数）",
    "技术": "点名了技能，还说清了怎么用",
    "落地": "讲的是真实项目 / 实习 / 课程设计，不是空话",
}


# ================================================================ 出题
def build_questions(skills: list[str], n: int = 5) -> list[dict]:
    """按技能列表出题：{skill, q}。技能不够就少出几题，不重复。"""
    out: list[dict] = []
    seen: set[str] = set()
    for s in skills:
        s = str(s or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        i = len(out)
        out.append({"skill": s, "q": TEMPLATES[i % len(TEMPLATES)].format(skill=s)})
        if len(out) >= n:
            break
    return out


def new_state(student: str, family: str, questions: list[dict],
              persona: str = "温和型 HR", mode: str = "rules") -> dict:
    """开一场面试：返回初始 state（已含开场白 + 第一题）。"""
    p = PERSONAS.get(persona, PERSONAS["温和型 HR"])
    topic = f"「{family}」这个方向" if family and family != "全部" else "你这个方向"
    qs = questions or build_questions(["数据分析", "SQL", "Python"])
    opening = p["open"].format(topic=topic, n=len(qs))
    st = {
        "sid": 0,
        "student": student or "同学",
        "family": family or "全部",
        "persona": persona if persona in PERSONAS else "温和型 HR",
        "mode": mode,
        "qs": qs,
        "idx": 0,
        "stage": "ask",          # ask / probe / closing / report
        "probe_n": 0,
        "turns": [
            {"role": "ai", "kind": "open", "text": opening},
            {"role": "ai", "kind": "ask", "text": qs[0]["q"]},
        ],
        "scores": [],            # 每题一条：{skill, q, answer, probe, dims, score, tags, tips}
        "started_at": _now(),
        "ended_at": "",
        "report": "",
        "used_probe": [],        # 本轮面试用过的追问 key，防止同一句反复出现
    }
    return st


def total_q(st: dict) -> int:
    return len(st.get("qs") or [])


def cur_q(st: dict) -> dict:
    qs = st.get("qs") or []
    i = int(st.get("idx", 0))
    return qs[i] if 0 <= i < len(qs) else {"skill": "", "q": ""}


def progress(st: dict) -> tuple[int, int]:
    """(当前第几题, 总题数)，收尾阶段返回 (总数, 总数)。"""
    n = total_q(st)
    return (min(int(st.get("idx", 0)) + 1, n), n)


def elapsed_min(st: dict) -> int:
    try:
        t0 = datetime.strptime(str(st.get("started_at")), "%Y-%m-%d %H:%M:%S")
        t1 = datetime.strptime(str(st.get("ended_at")), "%Y-%m-%d %H:%M:%S") \
            if st.get("ended_at") else datetime.now()
        return max(int((t1 - t0).total_seconds() // 60), 0)
    except Exception:
        return 0


# ================================================================ 判定与追问
def judge(text: str, skill: str) -> dict:
    """规则评分：四维各 0–5 分，返回 {dims, score(0-100), tags, tips, probe}。

    probe 为 None 表示"这题可以过了"，否则是应该追问的那句话。
    """
    t = str(text or "").strip()
    low = t.lower()
    n_char = len(re.sub(r"\s", "", t))
    # 阿拉伯数字，或中文数量表达（三万条 / 两个多月 / 提升了五成）——语音作答常见中文数字
    nums = re.findall(r"\d+(?:\.\d+)?\s*(?:%|％|条|个|万|倍|次|分钟|小时|天|人|项)?", t)
    if re.search(r"[一二两三四五六七八九十百千万零]+(?:%|％|成|条|个|万|倍|次|分钟|小时|天|人|项|张|家|款|行|列|页|章|月|年|秒|块|台|份)", t):
        nums.append("中文数字")
    scanned = SK.scan_text(t) if t else {}
    mention_skill = bool(skill) and (skill.lower() in low or skill in scanned)

    seq_words = ("首先", "第一步", "一开始", "当时", "然后", "接着", "之后", "最后",
                 "结果", "因为", "所以", "背景", "需求", "负责")
    n_seq = sum(1 for w in seq_words if w in t)
    proj_words = ("项目", "实习", "比赛", "课程设计", "作业", "实训", "公司",
                  "负责", "完成", "实现", "搭建", "上线", "交付")
    n_proj = sum(1 for w in proj_words if w in t)
    method_words = ("用", "通过", "基于", "工具", "方法", "步骤", "脚本", "函数",
                    "库", "模型", "sql", "excel", "python", "pandas", "流程")
    n_method = sum(1 for w in method_words if w in low)
    team = any(w in t for w in ("我们", "团队", "大家", "组里")) and not any(
        w in t for w in ("我负责", "我做", "我写", "我搭", "我完成"))

    dims: dict[str, int] = {}
    # 结构：有顺序/因果词 + 有长度
    dims["结构"] = 5 if (n_seq >= 3 and n_char >= 80) else 3 if (n_seq >= 2 or n_char >= 120) else 1 if n_char >= 50 else 0
    # 具体：数字个数
    dims["具体"] = 5 if len(nums) >= 2 else 3 if len(nums) == 1 else 0
    # 技术：点名技能 + 说清方法
    dims["技术"] = 5 if (mention_skill and n_method >= 2) else 3 if (mention_skill or n_method >= 2) else 1 if scanned else 0
    # 落地：真实场景词
    dims["落地"] = 5 if (n_proj >= 2 and n_char >= 60) else 3 if n_proj >= 1 else 0

    # 太短的一律压到 2 分以下：三句话都不到的答案，撑不起任何维度
    if n_char < 25:
        dims = {k: min(v, 1) for k, v in dims.items()}
    elif n_char < 45:
        dims = {k: min(v, 3) for k, v in dims.items()}

    score = int(round(sum(dims.values()) / 20 * 100))
    tags, tips = _tags_tips(dims, skill, t)
    probe = probe_for(t, skill, nums, n_proj, n_method, mention_skill, team)
    return {"dims": dims, "score": score, "tags": tags, "tips": tips, "probe": probe}


def _tags_tips(dims: dict, skill: str, text: str) -> tuple[list[str], list[str]]:
    """按最终得分维度反推"做得好的点"和"该改的点"。

    单独抽出来是为了追问合并后能重算——否则会出现"分数给了 5 分、提示却说没提到技能"
    这种自相矛盾（同一份报告里两句话打架，答辩现场最容易被抓）。
    """
    low = str(text or "").lower()
    mention = bool(skill) and (skill.lower() in low or skill in SK.scan_text(text))
    tags, tips = [], []
    if mention:
        tags.append("点名技能")
    else:
        tips.append(f"回答里没出现「{skill}」——面试官会以为你没真正用过它")
    if dims.get("具体", 0) >= 3:
        tags.append("有数字")
    else:
        tips.append("补一个数字：数据量、提升幅度、处理条数，任选一个")
    if dims.get("落地", 0) >= 3:
        tags.append("讲的具体")
    else:
        tips.append("换成真实项目 / 课程设计里的一件事，别讲道理")
    if dims.get("结构", 0) < 3:
        tips.append("按「背景 → 我做了什么 → 结果」三句话组织，面试官才跟得上")
    if any(w in text for w in ("我们", "团队", "大家", "组里")) and not any(
            w in text for w in ("我负责", "我做", "我写", "我搭", "我完成")):
        tips.append("多用「我负责……」，少用「我们」——面试官要分辨哪部分是你做的")
    return tags, tips


def probe_for(t: str, skill: str, nums: list, n_proj: int, n_method: int,
              mention_skill: bool, team: bool) -> str | None:
    """挑一句最该追问的话；没什么可追的返回 None（直接进下一题）。"""
    n_char = len(re.sub(r"\s", "", t))
    has = {
        "short": n_char < 30,
        "vague": n_proj == 0,
        "we": team,
        "nodigit": len(nums) == 0,
        "shallow": mention_skill and n_method < 2,
        "why": n_char >= 60 and n_proj >= 1 and n_method < 2,
    }
    for key, text in PROBES:
        if has.get(key):
            return text.format(skill=skill)
    return None


# ================================================================ 对话推进
def answer(st: dict, text: str) -> dict:
    """学生答一轮，推进状态机。原地修改并返回 st。

    返回的 st["_last"] 是这一轮面试官说的话（页面拿去打字机展示）。
    """
    text = str(text or "").strip()
    stage = st.get("stage", "ask")
    st["_last"] = ""
    # 答题前拍个快照，识别错了可以撤回重说
    st["_undo"] = {
        "stage": stage, "idx": st.get("idx", 0), "probe_n": st.get("probe_n", 0),
        "n_turns": len(st.get("turns", [])), "n_scores": len(st.get("scores", [])),
        "rec": json.loads(json.dumps(st["scores"][-1])) if st.get("scores") else None,
        "stage_before": stage,
    }

    if stage == "report":
        return st

    if stage == "closing":
        # 学生的反问：记下来，礼貌收尾，出报告
        st["turns"].append({"role": "me", "kind": "ask_back", "text": text or "（没有提问）"})
        p = PERSONAS.get(st["persona"], PERSONAS["温和型 HR"])
        say = (("这个问题问得实在，我说两句：" if text else "没关系，那今天就到这儿。")
               + "团队这边最看重的是肯动手、能讲清楚的人。后面有消息 HR 会联系你。"
               + p["close"])
        st["turns"].append({"role": "ai", "kind": "close", "text": say})
        finish(st)
        st["_last"] = say
        return st

    skill = cur_q(st)["skill"]
    q_text = cur_q(st)["q"]
    j = judge(text, skill)
    st["turns"].append({"role": "me", "kind": "answer", "text": text or "（未作答）"})

    if stage == "ask":
        rec = {"skill": skill, "q": q_text, "answer": text, "probe": "",
               "dims": j["dims"], "score": j["score"], "tags": j["tags"], "tips": j["tips"]}
        if j["probe"]:
            # 追问一轮：先把这题的初答存下来，追问后按两轮的最好表现合并计分
            st["scores"].append(rec)
            st["probe_n"] = 1
            st["stage"] = "probe"
            st["turns"].append({"role": "ai", "kind": "probe", "text": j["probe"]})
            st["_last"] = j["probe"]
            return st
        st["scores"].append(rec)
        _advance(st)
        return st

    # stage == "probe"：追问的回答，和初答合并（逐维取更好的一轮）
    if st["scores"]:
        rec = st["scores"][-1]
        rec["probe"] = text
        merged = {k: max(v, j["dims"].get(k, 0)) for k, v in rec["dims"].items()}
        rec["dims"] = merged
        rec["score"] = int(round(sum(merged.values()) / 20 * 100))
        combined = (str(rec.get("answer", "")) + " " + text).strip()
        rec["tags"], rec["tips"] = _tags_tips(merged, skill, combined)
    _advance(st)
    return st


def _advance(st: dict) -> None:
    """进入下一题；题目问完就进收尾反问。"""
    st["probe_n"] = 0
    st["idx"] = int(st.get("idx", 0)) + 1
    if st["idx"] < total_q(st):
        st["stage"] = "ask"
        q = cur_q(st)["q"]
        st["turns"].append({"role": "ai", "kind": "ask", "text": q})
        st["_last"] = q
    else:
        st["stage"] = "closing"
        say = ("好，我这边的问题问完了。你有什么想问我的吗？"
               "比如团队现在做什么、新人怎么带、这个岗位最看重什么。没有的话直接点「结束面试」。")
        st["turns"].append({"role": "ai", "kind": "closing", "text": say})
        st["_last"] = say


def skip_closing(st: dict) -> dict:
    """不提问，直接结束。"""
    if st.get("stage") == "closing":
        answer(st, "")
    return st


# ================================================================ 报告
def overall(st: dict) -> dict:
    """总分与各维度均分（每题等权）。"""
    rows = st.get("scores") or []
    if not rows:
        return {"score": 0, "level": LEVELS[-1][1], "dims": {k: 0.0 for k in DIM_NAMES}, "n": 0}
    score = int(round(sum(r["score"] for r in rows) / len(rows)))
    dims = {k: round(sum(r["dims"].get(k, 0) for r in rows) / len(rows), 1) for k in DIM_NAMES}
    level = next(txt for th, txt in LEVELS if score >= th)
    return {"score": score, "level": level, "dims": dims, "n": len(rows)}


def finish(st: dict) -> dict:
    """收尾：算总分、生成报告、定稿状态。"""
    if st.get("stage") == "report":
        return st
    st["ended_at"] = st.get("ended_at") or _now()
    st["stage"] = "report"
    st["report"] = report_md(st)
    return st


def report_md(st: dict, gap: list[str] | None = None) -> str:
    """生成 Markdown 面试反馈（可下载、可存档）。"""
    ov = overall(st)
    p = PERSONAS.get(st.get("persona"), PERSONAS["温和型 HR"])
    mins = elapsed_min(st)
    L = [f"# 模拟面试反馈 · {st.get('student', '同学')}", "",
         f"> {str(st.get('ended_at') or _now())[:16]}　·　面试官：{p['name']}（{p['title']}，**AI 模拟，非真人**）"
         f"　·　方向：{st.get('family', '全部')}　·　{len(st.get('scores') or [])} 题 / 约 {mins} 分钟", ""]

    L += ["## 总评", "", f"**{ov['score']} 分 · {ov['level']}**", ""]
    L += ["| 维度 | 得分 | 看什么 |", "|---|---|---|"]
    for k in DIM_NAMES:
        L.append(f"| {k} | {ov['dims'][k]:.1f} / 5 | {DIM_DESC[k]} |")
    L.append("")

    weak = sorted(DIM_NAMES, key=lambda k: ov["dims"][k])[:2]
    L += [f"最该补的两块：**{weak[0]}**和**{weak[1]}**。", ""]

    L += ["## 逐题复盘", ""]
    for i, r in enumerate(st.get("scores") or [], 1):
        L += [f"### 第 {i} 题 · {r['skill']}", "",
              f"**问**：{r['q']}", "",
              f"**你的回答**：{_clip(r['answer'], 160)}", ""]
        if r.get("probe"):
            L += [f"**追问后补充**：{_clip(r['probe'], 160)}", ""]
        L.append(f"**得分**：{r['score']} / 100　" + "　".join(f"{k} {v}/5" for k, v in r["dims"].items()))
        L.append("")
        for t in (r.get("tips") or [])[:3]:
            L.append(f"- ⚠ {t}")
        L += ["", "**改一版可以这样说**：", "",
              f"> 当时在（哪门课 / 哪个项目）里，我负责{r['skill']}这块，具体做法是（用了什么工具、几步），"
              f"最后结果是（数字）。中间遇到的坑是（什么坑），我的处理是（怎么绕过去）。", ""]

    tips_all = []
    for r in st.get("scores") or []:
        tips_all.extend(r.get("tips") or [])
    if tips_all:
        seen, top = set(), []
        for t in tips_all:
            if t not in seen:
                seen.add(t)
                top.append(t)
        L += ["## 最该改的 3 句", ""]
        L += [f"{i}. {t}" for i, t in enumerate(top[:3], 1)]
        L.append("")

    if gap:
        L += ["## 下一步补什么", "",
              "按你目标方向「{}」的岗位要求，先补这几项：".format(st.get("family", "全部")), ""]
        L += [f"- {g}" for g in gap[:3]]
        L += ["", "补完再回「④ 差距路径」重算一次命中率，数字会动。", ""]

    L += ["---", "",
          "> 说明：以上是**训练反馈**，基于回答里的可观察要素（结构、数字、技能、场景）按规则打分，"
          "不是录用预测，也不代表任何企业的真实评价标准。"]

    # 报告跟着状态走：state 存库时 report 直接可读，不用重算
    st["report"] = "\n".join(L)
    return st["report"]


def _clip(s: str, n: int) -> str:
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "……"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ================================================================ 在线增强（可选）
def ai_prompt(st: dict, line: str, skill: str = "") -> tuple[str, str]:
    """给在线模型的提示词：(system, user)。

    注意这里不是"让 AI 决定问什么"——流程由状态机定，AI 只负责把已经定好的那句话
    说得更像真人。这样即使模型抽风，面试的题目数、追问与否、评分口径都不会变。
    """
    p = PERSONAS.get(st.get("persona"), PERSONAS["温和型 HR"])
    skill = skill or cur_q(st)["skill"]
    system = (
        f"你在扮演模拟面试官{p['name']}（{p['title']}），人设：{p['style']}。"
        "你的任务只有一件：把给你的一句面试官台词改写得更自然、更像真人当面说话，"
        "但**意图、追问的点、信息量必须完全不变**。"
        "硬性要求：①只输出一句话，不超过 60 字；②不加点评、不打分、不总结、不寒暄；"
        "③不用 Markdown、不加引号、不写「面试官：」；④不改动台词里提到的技能名和事实。"
    )
    qa = []
    for t in (st.get("turns") or [])[-6:]:
        qa.append(("学生" if t["role"] == "me" else "面试官") + "：" + t["text"])
    user = (f"目标方向：{st.get('family')}　当前能力点：{skill}\n"
            + "\n".join(qa) + f"\n\n需要改写的那句台词：{line}\n\n请只输出改写后的一句话。")
    return system, user


def apply_ai(st: dict, line: str, skill: str = "") -> str | None:
    """把规则生成的那句台词润色成更自然的说法；不可用或输出不像话时返回 None。"""
    from core import coze as CZ
    if not (CZ.available() or CZ.fallback_available()):
        return None
    if not str(line or "").strip():
        return None
    system, user = ai_prompt(st, line, skill)
    try:
        r = CZ.chat(user, system, [], None, 25)
    except Exception:
        return None
    if not r.get("ok") or r.get("engine") == "离线规则引擎":
        return None
    out = str(r.get("text") or "").strip().replace("\n", " ")
    out = re.sub(r"^\s*(面试官|AI)[:：]\s*", "", out).strip("「」\"' ")
    # 太长、带 Markdown、明显在点评的，一律不要——宁可保留规则原句
    if not out or len(out) > 95 or out.startswith("#") or re.search(r"(评分|得分|总分|建议你|综上)", out):
        return None
    return out


# ================================================================ 自由对话
# 学生随时可以向面试官提问（不影响面试进度）。在线模型优先；离线按规则表兜底。
FREE_RULES: list[tuple[str, str]] = [
    ("加班|几点下班|大小周|996|作息",
     "节奏确实不轻松，但我们更看重把活儿干完的质量，不提倡熬时长。"
     "这些入职后都会讲清楚——先回到刚才那题，把你的事讲完整。"),
    ("薪资|工资|待遇|多少钱|报酬|offer|Offer",
     "薪资要等 Offer 阶段才谈数，今天这场看的是能力匹不匹配。"
     "你现在把能力讲清楚，将来谈薪才有底气。"),
    ("五险|保险|公积金|合同|编制|转正|试用期",
     "这些入职后 HR 会跟你一条条讲，都是标准流程。今天咱们把时间留给能力本身。"),
    ("提示|不会答|不知道|怎么回答|帮帮我|卡住|没思路",
     "给你个提示：按「当时在做什么 → 我具体做了哪一步 → 结果带个数字」三句走。"
     "围绕「{skill}」，挑最真实的那件事讲。"),
    ("看重|要求|什么样的人|加分|标准",
     "{focus}是我最看重的。回答里把这两样亮出来，比什么话术都管用。"),
    ("真人吗|是AI|是AI吗|人工智能|机器人",
     "我是 AI 模拟面试官，不是真人——但评分标准和追问逻辑，都是照真实面试来的。放心练。"),
    ("你好|你好呀|hi|hello|自我介绍",
     "你好，我是{name}，{title}。咱们不寒暄了，直接看你的本事——回到刚才那题。"),
    ("谢谢|辛苦了|麻烦了",
     "不客气。你的表现在进步，继续——回到刚才那题。"),
    ("紧张|怕|担心|第一次",
     "紧张很正常，真面试也紧张。你就当跟我聊天，讲你真做过的事——"
     "真实的事是讲不砸的。"),
]


def _free_rule(st: dict, text: str) -> str:
    p = PERSONAS.get(st.get("persona"), PERSONAS["温和型 HR"])
    skill = cur_q(st).get("skill", "这项技能")
    focus = p.get("tag", "表达和动手")
    for pat, tpl in FREE_RULES:
        if re.search(pat, text, re.I):
            return tpl.replace("{skill}", skill).replace("{focus}", focus).replace("{name}", p["name"]).replace("{title}", p["title"])
    return ("这个问题现场我也会答，但今天的主角是你。"
            "先回到「{skill}」这题——把你做过的事讲清楚，比什么都强。"
            ).replace("{skill}", skill)


def ai_free_prompt(st: dict, text: str) -> tuple[str, str]:
    p = PERSONAS.get(st.get("persona"), PERSONAS["温和型 HR"])
    skill = cur_q(st).get("skill", "")
    system = (
        f"你是模拟面试官{p['name']}（{p['title']}），人设：{p['style']}。"
        f"学生刚在面试中问了你一个场外问题，请以面试官身份简短回答。"
        "硬性要求：①一到两句话、不超过 70 字；②不要 Markdown；③不要评分不要总结；"
        "④回答完自然把话题带回当前问题（当前能力点：" + skill + "）；⑤涉及薪资/加班等敏感话题就简短带过并拉回。"
    )
    qa = []
    for t in (st.get("turns") or [])[-6:]:
        qa.append(("学生" if t["role"] == "me" else "面试官") + "：" + t["text"])
    user = "\n".join(qa) + f"\n学生的场外提问：{text}\n\n请只输出你的回答。"
    return system, user


def undo_last(st: dict) -> bool:
    """撤回最近一次作答（语音识别错了用），恢复到答题前的状态。"""
    u = st.pop("_undo", None)
    if not u:
        return False
    st["stage"] = u["stage"]
    st["idx"] = u["idx"]
    st["probe_n"] = u["probe_n"]
    del st["turns"][u["n_turns"]:]
    if u["stage"] == "probe" and u.get("rec") is not None:
        # 撤的是追问那答：最后一题被合并过，恢复成合并前的样子
        st["scores"] = st["scores"][:max(0, u["n_scores"] - 1)] + [u["rec"]]
    else:
        # 撤的是整题作答：直接砍掉新增的那条
        del st["scores"][u["n_scores"]:]
    st["_last"] = ""
    st["_tts_k"] = ""  # 让面试官重新念一遍被撤回的那题
    return True


def free_chat(st: dict, text: str) -> str:
    """学生自由提问：先试在线模型，失败/不像话就落规则表。同时把两轮都记进 turns。"""
    text = str(text or "").strip()
    if not text:
        return ""
    st["turns"].append({"role": "me", "kind": "chat", "text": text})
    reply = ""
    if st.get("mode") != "demo":
        from core import coze as CZ
        if CZ.available() or CZ.fallback_available():
            try:
                system, user = ai_free_prompt(st, text)
                r = CZ.chat(user, system, [], None, 30)
                if r.get("ok") and r.get("engine") != "离线规则引擎":
                    out = str(r.get("text") or "").strip().replace("\n", " ")
                    out = re.sub(r"^\s*(面试官|AI|李敏|陈工)[:：]\s*", "", out).strip()
                    if 0 < len(out) <= 140 and not out.startswith("#"):
                        reply = out
            except Exception:
                reply = ""
    if not reply:
        reply = _free_rule(st, text)
    st["turns"].append({"role": "ai", "kind": "chat", "text": reply})
    return reply


# 演示场用的回答库：路演现场没时间打字，一键跑完整场。
# 按技能关键词取答案，学生看到的是"这个方向的人该怎么答"，而不是一段无关的万能话。
DEMO_ANSWERS: dict[str, str] = {
    "数据分析": "去年课程设计做过一个校园二手交易的数据分析，我负责清洗和可视化两块。"
              "原始数据 3000 多条，重复和缺失大概占 12%，我先用 pandas 去重，再按字段类型分别填充，"
              "最后用 matplotlib 出了 5 张图，把品类和价格分布讲清楚了，报告拿了专业第一。",
    "SQL": "我会先确认需求口径：给谁看、要得出什么结论。然后取数，用 SQL 从 MySQL 按时间范围拉明细、"
           "写成视图；再用 Python 做清洗和指标计算，最后用 Excel 透视表出看板。"
           "交付前一定跟需求方对一遍数字，避免口径不一致。",
    "Python": "我用 Python 写过一个自动整理实习周报的脚本：读 Excel、按周合并、算环比，"
              "再用 openpyxl 回写格式。原来每周手工弄 40 分钟，现在跑一次 20 秒。"
              "中间最麻烦的是日期格式不统一，我加了一层解析和异常兜底才稳定。",
    "Excel": "Excel 这块我做过一个门店销售周报模板：8 家门店、每天 200 多条流水，我用数据透视表按门店和"
             "品类两层汇总，再加条件格式标出环比下滑的店。原来手工做要两小时，现在十分钟就能出。",
    "机器学习": "机器学习我只做到能跑通的程度：用 sklearn 做过一个二手房价的回归，样本 1200 条，"
              "特征选了 8 个，交叉验证的 R² 大概 0.72。调参只会网格搜索，参数一多就跑得慢，这是我还想补的。",
    "probe": "踩过最大的坑是编码问题：中文城市名导进来是乱码，导致分组全错。"
             "我一开始以为是数据本身脏，排查了两小时才发现是读取时没指定编码。"
             "之后我固定用 utf-8 读，并在清洗脚本里加了一步字段类型和唯一值检查，同样的错没再犯。",
}


def demo_answer(skill: str, probe: bool = False) -> str:
    """按技能挑演示答案；追问时用"踩坑"那段（对任何技能都成立）。"""
    if probe:
        return DEMO_ANSWERS["probe"]
    s = str(skill or "")
    for k in ("SQL", "数据库", "MySQL", "Hive", "数据仓库"):
        if k.lower() in s.lower():
            return DEMO_ANSWERS["SQL"]
    for k in ("Python", "脚本", "爬虫"):
        if k.lower() in s.lower():
            return DEMO_ANSWERS["Python"]
    for k in ("Excel", "可视化", "图表", "报表", "BI"):
        if k.lower() in s.lower():
            return DEMO_ANSWERS["Excel"]
    for k in ("机器学习", "算法", "模型", "深度学习", "NLP"):
        if k in s:
            return DEMO_ANSWERS["机器学习"]
    return DEMO_ANSWERS["数据分析"]


# ================================================================ 序列化（落库用）
def to_json(st: dict) -> str:
    return json.dumps(st, ensure_ascii=False)


def from_json(s: str | dict) -> dict:
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


# ================================================================ 数字人形象（纯 SVG + CSS）
# 为什么不用图片/视频：一张 PNG 换不了表情，一段视频换不了台词。
# SVG 能按 mood 换嘴型、眼睛、声波，断网也在，渲染零延迟——路演现场最怕的就是加载圈。
CSS = """
.ivcard{position:relative;overflow:hidden;border-radius:16px;padding:12px 14px 14px;
  background:linear-gradient(160deg,#0b3f7a 0%,#5586bd 62%,#2f8fe0 100%);
  box-shadow:0 12px 28px rgba(11,63,122,.26)}
.ivcard:after{content:"";position:absolute;right:-52px;top:-60px;width:170px;height:170px;
  border-radius:50%;background:rgba(255,255,255,.09)}
.ivlive{position:relative;z-index:2;display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);border-radius:999px;
  padding:3px 10px;font-size:11px;color:#eaf5ff;letter-spacing:.3px}
.ivlive .d{width:6px;height:6px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 3px rgba(74,222,128,.25);
  animation:ivpulse 1.8s ease-in-out infinite}
@keyframes ivpulse{0%,100%{opacity:1}50%{opacity:.35}}
.ivstage{position:relative;z-index:2;display:flex;justify-content:center;margin:6px 0 2px}
.ivname{position:relative;z-index:2;text-align:center;color:#fff;font-size:16px;font-weight:700;letter-spacing:.5px}
.ivtitle{position:relative;z-index:2;text-align:center;color:#c9e3ff;font-size:11.5px;margin-top:2px}
.ivstate{position:relative;z-index:2;margin-top:9px;text-align:center;font-size:12px;color:#eaf5ff;
  background:rgba(255,255,255,.12);border-radius:9px;padding:5px 8px;min-height:28px;line-height:1.5}
.ivstate.think{color:#ffe6a8}
.ivstate.talk{color:#c9f7d8}
.ivstate.nod{color:#c9f7d8}
.ivstate.frown{color:#ffd0d0}
.ivsvg{width:100%;max-width:230px;height:auto;display:block}
.iv-eye{transform-box:fill-box;transform-origin:center;animation:ivblink 4.6s infinite}
@keyframes ivblink{0%,96%,100%{transform:scaleY(1)}98%{transform:scaleY(.1)}}
.iv-mouth-t{transform-box:fill-box;transform-origin:center;animation:ivtalk .42s ease-in-out infinite}
@keyframes ivtalk{0%,100%{transform:scaleY(1)}50%{transform:scaleY(.28)}}
.iv-wave{transform-box:fill-box;transform-origin:center bottom;animation:ivwave .7s ease-in-out infinite}
.iv-wave:nth-child(2){animation-delay:.16s}
.iv-wave:nth-child(3){animation-delay:.32s}
@keyframes ivwave{0%,100%{transform:scaleY(.35);opacity:.55}50%{transform:scaleY(1);opacity:1}}
.iv-dot{animation:ivdots 1.15s ease-in-out infinite}
.iv-dot:nth-child(2){animation-delay:.18s}
.iv-dot:nth-child(3){animation-delay:.36s}
@keyframes ivdots{0%,100%{opacity:.25;transform:translateY(0)}50%{opacity:1;transform:translateY(-3px)}}
.iv-halo{animation:ivhalo 2.6s ease-in-out infinite}
@keyframes ivhalo{0%,100%{opacity:.16}50%{opacity:.30}}
.ivbub{animation:ivfade .32s ease-out both}
@keyframes ivfade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.ivrow{display:flex;gap:8px;align-items:center;font-size:12.5px;color:#134a8e;margin:2px 0}
.ivrow .b{flex:1;height:7px;border-radius:99px;background:#dbe9f7;overflow:hidden}
.ivrow .b i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#5586bd,#2f8fe0)}
.ivsum{display:flex;align-items:center;gap:20px;border-radius:14px;padding:14px 20px;margin-bottom:10px;
  background:linear-gradient(100deg,#eaf3ff,#f7fbff);border:1px solid #cfe3f8}
.ivsum .sc{font-size:40px;font-weight:800;color:#0b3f7a;line-height:1}
.ivsum .sc span{font-size:15px;color:#5b7a9d;font-weight:600;margin-left:2px}
.ivsum .lv{font-size:15.5px;font-weight:700;color:#5586bd}
.ivsum .ds{font-size:12.5px;color:#5b7a9d;line-height:1.65;flex:1}
"""

MOOD_TEXT = {
    "idle": ("在线，等你回答", ""),
    "think": ("正在听，也在想你怎么答的…", "think"),
    "talk": ("正在提问…", "talk"),
    "nod": ("点了点头，这题答得住", "nod"),
    "frown": ("眉头皱了一下，这段还得补", "frown"),
}


def avatar_html(persona: str = "温和型 HR", mood: str = "idle") -> str:
    """数字人面板：头肩像 + 名牌 + 状态。mood 换表情，纯 CSS 动画，无外部依赖。"""
    p = PERSONAS.get(persona, PERSONAS["温和型 HR"])
    mood = mood if mood in MOOD_TEXT else "idle"
    txt, cls = MOOD_TEXT[mood]

    # ---- 嘴：不同状态换形状 ----
    if mood == "talk":
        mouth = ('<ellipse class="iv-mouth-t" cx="130" cy="158" rx="10" ry="7" fill="#a8412f"/>')
    elif mood == "nod":
        mouth = ('<path d="M116 156 q14 14 28 0" stroke="#a8412f" stroke-width="4.5" '
                 'fill="none" stroke-linecap="round"/>')
    elif mood == "frown":
        mouth = ('<path d="M118 162 q12 -9 24 0" stroke="#a8412f" stroke-width="4.5" '
                 'fill="none" stroke-linecap="round"/>')
    elif mood == "think":
        mouth = ('<path d="M120 159 h20" stroke="#a8412f" stroke-width="4.5" '
                 'fill="none" stroke-linecap="round"/>')
    else:
        mouth = ('<path d="M118 157 q12 9 24 0" stroke="#a8412f" stroke-width="4.5" '
                 'fill="none" stroke-linecap="round"/>')

    # ---- 眉眼：皱眉时眉毛压低 ----
    brow_l = ('M99 118 q13 -9 26 -2' if mood == "frown" else 'M99 116 q13 -6 25 -1')
    brow_r = ('M135 116 q13 -7 26 2' if mood == "frown" else 'M136 115 q13 -5 25 1')

    # ---- 说话声波 / 思考三点 ----
    extra = ""
    if mood == "talk":
        extra = ('<g transform="translate(196 128)">'
                 '<rect class="iv-wave" x="0" y="0" width="5" height="26" rx="2.5" fill="#7fd0ff"/>'
                 '<rect class="iv-wave" x="10" y="4" width="5" height="18" rx="2.5" fill="#a8e0ff"/>'
                 '<rect class="iv-wave" x="20" y="8" width="5" height="12" rx="2.5" fill="#7fd0ff"/>'
                 '</g>')
    elif mood == "think":
        extra = ('<g transform="translate(160 56)">'
                 '<circle class="iv-dot" cx="0" cy="0" r="4.2" fill="#ffffff"/>'
                 '<circle class="iv-dot" cx="14" cy="0" r="4.2" fill="#ffffff"/>'
                 '<circle class="iv-dot" cx="28" cy="0" r="4.2" fill="#ffffff"/>'
                 '</g>')

    svg = f"""
<svg class="ivsvg" viewBox="0 0 260 300" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="AI 模拟面试官 {p['name']}">
  <defs>
    <linearGradient id="ivsuit" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1e3a5f"/><stop offset="1" stop-color="#16283f"/>
    </linearGradient>
    <linearGradient id="ivskin" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fbdcbd"/><stop offset="1" stop-color="#f0c39a"/>
    </linearGradient>
    <radialGradient id="ivglow" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#8ecbff"/><stop offset="1" stop-color="#8ecbff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <circle class="iv-halo" cx="130" cy="126" r="112" fill="url(#ivglow)"/>
  <path d="M34 300 C34 234 76 204 130 204 C184 204 226 234 226 300 Z" fill="url(#ivsuit)"/>
  <path d="M108 206 L130 246 L152 206 L166 213 L130 270 L94 213 Z" fill="#f2f8ff"/>
  <path d="M130 250 L139 264 L130 292 L121 264 Z" fill="#c0392b"/>
  <rect x="114" y="172" width="32" height="36" rx="13" fill="#e8b48b"/>
  <ellipse cx="130" cy="132" rx="54" ry="60" fill="url(#ivskin)"/>
  <path d="M76 130 C76 82 101 64 130 64 C159 64 184 82 184 130 C184 112 166 96 130 96
           C94 96 76 112 76 130 Z" fill="#2b2f3a"/>
  <ellipse cx="77" cy="138" rx="8" ry="11" fill="#eab992"/>
  <ellipse cx="183" cy="138" rx="8" ry="11" fill="#eab992"/>
  <path d="{brow_l}" stroke="#3a3f4b" stroke-width="4" fill="none" stroke-linecap="round"/>
  <path d="{brow_r}" stroke="#3a3f4b" stroke-width="4" fill="none" stroke-linecap="round"/>
  <ellipse class="iv-eye" cx="112" cy="134" rx="5" ry="6.2" fill="#2b2f3a"/>
  <ellipse class="iv-eye" cx="148" cy="134" rx="5" ry="6.2" fill="#2b2f3a"/>
  <path d="M130 138 l-4 12 h8 z" fill="#e0a97f" opacity=".7"/>
  {mouth}
  {extra}
</svg>"""

    return f"""<div class="ivcard">
  <div class="ivlive"><span class="d"></span>AI 模拟面试官 · 非真人</div>
  <div class="ivstage">{svg}</div>
  <div class="ivname">{p['name']}</div>
  <div class="ivtitle">{p['title']}</div>
  <div class="ivstate {cls}">{txt}</div>
</div>"""

