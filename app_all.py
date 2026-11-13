r"""职航罗盘 · 学生职业规划大数据平台（学生端七屏）

    市场在要什么（① 市场全景）→ 专业学什么（② 方向画像）
        → 我差在哪里（③ 我的定位 → ④ 差距路径）→ 我接下来做什么（⑤ 成长档案 → ⑥ AI 顾问）
    ⑦ 求职实战：JD 透视镜 → 简历技能段 → 模拟面试 → 投递行动清单，学生动线的最后一步。
屏幕上的每一个数字，都要能变成学生今天就能做的一个动作。

工程能力（采集入库 / 技能标注 / 数据规范 / 账号台账）内嵌为 ⑧ 工程后台屏：
    core/admin_ui.py，只有 config/admin.json 名单里的开发者账号能看到 ⑧；
    学生账号导航只有 ①–⑦ 七屏，完全加载不到后台代码。
    （旧的独立入口 app_admin.py / app_mysql.py / app.py 及对应启动 bat 已下线）

双引擎智能体：
    平台引擎（analyze / pathway / agent）算得准——每个数字可复算、可追溯；
    Coze 引擎（core/coze.py）聊得开——上下文注入式 RAG、对话式规划、规划书工作流；
    三级降级：Coze 在线 → OpenAI 兼容接口 → 离线规则兜底，赛场断网不冷场。

数据怎么流（一条数据流水线）：
    智联公开搜索页
        └─ 采集线程 ──► MySQL（主库：jobs / crawl_progress / crawl_log）
                   └──► SQLite（分析快照：data/jobs.db，含成长档案 career_snapshot）

启动：
    双击 启动_职航罗盘.bat    （.venv\Scripts\python -m streamlit run app_all.py）
    学生账号只见 ①–⑦；config/admin.json 名单内的开发者账号自动多出 ⑧ 工程后台。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import analyze as A  # noqa: E402
from core import apply as AP  # noqa: E402
from core import asr as ASR  # noqa: E402
from core import auth as AU  # noqa: E402
from core import coze as CZ  # noqa: E402
from core import crawl as ZP  # noqa: E402
from core import demo_seed as DS  # noqa: E402
from core import factcheck as FC  # noqa: E402
from core import interview as IV  # noqa: E402
from core import jd as JDX  # noqa: E402
from core import majors as MJ  # noqa: E402
from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402
from core import semantic as SEM  # noqa: E402
from core import skills as SK  # noqa: E402
from core import sms as SMS  # noqa: E402
from core import syncpack as SP  # noqa: E402
from core import tts as TTS  # noqa: E402
from core import viz  # noqa: E402
from core import weekly as WK  # noqa: E402
from core.admin_ui import is_admin, render_admin_screen  # noqa: E402
from core.cloud_secrets import sync_cloud_secrets  # noqa: E402
from core.theme import THEME_CSS  # noqa: E402

sync_cloud_secrets()   # Streamlit Community Cloud：st.secrets 里的 [coze]/[llm]/[dify]/[sms] 自动落成 config/*.json；本地有配置文件时本地优先

SQLITE_DB = ROOT / "data" / "jobs.db"

st.set_page_config(page_title="职航罗盘 · 学生职业规划大数据平台", page_icon="🧭",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown(THEME_CSS, unsafe_allow_html=True)


# ================================================================ 账号门禁（网站首页 / 登录 / 注册）
# 未登录只渲染首页（产品介绍 + 登录注册卡），登录后才进入八屏工作台。
# 数据隔离靠 users.id：成长档案、投递记录都写 user_id，换账号看到的是自己的记录。


def _remember(token: str) -> None:
    """会话 token 写进地址栏 ?t=：刷新页面、换标签页都不掉登录。"""
    st.session_state["_token"] = token
    try:
        if token and st.query_params.get("t") != token:
            st.query_params["t"] = token
    except Exception:          # AppTest / 老版本没有 query_params，降级为仅 session
        pass


def _forget() -> None:
    try:
        st.query_params.clear()
    except Exception:
        pass


def _current_user() -> dict | None:
    u = st.session_state.get("user")
    if u:
        return u
    try:
        token = st.query_params.get("t") or ""
    except Exception:
        token = ""
    if token:
        u = AU.user_by_token(token)
        if u:
            st.session_state["user"] = u
            st.session_state["_token"] = token
            st.session_state["student_name"] = u.get("nickname") or "同学"
            return u
    return None


# 属于"当前这个人"的会话状态：换账号必须一起清，否则上一个人的定位/规划书/对话会串到下一个账号
USER_KEYS = (
    "user", "_token", "student_name", "major_name", "screen",
    "lp", "lp_top", "lp_family", "lp_major", "lp_sig", "have_last",
    "plan_md", "plan_engine", "plan_key", "weekly_md", "_weekly",
    "chat", "jd_res", "jd_text", "jd_text2", "jd_text3",
    # ⑦ 库内岗位模式：模式/筛选/游标 + 截图识别结果（换号必须全清，否则会看到别人的岗）
    "jd_mode", "jd_fam", "jd_city", "jd_kw", "jd_only_new", "jd_skill_only",
    "jd_cursor", "jd_sig", "shot_res", "shot_text", "shot_kind", "shot_when", "shot_aid",
    "iv", "iv_persona", "iv_hist", "iv_export", "_iv_last_asr",
    "todo_done", "todo_sig", "_show_resume", "snap_saved", "task_week",
    "snap_note", "snap_sel",           # ⑤ 备注 + 记录表选中（换号后不能再选中别人的行）
    "fam_locate", "top_locate", "fam_portrait",   # 各屏方向选择（覆盖率口径已固定，无 radio）
    "ap_title", "ap_comp", "ap_city", "ap_status", "ap_msg", "del_app",
    "login_mode", "lg_phone", "lg_code", "lg_sms", "rg_phone", "rg_code", "rg_name", "rg_sms",
    "lg_sub", "rg_sub",
    "lg_pwd", "rg_pwd", "rg_pwd2", "bp_phone", "bp_pwd", "bp_code", "bp_sms",
    "last_checkin_sid", "done_msg", "done_evidence",
    "_demo_seeded_uid",                # 演示账号播种标记（每个会话只播一次）
)


def _reset_user_state() -> None:
    """清空与"这个人"绑定的会话状态（含技答、勾选等带前缀的键）。"""
    for k in USER_KEYS:
        st.session_state.pop(k, None)
    for k in [k for k in list(st.session_state.keys())
              if k.startswith(("qa_", "todo_", "demo_", "sms_", "iv_", "done_",
                               "delok_", "delgo_", "_snap_"))]:
        st.session_state.pop(k, None)


def _enter(u: dict, token: str = "") -> None:
    """登录成功：一次把账号、档案名、专业都切到这个人身上（先清干净上一个人的痕迹）。"""
    _reset_user_state()
    st.session_state["user"] = u
    st.session_state["student_name"] = u.get("nickname") or "同学"
    if u.get("major"):
        st.session_state["major_name"] = u["major"]
    if token:
        _remember(token)


def _logout() -> None:
    AU.drop_session(st.session_state.get("_token", ""))
    _reset_user_state()
    _forget()


def _landing_stats() -> dict:
    out = {"jobs": 0, "cities": 0, "skills": 0, "users": 0}
    try:
        c = sqlite3.connect(SQLITE_DB)
        out["jobs"] = int(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        out["cities"] = int(c.execute("SELECT COUNT(DISTINCT city) FROM jobs").fetchone()[0])
        c.close()
    except Exception:
        pass
    try:
        out["skills"] = len(SK._DF)
    except Exception:
        pass
    try:
        out["users"] = AU.stats().get("users", 0)
    except Exception:
        pass
    return out


def hint(msg: str) -> None:
    """空状态提示：无底色无边框，与页面正文同风格。"""
    st.markdown(f'<div class="hint">{msg}</div>', unsafe_allow_html=True)


def _ss_pick(key: str, value: str, qkey: str, nkey: str) -> None:
    """选中一项：写回值、清空搜索框，并换一个面板 key（让下拉收起）。"""
    st.session_state[key] = value
    st.session_state[qkey] = ""
    st.session_state[nkey] = int(st.session_state.get(nkey) or 0) + 1


@st.fragment
def _ss_panel(label: str, options: list[str], key: str,
              placeholder: str, max_show: int) -> None:
    """下拉面板：顶部就是搜索框，下面列选项，点一下就选中。

    搜索框放在选项列表最上面（不是控件外面另起一行），点开下拉即可直接输；
    包含匹配、忽略大小写，命中的项即时收窄，当前选中项打勾高亮。
    """
    st.markdown('<div class="ss-panel"></div>', unsafe_allow_html=True)
    _kw = str(st.text_input("搜索", key=f"{key}_q",
                            placeholder=placeholder or f"🔍 搜索{label}",
                            label_visibility="collapsed") or "").strip()
    _cur = str(st.session_state.get(key) or "")
    _low = _kw.lower()
    _hit = [o for o in options if _low in o.lower()] if _low else list(options)
    if not _hit:
        st.caption("没有匹配的选项，换个关键词试试。")
        return
    for _i, _o in enumerate(_hit[:max_show]):
        _on = _o == _cur
        if st.button(("✓ " if _on else "") + _o, key=f"{key}_o{_i}",
                     width="stretch",
                     type="primary" if _on else "secondary",
                     on_click=_ss_pick,
                     args=(key, _o, f"{key}_q", f"{key}_pop_n")):
            st.rerun(scope="app")
    if len(_hit) > max_show:
        st.caption(f"命中 {len(_hit)} 项，只列前 {max_show} 项，再输几个字收窄。")


def search_select(label: str, options: list[str], key: str, index: int = 0,
                  help: str | None = None, placeholder: str | None = None,
                  ctx=None, max_show: int = 60) -> str:
    """带搜索的下拉：搜索框就长在选项列表的最顶部，点开即可筛。

    原生 selectbox 的搜索框只在选项多时才出现（少于 10 项干脆没有），而专业、
    方向、城市这些恰好是「选项不多但需要找」的场景。所以这里自建下拉：
    触发按钮显示「名称：当前值」，点开后面板第一行就是搜索框，下面即时过滤，
    点一项立即选中并收起。返回值与 session_state[key] 仍是原来那个字符串，
    调用方一行都不用改。ctx 传 st 的 column/container 就能放进分栏里。
    """
    box = ctx if ctx is not None else st
    _all = [str(o) for o in options]
    if not _all:
        return ""
    _cur = st.session_state.get(key)
    if _cur not in _all:
        _cur = _all[index] if 0 <= index < len(_all) else _all[0]
        st.session_state[key] = _cur          # 首次进入 / 选项变了：落回默认项
    _n = int(st.session_state.get(f"{key}_pop_n") or 0)
    with box.container(key=f"ssbox_{key}"):
        with st.popover(f"{label}：{_cur}", help=help, width="stretch",
                        key=f"{key}_pop_{_n}"):
            _ss_panel(label, _all, key, placeholder or "", max_show)
    return _cur



def _code_block(prefix: str, phone: str) -> str:
    """验证码一行：输入框 + 发送按钮（只走真实短信网关）。

    按钮本身就是状态：没发出去还是「发送验证码」，发出去变「已发送」。
    未发送一律不弹提示（网关没配置也不提示），页面只留这一行，不打断填表。
    """
    _remote = SMS.remote_verify()  # Mob 通道：码在对方手里，位数也由对方后台定
    _sent = bool((st.session_state.get(f"{prefix}_sms") or {}).get("ok"))
    c1, c2 = st.columns([1.15, 1], vertical_alignment="bottom")
    code = c1.text_input("验证码", key=f"{prefix}_code", max_chars=6,
                         placeholder="4 位数字" if _remote else "6 位数字")
    if c2.button("已发送" if _sent else "发送验证码", key=f"{prefix}_send",
                 width="stretch"):
        st.session_state[f"{prefix}_sms"] = AU.send_code(phone)
        st.rerun()   # 本轮按钮文案已渲染，重跑一次才会变成「已发送」
    return code


def _fam_index(major_name: str) -> int:
    """本专业第一个岗位族在方向清单里的下标：下拉默认就落在"我的方向"上。"""
    _fams = PW.families()
    _own = [f for f in MJ.families_of(major_name) if f in _fams]
    if _own:
        return _fams.index(_own[0])
    return 1 if len(_fams) > 1 else 0


def landing() -> None:
    """首页：产品是什么 + 一眼看懂四个问题 + 右边直接注册登录。"""
    s = _landing_stats()
    # ---- 开发者入口（首页右上角）：名单内账号在此登录，进入后自动带工程后台
    with st.container(key="dev_entry"):
        with st.popover("🛠 开发者入口"):
            st.caption("开发者账号登录后，可使用工程后台与学生端全部页面")
            _dacc = st.text_input("账号", key="dev_acc",
                                  placeholder="手机号或自定义账号")
            _dpw = st.text_input("密码", key="dev_pw", type="password")
            if st.button("登 录", type="primary", key="dev_go", width="stretch"):
                _r = AU.login_with_password(_dacc.strip(), _dpw)
                if _r.get("ok") and is_admin(_r["user"]["account"]):
                    _enter(_r["user"], _r.get("token", ""))
                    st.rerun()
                else:
                    st.error("账号或密码不对，或该账号不在开发者名单里。")
    st.markdown(f"""
