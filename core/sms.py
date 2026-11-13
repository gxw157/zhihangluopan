"""短信网关：一条 `send()` 打通阿里云 / 腾讯云 / 通用 webhook，配好即自动真发。

设计原则
--------
- **只走真发**：`status()` 判定配置是否齐全 —— 齐全走真实短信；没配好就不发，
  发送按钮返回失败提示，引导去「⑧ 工程后台 → 账号与登录」配置网关。
- **不装 SDK**：阿里云 RPC 签名（HMAC-SHA1）与腾讯云 TC3 签名（HMAC-SHA256）都用
  标准库实现，少两个大依赖，离线环境照样能跑。
- **一处配置**：`config/sms.json`，页面「⑧ 工程后台 → 账号与登录」有可视化配置 + 测试发送。

配置格式（provider 决定用哪家）
-------------------------------
{
  "provider": "aliyun",                       // aliyun | tencent | mob | webhook
  "enabled": true,
  "aliyun":  {"access_key_id": "", "access_key_secret": "",
              "sign_name": "职航罗盘", "template_code": "SMS_123456789",
              "template_param": "code", "region": "cn-hangzhou"},
  "tencent": {"secret_id": "", "secret_key": "", "sdk_app_id": "1400000000",
              "sign_name": "职航罗盘", "template_id": "1234567", "region": "ap-guangzhou"},
  "mob":     {"appkey": "", "appsecret": "", "zone": "86"},
  "webhook": {"url": "", "token": "", "template": "career_compass", "sign": "职航罗盘"}
}

Mob 是特例：验证码由 Mob 生成，平台拿不到明文，所以 `send()` 传的 code 被忽略，
校验走 `verify()`（/sms/verify）。其余通道都是「平台生成 → 平台比对」。

兼容旧格式：`{"webhook": "https://...", "token": "..."}` 会被自动识别为 webhook 通道。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "sms.json"

PROVIDERS = {
    "aliyun": "阿里云短信",
    "tencent": "腾讯云短信",
    "mob": "Mob 免费短信（SMSSDK）",
    "webhook": "通用短信网关（HTTP）",
}

FIELDS = {
    "aliyun": [
        ("access_key_id", "AccessKey ID", False),
        ("access_key_secret", "AccessKey Secret", True),
        ("sign_name", "短信签名（如：职航罗盘）", False),
        ("template_code", "模板 CODE（如：SMS_123456789）", False),
        ("template_param", "模板变量名（默认 code，须与模板里 ${code} 一致）", False),
        ("region", "区域（默认 cn-hangzhou）", False),
    ],
    "tencent": [
        ("secret_id", "SecretId", False),
        ("secret_key", "SecretKey", True),
        ("sdk_app_id", "短信应用 SdkAppId（如：1400000000）", False),
        ("sign_name", "短信签名（如：职航罗盘）", False),
        ("template_id", "模板 ID（如：1234567）", False),
        ("region", "区域（默认 ap-guangzhou）", False),
    ],
    "mob": [
        ("appkey", "AppKey", False),
        ("appsecret", "AppSecret（仅服务端使用，勿写进前端）", True),
        ("zone", "区号（默认 86）", False),
    ],
    "webhook": [
        ("url", "网关地址（POST JSON）", False),
        ("token", "Bearer 令牌（可空）", True),
        ("template", "模板标识（如：career_compass）", False),
        ("sign", "签名（如：职航罗盘）", False),
    ],
}

DEFAULTS = {
    "aliyun": {"region": "cn-hangzhou", "template_param": "code"},
    "tencent": {"region": "ap-guangzhou"},
    "mob": {"zone": "86"},
    "webhook": {"template": "career_compass", "sign": "职航罗盘"},
}


# ================================================================ 配置读写
def load_cfg() -> dict:
    """读配置；不存在返回空 dict，旧格式自动升级为新格式。"""
    if not CFG.exists():
        return {}
    try:
        raw = json.loads(CFG.read_text("utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    # 旧格式：{"webhook": "https://...", "token": "..."}
    if "provider" not in raw and isinstance(raw.get("webhook"), str):
        raw = {"provider": "webhook", "enabled": True,
               "webhook": {"url": raw.get("webhook", ""), "token": raw.get("token", ""),
                           "template": raw.get("template", "career_compass"),
                           "sign": raw.get("sign", "职航罗盘")}}
    return raw


def save_cfg(cfg: dict) -> None:
    """原子写盘（WPS/编辑器占用也不会写坏）。"""
    CFG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CFG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, CFG)


def active_provider(cfg: dict | None = None) -> str:
    cfg = load_cfg() if cfg is None else cfg
    p = str(cfg.get("provider") or "").strip()
    if p in PROVIDERS:
        return p
    if isinstance(cfg.get("webhook"), dict) and cfg["webhook"].get("url"):
        return "webhook"
    return ""


def _section(cfg: dict, prov: str) -> dict:
    sec = dict(DEFAULTS.get(prov, {}))
    sec.update(cfg.get(prov) or {})
    return {k: str(v or "").strip() for k, v in sec.items()}


def missing_fields(cfg: dict | None = None) -> list[str]:
    """缺哪些必填项（有默认值或可选的字段不算：region / template / sign / token）。"""
    cfg = load_cfg() if cfg is None else cfg
    prov = active_provider(cfg)
    if not prov:
        return ["provider"]
    sec = _section(cfg, prov)
    optional = {"region", "template", "sign", "token", "template_param"}
    out = []
    for key, label, _secret in FIELDS[prov]:
        if key in optional:
            continue
        if not sec.get(key):
            out.append(label)
    return out


def ready(cfg: dict | None = None) -> bool:
    cfg = load_cfg() if cfg is None else cfg
    return bool(cfg.get("enabled", True)) and active_provider(cfg) != "" and not missing_fields(cfg)


def status(cfg: dict | None = None) -> dict:
    """给页面用：当前通道、是否就绪、缺什么、怎么修。"""
    cfg = load_cfg() if cfg is None else cfg
    prov = active_provider(cfg)
    miss = missing_fields(cfg)
    ok = ready(cfg)
    if not prov:
        tip = "还没有配置短信网关，验证码无法发送。请在工程后台 → 账号与登录配置。"
    elif miss:
        tip = "网关配置不完整，验证码无法发送。还缺：" + "、".join(miss)
    elif not cfg.get("enabled", True):
        tip = "网关已配置但被手动关闭（enabled=false），验证码无法发送。"
    else:
        tip = f"已接入{PROVIDERS[prov]}，验证码会真实发送到手机。"
    return {"ready": ok, "provider": prov,
            "provider_label": PROVIDERS.get(prov, "未配置"),
            "missing": miss, "enabled": bool(cfg.get("enabled", True)),
            "mode": "真实短信" if ok else "未配置", "tip": tip}


def channel_name() -> str:
    return status()["mode"]


# ================================================================ 发送
def _http(req: urllib.request.Request, timeout: int = 10) -> tuple[int, str]:
    """绕开系统代理直连（国内短信 API 走代理反而容易失败）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return int(getattr(r, "status", 200)), r.read().decode("utf-8", "replace")


