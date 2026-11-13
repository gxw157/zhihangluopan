"""账号体系：注册/登录各有两种方式（账号密码 / 短信验证码），一个账号一份数据。

设计要点
--------
- 账号唯一：users.account 列是唯一账号标识（UNIQUE）。账号密码注册用**自定义账号名**
  （3–24 位，不需要手机号、不需要验证码）；验证码注册用手机号作为账号。两种账号
  存同一列，登录时「账号 + 密码」或「手机号 + 验证码」都能进来。
- 注册与登录双通道：① 账号密码（新增）：注册即设密码，全程不用等短信；
  ② 短信验证码（原有）：验证码 6 位、5 分钟有效、60 秒重发冷却、每小时限 10 条。
- 密码存 PBKDF2-HMAC-SHA256（12 万次迭代 + 每账号独立 16 字节随机盐），
  库里只有 password_hash / password_salt 两列十六进制串，永不存明文；
  校验用 hmac.compare_digest 防时序比较泄漏。
- 老账号（验证码时代注册的）password_hash 为空：用验证码验一次身份即可绑定密码，
  一次绑定，以后都能密码登录。
- 短信只走真发：验证码经 config/sms.json 配置的网关真实下发，页面不回显验证码；
  没配好网关时发送直接失败并提示去工程后台配置。
- 一人一份：users.id 是数据隔离的唯一依据。成长档案、投递记录都带 user_id，
  换账号登录看到的是自己的记录，两个账号用同一个昵称也不会串。
- 登录态：sessions 表存随机 token，写进 URL 的 ?t=，刷新页面不掉登录；
  14 天过期，退出登录即删。

存储：与分析快照同一个 SQLite（data/jobs.db），表 users / sms_code / sessions。
"""
from __future__ import annotations

import hashlib
import hmac
import random
import re
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from core import analyze
from core import sms as SMS

DB = analyze.DB
ROOT = Path(__file__).resolve().parent.parent
SMS_CFG = ROOT / "config" / "sms.json"

CODE_TTL = 300          # 验证码有效期（秒）
RESEND_GAP = 60         # 重发冷却（秒）
HOURLY_CAP = 10         # 同一手机号每小时最多发 10 条
SESSION_DAYS = 14       # 登录态有效期
PBKDF2_ITERS = 120_000  # 密码哈希迭代次数（OWASP 推荐 ≥ 10 万）
DEMO_PW = "demo123456"  # 演示账号的默认密码（页面说明里写明，仅供答辩）

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
USERNAME_RE = re.compile(r"^[\w.\-]{3,24}$")   # \w 含中文；账号名 3–24 位

