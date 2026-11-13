# -*- coding: utf-8 -*-
"""数字人语音。

两级通道，都失败才静默（字幕照常，面试流程一步不少）：
1. edge-tts —— 在线合成，音质好（微软神经网络音色）；断网/被墙自动失败；
2. Windows SAPI —— 本机离线合成（Huihui 中文音色），零网络依赖，路演现场最稳。

同一句话只合成一次，结果缓存到 data/tts/，第二次直接读文件。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_DIR = ROOT / "data" / "tts"

# 每个面试官人设一个音色（仅 edge-tts 用；SAPI 只有本机装了的音色）
VOICE_OF = {
    "温和型 HR": "zh-CN-XiaoxiaoNeural",
    "技术主管": "zh-CN-YunxiNeural",
}
DEFAULT_VOICE = "zh-CN-YunxiNeural"

# 引擎标记，页面可以显示"声音来自哪条通道"
LAST_ENGINE = ""

# 本进程里 edge-tts 失败过一次就不再试（避免每句话都等一次网络超时）
_EDGE_DEAD = False
_EDGE_TIMEOUT = 8.0  # 秒；超时就当断网，立刻走离线


def clean_text(text: str) -> str:
    """去掉 Markdown 记号和特殊符号，念出来更像人话。"""
    t = str(text or "")
    t = t.translate(str.maketrans({"<": "《", ">": "》", "&": "和", '"': "", "'": ""}))
    t = re.sub(r"[*#`_|]{1,}", "", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)  # 链接只念文字
    return t.strip()[:300]  # 太长念不完，截断


def _cache_path(text: str, voice: str, ext: str) -> Path:
    h = hashlib.md5(f"{voice}::{text}".encode("utf-8")).hexdigest()
    return TTS_DIR / f"{h}.{ext}"


# ---------------------------------------------------------------- edge-tts
def _edge(text: str, voice: str, out: Path) -> bool:
    global _EDGE_DEAD
    if _EDGE_DEAD:
        return False
    mark = TTS_DIR / ".edge_dead"
    if mark.exists():  # 上次运行就失败了，直接跳过（每 24h 重探一次）
        if time.time() - mark.stat().st_mtime < 86400:
            _EDGE_DEAD = True
            return False
        try:
            mark.unlink()
        except Exception:
            pass
    try:
        import asyncio

        import edge_tts

        async def _run() -> None:
            com = edge_tts.Communicate(text, voice)
            await com.save(str(out))

        asyncio.run(asyncio.wait_for(_run(), timeout=_EDGE_TIMEOUT))
        if out.exists() and out.stat().st_size > 1024:
            return True
    except Exception:
        pass
    _EDGE_DEAD = True  # 这台机器/这个网络用不了在线合成，后面直接走离线
    try:
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        mark.write_text("", encoding="utf-8")
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- SAPI 离线
def _sapi_pick(s, want_zh: bool):
    try:
        n = s.GetVoices().Count
        fallback = None
        for i in range(n):
            v = s.GetVoices().Item(i)
            d = v.GetDescription() or ""
            if fallback is None:
                fallback = v
            if want_zh and ("Chinese" in d or "Huihui" in d or "中文" in d):
                return v
            if not want_zh and "English" in d:
                return v
        return fallback
    except Exception:
        return None


def _sapi(text: str, want_zh: bool, out: Path) -> bool:
    try:
        import pythoncom
        pythoncom.CoInitialize()  # Streamlit 每次脚本运行可能在不同线程，必须先初始化 COM
        from win32com.client import dynamic  # 晚绑定：不依赖 win32com 生成缓存（缓存坏了照样能用）

        s = dynamic.Dispatch("SAPI.SpVoice")
        v = _sapi_pick(s, want_zh)
        if v is not None:
            s.Voice = v
        s.Rate = 1  # 稍快一点，更像正常说话
        fmt = dynamic.Dispatch("SAPI.SpFileStream")
        try:
            fmt.Format.Type = 34  # SAFT22kHz16BitMono，体积和质量折中
        except Exception:
            pass                  # 晚绑定下个别系统不给设 Format，用默认格式也能出声
        fmt.Open(str(out), 3)     # SSFMCreateForWrite
        s.AudioOutputStream = fmt
        s.Speak(text)
        fmt.Close()
        return out.exists() and out.stat().st_size > 2048
    except Exception:
        return False
    finally:
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ---------------------------------------------------------------- 对外入口
def speak(text: str, voice: str | None = None, timeout: float = 15.0) -> str | None:
    """合成并返回本地音频文件路径；失败返回 None（调用方静默降级）。"""
    global LAST_ENGINE
    t = clean_text(text)
    if not t:
        return None
    v = voice or DEFAULT_VOICE
    want_zh = v.startswith("zh")
    TTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 在线 edge-tts（有缓存先回缓存）
    p_mp3 = _cache_path(t, v, "mp3")
    if p_mp3.exists() and p_mp3.stat().st_size > 1024:
        LAST_ENGINE = "在线音色"
        return str(p_mp3)
    if _edge(t, v, p_mp3):
        LAST_ENGINE = "在线音色"
        return str(p_mp3)
    try:
        p_mp3.unlink(missing_ok=True)
    except Exception:
        pass

    # 2) Windows 离线 SAPI
    p_wav = _cache_path(t, "sapi", "wav")
    if p_wav.exists() and p_wav.stat().st_size > 2048:
        LAST_ENGINE = "离线音色"
        return str(p_wav)
    if _sapi(t, want_zh, p_wav):
        LAST_ENGINE = "离线音色"
        return str(p_wav)
    try:
        p_wav.unlink(missing_ok=True)
    except Exception:
        pass

    LAST_ENGINE = ""
    return None


def voice_of(persona: str) -> str:
    return VOICE_OF.get(persona, DEFAULT_VOICE)


def available() -> bool:
    """本机是否至少有一条可用通道（edge-tts 可导入 或 pywin32 可导入）。"""
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        pass
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False
