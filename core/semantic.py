"""语义层：技能新词的向量语义归并。

解决什么问题：平台标签写法五花八门（"大模型应用开发"≈"LLM 应用"≈"AIGC 开发"），
纯字符串匹配认不出来，导致技能需求被低估。这里把"未入典新标签"和"已有技能词典"
都变成向量，按余弦相似度找出最相近的已有技能，给出三级处理建议：
  自动归并（相似度 >= threshold）→ 建议人工（>= suggest）→ 无相近（< suggest）

两级后端，自动选择、结果格式完全一致：
  transformer  装了 sentence-transformers 且能加载中文预训练模型时启用（语义最强）
  tfidf        字符级 n-gram TF-IDF 向量 + 余弦相似度，纯 sklearn、零下载、离线可跑

赛场网络不可用时照样能跑——这是刻意的设计，答辩时可以讲"工程可靠性"。
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from core import skills as SK

# 相似度阈值按后端分别定：transformer 语义向量的分数普遍偏高，
# tfidf 字符 n-gram 对短中文词的余弦分普遍偏低（同义也可能只有 0.4），
# 用同一把尺子会把大量真同义词判成"无相近"。
THRESHOLDS = {
    "transformer": {"auto": 0.72, "suggest": 0.55},
    "tfidf": {"auto": 0.52, "suggest": 0.34},
}
# 相似度达到该值视为"同一技能的不同写法"，可自动归并（transformer 后端默认）
AUTO_THRESHOLD = 0.72
# 相似度达到该值视为"可能相关"，建议人工确认（transformer 后端默认）
SUGGEST_THRESHOLD = 0.55


# ---------------------------------------------------------------- 向量后端
_model = None  # 缓存，避免重复加载


def _try_transformer():
    """尝试加载预训练中文向量模型；装不上/加载不了就返回 None。"""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    except Exception:
        _model = False  # False 表示"试过了，没有"
    return _model


def _clean(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def _tfidf_matrix(texts: list[str]) -> np.ndarray:
    """字符级 n-gram TF-IDF。对中文短文本（技能名 2~10 字）效果稳定。"""
    from sklearn.feature_extraction.text import TfidfVectorizer
    corpus = [_clean(t) for t in texts]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3))
    m = vec.fit_transform(corpus).toarray()
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return m / norms


def embed(texts: list[str]) -> tuple[np.ndarray, str]:
    """把一批短文本变成归一化向量。返回 (矩阵, 后端名)。"""
    model = _try_transformer()
    if model:
        m = model.encode([_clean(t) for t in texts], normalize_embeddings=True)
        return np.asarray(m, dtype=float), "transformer"
    return _tfidf_matrix(texts), "tfidf"


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a @ b.T


# ---------------------------------------------------------------- 归并主入口
def merge_unknown(threshold: float | None = None,
                  suggest: float | None = None,
                  limit: int = 30) -> dict:
    """未入典新标签 → 最相近的已有技能。

    threshold/suggest 不传时按向量后端自动取默认值（见 THRESHOLDS）。
    返回 {ok, backend, table, auto_n, suggest_n, none_n, brief}
    table 列：tag 出现次数 | match_skill 相近技能 | sim 相似度 | action 处理建议
    """
    unk = SK.unknown_tags(min_n=1, limit=int(limit))
    if unk.empty:
        return {"ok": True, "backend": "-", "table": pd.DataFrame(),
                "auto_n": 0, "suggest_n": 0, "none_n": 0, "brief": "没有待归并的新标签"}
    known_df = SK.load_dict()
    known = [s for s in known_df["canonical"].dropna().unique().tolist() if str(s).strip()]
    if not known:
        return {"ok": False, "msg": "技能词典为空，先在「技能标注」页初始化"}

    tags = unk["tag"].astype(str).tolist()
    texts = tags + known
    mat, backend = embed(texts)
    th = THRESHOLDS.get(backend, {"auto": AUTO_THRESHOLD, "suggest": SUGGEST_THRESHOLD})
    threshold = float(threshold) if threshold is not None else th["auto"]
    suggest = float(suggest) if suggest is not None else th["suggest"]
    sim = cosine(mat[:len(tags)], mat[len(tags):])
    best_idx = sim.argmax(axis=1)
    best_sim = sim.max(axis=1)

    rows = []
    for i, tag in enumerate(tags):
        s = float(best_sim[i])
        action = ("自动归并" if s >= threshold
                  else "建议人工" if s >= suggest else "无相近技能")
        rows.append({"tag": tag, "出现次数": int(unk["n"].iloc[i]),
                     "match_skill": known[int(best_idx[i])],
                     "sim": round(s, 3), "action": action})
    table = pd.DataFrame(rows).sort_values("sim", ascending=False).reset_index(drop=True)
    auto_n = int((table["action"] == "自动归并").sum())
    sug_n = int((table["action"] == "建议人工").sum())
    none_n = int((table["action"] == "无相近技能").sum())
    brief = (f"向量后端 {backend}：自动归并 {auto_n} 个、建议人工 {sug_n} 个、"
             f"无相近 {none_n} 个")
    return {"ok": True, "backend": backend, "table": table, "threshold": threshold,
            "auto_n": auto_n, "suggest_n": sug_n, "none_n": none_n, "brief": brief}


def apply_merge(mapping: dict[str, str]) -> int:
    """把 {新词: 归并目标} 写进词典映射，下次抽取即生效。返回写入条数。

    实现方式：往 data/dict/skill_alias.csv 追加别名记录（skill_dict.csv 本体不动，
    保持人工维护的词典干净，机器建议走别名表，可随时删除回退）。
    """
    if not mapping:
        return 0
    path = SK.ROOT / "data" / "dict" / "skill_alias.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(path, encoding="utf-8-sig") if path.exists() else pd.DataFrame()
    new = pd.DataFrame([{"alias": k, "skill": v} for k, v in mapping.items()])
    allm = pd.concat([old, new]).drop_duplicates(subset=["alias"], keep="last")
    allm.to_csv(path, index=False, encoding="utf-8-sig")
    return len(new)