USERS_DDL = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL UNIQUE,
    nickname TEXT,
    major TEXT,
    created_at TEXT,
    last_login TEXT,
    login_count INTEGER DEFAULT 0,
    password_hash TEXT,
    password_salt TEXT
)
"""

CODE_DDL = """
CREATE TABLE IF NOT EXISTS sms_code(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    code TEXT NOT NULL,
    purpose TEXT DEFAULT 'auth',
    created_at REAL,
    expire_at REAL,
    used INTEGER DEFAULT 0,
    remote INTEGER DEFAULT 0
)
"""

SESSION_DDL = """
CREATE TABLE IF NOT EXISTS sessions(
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at REAL,
    expire_at REAL
)
"""


# ================================================================ 基础
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    _migrate_users(c)       # 老库迁移：phone 列改名 account、补密码两列（幂等）
    c.execute(USERS_DDL)    # 新装库直接建新结构
    c.execute(CODE_DDL)
    c.execute(SESSION_DDL)
    # 老库补列：remote=1 表示这条码由短信服务商生成，本地没有明文
    cols = {r[1] for r in c.execute("PRAGMA table_info(sms_code)")}
    if "remote" not in cols:
        c.execute("ALTER TABLE sms_code ADD COLUMN remote INTEGER DEFAULT 0")
        c.commit()
    c.execute("CREATE INDEX IF NOT EXISTS idx_sms_phone ON sms_code(phone, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(user_id)")
    return c


def _migrate_users(c: sqlite3.Connection) -> None:
    """users 表老库迁移（幂等）：
    ① phone 列改名 account（账号统一列：手机号或自定义账号名都存这）；
    ② 补 password_hash / password_salt 两列。
    """
    info = list(c.execute("PRAGMA table_info(users)"))
    if not info:                    # 新库：_conn 里的 CREATE TABLE 会建新结构
        return
    cols = {r[1] for r in info}
    if "phone" in cols and "account" not in cols:
        c.execute("ALTER TABLE users RENAME COLUMN phone TO account")
        c.commit()
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "password_hash" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        c.execute("ALTER TABLE users ADD COLUMN password_salt TEXT")
        c.commit()


def valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(str(phone or "").strip()))


def norm_phone(phone: str) -> str:
    return str(phone or "").strip().replace(" ", "").replace("-", "")


def norm_account(acc: str) -> str:
    """账号统一规范化：去首尾空格与中间空格/横线。"""
    return str(acc or "").strip().replace(" ", "").replace("-", "")


def valid_username(acc: str) -> tuple[bool, str]:
    a = norm_account(acc)
    if not USERNAME_RE.match(a):
        return False, "账号 3–24 位，可用中文、字母、数字、下划线、点或短横线"
    return True, "ok"


def mask(acc: str) -> str:
    """138****0001，页面上不显示完整手机号；自定义账号名原样显示。"""
    a = norm_account(acc)
    return f"{a[:3]}****{a[-4:]}" if PHONE_RE.match(a) else a


def _now() -> float:
    return time.time()


def _fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def _row_to_user(row: sqlite3.Row | tuple) -> dict:
    keys = ("id", "account", "nickname", "major", "created_at", "last_login", "login_count")
    d = dict(zip(keys, row))
    d["account_masked"] = mask(d.get("account") or "")
    return d


# ================================================================ 短信通道
# 真正的发送逻辑在 core/sms.py（阿里云 / 腾讯云 / 通用 webhook，配好即真发）；
# 这里只做「验证码 → 通道 → 结果」的编排；没配网关就不发，不回显验证码。
def sms_config() -> dict:
    try:
        return SMS.load_cfg()
    except Exception:
        return {}


def sms_ready() -> bool:
    """配置齐全 = 真发短信；否则发送直接失败。"""
    try:
        return SMS.ready()
    except Exception:
        return False


def channel_name() -> str:
    try:
        return SMS.channel_name()
    except Exception:
        return "未配置"


def _deliver(phone: str, code: str) -> dict:
    """交给 core/sms 投递，返回 {ok, demo, provider, msg}。"""
    return SMS.send(phone, code)


# ================================================================ 验证码
def send_code(phone: str, purpose: str = "auth") -> dict:
    """发一条验证码。返回 {ok, msg, demo, code}；只走真实网关，code 不回显。"""
    p = norm_phone(phone)
    if not valid_phone(p):
        return {"ok": False, "msg": "手机号格式不对，请输入 11 位大陆手机号", "demo": False}
    c = _conn()
    try:
        last = c.execute("SELECT created_at FROM sms_code WHERE phone=? ORDER BY id DESC LIMIT 1",
                         (p,)).fetchone()
        now = _now()
        if last and now - float(last[0]) < RESEND_GAP:
            wait = int(RESEND_GAP - (now - float(last[0])))
            return {"ok": False, "msg": f"刚刚发过一条，{wait} 秒后可重发", "demo": False}
        n_hour = c.execute("SELECT COUNT(*) FROM sms_code WHERE phone=? AND created_at>?",
                           (p, now - 3600)).fetchone()[0]
        if int(n_hour) >= HOURLY_CAP:
            return {"ok": False, "msg": "这个号码一小时内发得太频繁了，稍后再试", "demo": False}
        remote = SMS.remote_verify()  # Mob 通道：码由对方生成，本地不存明文
        code = f"{random.randint(0, 999999):06d}"
        cur = c.execute("INSERT INTO sms_code(phone,code,purpose,created_at,expire_at,used,remote) "
                        "VALUES(?,?,?,?,?,0,?)",
                        (p, "" if remote else code, purpose, now, now + CODE_TTL, 1 if remote else 0))
        c.commit()
        rid = int(cur.lastrowid)
    finally:
        c.close()

    res = _deliver(p, code)
    if not res.get("ok"):
        # 真发失败：立刻删掉这条记录，用户可以马上重试，不被 60 秒冷却卡住
        c = _conn()
        try:
            c.execute("DELETE FROM sms_code WHERE id=?", (rid,))
            c.commit()
        finally:
            c.close()
        return {"ok": False, "msg": res.get("msg", "短信没发出去"), "demo": False}
    # 只走真实网关：验证码永远不落到页面
    return {"ok": True, "msg": res.get("msg", "验证码已发送"), "demo": False, "code": ""}

def verify_code(phone: str, code: str, consume: bool = True) -> tuple[bool, str]:
    p, cd = norm_phone(phone), str(code or "").strip()
    if not valid_phone(p):
        return False, "手机号格式不对"
    c = _conn()
    try:
        row = c.execute("SELECT id, code, expire_at, used, COALESCE(remote,0) FROM sms_code "
                        "WHERE phone=? ORDER BY id DESC LIMIT 1", (p,)).fetchone()
        if not row:
            return False, "还没发过验证码，先点「发送验证码」"
        if int(row[3]):
            return False, "这条验证码已用过，请重新发送"
        if _now() > float(row[2]):
            return False, "验证码已过期（5 分钟），请重新发送"
        if int(row[4]):
            # Mob 通道：明文在对方服务器，只能把用户填的码转过去让它判
            if not re.fullmatch(r"\d{4,8}", cd):
                return False, "请输入短信里的数字验证码"
            ok, msg = SMS.verify(p, cd)
            if not ok:
                return False, msg
            if consume:
                c.execute("UPDATE sms_code SET used=1 WHERE id=?", (int(row[0]),))
                c.commit()
            return True, "ok"
        if not re.fullmatch(r"\d{6}", cd):
            return False, "请输入 6 位数字验证码"
        if str(row[1]) != cd:
            return False, "验证码不对，核对一下短信里的 6 位数字"
        if consume:
            c.execute("UPDATE sms_code SET used=1 WHERE id=?", (int(row[0]),))
            c.commit()
        return True, "ok"
    finally:
        c.close()


# ================================================================ 密码（PBKDF2，不存明文）
def valid_password(pw: str) -> tuple[bool, str]:
    p = str(pw or "")
    if len(p) < 6:
        return False, "密码至少 6 位"
    if len(p) > 64:
        return False, "密码最长 64 位"
    if not p.strip():
        return False, "密码不能全是空格"
    return True, "ok"


def hash_password(password: str) -> tuple[str, str]:
    """返回 (hash_hex, salt_hex)：每账号独立 16 字节随机盐。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return dk.hex(), salt.hex()


