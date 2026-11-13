"""Coze 智能体双引擎：上下文注入式 RAG + 对话式规划 + 规划书工作流 + 离线规则兜底。

双引擎分工：
    平台引擎（analyze/pathway/agent）强在"算得准"——每个数字可复算、可追溯；
    Coze 引擎强在"聊得开"——追问、鼓励、把规划翻译成每周动作。

四级降级设计（赛场断网也不冷场）：
    ⓿ Dify 本地化（本次新增）：config/dify.json 配了 base_url+api_key，
       走校内私有化部署的 Dify（本地 Ollama 模型 + 本校知识库），全程不出校园网；
    ① Coze 在线：config/coze.json 配了 token+bot_id，走 Coze Chat API（SSE 流式）；
    ② OpenAI 兼容兜底：没配 Coze 但配了 config/llm.json，走任意 OpenAI 兼容接口；
    ③ 离线规则兜底：都没配，用平台引擎算出的结构化结论直接生成回答与规划书，
       每句话都来自数据库真实查询，不编一个数字。

上下文注入式 RAG：学生提问时，先把平台算好的结构化结论打包成 ≤1200 字的
「学生档案上下文块」（已会技能、目标岗位族、命中率、差距 Top5、关联课程、数据口径），
随问题一起发给智能体——智能体不用检索就能"认识"这个学生，回答不跑偏、不幻觉。

配置方法：
    Dify 本地化：docs/参赛材料/职航罗盘四人演示分工与操作手册_v2.md 第 6 章，或
                 把 config/dify.json.example 复制为 config/dify.json，填 base_url / api_key；
    Coze 在线：  把 config/coze.json.example 复制为 config/coze.json，填 token / bot_id / workflow_id。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "coze.json"
DIFY_CFG = ROOT / "config" / "dify.json"

COZE_BASE = "https://api.coze.cn"

SYSTEM_PROMPT = (
    "你是「职航罗盘」的 AI 职业顾问，服务对象是高职在校生（人工智能应用技术等专业）。"
    "平台会随每条消息附带一份【学生档案】上下文块，里面的数字来自真实采集的招聘数据，"
    "你必须以这些数字为准，不要编造统计数字。回答要求："
    "①语气像学长，鼓励但不灌鸡汤；②每次回答落到具体动作（学哪门课、做哪个作品、考哪个证书）；"
    "③学生问市场结论时引用档案里的命中率、差距技能；④不确定的事直说不确定；"
    "⑤数据有采集时间窗，提醒结论是近期的市场快照。"
)


def load_cfg() -> dict | None:
    """读取 Coze 配置；没配置或字段不全返回 None。"""
    if not CFG.exists():
        return None
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        if cfg.get("token") and cfg.get("bot_id"):
            return cfg
    except Exception:
        pass
    return None


def available() -> bool:
    return load_cfg() is not None


def load_dify_cfg() -> dict | None:
    """读取本地化 Dify 配置；没配置或字段不全返回 None（不影响原有链路）。"""
    if not DIFY_CFG.exists():
        return None
    try:
        cfg = json.loads(DIFY_CFG.read_text(encoding="utf-8"))
        if cfg.get("base_url") and cfg.get("api_key"):
            return cfg
    except Exception:
        pass
    return None


def dify_available() -> bool:
    return load_dify_cfg() is not None


def fallback_available() -> bool:
    """二级兜底：OpenAI 兼容接口是否可用。"""
    from core import llm
    return llm.available()


def engine_name() -> str:
    """当前对话走哪条通道，页面上如实显示。"""
    if dify_available():
        return "Dify 本地化引擎"
    if available():
        return "Coze 在线引擎"
    if fallback_available():
        return "OpenAI 兼容接口"
    return "离线规则引擎"


# ================================================================ 上下文注入式 RAG
def pack_context(have: list[str], family: str, lp: dict | None,
                 cov: dict | None, ov: dict | None, student: str = "") -> str:
    """把平台引擎的结构化结论打包成 ≤1200 字的学生档案上下文块。

    lp  = pathway.build_path 的结果；cov = analyze.coverage 的结果；ov = analyze.overview。
    每个数字都来自数据库真实查询，Coze 只负责"翻译"，不负责"发明"。
    """
    L = ["【学生档案】"]
    if student:
        L.append(f"学生：{student}")
    L.append(f"专业：{lp.get('major', '') if lp else ''}　目标岗位族：{family}")
    if have:
        L.append(f"已掌握技能：{'、'.join(have[:15])}")
    else:
        L.append("已掌握技能：尚未勾选")
    if lp and lp.get("ok"):
        L.append(f"岗位需求命中率：{lp['match']:.0%}（目标 {family}，{lp['n_family']} 条岗位样本）")
        gap = lp["gap"].head(5)
        if len(gap):
            L.append("差距最大 5 项（按岗位要求次数）：")
            for r in gap.itertuples():
                L.append(f"  · {r.技能}：{r.岗位数} 条岗位要求，课程覆盖 {r.课程覆盖:.0%}，"
                         f"关联课程：{r.相关课程}")
    if cov and cov.get("ok"):
        L.append(f"本专业课程覆盖率 {cov['coverage']:.0%}（{cov.get('n_courses', 0)} 门课、"
                 f"{cov.get('n_links', 0)} 条课程—技能映射），红色缺口 {cov['red']} 项、橙色 {cov['orange']} 项")
    if ov:
        L.append(f"数据口径：{ov.get('n', 0)} 条公开岗位、{ov.get('cities', 0)} 个城市、"
                 f"月薪中位数 ¥{ov.get('median', 0):,.0f}（智联公开搜索页采集）")
    L.append("以上数字来自平台引擎的真实计算，回答时直接引用，不要修改或重新估计。")
    text = "\n".join(L)
    return text[:1200]


# ================================================================ Coze Chat API（SSE 流式）
def chat(message: str, context: str = "", history: list[dict] | None = None,
         on_delta=None, timeout: int = 60, lp: dict | None = None) -> dict:
    """对话入口，按三级降级自动选通道。

    on_delta: 回调函数，收到一段流式文本就调一次（页面打字机效果用）。
    lp: 平台引擎算好的学习路径结果，离线兜底回答时直接引用，不让学生白问一遍。
    返回 {"ok": bool, "text": str, "engine": str}。
    """
    last_err = ""
    # ⓿ 本地化 Dify：校内私有化部署，数据不出校园网
    dcfg = load_dify_cfg()
    if dcfg:
        r0 = _dify_chat(dcfg, message, context, history, on_delta, timeout)
        if r0.get("ok"):
            return r0
        last_err = r0.get("msg", "")
    cfg = load_cfg()
    if cfg:
        r = _coze_chat(cfg, message, context, history, on_delta, timeout)
        if r.get("ok"):
            return r
        last_err += "；" + r.get("msg", "")
    else:
        last_err += "；未配置 Coze"
    # 二级兜底：OpenAI 兼容接口
    if fallback_available():
        r2 = _compat_chat(message, context, history, on_delta, timeout)
        if r2.get("ok"):
            return r2
        last_err += "；" + r2.get("msg", "")
    # 三级兜底：离线规则
    return {"ok": True, "engine": "离线规则引擎",
            "text": offline_answer(message, lp),
            "note": f"在线引擎不可用（{last_err.strip('；')}），已用离线规则回答"}


def _dify_chat(cfg: dict, message: str, context: str, history: list[dict] | None,
               on_delta, timeout: int) -> dict:
    """Dify Chat API（社区版 /chat-messages）。失败返回 ok=False，由上层降级。

    约定：⑥ 屏对应的 Dify 应用是「Chatflow」，开始节点除 sys.query 外不需要额外变量，
    学生档案通过 query 前置的上下文块注入——和 Coze 通道共用同一套 pack_context，
    这样换引擎不会换口径。
    """
    import requests
    base = str(cfg["base_url"]).rstrip("/")
    stream = bool(cfg.get("stream", True)) and on_delta is not None
    body = {
        "inputs": {},
        "query": (context + "\n\n" + message) if context else message,
        "response_mode": "streaming" if stream else "blocking",
        "conversation_id": cfg.get("conversation_id", ""),
        "user": cfg.get("user", "student-0001"),
        "auto_generate_name": False,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}",
               "Content-Type": "application/json"}
    try:
        resp = requests.post(base + "/chat-messages", headers=headers, json=body,
                             stream=stream, timeout=timeout or 90)
        resp.raise_for_status()
        if not stream:
            obj = resp.json()
            text = str(obj.get("answer", "")).strip()
            if not text:
                return {"ok": False, "msg": "Dify 返回了空回答"}
            return {"ok": True, "text": text, "engine": "Dify 本地化引擎"}

        pieces: list[str] = []
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data in ("[DONE]", ""):
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("event") in ("message", "agent_message") and obj.get("answer"):
                pieces.append(obj["answer"])
                if on_delta:
                    on_delta(obj["answer"])
            elif obj.get("event") == "error":
                return {"ok": False, "msg": f"Dify 流式错误：{obj.get('message', '')}"}
        text = "".join(pieces).strip()
        if not text:
            return {"ok": False, "msg": "Dify 返回了空回答"}
        return {"ok": True, "text": text, "engine": "Dify 本地化引擎"}
    except Exception as e:
        return {"ok": False, "msg": f"Dify 调用失败：{type(e).__name__}: {e}"}


def _coze_chat(cfg: dict, message: str, context: str, history: list[dict] | None,
               on_delta, timeout: int) -> dict:
    """Coze Chat API v3，SSE 流式。失败返回 ok=False，由上层降级。"""
    import requests
    msgs = []
    full_context = (context + "\n\n") if context else ""
    for h in (history or [])[-6:]:
        role = "assistant" if h.get("role") == "ai" else "user"
        msgs.append({"role": role, "type": "answer" if role == "assistant" else "question",
                     "content": str(h.get("content", ""))[:800], "content_type": "text"})
    msgs.append({"role": "user", "type": "question",
                 "content": full_context + message, "content_type": "text"})
    body = {
        "bot_id": cfg["bot_id"], "user_id": cfg.get("user_id", "student-0001"),
        "stream": True, "auto_save_history": False, "additional_messages": msgs,
    }
    try:
        resp = requests.post(
            COZE_BASE + "/v3/chat",
            headers={"Authorization": f"Bearer {cfg['token']}",
                     "Content-Type": "application/json"},
            json=body, stream=True, timeout=timeout)
        resp.raise_for_status()
        pieces: list[str] = []
        event = ""
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                event = raw[6:].strip()
                continue
            if not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[done]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if event == "conversation.message.completed":
                if obj.get("type") == "answer":
                    pieces = [obj.get("content", "")]
                    break
            elif obj.get("content"):
                pieces.append(obj["content"])
                if on_delta:
                    on_delta(obj["content"])
        text = "".join(pieces).strip()
        if not text:
            return {"ok": False, "msg": "Coze 返回了空回答"}
        return {"ok": True, "text": text, "engine": "Coze 在线引擎"}
    except Exception as e:
        return {"ok": False, "msg": f"Coze 调用失败：{type(e).__name__}: {e}"}


def _compat_chat(message: str, context: str, history: list[dict] | None,
                 on_delta, timeout: int) -> dict:
    """二级兜底：任意 OpenAI 兼容接口（DeepSeek / 通义 / 本地 /v1 等）。"""
    from core import llm
    cfg = llm.load_cfg()
    import requests
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": context})
    for h in (history or [])[-6:]:
        messages.append({"role": "assistant" if h.get("role") == "ai" else "user",
                         "content": str(h.get("content", ""))[:800]})
    messages.append({"role": "user", "content": message})
    try:
        r = requests.post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={"model": cfg["model"], "temperature": 0.4, "stream": False,
                  "messages": messages}, timeout=timeout)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        if on_delta:
            on_delta(text)
        return {"ok": True, "text": text, "engine": f"OpenAI 兼容接口（{cfg['model']}）"}
    except Exception as e:
        return {"ok": False, "msg": f"兼容接口调用失败：{type(e).__name__}: {e}"}


# ================================================================ 离线规则兜底
def offline_answer(message: str, lp: dict | None = None) -> str:
    """没有在线模型时按规则回答。覆盖学生最常问的四类问题。"""
    m = str(message)
    low = m.lower()
    lines: list[str] = []
    gap = lp.get("gap") if lp and lp.get("ok") else None
    match = lp.get("match") if lp and lp.get("ok") else None
    family = (lp or {}).get("family") or "目标岗位族"
    if any(k in low for k in ("学什么", "补什么", "差什么", "缺口", "差距", "先学")):
        if match is not None:
            lines.append(f"你现在对「{family}」的命中率是 **{match:.0%}**。")
        lines.append("**先补这几项，别平均用力：**")
        if gap is not None and len(gap):
            for i, r in enumerate(gap.head(3).itertuples(), 1):
                cov = f"{r.课程覆盖:.0%}"
                first = str(r.相关课程).split("、")[0]
                if r.课程覆盖 <= 0:
                    lines.append(f"{i}. **{r.技能}**（{r.岗位数} 条岗位要求，课程 0 覆盖）"
                                 f"——不等排课，跟 1+X 证书模块或在线课学，两周交一个练手作品。")
                else:
                    lines.append(f"{i}. **{r.技能}**（{r.岗位数} 条岗位要求，课程覆盖 {cov}）"
                                 f"——去《{first}》这门课把对应章节做扎实。")
        else:
            lines.append("先回「③ 我的定位」勾上已会技能、选好目标岗位族，我就能按数据给出补课顺序。")
    elif any(k in low for k in ("城市", "去哪", "哪里机会", "就业地", "地点")):
        lines.append("城市这块看「① 市场全景」的「机会在哪」：岗位数和月薪中位并排摆着。")
        lines.append("给个判断顺序：**先按你能接受的城市筛岗位数 → 再看这个城市的 Top 技能**。"
                     "同一个技能在不同城市的热度会变，你的补课清单要按目标城市重排一次。")
        if match is not None:
            lines.append(f"你现在这份档案是按全量岗位算的，命中率 {match:.0%}；"
                         "定了城市后重新定位一次，数字会更贴近你的真实竞争环境。")
    elif any(k in low for k in ("证书", "1+x", "考证", "证")):
        lines.append("证书不是越多越好，**只补课程零覆盖的那几项**：")
        if gap is not None and len(gap):
            zero = gap[gap["课程覆盖"] <= 0].head(4)
            if len(zero):
                for r in zero.itertuples():
                    lines.append(f"· {r.技能}：课程 0 覆盖，直接找对应 1+X 职业技能等级证书模块")
            else:
                lines.append("你现在的差距项课程都有覆盖——不用额外考证，把课上项目做深更划算。")
        else:
            lines.append("先在「③ 我的定位」生成路径，我按零覆盖缺口告诉你该考哪个。")
    elif any(k in low for k in ("命中", "定位", "水平", "我会的够不够", "怎么样")):
        if match is not None:
            lines.append(f"按你勾选的技能，目标岗位族的**需求命中率是 {match:.0%}**。")
            lines.append("命中率是「已会技能覆盖的岗位需求占比」。低于 50% 就先补榜单前 3 项，"
                         "高于 70% 可以开始投实习岗，边面试边补。")
        else:
            lines.append("先去「③ 我的定位」勾技能，我才能算出你的命中率。")
    elif any(k in low for k in ("规划", "计划", "路径", "方向")):
        lines.append("一条被数据校准的规划长这样：**市场要什么 → 课程教什么 → 我差什么 → 本周做什么**。")
        lines.append("点「生成职业规划书」，我按你当前档案产出 现状 / 目标 / 差距 / 行动 / 时间表 五节，"
                     "可直接贴进求职简历或成长记录里。")
    elif any(k in low for k in ("课程", "哪门课")):
        if gap is not None and len(gap):
            lines.append("差距技能对应的课程都在「④ 差距路径」的补课清单里，每行挂着本专业课程名：")
            for r in gap.head(4).itertuples():
                lines.append(f"· {r.技能} → {r.相关课程}")
    else:
        lines.append("我是职航罗盘的 AI 顾问，可以帮你回答：**先学什么、命中率够不够、哪门课能补、"
                     "规划怎么写**。也可以直接说「我以后想做数据分析」，我按岗位数据给你拆行动。")
        if gap is not None and len(gap):
            lines.append(f"\n顺带提醒：你当前最该补的是「{gap['技能'].iloc[0]}」"
                         f"（{int(gap['岗位数'].iloc[0])} 条岗位要求）。")
    return "\n".join(lines)


# ================================================================ 规划书工作流
PLAN_PROMPT = (
    "你是职业规划书代笔。根据【学生档案】写一份职业规划书，固定五节，不要写空话：\n"
    "一、现状（用档案里的命中率与已会技能说话）\n"
    "二、目标（结合目标岗位族，写半年内可验证的目标）\n"
    "三、差距（按档案差距列表写，注明每项的课程覆盖与关联课程）\n"
    "四、行动（每项差距给一个本周就能开始的动作）\n"
    "五、时间表（按周排 12 周）\n"
    "全文不超过 900 字，所有数字必须来自档案。"
)


def plan_document(have: list[str], family: str, lp: dict | None, cov: dict | None,
                  ov: dict | None, student: str = "") -> dict:
    """生成职业规划书（五节）。Dify 工作流 → Coze Workflow → OpenAI 兼容 → 离线规则。

    返回 {ok, text, engine}。
    """
    context = pack_context(have, family, lp, cov, ov, student)
    dcfg = load_dify_cfg()
    if dcfg and dcfg.get("workflow_app", True):
        r0 = _dify_workflow(dcfg, context)
        if r0.get("ok"):
            return r0
    cfg = load_cfg()
    wid = (cfg or {}).get("workflow_id")
    if cfg and wid:
        r = _coze_workflow(cfg, wid, context)
        if r.get("ok"):
            return r
    if fallback_available():
        from core import llm
        r2 = llm.chat(PLAN_PROMPT + "\n\n" + context,
                      system="你是职业规划书代笔，只依据给定档案写作，不编数字。")
        if r2.get("ok"):
            return {"ok": True, "text": r2["text"], "engine": "OpenAI 兼容接口"}
    return {"ok": True, "text": offline_plan(have, family, lp, cov, ov, student),
            "engine": "离线规则引擎"}


def _dify_workflow(cfg: dict, context: str) -> dict:
    """Dify 工作流 API（/workflows/run，blocking）。

    约定：工作流开始节点定义字符串变量 student_profile；结束节点输出 text。
    返回结构容错 text / result / output / answer / plan 五个常见键名。
    """
    import requests
    base = str(cfg["base_url"]).rstrip("/")
    body = {"inputs": {"student_profile": context, "question": "按档案生成五节职业规划书"},
            "response_mode": "blocking", "user": cfg.get("user", "student-0001")}
    try:
        r = requests.post(base + "/workflows/run", json=body, timeout=120,
                          headers={"Authorization": f"Bearer {cfg['api_key']}",
                                   "Content-Type": "application/json"})
        r.raise_for_status()
        obj = r.json()
        data = obj.get("data") or {}
        if data.get("status") not in (None, "succeeded"):
            return {"ok": False, "msg": f"Dify 工作流状态 {data.get('status')}"}
        outs = data.get("outputs") or {}
        text = ""
        for k in ("text", "result", "output", "answer", "plan"):
            v = outs.get(k)
            if isinstance(v, str) and v.strip():
                text = v.strip()
                break
        if not text:
            return {"ok": False, "msg": "Dify 工作流没有可用的文本输出"}
        return {"ok": True, "text": text, "engine": "Dify 本地化工作流"}
    except Exception as e:
        return {"ok": False, "msg": f"Dify 工作流调用失败：{type(e).__name__}: {e}"}


def _coze_workflow(cfg: dict, workflow_id: str, context: str) -> dict:
    """Coze Workflow API：一键生成固定五节规划书。"""
    import requests
    try:
        r = requests.post(
            COZE_BASE + "/v1/workflow/run",
            headers={"Authorization": f"Bearer {cfg['token']}",
                     "Content-Type": "application/json"},
            json={"workflow_id": workflow_id,
                  "parameters": {"student_profile": context}},
            timeout=90)
        r.raise_for_status()
        obj = r.json()
        # Coze 工作流返回 data 字段是输出 JSON 字符串，兼容直接文本输出
        text = ""
        if isinstance(obj.get("data"), str) and obj["data"].strip():
            try:
                inner = json.loads(obj["data"])
                text = inner.get("output") or inner.get("text") or obj["data"]
            except json.JSONDecodeError:
                text = obj["data"]
        elif obj.get("content"):
            text = obj["content"]
        text = (text or "").strip()
        if not text:
            return {"ok": False, "msg": "Coze 工作流返回为空"}
        return {"ok": True, "text": text, "engine": "Coze 规划书工作流"}
    except Exception as e:
        return {"ok": False, "msg": f"Coze 工作流调用失败：{type(e).__name__}: {e}"}


def offline_plan(have: list[str], family: str, lp: dict | None, cov: dict | None,
                 ov: dict | None, student: str = "") -> str:
    """离线规则版规划书：五节结构，全部由平台引擎的真实结果拼装，不依赖任何在线模型。"""
    major = lp.get("major", "") if lp else ""
    match = f"{lp['match']:.0%}" if lp and lp.get("ok") else "—"
    gap = lp["gap"] if lp and lp.get("ok") else None
    L = [f"# 个人职业规划书（{student or '同学'} · {major} · 目标：{family}）\n",
         f"> 生成时间 {datetime.now():%Y-%m-%d}\n"]
    L.append("## 一、现状")
    if ov:
        L.append(f"市场样本：{ov.get('n', 0)} 条公开岗位、{ov.get('cities', 0)} 个城市，"
                 f"月薪中位数 ¥{ov.get('median', 0):,.0f}。")
    held = "、".join(have[:12]) if have else "（尚未登记）"
    L.append(f"已掌握技能：{held}。目标岗位族「{family}」的需求命中率 **{match}**。")
    if cov and cov.get("ok"):
        L.append(f"本专业 {cov.get('n_courses', 0)} 门课程对市场技能的加权覆盖率 {cov['coverage']:.0%}。")
    L.append("")
    L.append("## 二、目标（半年）")
    if lp and lp.get("ok"):
        L.append(f"把「{family}」岗位需求命中率从 {match} 提到 70% 以上；"
                 f"补齐差距 Top5 中的至少 3 项，并完成 1 个可写进简历的作品项目。")
    else:
        L.append(f"围绕「{family}」岗位族建立技能清单，完成首次定位。")
    L.append("")
    L.append("## 三、差距")
    if gap is not None and len(gap):
        L.append("| 优先级 | 技能 | 岗位要求 | 课程覆盖 | 关联课程 |")
        L.append("|---|---|---|---|---|")
        for r in gap.head(6).itertuples():
            L.append(f"| {int(r.优先级)} | {r.技能} | {int(r.岗位数)} 条 | "
                     f"{r.课程覆盖:.0%} | {r.相关课程} |")
    else:
        L.append("先生成学习路径后自动填入。")
    L.append("")
    L.append("## 四、行动（本周就能开始）")
    if gap is not None and len(gap):
        for i, r in enumerate(gap.head(3).itertuples(), 1):
            first_course = str(r.相关课程).split("、")[0]
            if r.课程覆盖 <= 0:
                act = (f"{r.技能} 课程零覆盖——不等排课，跟 1+X 证书对应模块或在线课程学，"
                       "两周内交出一个练手作品")
            else:
                act = f"在《{first_course}》里定位 {r.技能} 对应章节，把课程作业做到工程可用级别"
            L.append(f"{i}. {act}。")
    else:
        L.append("1. 完成技能自评，生成首份学习路径。")
    L.append("")
    L.append("## 五、12 周时间表")
    if gap is not None and len(gap):
        g = gap.head(3).reset_index(drop=True)
        L.append("| 周次 | 安排 | 验收标准 |")
        L.append("|---|---|---|")
        L.append(f"| 1-2 周 | 补「{g['技能'].iloc[0]}」 | 能独立完成一个课程级小项目 |")
        if len(g) > 1:
            L.append(f"| 3-6 周 | 补「{g['技能'].iloc[1]}」 | 作品上线 / 作业达到工程可用 |")
        if len(g) > 2:
            L.append(f"| 7-10 周 | 补「{g['技能'].iloc[2]}」 | 融入作品项目 |")
        L.append("| 11-12 周 | 整理作品与简历，对照命中率复测 | 命中率较本档案提升 10 个百分点以上 |")
    else:
        L.append("| 周次 | 安排 |\n|---|---|\n| 1-2 周 | 定位与自评 |")
    return "\n".join(L)
