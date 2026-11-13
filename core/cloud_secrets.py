r"""Streamlit Community Cloud（免费云端版）配置自举。

云端容器是"一次性"的：真实密钥文件（config/coze.json / llm.json / dify.json /
sms.json）不能提交进 Git（会泄露），所以改为把密钥填进 Streamlit 后台的
Secrets（dashboard → App → Settings → Secrets，TOML 格式），形如：

    [coze]
    token = "pat_xxx"
    bot_id = "123456"

    [llm]
    base_url = "https://api.deepseek.com/v1"
    api_key = "sk-xxx"
    model = "deepseek-chat"

    [sms]
    provider = "aliyun"
    enabled = true
    [sms.aliyun]
    access_key_id = "LTAIxxx"
    access_key_secret = "xxx"
    sign_name = "职航罗盘"
    template_code = "SMS_xxx"

    [dify]
    base_url = "https://xxx/v1"
    api_key = "app-xxx"

本模块在应用启动时把 st.secrets 里有内容的段自动写成 config/<段名>.json；
文件已存在则本地优先、不覆盖。core/coze.py、core/llm.py、core/sms.py
的读取逻辑一行都不用改。

本机运行完全不受影响：无 secrets.toml / 无对应段 / 任何异常 → 直接返回。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SECTIONS = ("coze", "llm", "dify", "sms")


def sync_cloud_secrets() -> None:
    """把 st.secrets 的 [coze]/[llm]/[dify]/[sms] 段落落到 config/*.json（不覆盖已有）。"""
    try:
        import streamlit as st

        data_all = st.secrets.to_dict()          # 无 secrets 配置时这里会抛异常 → 直接返回
    except Exception:
        return
    for name in _SECTIONS:
        try:
            data = data_all.get(name)
            if not isinstance(data, dict) or not data:
                continue
            cfg = ROOT / "config" / f"{name}.json"
            if cfg.exists():                     # 本地/手工配置优先，避免重启时覆盖
                continue
            cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        except Exception:
            continue