def check_password(password: str, pw_hash: str | None, salt_hex: str | None) -> bool:
    if not pw_hash or not salt_hex:
        return False
    try:
        dk = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"),
                                 bytes.fromhex(salt_hex), PBKDF2_ITERS)
        return hmac.compare_digest(dk.hex(), str(pw_hash))
    except ValueError:
        return False


def _pw_of(uid: int) -> tuple[str | None, str | None]:
    """单独取密码字段，避免混进 user dict 传到页面。"""
    c = _conn()
    try:
        row = c.execute("SELECT password_hash, password_salt FROM users WHERE id=?",
                        (int(uid),)).fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        c.close()


def has_password(account: str) -> bool:
    u = user_by_account(account)
    if not u:
        return False
    h, _ = _pw_of(int(u["id"]))
    return bool(h)


# ================================================================ 注册 / 登录
def user_by_account(acc: str) -> dict | None:
    """按账号查：自定义账号名与手机号统一存 account 列。"""
    c = _conn()
    try:
        row = c.execute("SELECT id,account,nickname,major,created_at,last_login,login_count "
                        "FROM users WHERE account=?", (norm_account(acc),)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        c.close()


# 兼容旧调用名（测试与脚本里大量出现 user_by_phone）
user_by_phone = user_by_account


def get_user(uid: int) -> dict | None:
    c = _conn()
    try:
        row = c.execute("SELECT id,account,nickname,major,created_at,last_login,login_count "
                        "FROM users WHERE id=?", (int(uid),)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        c.close()


def register(phone: str, code: str, nickname: str = "", major: str = "") -> dict:
    """验证码注册（原通道保留）：手机号即账号，校验验证码 → 建账号 → 建会话。"""
    p = norm_phone(phone)
    ok, msg = verify_code(p, code)
    if not ok:
        return {"ok": False, "msg": msg}
    if user_by_account(p):
        return {"ok": False, "msg": "这个手机号已注册，直接登录就行"}
    name = str(nickname or "").strip()[:20] or f"学生{p[-4:]}"
    c = _conn()
    try:
        cur = c.execute("INSERT INTO users(account,nickname,major,created_at,last_login,login_count) "
                        "VALUES(?,?,?,?,?,1)",
                        (p, name, str(major or "")[:40], _fmt(_now()), _fmt(_now())))
        c.commit()
        uid = int(cur.lastrowid)
    finally:
        c.close()
    return {"ok": True, "msg": "注册成功", "user": get_user(uid), "token": create_session(uid)}


def login_with_code(phone: str, code: str) -> dict:
    p = norm_phone(phone)
    if not valid_phone(p):
        return {"ok": False, "msg": "手机号格式不对"}
    u = user_by_account(p)
    if not u:
        return {"ok": False, "msg": "这个手机号还没注册，先点「注册新账号」"}
    ok, msg = verify_code(p, code)
    if not ok:
        return {"ok": False, "msg": msg}
    c = _conn()
    try:
        c.execute("UPDATE users SET last_login=?, login_count=COALESCE(login_count,0)+1 WHERE id=?",
                  (_fmt(_now()), int(u["id"])))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "msg": "登录成功", "user": get_user(int(u["id"])),
            "token": create_session(int(u["id"]))}


def register_password(account: str, password: str, nickname: str = "",
                      major: str = "") -> dict:
    """注册（账号密码版）：自定义账号名（全库唯一）+ 密码。

    不需要手机号、不需要验证码；账号可以是纯用户名，也可以直接用手机号当账号名。
    返回 {ok, msg, user?, token?}。
    """
    acc = norm_account(account)
    ok, msg = valid_username(acc)
    if not ok:
        return {"ok": False, "msg": msg}
    ok, msg = valid_password(password)
    if not ok:
        return {"ok": False, "msg": msg}
    if user_by_account(acc):
        return {"ok": False, "msg": "这个账号已被注册，换一个或直接登录"}
    pw_hash, pw_salt = hash_password(password)
    name = str(nickname or "").strip()[:20] or f"同学{acc[-4:]}"
    c = _conn()
    try:
        cur = c.execute("INSERT INTO users(account,nickname,major,created_at,last_login,"
                        "login_count,password_hash,password_salt) VALUES(?,?,?,?,?,1,?,?)",
                        (acc, name, str(major or "")[:40], _fmt(_now()), _fmt(_now()),
                         pw_hash, pw_salt))
        c.commit()
        uid = int(cur.lastrowid)
    finally:
        c.close()
    return {"ok": True, "msg": "注册成功", "user": get_user(uid), "token": create_session(uid)}


def login_with_password(account: str, password: str) -> dict:
    """账号 + 密码登录：account 列查唯一账号，PBKDF2 校验通过才发会话 token。

    账号可以是注册时自定义的账号名，也可以是验证码注册用的手机号。
    失败提示刻意写「账号或密码不对」，不区分哪一项错，避免被人拿登录框探测账号。
    """
    acc = norm_account(account)
    if not acc:
        return {"ok": False, "msg": "请输入账号"}
    u = user_by_account(acc)
    if not u:
        return {"ok": False, "msg": "这个账号还没注册，先点「注册新账号」"}
    h, salt = _pw_of(int(u["id"]))
    if not h:
        return {"ok": False, "msg": "这个账号还没有设置密码：用验证码登录一次，"
                                    "或在下方「老账号绑定密码」里绑一个"}
    if not check_password(password, h, salt):
        return {"ok": False, "msg": "账号或密码不对，再试一次"}
    c = _conn()
    try:
        c.execute("UPDATE users SET last_login=?, login_count=COALESCE(login_count,0)+1 WHERE id=?",
                  (_fmt(_now()), int(u["id"])))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "msg": "登录成功", "user": get_user(int(u["id"])),
            "token": create_session(int(u["id"]))}


