"""可选的大模型对照通道（OpenAI 兼容接口）。

设计原则：
- 「可插拔」：config/llm.json 不存在或没填 key 时，所有函数返回 {"ok": False, "msg": ...}，
  上层节点显示"跳过"，主流程照走规则通道——赛场断网/没配 key 都不炸；
- 「只对照，不兜底」：LLM 的输出只用于和规则抽取结果做对照展示，不直接写库，
  避免大模型幻觉污染词典。每个结果都标注"来自大模型，建议人工确认"。

配置方法：把 config/llm.json.example 复制为 config/llm.json，填上 base_url / api_key / model。
任何 OpenAI 兼容服务都可以（DeepSeek、通义、本地 Ollama 的 /v1 等）。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "llm.json"


def load_cfg() -> dict | None:
    """读取 LLM 配置；没有配置返回 None。"""
    if not CFG.exists():
        return None
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        if cfg.get("api_key") and cfg.get("base_url") and cfg.get("model"):
            return cfg
    except Exception:
        pass
    return None


def available() -> bool:
    return load_cfg() is not None


def chat(prompt: str, system: str = "你是一个严谨的数据标注助手，只输出 JSON。", timeout: int = 30) -> dict:
    """调用 OpenAI 兼容接口。未配置时返回 ok=False，不抛异常。"""
    cfg = load_cfg()
    if not cfg:
        return {"ok": False, "msg": "未配置大模型（缺 config/llm.json），本节点跳过，规则通道兜底"}
    import requests
    try:
        r = requests.post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={"model": cfg["model"], "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}]},
            timeout=timeout)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return {"ok": True, "text": content}
    except Exception as e:
        return {"ok": False, "msg": f"大模型调用失败：{type(e).__name__}: {e}（规则通道兜底，不受影响）"}


def map_terms(tags: list[str], known_skills: list[str]) -> dict:
    """让大模型把新标签映射到词典技能，返回 {tag: skill or ""}。

    输出只是"建议"，是否采纳由人在页面上决定——大模型不给写库权限。
    """
    prompt = (
        "下面是招聘平台出现的技能标签，以及我们的标准技能词典。"
        "请把每个标签映射到词典里最相近的一个标准技能；"
        "词典里确实没有对应的，映射为空字符串。只输出 JSON 对象，键为原标签。\n\n"
        f"标签列表：{json.dumps(tags, ensure_ascii=False)}\n\n"
        f"标准技能词典：{json.dumps(known_skills, ensure_ascii=False)}"
    )
    r = chat(prompt)
    if not r["ok"]:
        return r
    try:
        text = r["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        mapping = json.loads(text)
        bad = [k for k in tags if k not in mapping]
        if bad:
            return {"ok": False, "msg": f"大模型返回缺少 {len(bad)} 个标签，结果不可信，已丢弃"}
        return {"ok": True, "mapping": {k: str(v) for k, v in mapping.items()},
                "model": load_cfg()["model"]}
    except Exception as e:
        return {"ok": False, "msg": f"大模型返回解析失败：{e}"}
