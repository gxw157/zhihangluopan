"""专业目录：一套分析口径，多个专业各取所需。

课程数据（courses.csv / course_skill_map.csv）按 major_code 分专业存放，
页面选专业 → coverage / pathway / 智能体报告全部按该专业的课程口径计算。
新增专业：改 tools/build_major_courses.py 后重跑，或在 majors.json + 两个 CSV 里按同样字段追加。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAJOR_JSON = ROOT / "data" / "dict" / "majors.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    if not MAJOR_JSON.exists():
        return {"default": "", "majors": [], "source": "《职业教育专业教学标准》"}
    return json.loads(MAJOR_JSON.read_text(encoding="utf-8"))


def all_majors() -> list[dict]:
    return list(_data().get("majors", []))


def families_of(key: str | None = None) -> list[str]:
    """本专业对应的岗位族（analyze.FAMILY_RULES 的名字），用于"专业相关"覆盖率口径。"""
    return [str(x) for x in (get(key).get("families") or [])]


def names() -> list[str]:
    return [m["name"] for m in all_majors()]


# 专业大类顺序：按教育部专业目录的大类编号排，下拉里同大类的专业挨在一起
_CATEGORY_ORDER = [
    "农林牧渔大类", "资源环境与安全大类", "能源动力与材料大类", "土木建筑大类",
    "水利大类", "装备制造大类", "生物与化工大类", "轻工纺织大类", "食品药品与粮食大类",
    "交通运输大类", "电子与信息大类", "医药卫生大类", "财经商贸大类", "旅游大类",
    "文化艺术大类", "新闻传播大类", "教育与体育大类", "公安与司法大类",
    "公共管理与服务大类",
]


def names_by_category() -> list[str]:
    """按专业大类排序的专业名（下拉用）：同大类的专业连在一起，找起来快。"""
    def _key(m: dict) -> tuple:
        cat = str(m.get("category") or "")
        try:
            i = _CATEGORY_ORDER.index(cat)
        except ValueError:
            i = 99
        return (i, str(m.get("code") or ""))
    return [m["name"] for m in sorted(all_majors(), key=_key)]


def categories() -> dict[str, list[str]]:
    """大类 → 专业名列表（按大类顺序），给下拉做分组提示用。"""
    out: dict[str, list[str]] = {}
    for name in names_by_category():
        m = get(name)
        out.setdefault(str(m.get("category") or "其他"), []).append(name)
    return out


def get(key: str | None = None) -> dict:
    """按专业名或专业代码取专业；空值取默认专业，找不到时回退第一个。"""
    ms = all_majors()
    if not ms:
        return {"code": "", "name": "未配置专业", "category": "", "jobs": "",
                "courses": 0, "base": 0, "core": 0, "ext": 0}
    if not key:
        key = _data().get("default") or ms[0]["code"]
    key = str(key).strip()
    for m in ms:
        if key in (str(m["code"]), m["name"]):
            return m
    for m in ms:
        if key in m["name"] or m["name"] in key:
            return m
    return ms[0]


def code_of(key: str | None = None) -> str:
    return str(get(key)["code"])


def name_of(key: str | None = None) -> str:
    return get(key)["name"]


def default_name() -> str:
    return get(None)["name"]


def source() -> str:
    return _data().get("source", "《职业教育专业教学标准》")


def refresh() -> None:
    _data.cache_clear()