def bind_password_by_code(phone: str, code: str, new_password: str) -> dict:
    """老账号（验证码时代注册、没有密码）绑定密码：用验证码验一次身份，之后可密码登录。"""
    p = norm_phone(phone)
    ok, msg = verify_code(p, code)
    if not ok:
        return {"ok": False, "msg": msg}
    u = user_by_account(p)
    if not u:
        return {"ok": False, "msg": "这个手机号还没注册"}
    ok2, msg2 = valid_password(new_password)
    if not ok2:
        return {"ok": False, "msg": msg2}
    pw_hash, pw_salt = hash_password(new_password)
    c = _conn()
    try:
        c.execute("UPDATE users SET password_hash=?, password_salt=? WHERE id=?",
                  (pw_hash, pw_salt, int(u["id"])))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "msg": "密码已绑定，以后可以直接用密码登录"}


def set_password(uid: int, new_password: str, old_password: str | None = None) -> dict:
    """已登录账号设置/修改密码：已有密码必须验原密码，没有密码可直接设。"""
    u = get_user(uid)
    if not u:
        return {"ok": False, "msg": "账号不存在"}
    h, salt = _pw_of(int(uid))
    if h and not check_password(old_password or "", h, salt):
        return {"ok": False, "msg": "原密码不对"}
    ok, msg = valid_password(new_password)
    if not ok:
        return {"ok": False, "msg": msg}
    pw_hash, pw_salt = hash_password(new_password)
    c = _conn()
    try:
        c.execute("UPDATE users SET password_hash=?, password_salt=? WHERE id=?",
                  (pw_hash, pw_salt, int(uid)))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "msg": "密码已更新"}