# ---------------- 阿里云（RPC 签名 · HMAC-SHA1）
def _pct(v: str) -> str:
    return urllib.parse.quote(str(v), safe="~")


def _aliyun_sign(params: dict, secret: str) -> str:
    q = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
    to_sign = "GET&%2F&" + _pct(q)
    dig = hmac.new((secret + "&").encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(dig).decode()


def _send_aliyun(sec: dict, phone: str, code: str, cfg: dict) -> tuple[bool, str]:
    params = {
        "AccessKeyId": sec["access_key_id"],
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": sec.get("region") or "cn-hangzhou",
        "SignName": sec["sign_name"],
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": sec["template_code"],
        "TemplateParam": json.dumps({sec.get("template_param") or "code": code},
                                    ensure_ascii=False, separators=(",", ":")),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    params["Signature"] = _aliyun_sign(params, sec["access_key_secret"])
    qs = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in params.items())
    req = urllib.request.Request(f"https://dysmsapi.aliyuncs.com/?{qs}", method="GET")
    try:
        code_http, body = _http(req)
        data = json.loads(body or "{}")
    except Exception as e:
        return False, f"阿里云接口连不上（{type(e).__name__}: {e}）"
    if str(data.get("Code")) == "OK":
        return True, f"已提交阿里云（BizId {data.get('BizId', '')}）"
    return False, f"阿里云返回 {data.get('Code')}：{data.get('Message')}"


# ---------------- 腾讯云（TC3-HMAC-SHA256）
def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _send_tencent(sec: dict, phone: str, code: str, cfg: dict) -> tuple[bool, str]:
    host, service, action, version = "sms.tencentcloudapi.com", "sms", "SendSms", "2021-01-11"
    region = sec.get("region") or "ap-guangzhou"
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    payload = json.dumps({
        "PhoneNumberSet": [f"+86{phone}"],
        "SmsSdkAppId": str(sec["sdk_app_id"]),
        "SignName": sec["sign_name"],
        "TemplateId": str(sec["template_id"]),
        "TemplateParamSet": [code],
    }, ensure_ascii=False, separators=(",", ":"))
    ct = "application/json; charset=utf-8"
    canonical = "\n".join(["POST", "/", "", f"content-type:{ct}", f"host:{host}", "",
                           "content-type;host",
                           hashlib.sha256(payload.encode("utf-8")).hexdigest()])
    scope = f"{date}/{service}/tc3_request"
    to_sign = "\n".join(["TC3-HMAC-SHA256", str(ts), scope,
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k_date = _hmac(("TC3" + sec["secret_key"]).encode("utf-8"), date)
    k_service = _hmac(k_date, service)
    k_signing = _hmac(k_service, "tc3_request")
    sig = hmac.new(k_signing, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = (f"TC3-HMAC-SHA256 Credential={sec['secret_id']}/{scope}, "
            f"SignedHeaders=content-type;host, Signature={sig}")
    req = urllib.request.Request(
        f"https://{host}/", data=payload.encode("utf-8"), method="POST",
        headers={"Authorization": auth, "Content-Type": ct, "Host": host,
                 "X-TC-Action": action, "X-TC-Version": version,
                 "X-TC-Region": region, "X-TC-Timestamp": str(ts)})
    try:
        _, body = _http(req)
        data = json.loads(body or "{}")
    except Exception as e:
        return False, f"腾讯云接口连不上（{type(e).__name__}: {e}）"
    resp = data.get("Response") or {}
    if resp.get("Error"):
        err = resp["Error"]
        return False, f"腾讯云返回 {err.get('Code')}：{err.get('Message')}"
    sets = resp.get("SendStatusSet") or []
    if sets and str(sets[0].get("Code")) == "Ok":
        return True, f"已提交腾讯云（SerialNo {sets[0].get('SerialNo', '')}）"
    return False, f"腾讯云未返回成功状态：{json.dumps(sets[:1], ensure_ascii=False)}"


# ---------------- 通用 webhook
def _send_webhook(sec: dict, phone: str, code: str, cfg: dict) -> tuple[bool, str]:
    url = sec.get("url", "")
    if not url:
        return False, "没有填网关地址"
    body = json.dumps({"phone": phone, "code": code,
                       "tpl": sec.get("template") or "career_compass",
                       "sign": sec.get("sign") or "职航罗盘"}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if sec.get("token"):
        headers["Authorization"] = f"Bearer {sec['token']}"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        http_code, text = _http(req)
    except Exception as e:
        return False, f"网关连不上（{type(e).__name__}: {e}）"
    if 200 <= http_code < 300:
        return True, "网关已接收"
    return False, f"网关返回 HTTP {http_code}：{text[:120]}"


# ---------------- Mob 免费短信（SMSSDK · web 发送 + 服务端校验）
# 与前两家最大的不同：**验证码由 Mob 生成，平台拿不到明文**。
# 所以这里传进去的 code 会被忽略，校验必须把用户填的码转给 /sms/verify 让 Mob 判。
MOB_API = "https://webapi.sms.mob.com"
MOB_PATHS = ("/sms/sendmsg", "/sms/send")

MOB_ERRORS = {
    206: "模板无效（不存在 / 未审核 / 非 SDK 模板）",
    405: "AppKey 为空",
    406: "AppKey 无效或不存在",
    456: "手机号或区号为空",
    457: "手机号格式错误",
    458: "该号码在 Mob 黑名单中",
    460: "没开「客户端发送短信」开关",
    462: "发送太频繁",
    463: "该号码今天发送次数超限",
    467: "校验太频繁，验证码已失效",
    468: "验证码错误",
    469: "没开后台上「web / http-api 发送短信」开关",
    470: "账户余额不足",
    471: "服务器 IP 不在白名单（把本机公网 IP 加进 Mob 后台）",
    474: "没开「服务端验证」开关",
    475: "AppKey 对应的应用信息不存在",
    476: "今日额度用完：包名未审核时每天只有 20 条",
    477: "该手机号今天已达 10 条上限（含 WebApi）",
    478: "该手机号 12 小时内已发 5 条",
    483: "AppSecret 错误",
    484: "模板不存在或未配置",
    489: "没配 Keystore MD5（3.3.0 之后必填）",
    491: "验证码已过期",
}


def _mob_post(path: str, params: dict) -> tuple[int, dict, str]:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        MOB_API + path, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "Accept": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; CareerCompass/1.0)"})
    http_code, text = _http(req, timeout=12)
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    return http_code, (data if isinstance(data, dict) else {}), text


def _mob_status(data: dict) -> int | None:
    try:
        return int(data.get("status"))
    except Exception:
        return None


def _send_mob(sec: dict, phone: str, code: str, cfg: dict) -> tuple[bool, str]:
    """web 发送：验证码由 Mob 生成下发，这里的 code 用不上。"""
    params = {"appkey": sec.get("appkey", ""), "phone": phone,
              "zone": sec.get("zone") or "86"}
    if sec.get("appsecret"):
        params["appsecret"] = sec["appsecret"]
    last = ""
    for path in MOB_PATHS:
        try:
            http_code, data, text = _mob_post(path, params)
        except Exception as e:
            last = f"连不上 Mob（{type(e).__name__}: {e}）"
            continue
        st = _mob_status(data)
        if st is not None:
            if st == 200:
                return True, "Mob 已下发（验证码由 Mob 生成）"
            return False, f"{st} · {MOB_ERRORS.get(st, '未知错误')}"
        last = f"{path} 返回 HTTP {http_code}：{text[:100]}"
    return False, last or "Mob 没有返回可识别的结果"


def remote_verify() -> bool:
    """当前通道是否由服务商校验验证码（只有 Mob 是这种模式）。"""
    try:
        cfg = load_cfg()
        return ready(cfg) and active_provider(cfg) == "mob"
    except Exception:
        return False


def verify(phone: str, code: str) -> tuple[bool, str]:
    """把用户填的码交给 Mob 核验；只在 Mob 通道下调用。"""
    sec = _section(load_cfg(), "mob")
    try:
        http_code, data, text = _mob_post(
            "/sms/verify", {"appkey": sec.get("appkey", ""), "phone": phone,
                            "zone": sec.get("zone") or "86", "code": code})
    except Exception as e:
        return False, f"Mob 校验接口连不上（{type(e).__name__}），请稍后重试"
    st = _mob_status(data)
    if st == 200:
        return True, "ok"
    if st is None:
        return False, f"Mob 校验接口返回异常（HTTP {http_code}）：{text[:100]}"
    return False, MOB_ERRORS.get(st, f"Mob 校验失败（{st}）")


_SENDERS = {"aliyun": _send_aliyun, "tencent": _send_tencent,
            "mob": _send_mob, "webhook": _send_webhook}


def send(phone: str, code: str) -> dict:
    """发一条验证码。返回 {ok, demo, provider, msg}。

    只走真实网关：没配置/配置缺项一律 ok=False（调用方应把验证码记录删掉，
    允许用户重试），提示去工程后台配置网关；绝不在页面回显验证码。
    """
    cfg = load_cfg()
    prov = active_provider(cfg)
    if not ready(cfg):
        return {"ok": False, "demo": False, "provider": prov or "",
                "msg": "短信网关还没配置好，验证码发不出去。"
                       "请在工程后台 → 账号与登录配置网关后再发。"}
    sec = _section(cfg, prov)
    try:
        ok, msg = _SENDERS[prov](sec, phone, code, cfg)
    except Exception as e:
        ok, msg = False, f"发送异常（{type(e).__name__}: {e}）"
    if ok:
        return {"ok": True, "demo": False, "provider": prov,
                "msg": f"验证码已发送到 {phone[:3]}****{phone[-4:]}，5 分钟内有效"}
    return {"ok": False, "demo": False, "provider": prov,
            "msg": f"短信没发出去：{msg}（配置检查见 ⑧ 工程后台 → 账号与登录）"}


def send_test(phone: str) -> dict:
    """页面上的「发送测试短信」：真实走一次通道，返回详细结果。"""
    cfg = load_cfg()
    if not ready(cfg):
        return {"ok": False, "demo": True,
                "msg": "还没配好（" + status(cfg)["tip"] + "），没法真发。先保存配置再测。"}
    prov = active_provider(cfg)
    is_mob = prov == "mob"
    # Mob 自己生成验证码，平台并不知道明文，所以不能编一个假的「测试验证码」给用户
    code = "" if is_mob else f"{int(time.time()) % 1000000:06d}"
    try:
        ok, msg = _SENDERS[prov](_section(cfg, prov), phone, code, cfg)
    except Exception as e:
        return {"ok": False, "demo": False, "msg": f"发送异常（{type(e).__name__}: {e}）"}
    if is_mob:
        return {"ok": ok, "demo": False, "code": "",
                "msg": (f"{PROVIDERS[prov]} 已下发：{msg}。验证码由 Mob 生成"
                        "（后台可设 4 位或 6 位），请查收手机短信。" if ok
                        else f"{PROVIDERS[prov]} 发送失败：{msg}")}
    return {"ok": ok, "demo": False, "code": code,
            "msg": (f"{PROVIDERS[prov]} 发送成功：{msg}（测试验证码 {code}）" if ok
                    else f"{PROVIDERS[prov]} 发送失败：{msg}")}