<div class="lp-hero">
  <div class="brand">职航罗盘 · CAREER COMPASS</div>
  <h1>让每个学生，跟着真实岗位数据规划学业</h1>
  <div class="lead">把公开岗位数据与专业课程标准对齐，回答学生最关心的四个问题：
  市场在要什么、专业学什么、我差在哪里、我接下来做什么。
  每个数字都能变成今天能做的一个动作，每一次定位都留在自己的成长档案里。</div>
  <div class="stats">
    <div class="stat"><b>{s['jobs']:,}</b><span>真实岗位样本</span></div>
    <div class="stat"><b>{s['cities']}</b><span>覆盖城市</span></div>
    <div class="stat"><b>{s['skills']}</b><span>标准技能词条</span></div>
    <div class="stat"><b>{s['users']}</b><span>已注册账号</span></div>
  </div>
  <div class="flow"><i>市场在要什么</i><u>→</u><i>专业学什么</i><u>→</u>
    <i>我差在哪里</i><u>→</u><i>我接下来做什么</i></div>
</div>""", unsafe_allow_html=True)

    left, right = st.columns([1.22, 1], gap="large")

    with left:
        st.markdown("""
<div class="lp-card">
  <div class="n">STUDENT JOURNEY</div>
  <h4>登录之后，四步走完一次职业规划</h4>
  <div style="margin-top:8px">
    <div class="lp-step"><div class="no">①</div><div class="tx">
      <b>市场全景 · 市场在要什么</b>
      <span>真实采集的招聘岗位：哪些技能在被要、给多少钱、在哪些城市。</span></div></div>
    <div class="lp-step"><div class="no">②</div><div class="tx">
      <b>方向画像 · 专业学什么</b>
      <span>你的专业开了哪些课，这些课覆盖了目标岗位的多少要求。</span></div></div>
    <div class="lp-step"><div class="no">③</div><div class="tx">
      <b>我的定位 · 我差在哪里</b>
      <span>勾出你已经会的技能，算出命中率与缺口清单，一项一项说清楚。</span></div></div>
    <div class="lp-step"><div class="no">④</div><div class="tx">
      <b>差距路径 · 我接下来做什么</b>
      <span>按岗位需求排序的十二周补课表、本周任务卡、成长档案与 AI 顾问。</span></div></div>
  </div>
</div>""", unsafe_allow_html=True)
        st.write("")

    with right:
        with st.container(border=True):
            st.markdown('<div class="head"></div>'
                        '<div class="sub"></div>',
                        unsafe_allow_html=True)
            mode = st.radio("登录或注册", ["登录", "注册新账号"], horizontal=True,
                            key="lg_mode", label_visibility="collapsed")
            # ⚠ 短信验证码通道已按需求关闭（网关未接入）：只走账号密码。
            #   代码全部保留在下方注释里，恢复时解开注释、把账号密码那段缩进加回 4 格即可。
            if mode == "登录":
                # sub = st.radio("登录方式", ["账号密码", "手机验证码"], horizontal=True,
                #                key="lg_sub", label_visibility="collapsed")
                # if sub == "账号密码":
                p1 = st.text_input("账号", key="lg_phone",
                                   max_chars=24, placeholder="例如 zhangsan 或 13812345678")
                w1 = st.text_input("密码", type="password", key="lg_pwd", max_chars=64,
                                   placeholder="注册时设置的密码（至少 6 位）")
                if st.button("登 录", type="primary", key="lg_do", width="stretch"):
                    r = AU.login_with_password(p1, w1)
                    if r.get("ok"):
                        _enter(r["user"], r.get("token", ""))
                        st.rerun()
                    else:
                        hint(r.get("msg", "登录失败"))
                # else:   # —— 手机验证码登录（暂不开放，恢复时解开）
                    # p1 = st.text_input("手机号", key="lg_phone", max_chars=11,
                                       # placeholder="请输入 11 位手机号")
                    # c1 = _code_block("lg", p1)
                    # if st.button("登 录", type="primary", key="lg_do", width="stretch"):
                        # r = AU.login_with_code(p1, c1)
                        # if r.get("ok"):
                            # _enter(r["user"], r.get("token", ""))
                            # st.rerun()
                        # else:
                            # hint(r.get("msg", "登录失败"))
            else:
                # sub = st.radio("注册方式", ["账号密码", "手机验证码"], horizontal=True,
                #                key="rg_sub", label_visibility="collapsed")
                # if sub == "账号密码":
                p2 = st.text_input("账号", key="rg_phone",
                                   max_chars=24,
                                   placeholder="3–24 位：中文、字母、数字、下划线、点、短横线")
                w2 = st.text_input("密码", type="password", key="rg_pwd",
                                   max_chars=64, placeholder="6–64 位，建议字母 + 数字")
                w3 = st.text_input("确认密码", type="password", key="rg_pwd2",
                                   max_chars=64, placeholder="两次输入要一致")
                n2 = st.text_input("姓名", key="rg_name",
                                   placeholder="例如：林小雨")
                m2 = st.selectbox("专业", MJ.names(), key="rg_major",
                                  index=MJ.names().index(MJ.default_name())
                                  if MJ.default_name() in MJ.names() else 0)
                if st.button("注册并进入", type="primary", key="rg_do", width="stretch"):
                    if w2 != w3:
                        hint("两次输入密码不一致")
                    else:
                        r = AU.register_password(p2, w2, n2, m2)
                        if r.get("ok"):
                            _enter(r["user"], r.get("token", ""))
                            st.rerun()
                        else:
                            hint(r.get("msg", "注册失败"))
                # else:   # —— 手机验证码注册（暂不开放，恢复时解开）
                    # p2 = st.text_input("手机号", key="rg_phone",
                                       # max_chars=11, placeholder="请输入 11 位手机号")
                    # c2 = _code_block("rg", p2)
                    # n2 = st.text_input("姓名", key="rg_name",
                                       # placeholder="例如：林小雨")
                    # m2 = st.selectbox("专业", MJ.names(), key="rg_major",
                                      # index=MJ.names().index(MJ.default_name())
                                      # if MJ.default_name() in MJ.names() else 0)
                    # if st.button("注册并进入", type="primary", key="rg_do", width="stretch"):
                        # r = AU.register(p2, c2, n2, m2)
                        # if r.get("ok"):
                            # _enter(r["user"], r.get("token", ""))
                            # st.rerun()
                        # else:
                            # hint(r.get("msg", "注册失败"))

    st.write("")
    k1, k2, k3 = st.columns(3, gap="medium")
    with k1:
        st.markdown("""<div class="lp-card"><div class="n">DATA</div>
<h4>数字都算得出来</h4>
<p>岗位需求、薪资溢价、课程覆盖由平台引擎复算。</p></div>""", unsafe_allow_html=True)
    with k2:
        st.markdown("""<div class="lp-card"><div class="n">GROWTH</div>
<h4>成长看得见</h4>
<p>每次定位存一份快照，命中率曲线、缺口变化、周报自动生成，
一份可以直接放进求职材料的成长记录。</p></div>""", unsafe_allow_html=True)
    with k3:
        st.markdown("""<div class="lp-card"><div class="n">ACTION</div>