def update_user(uid: int, nickname: str | None = None, major: str | None = None) -> dict | None:
    sets, args = [], []
    if nickname is not None and str(nickname).strip():
        sets.append("nickname=?")
        args.append(str(nickname).strip()[:20])
    if major is not None and str(major).strip():
        sets.append("major=?")
        args.append(str(major).strip()[:40])
    if not sets:
        return get_user(uid)
    c = _conn()
    try:
        c.execute(f"UPDATE users SET {','.join(sets)} WHERE id=?", (*args, int(uid)))
        c.commit()
    finally:
        c.close()
    return get_user(uid)


# ================================================================ 会话（刷新不掉登录）
def create_session(uid: int, days: int = SESSION_DAYS) -> str:
    token = secrets.token_urlsafe(24)
    now = _now()
    c = _conn()
    try:
        c.execute("DELETE FROM sessions WHERE expire_at<?", (now,))
        c.execute("INSERT INTO sessions(token,user_id,created_at,expire_at) VALUES(?,?,?,?)",
                  (token, int(uid), now, now + days * 86400))
        c.commit()
    finally:
        c.close()
    return token


def user_by_token(token: str) -> dict | None:
    if not token:
        return None
    c = _conn()
    try:
        row = c.execute("SELECT user_id FROM sessions WHERE token=? AND expire_at>?",
                        (str(token), _now())).fetchone()
        if not row:
            return None
        uid = int(row[0])
    finally:
        c.close()
    return get_user(uid)


