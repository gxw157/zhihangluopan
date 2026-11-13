# -*- coding: utf-8 -*-
"""学生语音作答 → 文字（ASR）。

三级通道，按可用性自动选：
1. 本地 FunASR Paraformer（阿里，模型走 ModelScope 国内源，中文准确率最高）；
2. Windows 系统听写（SAPI，零依赖，准确率一般，仅兜底）；
3. 都不可用 → 返回 ok=False，页面提示改用键盘输入。

所有通道都离线运行，不依赖任何境外服务。
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "data" / "asr"
TMP.mkdir(parents=True, exist_ok=True)

_MODEL = None          # 懒加载的 FunASR 模型
_MODEL_FAILED = False  # 本进程判定为加载失败，不再重试

# 识别结果里常见的技术词写法归一（长词优先，避免 sql 抢先吃掉 mysql）
_TERMS = [
    ("javascript", "JavaScript"), ("power bi", "Power BI"), ("mysql", "MySQL"),
    ("python", "Python"), ("pandas", "Pandas"), ("numpy", "NumPy"),
    ("excel", "Excel"), ("sequal", "SQL"), ("sql", "SQL"), ("linux", "Linux"),
    ("java", "Java"), ("html", "HTML"), ("css", "CSS"), ("ppt", "PPT"),
    ("word", "Word"), ("git", "Git"), ("bi", "BI"), ("ai", "AI"),
]


def tidy(text: str) -> str:
    """清洗识别结果：去掉汉字之间的空格、规整技术词大小写。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    for k, v in _TERMS:
        t = re.sub(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", v, t, flags=re.I)
    t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", t)  # 汉字间空格
    t = re.sub(r"\s*([，。！？、；：])\s*", r"\1", t)
    return t.strip()


# ---------------------------------------------------------------- 音频规整
def to_wav16k(data: bytes | str | Path) -> str | None:
    """把任意 wav 字节/路径转成 16k 单声道 wav，返回临时文件路径。"""
    try:
        if isinstance(data, (str, Path)):
            src, tmp_in = str(data), None
        else:
            fd, tmp_in = tempfile.mkstemp(suffix=".wav", dir=TMP)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            src = tmp_in
        with wave.open(src, "rb") as w:
            nch, sw, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.readframes(w.getnframes())
        if sw != 2:
            return None
        pcm = np.frombuffer(frames, dtype=np.int16)
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1).astype(np.int16)
        if sr != 16000 and len(pcm):
            n = int(round(len(pcm) * 16000 / sr))
            pcm = np.interp(np.linspace(0, len(pcm) - 1, n),
                            np.arange(len(pcm)), pcm).astype(np.int16)
        out = TMP / f"in16k_{int(time.time() * 1000)}.wav"
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        if tmp_in:
            try:
                os.unlink(tmp_in)
            except Exception:
                pass
        return str(out)
    except Exception:
        return None


# ---------------------------------------------------------------- 通道 1：Paraformer
def _load_model():
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None or _MODEL_FAILED:
        return _MODEL
    try:
        from funasr import AutoModel

        _MODEL = AutoModel(model="paraformer-zh", disable_update=True, device="cpu")
    except Exception:
        _MODEL_FAILED = True
        _MODEL = None
    return _MODEL


def _paraformer(path: str) -> str:
    m = _load_model()
    if m is None:
        return ""
    try:
        r = m.generate(input=path, batch_size_s=60)
        if not r:
            return ""
        return tidy(str(r[0].get("text") or ""))
    except Exception:
        return ""


# ---------------------------------------------------------------- 通道 2：系统听写
def _sapi(path: str, timeout: float = 30.0) -> str:
    try:
        import pythoncom
        import win32com.client
        from win32com.client import DispatchWithEvents

        pythoncom.CoInitialize()  # 脚本线程里必须先初始化 COM

        got: list[str] = []

        class Ev:
            def OnRecognition(self, StreamNumber, StreamPosition, RecognitionType, Result):
                try:
                    r = win32com.client.CastTo(Result, "ISpeechRecoResult")
                    t = r.PhraseInfo.GetText()
                    if t:
                        got.append(t)
                except Exception:
                    pass

            def OnEndStream(self, *a):
                got.append("__END__")

        rec = win32com.client.Dispatch("SAPI.SpInProcRecognizer")
        engines = rec.GetRecognizers()
        for i in range(engines.Count):
            d = engines.Item(i).GetDescription() or ""
            if "Chinese" in d or "简体" in d or "中文" in d:
                rec.Recognizer = engines.Item(i)
                break
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Format.Type = 39  # 16kHz 16bit mono
        stream.Open(path, 0)
        rec.AudioInputStream = stream
        ctx = DispatchWithEvents(rec.CreateRecoContext(), Ev)
        g = ctx.CreateGrammar()
        g.DictationSetState(1)
        ctx.State = 1
        t0 = time.time()
        while time.time() - t0 < timeout and "__END__" not in got:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.03)
        return tidy("".join(x for x in got if x != "__END__"))
    except Exception:
        return ""
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ---------------------------------------------------------------- 对外入口
def transcribe(data: bytes | str | Path) -> dict:
    """返回 {ok, text, engine, ms}。ok=False 时页面应回退到键盘输入。"""
    t0 = time.time()
    path = to_wav16k(data)
    if not path:
        return {"ok": False, "text": "", "engine": "", "ms": 0, "err": "音频格式读不出来"}
    try:
        txt = _paraformer(path)
        if txt:
            return {"ok": True, "text": txt, "engine": "本地语音识别",
                    "ms": int((time.time() - t0) * 1000)}
        txt = _sapi(path, timeout=max(15.0, 30.0))
        if txt:
            return {"ok": True, "text": txt, "engine": "系统听写",
                    "ms": int((time.time() - t0) * 1000)}
        return {"ok": False, "text": "", "engine": "",
                "ms": int((time.time() - t0) * 1000), "err": "没听清，再说一遍或直接打字"}
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def warmup() -> None:
    """后台先把模型加载进内存，学生真开口时不用等（进了面试板块就调一次）。"""
    try:
        import threading
        if _MODEL is None and not _MODEL_FAILED:
            threading.Thread(target=_load_model, daemon=True).start()
    except Exception:
        pass


def engine_ready() -> tuple[bool, str]:
    """页面显示用：本机哪种识别通道可用。"""
    try:
        import funasr  # noqa: F401
        return True, "本地语音识别（Paraformer）"
    except Exception:
        pass
    try:
        import win32com.client  # noqa: F401
        return True, "系统听写（准确率一般）"
    except Exception:
        return False, "本机暂无语音识别，请用键盘作答"