<h4>输出可执行结果</h4>
<p>十二周补课表、本周任务卡、简历技能段、模拟面试题，直接可用。</p></div>""", unsafe_allow_html=True)

    st.markdown('<div class="lp-foot">职航罗盘 · 学生职业规划大数据平台'
                '</div>',
                unsafe_allow_html=True)


_user = _current_user()
if not _user:
    landing()
    st.stop()

UID = int(_user["id"])
ACCOUNT = _user
# 演示账号自动播种：换电脑登录同一演示账号时，成长档案/投递剧本数据自动补齐，
# 保证「不同电脑、同一账号、同一份数据」。幂等：账号下已有数据就一个字不动。
if ACCOUNT.get("account") in DS.DEMO_ACCOUNTS and \
        st.session_state.get("_demo_seeded_uid") != UID:
    DS.seed_demo_account(ACCOUNT)
    st.session_state["_demo_seeded_uid"] = UID
if not st.session_state.get("student_name"):
    st.session_state["student_name"] = _user.get("nickname") or "同学"


# ================================================================ 缓存与分析
def db_ver() -> float:
    return SQLITE_DB.stat().st_mtime if SQLITE_DB.exists() else 0.0


@st.cache_data(show_spinner=False)
def c_overview(v: float) -> dict:
    return A.overview()


@st.cache_data(show_spinner=False)
def c_market(v: float, fams: tuple = ()) -> dict:
    """① KPI：fams 空元组 = 技术岗大盘口径；给了岗位族 = 本专业相关口径。"""
    return A.market_overview(list(fams) if fams else None)


@st.cache_data(show_spinner=False)
def c_demand(v: float, k: int = 20, fams: tuple = ()) -> pd.DataFrame:
    return (A.demand_of_families(list(fams), top_k=k) if fams
            else A.demand(top_k=k))


@st.cache_data(show_spinner="正在回归技能溢价…")
def c_premium(v: float, fams: tuple = (), floor: int = 25) -> dict:
    return A.salary_premium(top_n=12, count_floor=floor, boot=60,
                            fams=list(fams) if fams else None)


@st.cache_data(show_spinner=False)
def c_edges(v: float, min_n: int = 15, fams: tuple = ()) -> pd.DataFrame:
    return A.pmi_edges(min_n=min_n, top_k=40, fams=list(fams) if fams else None)


@st.cache_data(show_spinner=False)
def c_city(v: float, fams: tuple = ()) -> pd.DataFrame:
    return A.city_profile(list(fams) if fams else None)


@st.cache_data(show_spinner=False)
def c_trend(v: float, fams: tuple = ()) -> dict:
    """① 需求变化：专业相关口径月样本门槛放宽到 20（族内岗位少）。"""
    return A.demand_trend(top_k=6, min_jobs=20 if fams else 30,
                          fams=list(fams) if fams else None)


@st.cache_data(show_spinner=False)
def c_family(v: float, fams: tuple = ()) -> pd.DataFrame:
    """各岗位族的岗位数与月薪中位——学生选方向前先看机会密度。

    fams 给了就只列这些族（全库口径，含非技术岗）。
    """
    j = A.jobs(all_rows=True) if fams else A.jobs()
    if fams:
        j = j[j["family"].isin(fams)]
    if j.empty:
        return pd.DataFrame()
    g = j.groupby("family").agg(岗位数=("jd_id", "count"),
                                月薪中位=("salary_mid", "median")).reset_index()
    g["月薪中位"] = g["月薪中位"].round(0)
    return g.sort_values("岗位数", ascending=False).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def c_cov(v: float, major: str = "", scope: str = "全部") -> dict:
    return A.coverage(major or None, scope=scope)


@st.cache_data(show_spinner=False)
def c_job_pool(v: float) -> pd.DataFrame:
    """⑦ 库内岗位候选池：全库岗位（技术岗 + 各行各业）+ 解析好的技能清单。

    专业目录已覆盖 19 个专业大类，会计、销售、护理的学生也要能翻到自己的岗位，
    所以这里取全库，靠「方向」下拉按岗位族筛。
    """
    import json as _json
    df = A.jobs(all_rows=True)
    if df.empty:
        return df
    keep = ["jd_id", "title", "company", "city", "district", "salary_text", "salary_mid",
            "edu", "exp", "company_size", "publish_date", "family", "skills_raw", "url"]
    d = df[[c for c in keep if c in df.columns]].copy()

    def _sk(s):
        try:
            raw = _json.loads(s) if isinstance(s, str) else (s or [])
            return [str(x).strip() for x in raw if str(x).strip()]
        except Exception:
            return []

    d["skills"] = d["skills_raw"].map(_sk)
    return d.reset_index(drop=True)


def clear_analysis_cache() -> None:
    for f in (c_overview, c_market, c_demand, c_premium, c_edges, c_cov, c_family,
              c_city, c_trend, c_job_pool):
        f.clear()


def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="k">{label}</div><div class="v">{value}</div>'
                 f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


def screen_head(no: str, title: str = "", desc: str = "") -> None:
    """屏头：屏名与内容说明。"""
    _parts = [f"<b>{title}</b>"] if title else []
    if desc:
        _parts.append(desc)
    st.markdown(f'<div class="screen-head"><span class="no">{no}</span>'
                f'<span class="ans">{"　·　".join(_parts)}</span></div>',
                unsafe_allow_html=True)


# ================================================================ 导出
def _snap_pick_rows(snaps) -> list[int]:
    """⑤ 定位记录表当前选中的行号列表（0 起，按旧→新），可多选。"""
    raw = st.session_state.get("snap_sel")
    rows: list = []
    if isinstance(raw, dict):
        rows = list((raw.get("selection") or {}).get("rows") or [])
    else:
        try:
            rows = list(getattr(raw.selection, "rows", []) or [])
        except Exception:
            rows = []
    out: list[int] = []
    for r in rows:
        try:
            i = int(r)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(snaps):
            out.append(i)
    return out


def _snap_pick_index(snaps) -> int | None:
    """⑤ 定位记录表当前选中的第一行（曲线只框一个点），没选中返回 None。"""
    _rows = _snap_pick_rows(snaps)
    return _rows[0] if _rows else None


def md_parts(md: str, level: int = 2) -> tuple[str, list[tuple[str, str]]]:
    """把 Markdown 按指定级别标题切成 (前言, [(标题, 正文), …])。

    面试反馈、职业规划书都是「## 一节」的结构：切开才能一节一张卡，
    比整篇塞进一个滚动框好看得多。level=3 用于把逐题复盘拆成单题卡。
    """
    tag = "#" * max(1, min(level, 6)) + " "
    head: list[str] = []
    secs: list[tuple[str, str]] = []
    cur: str | None = None
    buf: list[str] = []
    for ln in str(md or "").splitlines():
        s = ln.rstrip()
        if s.startswith(tag) and not s.startswith(tag + "#"):
            if cur is not None:
                secs.append((cur, "\n".join(buf).strip()))
            cur, buf = s[len(tag):].strip(), []
        elif cur is None:
            head.append(s)
        else:
            buf.append(s)
    if cur is not None:
        secs.append((cur, "\n".join(buf).strip()))
    return "\n".join(head).strip(), secs


def write_docx(md: str, prefix: str) -> Path:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.styles["Normal"].font.name = "微软雅黑"
    doc.styles["Normal"].font.size = Pt(10.5)
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            doc.add_heading(s[2:], level=0)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=1)
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            doc.add_paragraph(" ｜ ".join(cells))
        elif re.match(r"^\d+\.\s", s) or s.startswith("- "):
            doc.add_paragraph(s.lstrip("- "))
        elif s == "---":
            doc.add_paragraph("")
        else:
            doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", s))
    out = ROOT / "data" / "exports" / f"{prefix}_{datetime.now():%Y%m%d_%H%M}.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


# ================================================================ 侧边栏
ov = c_overview(db_ver())

with st.sidebar:
    st.markdown("### 职航罗盘")
    st.markdown(f'<div class="acct"><div class="nm">{ACCOUNT.get("nickname") or "同学"}</div>'
                f'<div class="ph">{ACCOUNT.get("account_masked", "")} · 已登录</div></div>',
                unsafe_allow_html=True)
    st.button("退出登录", key="logout_btn", width="stretch", on_click=_logout)
    st.markdown('<div class="flat"><br>'
                '市场在要什么 → 专业学什么 → 我差在哪里 → 我接下来做什么</div>',
                unsafe_allow_html=True)
    st.divider()

    # ---- 我是谁：档案名跟随登录账号（数据隔离钥匙始终是 user_id）
    student = str(st.session_state.get("student_name") or ACCOUNT.get("nickname") or "同学")

    # ---- 专业选择：全站口径的开关（36 个专业按大类排序，覆盖 19 个专业大类）
    major_names = MJ.names_by_category()
    _default = MJ.default_name()
    major_name = search_select(
        "我的专业", major_names,
        "major_name",
        index=major_names.index(_default) if _default in major_names else 0,
        help="切换专业后，课程覆盖、学习路径、相关课程、技能成长方案全部按该专业口径重算",
        placeholder="🔍 搜索专业")
    mj = MJ.get(major_name)
    # 专业一换，方向/目标岗位族的默认值跟着走：旧专业选的"财务"不该留在护理专业上
    if st.session_state.get("_major_seen") != major_name:
        st.session_state["_major_seen"] = major_name
        for _k in ("fam_portrait", "fam_locate"):
            st.session_state.pop(_k, None)
    st.markdown(f'<div class="major-chip"><b>{mj["code"]}</b> · {mj["category"]}<br>'
                f'{mj["jobs"]}<br>'
                f'课程 <b>{mj["courses"]}</b> 门（基础 {mj["base"]} / 核心 {mj["core"]} / 拓展 {mj["ext"]}）'
                f'</div>', unsafe_allow_html=True)
    st.divider()
# ================================================================ 当前定位的有效性
def lp_ok() -> dict | None:
    """取当前定位，但要求它与所选专业一致。

    专业是课程覆盖、相关课程的口径开关：切了专业还拿旧专业的定位往下算，
    补课清单和课程名就对不上了。所以专业一变，旧定位视为过期，各屏统一提示重新定位。
    """
    _l = st.session_state.get("lp")
    if not (_l and _l.get("ok")):
        return None
    if _l.get("major") and _l["major"] != major_name:
        return None
    return _l


def lp_expired_note() -> None:
    """旧定位因专业切换而过期时的统一提示。"""
    _l = st.session_state.get("lp")
    if _l and _l.get("ok") and _l.get("major") and _l["major"] != major_name:
        st.warning(f"你的定位是按「{_l['major']}」生成的；专业已切到「{major_name}」——"
                   "回「③ 我的定位」重新生成一次，这里的课程名与覆盖率才对得上。")

# ================================================================ 顶部品牌头图
st.markdown(f"""
<div class="hero">
  <div class="brand">职航罗盘 · CAREER COMPASS</div>
  <h1>让每个学生，跟着真实岗位数据规划学业</h1>
  <div class="tag">公开岗位数据 × 专业课程标准 → 可执行的成长路径</div>
</div>
""", unsafe_allow_html=True)

# ================================================================ 屏导航
# 用单选做路由：只渲染当前这一屏，避免每次交互都把八屏的图、模型、表格全部算一遍
SCREENS = ["① 市场全景", "② 方向画像", "③ 我的定位", "④ 差距路径",
           "⑤ 成长档案", "⑥ AI 顾问", "⑦ 求职实战"]
# 开发者视图由登录身份自动决定：名单内账号登录即见 ⑧ 工程后台（+学生端全部页面）
dev_mode = is_admin(ACCOUNT.get("account", ""))
if dev_mode:
    SCREENS = SCREENS + ["⑧ 工程后台"]
shown = list(SCREENS)
if st.session_state.get("screen") not in shown:
    st.session_state["screen"] = shown[0]
with st.container(key="screennav"):
    screen = st.radio("屏导航", shown, horizontal=True, label_visibility="collapsed",
                      key="screen")


def is_screen(i: int) -> bool:
    """当前屏是否第 i 个（① = 1）。"""
    return screen == SCREENS[i - 1]

# ---------------------------------------------------------------- ① 市场全景
if is_screen(1):
    screen_head("① 市场全景", "",
                "")
    if ov.get("n", 0) == 0:
        hint("数据库为空，还没有岗位数据。")
    else:
        _fams_all = PW.families()
        _own = [f for f in MJ.families_of(major_name) if f in _fams_all]
        _fams = tuple(_own)                       # ① 固定按「我的专业」聚焦，不再提供大盘切换
        mov = c_market(db_ver(), _fams)
        if _fams and mov.get("n", 0) == 0:
            hint(f"「{major_name}」对应方向（{'、'.join(_own)}）在库里还没有岗位，"
                 "到工程后台补采该方向的岗位后这里会自动出数。")
        elif _fams and mov.get("n", 0) < 30:
            hint(f"本专业相关方向目前只有 {mov['n']} 条岗位，下面的数字仅供参考；"
                 "采集更多该方向岗位后会自动变准。")
        if mov.get("n", 0) > 0:
            m1, m2, m3, m4, m5 = st.columns(5)
            kpi(m1, "岗位样本" if _fams else "技术岗样本", f"{mov.get('n', 0):,}",
                f"{'本专业 ' + str(len(_own)) + ' 个方向的岗位' if _fams else '标题粗筛后的有效岗位'}")
            kpi(m2, "覆盖城市", mov.get("cities", 0), "岗位分布的城市数")
            kpi(m3, "月薪中位数", f"¥{(mov.get('median') or 0):,.0f}", "招聘方标价口径")
            kpi(m4, "招聘企业", mov.get("companies", 0), "去重后")
            _d1, _d2 = str(mov.get("date_min", "")), str(mov.get("date_max", ""))
            try:
                _span = ((int(_d2[:4]) - int(_d1[:4])) * 12 + int(_d2[5:7]) - int(_d1[5:7]) + 1)
                _win = f"约 {_span} 个月"
            except ValueError:
                _win = "-"
            kpi(m5, "数据时间窗", _win,
                f"{_d1[:7]}~{_d2[:7]} · 薪资可解析 {mov.get('salary_rate', 0):.0%}")

            st.write("")
            dem = c_demand(db_ver(), 15, _fams)
            col1, col2 = st.columns([1.15, 1])
            with col1:
                st.markdown("#### 市场最抢手的技能 · Top15")
                st.markdown(f'<div class="fig">{viz.demand_bars(dem, 15)}</div>', unsafe_allow_html=True)
                #st.caption("""")
            with col2:
                st.markdown("#### 技能共现网络")
                st.markdown(f'<div class="fig">{viz.network(c_edges(db_ver(), 8 if _fams else 15, _fams))}</div>',
                            unsafe_allow_html=True)
                #st.caption("连在一起的一组技能，就是企业心里一个完整岗位的样子。" "找工作不是攒单技能，是凑齐一组。")

            st.divider()
            prem = c_premium(db_ver(), _fams, 10 if _fams else 25)
            st.markdown("#### 哪些技能更值钱")
            if prem.get("ok"):
                g1, g2 = st.columns([1.5, 1])
                with g1:
                    st.markdown(f'<div class="fig">{viz.premium_bars(prem["table"], 8)}</div>',
                                unsafe_allow_html=True)
                with g2:
                    st.caption(f"控制城市、岗位族、企业规模、经验、学历、岗位层级后的月薪差异"
                               f"（5 折交叉验证 R²={prem['r2']:.3f}，不含技能的基线 "
                               f"{prem.get('r2_base', 0):.3f}，样本 {prem['n']} 条）。"
                               "")
            else:
                hint(prem.get("msg"))

            st.markdown("#### 机会在哪：城市与方向")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.caption("各城市岗位数")
                st.dataframe(c_city(db_ver(), _fams).rename(columns={"月薪中位": "月薪中位数"}),
                             width="stretch", hide_index=True, height=300)
            with cc2:
                st.caption("各方向岗位密度")
                fam = c_family(db_ver(), _fams)
                if fam.empty:
                    hint("还没有方向数据。")
                else:
                    st.dataframe(fam, width="stretch", hide_index=True, height=300,
                                 column_config={"岗位数": st.column_config.ProgressColumn(
                                     "岗位数", min_value=0, max_value=int(fam["岗位数"].max()),
                                     format="%d")})
            st.divider()
            st.markdown("#### 需求变化")
            tr = c_trend(db_ver(), _fams)
            if tr.get("ok"):
                st.markdown(f'<div class="fig">{viz.trend_lines(tr["share"], tr["months"], tr["skills"])}</div>',
                            unsafe_allow_html=True)
                _d = list(tr["delta"].items())
                _up = "、".join(f"{k} {v:+.1%}" for k, v in _d[:2] if v > 0) or "无明显上升项"
                st.caption(f"按岗位发布时间分月，只统计月岗位数 ≥{20 if _fams else 30} 的月份（样本："
                           f"{'、'.join(f'{m} {tr['n_jobs'][m]} 条' for m in tr['months'])}）。"
                           f"较上月上升最多：{_up}。"
                           + (tr.get("note") or ""))
            else:
                hint(tr.get("msg", "暂无趋势数据"))