def drop_session(token: str) -> None:
    if not token:
        return
    c = _conn()
    try:
        c.execute("DELETE FROM sessions WHERE token=?", (str(token),))
        c.commit()
    finally:
        c.close()


# ================================================================ 演示账号 & 统计
DEMO_USERS = [
    ("13800000001", "林小雨", "人工智能技术应用"),
    ("13800000002", "陈子昂", "大数据技术"),
    ("13800000003", "周乐", "软件技术"),
]


def ensure_demo_users() -> list[dict]:
    """建 3 个演示账号（幂等）：答辩时用不同手机号登录，直接看到各自的档案。

    老账号没有密码时补一个默认密码（DEMO_PW），这样「账号密码登录」也能演示三个账号。
    """
    out = []
    for phone, name, major in DEMO_USERS:
        u = user_by_account(phone)
        if not u:
            c = _conn()
            try:
                pw_hash, pw_salt = hash_password(DEMO_PW)
                cur = c.execute("INSERT INTO users(account,nickname,major,created_at,last_login,"
                                "login_count,password_hash,password_salt) VALUES(?,?,?,?,?,0,?,?)",
                                (phone, name, major, _fmt(_now()), _fmt(_now()),
                                 pw_hash, pw_salt))
                c.commit()
                uid = int(cur.lastrowid)
            finally:
                c.close()
            u = get_user(uid)
        else:
            h, _ = _pw_of(int(u["id"]))
            if not h:
                c = _conn()
                try:
                    pw_hash, pw_salt = hash_password(DEMO_PW)
                    c.execute("UPDATE users SET password_hash=?, password_salt=? WHERE id=?",
                              (pw_hash, pw_salt, int(u["id"])))
                    c.commit()
                finally:
                    c.close()
        out.append(u)
    return out


def login_demo(phone: str) -> dict:
    """演示账号一键登录（只认 DEMO_USERS 白名单，答辩现场免验证码）。"""
    allow = {p for p, _, _ in DEMO_USERS}
    p = norm_phone(phone)
    if p not in allow:
        return {"ok": False, "msg": "不是演示账号"}
    ensure_demo_users()
    u = user_by_account(p)
    if not u:
        return {"ok": False, "msg": "演示账号初始化失败"}
    c = _conn()
    try:
        c.execute("UPDATE users SET last_login=?, login_count=COALESCE(login_count,0)+1 WHERE id=?",
                  (_fmt(_now()), int(u["id"])))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "msg": "已进入演示账号", "user": get_user(int(u["id"])),
            "token": create_session(int(u["id"]))}


def stats() -> dict:
    c = _conn()
    try:
        n = int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        today = datetime.now().strftime("%Y-%m-%d")
        active = int(c.execute("SELECT COUNT(*) FROM users WHERE last_login LIKE ?",
                               (today + "%",)).fetchone()[0])
        n_sess = int(c.execute("SELECT COUNT(*) FROM sessions WHERE expire_at>?",
                               (_now(),)).fetchone()[0])
        n_code = int(c.execute("SELECT COUNT(*) FROM sms_code").fetchone()[0])
        n_pw = int(c.execute("SELECT COUNT(*) FROM users "
                             "WHERE password_hash IS NOT NULL AND password_hash<>''").fetchone()[0])
    except sqlite3.Error:
        n = active = n_sess = n_code = n_pw = 0
    finally:
        c.close()
    return {"users": n, "active_today": active, "sessions": n_sess, "codes": n_code,
            "with_pw": n_pw}


def list_users(limit: int = 50) -> list[dict]:
    c = _conn()
    try:
        rows = c.execute("SELECT id,account,nickname,major,created_at,last_login,login_count,"
                         "COALESCE(password_hash,'')<>'' FROM users "
                         "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        out = []
        for r in rows:
            d = _row_to_user(r[:-1])
            d["has_pw"] = bool(r[-1])
            out.append(d)
        return out
    finally:
        c.close()