# ---------------------------------------------------------------- ② 方向画像
if is_screen(2):
    screen_head("② 方向画像", "",
                f"{major_name} 官方标准课程对照，依据 {MJ.source()}")
    if ov.get("n", 0) == 0:
        hint("还没有岗位数据，采完才会有方向画像。")
    else:
        fc1, fc2 = st.columns([1, 1.6])
        with fc1:
            _fams_all = PW.families()
            fam2 = search_select("方向", _fams_all, "fam_portrait", index=_fam_index(major_name),
                                 help="岗位族由职位标题关键词归类，与后面「我的定位」共用同一套规则",
                                 placeholder="🔍 搜索方向")
            fdem = PW.demand_of_family(fam2, 12)
            st.markdown(f"#### 「{fam2}」岗位族的技能要求")
            _nfam = PW.family_size(fam2)
            if fdem.empty:
                hint("该岗位族暂无样本，换一个方向看看。")
            else:
                st.caption(f"库内该方向 {_nfam} 条岗位"
                           + ("（样本偏少，结论仅供参考）" if 0 < _nfam < 30 else ""))
                st.dataframe(
                    fdem.rename(columns={"skill": "技能", "n": "岗位数", "share": "占该族岗位"}),
                    width="stretch", hide_index=True, height=380,
                    column_config={"岗位数": st.column_config.ProgressColumn(
                        "岗位数", min_value=0, max_value=int(fdem["n"].max()), format="%d"),
                        "占该族岗位": st.column_config.NumberColumn(format="%.1f%%")})
        with fc2:
            cov2 = c_cov(db_ver(), major_name, "全部")   # 口径固定为全部技术岗
            st.markdown(f"#### 课程跟不跟得上 · {major_name}")
            if cov2.get("ok"):
                st.markdown(f'<div class="fig">{viz.quadrant(cov2["table"])}</div>',
                            unsafe_allow_html=True)
            else:
                hint(cov2.get("msg", "暂无覆盖率数据"))

        st.write("")
        if cov2.get("ok"):
            k2 = st.columns(4)
            kpi(k2[0], "加权覆盖率", f"{cov2['coverage']:.1%}", "0.6×需求 + 0.4×溢价")
            kpi(k2[1], "红色缺口", cov2["red"], "需求高·课程没教")
            kpi(k2[2], "橙色缺口", cov2["orange"], "课程里有·要加深")
            kpi(k2[3], "已覆盖", cov2["green"], "自学即可达标")
            st.write("")
            rd1, rd2, rd3 = st.columns(3)
            rd1.markdown('<div class="todo red"><b>🔴 红色缺口 → 证书 / 在线课替代</b><br>'
                         '课程暂时没覆盖，不等排课：直接跟 1+X 证书对应模块或在线课程学，'
                         '做一个能写进简历的作品。</div>', unsafe_allow_html=True)
            rd2.markdown('<div class="todo orange"><b>🟠 橙色缺口 → 在现有课程里加深</b><br>'
                         '课里有但不深：把这门课的作业做到工程可用级别，再补一个真实项目案例。</div>',
                         unsafe_allow_html=True)
            rd3.markdown('<div class="todo green"><b>🟢 绿色已覆盖 → 自学巩固</b><br>'
                         '课程教到位了：跟着课走，把课后项目当作品集素材。</div>',
                         unsafe_allow_html=True)

# ---------------------------------------------------------------- ③ 我的定位
if is_screen(3):
    screen_head("③ 我的定位")
    lw, rw = st.columns([1, 2.1])
    with lw:
        #st.markdown("#### 第 1 步：告诉我你现在的位置")
        fam3 = search_select("目标岗位族", PW.families(), "fam_locate",
                             index=_fam_index(major_name),
                             help="与②方向画像同一套归类规则；默认落在本专业对应的方向上",
                             placeholder="🔍 搜索岗位族")
        top3 = st.slider("目标技能取需求榜前", 6, 20, 10, key="top_locate")
        have = st.multiselect("我已掌握的技能", PW.all_skills(),
                              default=st.session_state.get("have_last", []),
                              max_selections=30,
                              help="不用谦虚也不用高估——按「能独立完成任务」的标准勾")
        gen3 = st.button("📐 生成我的定位", type="primary", width="stretch")
        if gen3:
            with st.spinner("按目标岗位族统计技能需求…"):
                st.session_state["lp_family"] = fam3
                st.session_state["lp_major"] = major_name
                st.session_state["lp_top"] = int(top3)
                st.session_state["have_last"] = list(have)
                st.session_state["lp"] = PW.build_path(have, fam3, top3, major=major_name)
                # 重新定位 = 新一轮补课，④ 的「已提交」状态归零
                st.session_state.pop("done_submitted", None)
                # 定位变了，旧规划书就是旧档案：一并作废，避免⑥里还挂着上一版
                for _k in ("plan_md", "plan_engine", "plan_key"):
                    st.session_state.pop(_k, None)

    with rw:
        lp = lp_ok()
        if lp and lp.get("ok"):
            k3 = st.columns(3)
            kpi(k3[0], "岗位需求命中率", f"{lp['match']:.0%}", "已会技能覆盖的需求占比")
            kpi(k3[1], "待补技能", len(lp["gap"]), "按岗位要求次数排序")
            kpi(k3[2], "目标岗位族", st.session_state.get("lp_family", fam3),
                f"Top{st.session_state.get('lp_top', 10)} 技能合计 {lp['n_family']:,} 条要求")
            # 70% 是经验门槛：命中率到这里，投实习岗就有底气了
            _line = 0.70
            if lp["match"] < _line:
                st.progress(min(lp["match"] / _line, 1.0),
                            text=f"距离「70% 可投实习线」还差 {(_line - lp['match']):.0%}"
                                 f"——把下面 Top3 补完基本就到")
            else:
                st.progress(1.0, text="已达 70% 可投实习线：可以边投简历边补剩下的缺口")
            st.write("")
            t_held = lp["table"][lp["table"]["已掌握"]]
            t_gap = lp["gap"]
            c31, c32 = st.columns(2)
            with c31:
                st.markdown(f"#### 已会技能（{len(t_held)} 项）")
                ''''''
                if len(t_held):
                    st.caption("只算目标方向需求榜 Top"
                               f"{st.session_state.get('lp_top', 10)} 内的技能；"
                               "")
                if len(t_held):
                    st.dataframe(t_held[["技能", "岗位数"]], width="stretch", hide_index=True,
                                 height=210)
                else:
                    hint("还没勾上任何技能")
            with c32:
                st.markdown("#### 优先补齐的 5 项")
                if len(t_gap):
                    st.dataframe(t_gap.head(5)[["技能", "岗位数", "课程覆盖"]],
                                 width="stretch", hide_index=True, height=210,
                                 column_config={"课程覆盖": st.column_config.ProgressColumn(
                                     "课程覆盖", min_value=0, max_value=1, format="%.0f%%")})
                else:
                    st.success("这个方向的技能你已经全勾上了——去挑战更高的岗位族！")

            # ---- 存快照：成长档案的入口
            st.divider()
            st.markdown("#### 存一份成长档案")
            note3 = st.text_input("备注", key="snap_note",
                                  placeholder="可留空")
            s1c, s2c = st.columns([1, 1.6])
            if s1c.button("💾 存入成长档案", width="stretch",
                          disabled=not len(lp["table"])):
                # 存的是"这次定位"的技能，不是此刻勾选框里的值：改了勾选但没重新生成，
                # 直接存会让档案里的技能数与命中率对不上（演示现场最容易被追问的点）。
                sid = PF.save_snapshot(student, lp, st.session_state.get("have_last", []),
                                       note3, uid=UID)
                if sid:
                    st.session_state["snap_saved"] = sid
                    st.session_state.pop("weekly_md", None)   # 新快照 → 旧周报作废
                    _n_now = PF.list_snapshots(student, UID).shape[0]
                    hint(f"已存入「{student}」的成长档案（第 {_n_now} 次定位）"
                         "。下次定位后来「⑤ 成长档案」看变化。")

        else:
            _raw3 = st.session_state.get("lp") or {}
            if _raw3.get("ok"):
                lp_expired_note()          # 定位在，但专业换了 → 提示重新定位
            elif _raw3:
                st.warning(_raw3.get("msg", "生成失败"))

# ---------------------------------------------------------------- ④ 差距路径
if is_screen(4):
    screen_head("④ 差距路径")
    lp4 = lp_ok()
    if not (lp4 and lp4.get("ok")):
        if (st.session_state.get("lp") or {}).get("ok"):
            lp_expired_note()
        else:
            hint("先在「③ 我的定位」生成定位")
    else:
        gap4 = lp4["gap"]
        # 上一轮提交后清的佐证：必须等 widget 未实例化时再清（同一轮改已渲染的 widget 会报错）
        if st.session_state.pop("_clear_evidence", False):
            st.session_state["done_evidence"] = ""
        st.markdown(f'<div class="fig">{viz.roadmap(gap4, int((lp4["table"]["已掌握"]).sum()), lp4["match"])}</div>',
                    unsafe_allow_html=True)
        st.write("")
        # ---- 三类缺口 → 三种行动
        n_red = int((gap4["课程覆盖"] <= 0).sum())
        n_orange = int(((gap4["课程覆盖"] > 0) & (gap4["课程覆盖"] < 1)).sum())
        n_green = int((gap4["课程覆盖"] >= 1).sum())
        w4 = st.columns(3)
        w4[0].markdown(f'<div class="todo red"><b>🔴 先攻 {n_red} 项零覆盖技能</b><br>'
                       '课程没教的走 1+X 证书 / 在线课 / 开源项目，两周出第一个练手作品。</div>',
                       unsafe_allow_html=True)
        w4[1].markdown(f'<div class="todo orange"><b>🟠 加深 {n_orange} 项在教技能</b><br>'
                       '定位对应课程章节，把作业做到工程可用级别。</div>', unsafe_allow_html=True)
        w4[2].markdown(f'<div class="todo green"><b>🟢 巩固 {n_green} 项已覆盖技能</b><br>'
                       '跟课推进即可，课后项目当作品集素材。</div>', unsafe_allow_html=True)
        st.write("")
        st.markdown("#### 补课清单")
        st.dataframe(gap4, width="stretch", hide_index=True,
                     column_config={"课程覆盖": st.column_config.ProgressColumn(
                         "课程覆盖", min_value=0, max_value=1, format="%.0f%%")})
        md4 = PW.to_markdown(st.session_state.get("have_last", []),
                             st.session_state.get("lp_family", ""), lp4)
        d41, d42 = st.columns([1, 2])
        d41.download_button("下载学习路径（Markdown）", md4.encode("utf-8"),
                            f"学习路径_{lp4.get('major', major_name)}.md",
                            "text/markdown", width="stretch")
        if d42.button("导出为 Word", width="stretch"):
            path = write_docx(md4, f"学习路径_{lp4.get('major', major_name)}")
            st.success(f"已存到 {path}")

        # ---- 勾选提交：学完即打卡。勾上的技能并入定位重算，并自动存一份成长快照，
        #      ⑤成长档案据此识别"已补课程"、成长曲线用橙点标记这次提交。
        if len(gap4):
            st.write("")
            st.markdown("#### 勾选已完成项，提交后记入成长档案")
            _gap_skills = list(gap4["技能"])
            _base_have = list(st.session_state.get("have_last", []))
            _fam_c = st.session_state.get("lp_family", "")
            _top_c = int(st.session_state.get("lp_top", 10))
            _major_c = lp4.get("major", major_name)
            _picked = []
            for _ri in range(0, len(_gap_skills), 3):
                _rc = st.columns(3)
                for _cj, _sk in enumerate(_gap_skills[_ri:_ri + 3]):
                    if _rc[_cj].checkbox(_sk, key=f"done_{_sk}"):
                        _picked.append(_sk)
            ev4 = st.text_input("佐证（选填）：项目 / 证书 / 成绩，写进成长档案",
                                key="done_evidence")
            # 提交过就变灰并写「已提交」；再勾了新项才回到可提交
            _submitted = bool(st.session_state.get("done_submitted")) and not _picked
            if _picked:
                _lp_prev = PW.build_path(sorted(set(_base_have) | set(_picked)),
                                         _fam_c, _top_c, major=_major_c)
                if _lp_prev.get("ok"):
                    hint(f"勾上这 {len(_picked)} 项后：命中率 {lp4['match']:.0%} → "
                         f"{_lp_prev['match']:.0%}，待补 {len(gap4)} → {len(_lp_prev['gap'])} 项")
            if _submitted:
                st.button("已提交", width="stretch", disabled=True, key="checkin_done_btn")
            elif _picked and st.button("✅ 提交补课结果，记入成长档案", type="primary",
                                       width="stretch", key="checkin_btn"):
                _have_new = sorted(set(_base_have) | set(_picked))
                _lp_new = PW.build_path(_have_new, _fam_c, _top_c, major=_major_c)
                if _lp_new.get("ok"):
                    _note = f"④补课清单提交补齐：{'、'.join(_picked)}"
                    if ev4.strip():
                        _note += f"（佐证：{ev4.strip()[:60]}）"
                    st.session_state["have_last"] = _have_new
                    st.session_state["lp"] = _lp_new
                    st.session_state["lp_family"] = _fam_c
                    st.session_state["lp_top"] = _top_c
                    st.session_state["lp_major"] = _major_c
                    for _k in ("plan_md", "plan_engine", "plan_key", "weekly_md"):
                        st.session_state.pop(_k, None)
                    _sid = PF.save_snapshot(student, _lp_new, _have_new, _note,
                                            uid=UID, source="补课勾选")
                    # 记住这份快照是"本次会话刚提交"的：⑤用它决定用庆祝口径还是历史口径
                    st.session_state["last_checkin_sid"] = int(_sid or 0)
                    st.session_state["done_submitted"] = True    # 按钮变灰「已提交」
                    st.session_state["_clear_evidence"] = True   # 下一轮清空佐证框
                    st.rerun()

        st.divider()
        st.markdown("#### 本周任务卡")
        _wk = int(st.session_state.get("task_week", 1))
        _wk = max(1, min(_wk, len(gap4) or 1))
        _plan4 = WK.task_card(lp4, _wk)
        if _plan4.get("ok"):
            _w1, _w2, _w3 = st.columns([1, 1, 2.2])
            if _w1.button("← 上一周", disabled=_wk <= 1, width="stretch", key="wk_prev"):
                st.session_state["task_week"] = _wk - 1
                st.rerun()
            if _w2.button("下一周 →", disabled=_wk >= len(gap4), width="stretch", key="wk_next"):
                st.session_state["task_week"] = _wk + 1
                st.rerun()
            _w3.caption(f"第 {_wk} / {len(gap4)} 周")
            with st.container(border=True):
                st.markdown(WK.task_markdown(_plan4))
        else:
            hint(_plan4.get("msg", "暂无任务卡"))

# ---------------------------------------------------------------- ⑤ 成长档案
if is_screen(5):
    screen_head("⑤ 成长档案")
    # 删完记录的一次性收尾：清空表格选中。必须放在记录表实例化之前，
    # Streamlit 不允许在同一轮里改已经渲染过的 widget 的 state。
    if st.session_state.pop("_snap_reset_sel", False):
        st.session_state["snap_sel"] = {"selection": {"rows": []}}
    snaps = PF.list_snapshots(student, UID)
    cmp5 = PF.compare(student, UID)
    hist = PF.history(student, UID)

    # ---- 当前水平（取最新一条记录，永远不是缓存）
    if len(snaps):
        _cur = snaps.iloc[-1]
        _k5 = st.columns(4)
        kpi(_k5[0], "当前命中率", f"{float(_cur['命中率']):.0%}",
            f"最新记录 {str(_cur['时间'])[5:16]}")
        kpi(_k5[1], "已会技能", f"{int(_cur['已会技能数'])} 项", "③ 里勾选的全部技能")
        kpi(_k5[2], "待补缺口", f"{int(_cur['缺口数'])} 项", "目标榜内还没掌握的")
        kpi(_k5[3], "历史记录", f"{len(snaps)} 次",
            "定位保存 + 补课提交")
        st.write("")

    if cmp5.get("ok"):
        # 只有"本次会话刚在④提交的那份快照"才用"刚补齐"的庆祝口径；
        # 否则这条变化是历史事实，必须写清日期并说明"不是当前状态"，
        # 避免每次进页面重放同一句话、被当成缓存或刚发生的事。
        _last_id = int(snaps["id"].iloc[-1]) if len(snaps) else 0
        _fresh = bool(_last_id) and int(st.session_state.get("last_checkin_sid") or 0) == _last_id
        _fixed = "、".join(cmp5["fixed"][:6])
        if _fresh:
            st.markdown(
                f'<div class="grow">🎉 <b>刚补齐 {len(cmp5["fixed"])} 项'
                f'{("：" + _fixed) if _fixed else ""}</b><br>'
                f'<span class="big">{cmp5["prev"]["match"]:.0%} → {cmp5["now"]["match"]:.0%}</span>'
                f'　命中率（对比上一份记录）'
                f'{("　|　新增缺口 " + str(len(cmp5["new_gap"])) + " 项") if cmp5["new_gap"] else ""}'
                '</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="hist">🗂 <b>最近一次变化（历史记录 · {cmp5.get("t_now", "")}）</b><br>'
                f'{cmp5["headline"]}'
                '</div>', unsafe_allow_html=True)
        st.write("")
    elif len(snaps) == 1:
        st.caption("只有一条记录：再去 ③ 定位一次并存档（或在 ④ 提交补课），"
                   "这里才会出现「最近一次变化」。")

    # ---- 曲线 + 记录表都整行铺开：表更宽好点选，曲线能框出选中的那一次
    _pick_i = _snap_pick_index(snaps)
    st.markdown("#### 命中率成长曲线")
    st.markdown(f'<div class="fig">{viz.growth_curve(hist, _pick_i)}</div>', unsafe_allow_html=True)

    st.markdown("#### 定位记录")
    if snaps.empty:
        hint(f"「{student}」还没有定位记录。去「③ 我的定位」生成后点「存入成长档案」。")
    else:
        _sel5 = st.dataframe(
            snaps.drop(columns=["id"]), width="stretch", hide_index=True,
            height=min(48 + 35 * len(snaps), 300),
            on_select="rerun", selection_mode="multi-row", key="snap_sel",
            column_config={"命中率": st.column_config.ProgressColumn(
                "命中率", min_value=0, max_value=1, format="%.0f%%")})

        # ---- 最左列勾选（可多选）→ 一起删
        _rows5 = _snap_pick_rows(snaps)
        if _rows5:
            _del_ids = [int(snaps.iloc[i]["id"]) for i in _rows5]
            if st.button(f"🗑 删除选中 {len(_del_ids)} 条", key="snap_del_btn",
                         width="stretch"):
                for _sid in _del_ids:
                    PF.delete_snapshot(_sid, UID)
                    if int(st.session_state.get("last_checkin_sid") or 0) == _sid:
                        st.session_state.pop("last_checkin_sid", None)
                st.session_state.pop("weekly_md", None)
                st.session_state["_snap_reset_sel"] = True
                st.rerun()

        st.download_button("导出成长档案（Markdown）",
                           PF.export_markdown(student, UID).encode("utf-8"),
                           f"成长档案_{student}.md", "text/markdown", width="stretch")
    st.divider()
    st.markdown("#### 本周成长周报")
    _wc1, _wc2 = st.columns([1, 2.4])
    if _wc1.button("📰 生成本周周报", width="stretch", key="gen_weekly"):
        st.session_state["weekly_md"] = WK.weekly_report(student, UID)
    _wr = st.session_state.get("weekly_md")
    if _wr and _wr.get("ok"):
        with st.container(border=True):
            st.markdown(_wr["text"])
        _wc2.download_button("下载周报（Markdown）", _wr["text"].encode("utf-8"),
                             f"成长周报_{student}_{_wr.get('ts', '')}.md", "text/markdown",
                             width="stretch")
    elif _wr:
        hint(_wr.get("msg", "快照不足两份，先多存一次定位"))

# ---------------------------------------------------------------- ⑥ AI 顾问
if is_screen(6):
    screen_head("⑥ AI 顾问")
    st.write("")

    cc1, cc2 = st.columns([1.35, 1])
    with cc1:
        #st.markdown("#### 对话式规划")
        if "chat" not in st.session_state:
            st.session_state["chat"] = []

        # 快捷提问：不知道问什么的学生，从这三个开始
        q1, q2, q3 = st.columns(3)
        _quick = ["我该先学什么？", "命中率够找工作吗？", "帮我写一份规划"]
        for _i, _col in enumerate([q1, q2, q3]):
            if _col.button(_quick[_i], key=f"quick{_i}", width="stretch"):
                st.session_state["pending_q"] = _quick[_i]
                st.rerun()

        for m in st.session_state["chat"]:
            with st.chat_message("assistant" if m["role"] == "ai" else "user"):
                st.markdown(m["content"])
        quick_q = st.session_state.pop("pending_q", None)
        with st.form("ask_form", clear_on_submit=True):
            fc1, fc2 = st.columns([4.2, 1])
            typed = fc1.text_input("问 AI 顾问", placeholder="先学什么？哪个城市机会多？规划怎么写？",
                                   label_visibility="collapsed")
            sent = fc2.form_submit_button("发送", type="primary", width="stretch")
        prompt = quick_q or (typed.strip() if sent and typed.strip() else None)
        if prompt:
            st.session_state["chat"].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                ph = st.empty()
                acc: list[str] = []

                def _delta(piece: str) -> None:
                    acc.append(piece)
                    ph.markdown("".join(acc) + " ▌")

                _lp6 = lp_ok()
                _ctx = CZ.pack_context(
                    st.session_state.get("have_last", []),
                    st.session_state.get("lp_family", "全部"),
                    _lp6, c_cov(db_ver(), major_name), ov, student)
                _r = CZ.chat(prompt, _ctx, st.session_state["chat"], on_delta=_delta,
                             lp=_lp6)
                ph.markdown(_r["text"])
                _lv_c, _txt_c = FC.badge(
                    _r["text"],
                    FC.collect(lp=_lp6, cov=c_cov(db_ver(), major_name), ov=ov))
                if _lv_c == "ok":
                    st.caption("✅ " + _txt_c)
                elif _lv_c == "warn":
                    st.caption("⚠️ " + _txt_c)
                if _r.get("note"):
                    st.caption("ℹ️ " + _r["note"])
            st.session_state["chat"].append({"role": "ai", "content": _r["text"],
                                             "engine": _r.get("engine", "")})
            st.rerun()
        if st.session_state["chat"]:
            ecol1, ecol2 = st.columns([1, 2])
            if ecol1.button("清空对话", width="stretch"):
                st.session_state.pop("chat", None)
                st.rerun()


    with cc2:
        #st.markdown("#### 一键生成职业规划书（五节）")

        def _lp_key() -> str:
            """当前定位的指纹：定位（姓名/专业/岗位族/命中率/已会技能）一变，旧规划书即失效。"""
            _l = st.session_state.get("lp")
            if not (_l and _l.get("ok")):
                return ""
            _hv = st.session_state.get("have_last", [])
            # 技能清单要进指纹：换掉一项技能但命中率恰好不变时，旧规划书也必须作废
            return "|".join(map(str, (
                st.session_state.get("student_name", ""), major_name, _l.get("major", ""),
                st.session_state.get("lp_family", ""), round(float(_l.get("match", 0)), 4),
                len(_hv), tuple(sorted(str(x) for x in _hv)))))

        # 旧版规划书一旦与当前定位对不上，直接作废，不再挂在新页面上
        if st.session_state.get("plan_md") and st.session_state.get("plan_key") != _lp_key():
            for _k in ("plan_md", "plan_engine", "plan_key"):
                st.session_state.pop(_k, None)
            st.caption("上一版规划书基于旧定位生成，已自动清空；重新点「生成我的职业规划书」即可。")

        _lp6 = lp_ok()
        if not (_lp6 and _lp6.get("ok")):
            if (st.session_state.get("lp") or {}).get("ok"):
                lp_expired_note()
            else:
                hint("先去「③ 我的定位」生成一次")
        if st.button("📝 生成我的职业规划书", type="primary", width="stretch",
                     disabled=not (_lp6 and _lp6.get("ok"))):
            with st.spinner("按你的档案生成规划书…"):
                plan = CZ.plan_document(
                    st.session_state.get("have_last", []),
                    st.session_state.get("lp_family", "全部"),
                    _lp6, c_cov(db_ver(), major_name), ov, student)
            st.session_state["plan_md"] = plan["text"]
            st.session_state["plan_engine"] = plan.get("engine", "")
            st.session_state["plan_key"] = _lp_key()

    # 规划书整行显示：五节文档塞进 1/3 宽的右栏会被压成窄条，表格根本读不了
    plan_md = st.session_state.get("plan_md")
    if plan_md:
        _phead, _psecs = md_parts(plan_md, 2)
        _ptitle = next((ln[2:].strip() for ln in str(plan_md).splitlines()
                        if ln.startswith("# ")), f"职业规划书 · {student}")
        _pmeta = "　".join(ln.lstrip("> ").strip() for ln in _phead.splitlines()
                          if ln.strip().startswith(">"))
        st.markdown("### 我的职业规划书")
        st.markdown(
            f'<div class="dochead"><div class="t">📄 {_ptitle}</div>'
            f'<div class="m">{_pmeta}</div></div>', unsafe_allow_html=True)
        if _psecs:
            for _pi, (_pt, _pb) in enumerate(_psecs, 1):
                with st.container(border=True, key=f"plansec{_pi}"):
                    st.markdown(
                        f'<div class="sechead"><span class="num">{_pi:02d}</span>{_pt}</div>',
                        unsafe_allow_html=True)
                    st.markdown(_pb)
        else:
            # 在线工作流偶尔不按二级标题输出：退化成整篇渲染，不丢内容
            with st.container(border=True, key="plansec0"):
                st.markdown(plan_md)
        p1c, p2c = st.columns(2)
        p1c.download_button("下载规划书（Markdown）", plan_md.encode("utf-8"),
                            f"职业规划书_{student}.md", "text/markdown", width="stretch")
        if p2c.button("导出规划书 Word", width="stretch"):
            path = write_docx(plan_md, f"职业规划书_{student}")
            st.success(f"已存到 {path}")

    # 平台引擎工作台、Coze / Dify 接入配置已按要求从学生端移除

# ---------------------------------------------------------------- ⑦ 求职实战
if is_screen(7):
    screen_head("⑦ 求职实战")

    have_jd = st.session_state.get("have_last", [])
    fam_jd = st.session_state.get("lp_family", "全部") or "全部"
    have_set = {str(s).strip() for s in have_jd}
    # 与③同一个口径：③ 的滑块决定了取需求榜前几项，这里必须沿用，否则同一岗位族
    # 会出现「定位 76% / 简历 78%」两个命中率，答辩现场必被追问
    _lp_top = int(st.session_state.get("lp_top", 10) or 10)

    # ---------------- 板块 1 · JD 透视镜 ----------------
    #st.markdown("### JD 透视镜")

    def _esc(x) -> str:
        return (str(x or "")
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    _applied_ids = AP.applied_jd_ids(UID)
    # JD 只取库内岗位（「粘贴 JD」入口已按要求删除）
    r_jd = None
    fam_sel = fam_jd

    _pool = c_job_pool(db_ver())
    if _pool.empty:
        hint("还没有岗位数据。")
    else:
        _f1, _f2, _f3, _f4 = st.columns([1.05, 1, 1.6, 1.15])
        _fams = ["全部"] + sorted([x for x in _pool["family"].dropna().unique() if x])
        _fam = search_select("方向", _fams, "jd_fam",
                             index=_fams.index(fam_jd) if fam_jd in _fams else 0,
                             placeholder="🔍 搜索方向", ctx=_f1)
        # 城市不再只取前 15：库里有多少个就列多少个（按岗位数排），要找哪个搜哪个
        _cities = ["不限"] + _pool["city"].value_counts().index.tolist()
        _city = search_select("城市", _cities, "jd_city", placeholder="🔍 搜索城市",
                              ctx=_f2)
        _kw = _f3.text_input("关键词（岗位 / 公司）", key="jd_kw",
                             placeholder="留空看全部；例如：数据分析")
        _f4.write("")
        _only_new = _f4.checkbox("只看未投", value=False, key="jd_only_new")
        _sk_only = _f4.checkbox("只看有技能要求", value=True, key="jd_skill_only")

        _d = _pool
        if _fam != "全部":
            _d = _d[_d["family"] == _fam]
        if _city != "不限":
            _d = _d[_d["city"] == _city]
        if str(_kw or "").strip():
            _k = str(_kw).strip()
            _d = _d[_d["title"].str.contains(_k, na=False)
                    | _d["company"].str.contains(_k, na=False)]
        if _sk_only:
            _d = _d[_d["skills"].map(len) > 0]
        if _only_new and _applied_ids:
            _d = _d[~_d["jd_id"].isin(_applied_ids)]

        def _hit(sk: list[str]) -> float:
            if not sk:
                return 0.0
            return sum(1 for x in sk if x in have_set) / len(sk)

        _d = _d.copy()
        _d["hit"] = _d["skills"].map(_hit)
        _d = (_d.sort_values(["hit", "salary_mid", "jd_id"],
                             ascending=[False, False, True],
                             na_position="last").reset_index(drop=True))
        _n_pool = len(_d)

        # 筛选一变就回第 1 条：否则游标停在上一个筛选的序号上，会跳到不相干的岗位
        _sig = f"{_fam}|{_city}|{_kw}|{int(_only_new)}|{int(_sk_only)}|{_n_pool}"
        if st.session_state.get("jd_sig") != _sig:
            st.session_state["jd_sig"] = _sig
            st.session_state["jd_cursor"] = 0
        _cur = int(st.session_state.get("jd_cursor", 0) or 0)
        _cur = max(0, min(_cur, max(_n_pool - 1, 0)))
        st.session_state["jd_cursor"] = _cur

        if _n_pool == 0:
            hint("这个筛选下一共有 0 条岗位。放宽城市或关键词试试——"
                    f"岗位库共 {len(_pool)} 条，方向筛「全部」就能看到。")
        else:
            _nav1, _nav2, _nav3, _nav4, _nav5 = st.columns([0.9, 1, 2.4, 1, 0.9])
            if _nav1.button("⏮ 首页", width="stretch", key="jd_first", disabled=_cur == 0):
                st.session_state["jd_cursor"] = 0
                st.rerun()
            if _nav2.button("← 上一岗", width="stretch", key="jd_prev", disabled=_cur == 0):
                st.session_state["jd_cursor"] = _cur - 1
                st.rerun()
            _nav3.markdown(
                f'<div class="jc-load" style="text-align:center;padding-top:6px">第 '
                f'<b>{_cur + 1}</b> / {_n_pool} 条</div>',
                unsafe_allow_html=True)
            if _nav4.button("下一岗 →", type="primary", width="stretch",
                            key="jd_next", disabled=_cur >= _n_pool - 1):
                st.session_state["jd_cursor"] = _cur + 1
                st.rerun()
            if _nav5.button("末页 ⏭", width="stretch", key="jd_last",
                            disabled=_cur >= _n_pool - 1):
                st.session_state["jd_cursor"] = _n_pool - 1
                st.rerun()

            job = _d.iloc[_cur]
            _jd_id = str(job["jd_id"])
            _title_full = str(job["title"] or "—")
            # 招聘站标题常带「五险一金+」「双休·」这类前缀，展示取 + 号后面那段
            _title = _title_full.split("+")[-1].strip() if "+" in _title_full else _title_full
            _sk = list(job["skills"])
            _hit_v = float(job["hit"])
            _meta_bits = [str(job["city"] or ""), str(job["district"] or ""),
                          str(job["salary_text"] or "面议"), str(job["edu"] or "学历不限"),
                          str(job["exp"] or "经验不限"), str(job["company_size"] or "")]
            _meta = " · ".join([x for x in _meta_bits if x and x != "nan"])
            _chips = "".join(
                f'<span class="sk {"on" if s in have_set else "off"}">{_esc(s)}</span>'
                for s in _sk[:14])
            if not _chips:
                _chips = '<span class="sk">这条没抓到技能要求</span>'
            _done = _jd_id in _applied_ids
            st.markdown(
                f'<div class="jobcard">'
                f'<div class="jc-top"><div>'
                f'<div class="jc-title">{_esc(_title)}</div>'
                f'<div class="jc-co">{_esc(job["company"] or "—")}</div>'
                f'<div class="jc-meta">{_esc(_meta)}　|　发布 {_esc(job["publish_date"])}</div>'
                f'</div><div class="jc-hit"><b>{_hit_v:.0%}</b><span>你会多少</span></div></div>'
                f'<div class="jc-bar"><i style="width:{max(_hit_v * 100, 2):.0f}%"></i></div>'
                f'<div class="jc-skills">{_chips}</div></div>',
                unsafe_allow_html=True)

            _b1, _b2 = st.columns([1.15, 1.1])
            if _done:
                _b1.button("✓ 已记入投递", width="stretch", key="jd_applied_btn",
                           disabled=True)
            elif _b1.button("✅ 立即投递", type="primary", width="stretch", key="jd_apply"):
                _r = AP.log_apply(UID, student, _jd_id, _title, job["company"],
                                  job["city"], _hit_v, "JD体检", job["url"])
                if _r.get("ok"):
                    pass          # 按钮下一轮直接变「✓ 已记入投递」，不再弹提示
                else:
                    st.warning(_r.get("msg", "没记上"))
                st.rerun()
            if str(job["url"] or "").startswith("http"):
                _b2.link_button("🔗 看原招聘页", job["url"], width="stretch")

            if _sk:
                fam_sel = str(job["family"] or fam_sel)
                r_jd = {"ok": True, "counts": {s: 1 for s in _sk}, "skills": _sk,
                        "family_guess": fam_sel, "from_db": True,
                        "title": _title, "company": str(job["company"] or "")}
            else:
                hint("此岗位没有技能要求——点「下一岗」换一条。")
    if r_jd and not r_jd.get("ok"):
        st.warning(r_jd.get("msg", "JD 为空"))
    elif r_jd and r_jd.get("ok"):
        _from_db = bool(r_jd.get("from_db"))
        jd_skills = r_jd["skills"]
        jd_counts = r_jd["counts"]
        matched = [s for s in jd_skills if s in have_set]
        missing = [s for s in jd_skills if s not in have_set]
        jd_match = (sum(jd_counts[s] for s in matched) / max(sum(jd_counts.values()), 1))

        k1, k2, k3, k4 = st.columns(4)
        kpi(k1, "岗位要求技能", f"{len(jd_skills)} 项",
            f"{r_jd.get('company', '')[:12]}…" if _from_db else "按词典标准名归一，与平台同口径")
        kpi(k2, "你已经会", f"{len(matched)} 项", "、".join(matched[:5]) or "—")
        kpi(k3, "还缺", f"{len(missing)} 项", "、".join(missing[:5]) or "全中！")
        kpi(k4, "命中率", f"{jd_match:.0%}",
            "按这条岗位要求的技能条数算" if _from_db else "按 JD 里技能出现次数加权")

        cmap_jd = PW.course_map(major_name)
        covm_jd = PW.cover_map(major_name)
        if missing:
            rows = [{"技能": s, "JD 提到次数": jd_counts[s],
                     "相关课程": cmap_jd.get(s, "") or "本专业暂无对应课程 → 用 1+X 证书 / 在线课替代",
                     "课程覆盖": covm_jd.get(s, 0.0)} for s in missing]
            mt = pd.DataFrame(rows).sort_values("JD 提到次数", ascending=False)
            st.markdown(f"#### 你还缺什么（{len(missing)} 项）")
            st.dataframe(mt, width="stretch", hide_index=True, height=min(46 + 35 * len(mt), 300))
            top2 = mt.head(2)
            tc1, tc2 = st.columns(2)
            for i, (_, rr) in enumerate(top2.iterrows()):
                with (tc1 if i == 0 else tc2):
                    st.markdown(
                        f'<div class="todo red"><b>先补「{rr["技能"]}」</b><br>'
                        f'这条 JD 提到 {rr["JD 提到次数"]} 次。去《{rr["相关课程"]}》把对应章节学扎实，'
                        f'本周交出一个能展示的小作业（清洗一份数据 / 复现一个图表）。</div>',
                        unsafe_allow_html=True)

        lp_fam = PW.build_path(have_jd, fam_sel, top=_lp_top, major=major_name)
        if lp_fam.get("ok"):
            delta = jd_match - lp_fam["match"]
            word = "高于" if delta >= 0 else "低于"
            st.caption(f"该 JD 命中率 {jd_match:.0%}，{word}「{fam_sel}」方向整体命中率"
                       f"（{lp_fam['match']:.0%}）。")
        if not have_jd:
            hint("还没在 ③ 我的定位 里勾「我已掌握的技能」""")

    st.divider()

    # ---------------- 板块 2 · 简历技能段生成器 ----------------
    st.markdown("### 简历技能段生成器")
    if not have_jd:
        hint("先去 ③ 我的定位 勾上已会技能，再来生成简历技能段。")
    else:
        lp_cv = PW.build_path(have_jd, fam_jd, top=_lp_top, major=major_name)
        if lp_cv.get("ok"):
            held_cv = lp_cv["table"][lp_cv["table"]["已掌握"]].sort_values("占比", ascending=False)
            L_cv = ["# 专业技能\n",
                    f"目标方向：{fam_jd}\n",
                    "## 专业技能"]
            for rr in held_cv.itertuples():
                course = str(rr.相关课程)
                ev = f"，系统学习自《{course}》" if course and course != "本专业暂无对应课程" else ""
                L_cv.append(f"- **{rr.技能}**：目标岗位中 {rr.占比:.0%} 的岗位要求，能独立使用{ev}")
            L_cv.append("\n## 成长记录（可写进自我评价）")
            cmp_cv = PF.compare(student, UID)
            if cmp_cv.get("ok"):
                L_cv.append(f"- {cmp_cv['headline']}")
            L_cv.append(f"- 目标「{fam_jd}」岗位需求命中率 {lp_cv['match']:.0%}")
            resume_md = "\n".join(L_cv)
            rv1, rv2, rv3 = st.columns([1, 1, 2])
            show_cv = rv1.button("👁 预览", width="stretch")
            rv2.download_button("⬇ 下载 Markdown", resume_md.encode("utf-8"),
                                f"{student}_简历技能段.md", "text/markdown", width="stretch")
            if rv3.button("📄 导出 Word", width="stretch"):
                path = write_docx(resume_md, f"{student}_简历技能段")
                st.success(f"已存到 {path}")
            if show_cv or st.session_state.get("_show_resume"):
                st.session_state["_show_resume"] = True
                with st.container(border=True):
                    st.markdown(resume_md)
            #st.caption(f"技能段可直接复制进简历；自我评价可写：「对照目标岗位 " f"{lp_cv['match']:.0%} 的技能要求，已系统掌握 ……」。")

    st.divider()

    # ---------------- 板块 3 · 模拟面试（数字人陪练） ----------------
    st.markdown("### 模拟面试")
    if not st.session_state.get("_iv_warm"):
        st.session_state["_iv_warm"] = True
        ASR.warmup()  # 后台加载语音识别模型，学生开口时不用等
    if r_jd and r_jd.get("ok") and r_jd["skills"]:
        q_skills = r_jd["skills"][:5]
        q_src = (f"题目来自挑选岗位（{r_jd.get('company') or '库内岗位'}）"
                 if r_jd.get("from_db") else "题目来自刚粘贴的这条 JD")
    else:
        q_skills = JDX.A_skills_demand(fam_jd, 5)
        q_src = (f"题目来自「{fam_jd}」岗位的高频技能要求" if fam_jd and fam_jd != "全部"
                 else "题目来自全部岗位的高频技能要求")

    if not q_skills:
        hint("还没有岗位数据。")
    else:
        # 题数必须按"实际能出几题"算，不能写死 5：JD 只识别出 3 个技能时真的只出 3 题，
        # 而开场白会说"问你 3 个能力点"——文案写死 5 题就自相矛盾了（演示现场一眼看穿）。
        _qs_uniq: list[str] = []
        for _s in q_skills:
            _s = str(_s or "").strip()
            if _s and _s not in _qs_uniq:
                _qs_uniq.append(_s)
        _n_q = max(1, min(len(_qs_uniq), 5))
        st.markdown(f"<style>{IV.CSS}</style>", unsafe_allow_html=True)
        iv = st.session_state.get("iv")
        _lp7 = lp_ok()
        _gap7 = ([str(x) for x in _lp7["gap"]["技能"].head(3).tolist()]
                 if _lp7 and _lp7.get("ok") else [])

        def _iv_save() -> None:
            """每答完一轮就落库：刷新页面能接着面；演示场不写历史，免得脏数据。"""
            if iv.get("mode") != "demo":
                PF.save_interview(student, iv, UID)

        def _iv_finalize() -> None:
            IV.finish(iv)
            iv["report"] = IV.report_md(iv, _gap7)
            _iv_save()

        def _iv_polish(skill: str = "") -> None:
            """把规则生成的那句台词交给在线模型润色；失败就保留原句，流程一点不动。"""
            if iv.get("mode") == "demo":
                return
            for _t in reversed(iv["turns"]):
                if _t.get("role") == "ai":
                    _new = IV.apply_ai(iv, _t["text"], skill)
                    if _new:
                        _t["text"] = _new
                        iv["mode"] = "ai"
                    break

        if not iv:
            ic1, ic2 = st.columns([1, 2.1])
            with ic1:
                st.markdown(IV.avatar_html(st.session_state.get("iv_persona", "温和型 HR"), "idle"),
                            unsafe_allow_html=True)
            with ic2:

                persona = st.radio("选一位面试官", list(IV.PERSONAS), horizontal=True, key="iv_persona")
                _pp = IV.PERSONAS[persona]
                st.markdown(f'<div class="ivrow"><span>风格</span><b>{_pp["style"]}</b></div>'
                            f'<div class="ivrow"><span>重点看</span><b>{_pp["tag"]}</b></div>',
                            unsafe_allow_html=True)
                st.write("")
                b1, b2 = st.columns(2)
                if b1.button("▶ 开始面试", type="primary", width="stretch"):
                    st.session_state["iv"] = IV.new_state(
                        student, fam_jd, IV.build_questions(q_skills, 5), persona)
                    st.session_state.pop("_iv_last_asr", None)
                    st.session_state.pop("iv_mic_sig", None)
                    st.rerun()
                if b2.button("⚡ 演示一场", width="stretch",
                             help="用三段预置回答快速演示"):
                    _d = IV.new_state(student, fam_jd, IV.build_questions(q_skills, 3),
                                      persona, mode="demo")
                    for _ in range(14):
                        if _d["stage"] == "report":
                            break
                        if _d["stage"] == "closing":
                            IV.skip_closing(_d)
                            break
                        IV.answer(_d, IV.demo_answer(IV.cur_q(_d).get("skill", ""),
                                                     _d["stage"] == "probe"))
                    IV.finish(_d)
                    _d["report"] = IV.report_md(_d, _gap7)
                    st.session_state["iv"] = _d
                    st.rerun()
                _pend = PF.pending_interview(student, UID)
                if _pend.get("ok"):
                    if st.button(f"⏯ 继续上次没走完的面试（第 {_pend['idx']}/{_pend['n']} 题）",
                                 width="stretch"):
                        st.session_state["iv"] = _pend["state"]
                        st.rerun()
        else:
            _stage = iv.get("stage", "ask")
            _mood = "nod" if _stage == "report" else "talk"
            _p, _n = IV.progress(iv)
            iv_left, iv_right = st.columns([1, 2.15])
            with iv_left:
                st.markdown(IV.avatar_html(iv.get("persona"), _mood), unsafe_allow_html=True)
                _pct = int(_p / max(_n, 1) * 100)
                st.markdown(
                    f'<div class="ivrow"><span>进度</span><span class="b">'
                    f'<i style="width:{_pct}%"></i></span><span>{_p}/{_n}</span></div>'
                    f'<div class="ivrow"><span>用时</span><b>{IV.elapsed_min(iv)} 分钟</b></div>',
                    unsafe_allow_html=True)
                # 数字人开口说话：合成面试官最新一句台词，自动播放；失败静默
                _last_ai = next((t for t in reversed(iv.get("turns", []))
                                 if t.get("role") == "ai"), None)
                _voice = st.toggle("🔊 ", key="iv_voice", value=True)
                if _voice and _last_ai:
                    _mp3 = TTS.speak(_last_ai["text"], TTS.voice_of(iv.get("persona")))
                    if _mp3:
                        _auto = iv.get("_tts_k") != _last_ai["text"]
                        iv["_tts_k"] = _last_ai["text"]
                        st.audio(_mp3, autoplay=_auto)
                        st.caption(f"🔈 {TTS.LAST_ENGINE or '缓存'} · 说的就是下面这句")
                    else:
                        st.caption("🔇 声音合成暂不可用，字幕照常")
                if _stage != "report":
                    _n_ans = len(iv.get("scores") or [])
                    st.caption(f"共 {_n} 题，每题可能追问 1 次；已答 {_n_ans} 题，"
                               f"答完任意一题后可随时提前结束。")
                    if _n_ans and st.button("⏹ 提前结束并出反馈", key="iv_end",
                                            type="primary", width="stretch"):
                        _iv_finalize()
                        st.session_state["iv"] = iv
                        st.rerun()
                    if st.button("放弃本场", key="iv_drop", width="stretch"):
                        if iv.get("mode") != "demo":
                            PF.delete_interview(int(iv.get("sid") or 0), UID)
                        st.session_state.pop("iv", None)
                        st.rerun()
            with iv_right:
                with st.container(height=430, border=True):
                    for _t in iv["turns"]:
                        _av = "🧑‍💼" if _t["role"] == "ai" else "🧑‍🎓"
                        with st.chat_message("assistant" if _t["role"] == "ai" else "user", avatar=_av):
                            st.markdown(_t["text"])
                if _stage in ("ask", "probe"):
                    _ph = ("面试官追问了一句，接着答。" if _stage == "probe"
                           else "3–5 句话：背景 → 你做了什么 → 结果（带数字）。")
                    # 语音作答：说一句，面试官听完立刻接话
                    _voice_ok, _voice_name = ASR.engine_ready()
                    if _voice_ok:
                        _vc1, _vc2 = st.columns([2.3, 1])
                        with _vc1:
                            _mic = st.audio_input("🎤 ",
                                                  key="iv_mic")
                        with _vc2:
                            #st.caption(f"识别引擎：{_voice_name}")
                            if iv.get("_undo") and st.button("↩️ 撤回上一句", key="iv_undo",
                                                             width="stretch"):
                                IV.undo_last(iv)
                                _iv_save()
                                st.session_state["iv"] = iv
                                st.rerun()
                        _last_asr = st.session_state.get("_iv_last_asr")
                        if _last_asr:
                            st.caption(f"🎤 上一句识别：{_last_asr['text']}"
                                       f"（{_last_asr['engine']} · {_last_asr['ms'] / 1000:.1f}s）")
                        if _mic is not None:
                            _sig = (len(_mic.getvalue()), hash(_mic.getvalue()))
                            if st.session_state.get("iv_mic_sig") != _sig:
                                st.session_state["iv_mic_sig"] = _sig
                                with st.spinner("面试官正在听你说…"):
                                    _r = ASR.transcribe(_mic.getvalue())
                                if _r.get("ok") and _r["text"].strip():
                                    st.session_state["_iv_last_asr"] = _r
                                    _sk_now = IV.cur_q(iv).get("skill", "")
                                    IV.answer(iv, _r["text"])
                                    _iv_polish(_sk_now)
                                    _iv_save()
                                    st.session_state["iv"] = iv
                                    st.rerun()
                                else:
                                    st.warning(_r.get("err") or "没听清，再说一遍或直接打字。")
                    with st.form("iv_form", clear_on_submit=True):
                        _ans = st.text_area("你的回答", height=84, key="iv_ans",
                                            placeholder=_ph, label_visibility="collapsed")
                        _c1, _c2 = st.columns([1, 3])
                        _sent = _c1.form_submit_button("提交回答", type="primary", width="stretch")
                        #_c2.caption("Ctrl+Enter 也能提交")
                    if _sent:
                        if not _ans.strip():
                            st.warning("先写两句再提交。")
                        else:
                            _sk_now = IV.cur_q(iv).get("skill", "")
                            IV.answer(iv, _ans)
                            _iv_polish(_sk_now)
                            _iv_save()
                            st.session_state["iv"] = iv
                            st.rerun()
                    # 自由交流：学生随时可以问面试官，不影响面试进度
                    with st.expander("💬 想跟面试官聊两句？", expanded=False):
                        with st.form("iv_free", clear_on_submit=True):
                            _fq = st.text_input("问面试官", key="iv_fq",
                                                placeholder="比如：这题能给个提示吗？/ 你们加班多吗？/ 你是真人吗？",
                                                label_visibility="collapsed")
                            _fs = st.form_submit_button("发送", width="stretch")
                        if _fs:
                            if not _fq.strip():
                                st.caption("先输入一句话再发送。")
                            else:
                                IV.free_chat(iv, _fq)
                                _iv_save()
                                st.session_state["iv"] = iv
                                st.rerun()
                elif _stage == "closing":
                    with st.form("iv_close", clear_on_submit=True):
                        _back = st.text_input("你想问面试官什么？", key="iv_back",
                                              placeholder="比如：团队现在主要做什么？新人怎么带？")
                        _c1, _c2 = st.columns(2)
                        _s1 = _c1.form_submit_button("提问并结束", type="primary", width="stretch")
                        _s2 = _c2.form_submit_button("直接结束", width="stretch")
                    if _s1 or _s2:
                        if _s1 and _back.strip():
                            IV.answer(iv, _back)
                        else:
                            IV.skip_closing(iv)
                        _iv_finalize()
                        st.session_state["iv"] = iv
                        st.rerun()
            # 反馈区不放在右栏：右栏只有 2/3 宽，表格与逐题卡会被挤成窄条 → 整行显示
            if _stage == "report":
                _ov = IV.overall(iv)
                _nd = len(iv.get("scores") or [])
                _dims = "".join(
                    f'<div class="dimcard"><div class="k">{k}</div>'
                    f'<div class="bar"><i style="width:'
                    f'{min(float(_ov["dims"][k]) / 5, 1) * 100:.0f}%"></i></div>'
                    f'<div class="v">{_ov["dims"][k]:.1f}<span> / 5</span></div></div>'
                    for k in IV.DIM_NAMES)
                st.markdown(
                    f'<div class="ivhero"><div class="scbox"><div class="sc">{_ov["score"]}'
                    f'<span>/100</span></div><div class="cap">训练综合得分</div></div>'
                    f'<div><div class="lv">{_ov["level"]}</div>'
                    f'<div class="meta">方向「{iv.get("family", "全部")}」　·　{_nd} 题　·　'
                    f'约 {IV.elapsed_min(iv)} 分钟　·　面试官 {iv.get("persona", "AI 模拟")}<br>'
                    f'结构 / 具体 / 技术 / 落地四维各 5 分，按回答里的证据点折算 100 分'
                    f'</div></div></div>'
                    f'<div class="dimgrid">{_dims}</div>', unsafe_allow_html=True)
                st.write("")

                # 报告按「## 一节」拆开：逐题复盘再拆成单题卡，整行宽度下更好读
                _rhead, _rsecs = md_parts(iv["report"], 2)
                _want = ("逐题复盘", "最该改", "下一步")
                _pick = [(t, b) for t, b in _rsecs if any(w in t for w in _want)]
                _tabs = st.tabs([t for t, _ in _pick] + ["完整反馈"]) if _pick else None
                if _tabs:
                    for _ti, (_rt, _rb) in enumerate(_pick):
                        with _tabs[_ti]:
                            if "逐题" in _rt:
                                _qs = md_parts(_rb, 3)[1]
                                if _qs:
                                    for _qi, (_qt, _qb) in enumerate(_qs, 1):
                                        _sk = _qt.split("·")[-1].strip()
                                        _badge = ""
                                        if _qi - 1 < _nd:
                                            _badge = (f'<span class="qs">'
                                                      f'{iv["scores"][_qi - 1]["score"]} 分</span>')
                                        st.markdown(
                                            f'<div class="qhead"><span class="qn">第 {_qi} 题</span>'
                                            f'<span class="qk">{_sk}</span>{_badge}</div>',
                                            unsafe_allow_html=True)
                                        with st.container(border=True, key=f"ivq{_qi}"):
                                            st.markdown(_qb)
                                else:
                                    with st.container(border=True, key="ivsub"):
                                        st.markdown(_rb)
                            else:
                                with st.container(border=True, key=f"ivsec{_ti}"):
                                    st.markdown(_rb)
                    with _tabs[-1]:
                        with st.container(border=True, key="ivfull"):
                            st.markdown(iv["report"])
                else:
                    with st.container(border=True, key="ivfull"):
                        st.markdown(iv["report"])
                _d1, _d2, _d3 = st.columns([1, 1, 1.25])
                _d1.download_button("下载反馈（Markdown）", iv["report"].encode("utf-8"),
                                    f"模拟面试反馈_{student}_{str(iv.get('ended_at', ''))[:10]}.md",
                                    "text/markdown", width="stretch")
                if _d2.button("🔁 再来一场", width="stretch"):
                    st.session_state.pop("iv", None)
                    st.rerun()
                if _d3.button("🤖 让 AI 顾问讲成 3 个动作", width="stretch"):
                    _ctx7 = CZ.pack_context(have_jd, fam_jd, _lp7,
                                            c_cov(db_ver(), major_name), ov, student)
                    _r7 = CZ.chat("模拟面试反馈。把它拆成本周就能做的 "
                                  "3 个具体动作：\n\n"
                                  + iv["report"][:1500], _ctx7, [])
                    st.markdown(f"**AI 顾问**（引擎：{_r7.get('engine', '')}）")
                    st.markdown(_r7["text"])

        with st.expander("📚 历史面试记录", expanded=False):
            _hv = PF.list_interviews(student, UID)
            if _hv.empty:
                st.caption("还没有面试记录")
            else:
                st.dataframe(_hv.drop(columns=["id"]), width="stretch", hide_index=True, height=210,
                             column_config={"得分": st.column_config.ProgressColumn(
                                 "得分", min_value=0, max_value=100, format="%d")})
                _sid = st.selectbox(
                    "回看哪一场", _hv["id"].tolist(), key="iv_hist",
                    format_func=lambda x: (f"{_hv.loc[_hv['id'] == x, '时间'].iloc[0]} · "
                                           f"{_hv.loc[_hv['id'] == x, '方向'].iloc[0]} · "
                                           f"{int(_hv.loc[_hv['id'] == x, '得分'].iloc[0])} 分"))
                _rec = PF.load_interview(int(_sid), UID)
                if _rec.get("ok") and _rec.get("report"):
                    with st.container(height=380, border=True):
                        st.markdown(_rec["report"])

    st.divider()

    st.markdown("### 投递记录与转化")
    if not st.session_state.get("_legacy_done"):     # 老投递补事件（幂等，一次就够）
        AP.ensure_legacy()
        st.session_state["_legacy_done"] = True
    _swept = AP.timeout_sweep(UID)          # 14 天规则：满期无正向信号 → 自动补「无回音」
    _as = AP.stats(UID)
    _k1, _k2, _k3, _k4 = st.columns(4)
    kpi(_k1, "已投递", _as["n"], f"在流程中 {_as['pending']} 条")
    kpi(_k2, "约面 / 面试", _as["interview"], f"转化率 {_as['rate']:.0%}（约面 ÷ 已投）")
    kpi(_k3, "已录用", _as["offer"], "offer 数")
    kpi(_k4, "无回音", _as["no_reply"],
        f"满 {AP.TIMEOUT_DAYS} 天自动判 · 含明确拒信 {_as['reject']} 条")
    if _swept:
        st.toast(f"{_swept} 条投递满 {AP.TIMEOUT_DAYS} 天无回音，已自动更新状态", icon="⏳")

    with st.expander("📷 收到面试 / offer 通知？拖一张截图进来",
                     expanded=False):

        _up = st.file_uploader("通知截图", type=["png", "jpg", "jpeg", "webp", "bmp"],
                               key="shot_up", label_visibility="collapsed")
        _sc1, _sc2 = st.columns([1, 1.6])
        if _sc1.button("🔍 识别截图", type="primary", width="stretch", key="shot_ocr"):
            if not _up:
                st.warning("先选一张截图。")
            else:
                _o = AP.ocr_image(_up.getvalue())
                if not _o.get("ok"):
                    st.error(_o.get("msg", "识别失败"))
                else:
                    st.session_state["shot_res"] = AP.ingest_notice(UID, _o["text"], "截图OCR")
                    st.session_state["shot_res"]["text"] = _o["text"]
                    st.rerun()
        _ptxt = st.text_area("或者直接粘贴通知文字", key="shot_text", height=90,
                             placeholder="例：您好，您的简历已通过筛选，请于……时间 到……参加面试。")
        if _sc2.button("识别文字", width="stretch", key="shot_parse"):
            if not str(_ptxt or "").strip():
                st.warning("先粘一段通知文字。")
            else:
                st.session_state["shot_res"] = AP.ingest_notice(UID, _ptxt, "粘贴通知")
                st.session_state["shot_res"]["text"] = _ptxt
                st.rerun()

        _sr = st.session_state.get("shot_res")
        if _sr:
            _rl = _sr.get("kind_label") or "没认出类型"
            st.markdown(f"**识别结果**：{_rl} · 公司 `{_sr.get('company') or '—'}` · "
                        f"时间 `{_sr.get('when') or '通知里没写'}`")
            if _sr.get("applied_id"):
                st.success(_sr.get("msg", "已记上"))
            else:
                st.warning(_sr.get("msg", "没能自动挂靠"))
                _cand = _sr.get("candidates")
                if _cand is not None and len(_cand):
                    _pick = st.selectbox(
                        "挂到哪条投递", _cand["id"].tolist(), key="shot_aid",
                        format_func=lambda i: (f"{_cand.loc[_cand['id'] == i, '岗位'].iloc[0]}"
                                               f" · {_cand.loc[_cand['id'] == i, '公司'].iloc[0]}"))
                    if st.button("确认挂上这条", key="shot_attach"):
                        _w = AP.add_event(UID, int(_pick), _sr["kind"], _sr.get("when", ""),
                                          f"截图OCR:{_sr.get('company', '')}", 0)
                        if _w.get("ok"):
                            st.session_state.pop("shot_res", None)
                            st.rerun()
                        else:
                            st.error(_w.get("msg", "挂不上"))
            with st.expander("看看识别到的原文", expanded=False):
                st.text(_sr.get("text", "")[:1200])

    _bd = _as["rows"]
    st.markdown("#### 投递记录")
    # 批量删完的一次性收尾：清空表格勾选。必须放在表实例化之前，
    # Streamlit 不允许在同一轮里改已经渲染过的 widget 的 state。
    if st.session_state.pop("_app_reset_sel", False):
        st.session_state["app_sel"] = {"selection": {"rows": []}}
    if _bd.empty:
        st.caption("还没有投递记录"
                   f"投出去满 {AP.TIMEOUT_DAYS} 天没动静，系统自动标「无回音」。")
    else:
        _show = _bd[["时间", "岗位", "公司", "城市", "命中率", "状态", "依据", "来源"]]
        # 最左一列就是勾选框：勾一条或几条，再点下面的按钮一起删。
        _sel = st.dataframe(_show, width="stretch", hide_index=True,
                            height=min(46 + 34 * len(_show), 300),
                            on_select="rerun", selection_mode="multi-row",
                            key="app_sel",
                            column_config={"依据": st.column_config.TextColumn(
                                "依据", width="large")})
        _rows = list(getattr(getattr(_sel, "selection", None), "rows", []) or [])
        _ids = [int(_bd["id"].iloc[i]) for i in _rows if 0 <= i < len(_bd)]
        if _ids:
            if st.button(f"🗑 删除选中 {len(_ids)} 条", key="del_app_btn",
                         width="stretch"):
                for _aid in _ids:
                    AP.delete_apply(UID, _aid)
                st.session_state["_app_reset_sel"] = True
                st.rerun()

# ------------------------------------------------ ⑧ 工程后台（仅开发者身份可见）
if dev_mode and is_screen(8):
    render_admin_screen(UID, ACCOUNT)

# ================================================================ 页脚（登录后各屏底部统一展示）
st.markdown('<div class="page-foot">职航罗盘  · 学生职业规划大数据平台'
            '</div>',
            unsafe_allow_html=True)
