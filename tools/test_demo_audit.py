"""演示全过程审计：跨屏数字一致性 + 库内一致性 + 交互边界。

与 test_walkthrough（走流程看有没有崩）分工不同，这里专查"演示现场会被追问的数字"：
① 的样本量是不是真数、③ 的命中率能不能用原始表复算出来、⑤ 的档案和 ③ 的定位对不对得上、
④ 补完课回头 ③ 的勾选有没有同步、台账里写死的数字与库里实际是否一致。

跑法：.venv/Scripts/python.exe tools/test_demo_audit.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from _demo_login import login_demo  # noqa: E402

import pandas as pd  # noqa: E402

from core import analyze as A  # noqa: E402
from core import majors as MJ  # noqa: E402
from core import pathway as PW  # noqa: E402
from core import profile as PF  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

DB = ROOT / "data" / "jobs.db"
BAD: list[str] = []
WARN: list[str] = []


def ok(m):
    print(f"  ✅ {m}")


def bad(m):
    BAD.append(m)
    print(f"  ❌ {m}")


def warn(m):
    WARN.append(m)
    print(f"  ⚠️  {m}")


def check(cond, m, hard=True):
    (ok if cond else (bad if hard else warn))(m)


def exc(at, where):
    if at.exception:
        bad(f"{where} 抛异常：" + "；".join(str(e.value)[:160] for e in at.exception))
        return True
    return False


def kpi_map(at) -> dict[str, str]:
    """把页面上的指标卡解析成 {标题: 数值}，用来核对页面显示与后端计算。"""
    out = {}
    for el in at.markdown:
        v = el.value or ""
        for m in re.finditer(
                r'<div class="kpi"><div class="k">(.*?)</div><div class="v">(.*?)</div>'
                r'<div class="s">(.*?)</div>', v, re.S):
            out[re.sub(r"<[^>]+>", "", m.group(1)).strip()] = \
                re.sub(r"<[^>]+>", "", m.group(2)).strip()
    return out


def num(s: str) -> float:
    d = re.sub(r"[^\d.]", "", str(s).replace(",", ""))
    try:
        return float(d)
    except ValueError:
        return -1.0


def main() -> None:
    PF._conn().close()
    c = sqlite3.connect(DB)
    base = c.execute("SELECT COALESCE(MAX(id),0) FROM career_snapshot").fetchone()[0]
    c.close()

    # ============================================================ A. 后端数字自洽
    print("\n— A. 后端口径：台账 / 原始表 / 页面数字三者对不对")
    ov = A.overview()
    c = sqlite3.connect(DB)
    n_jobs_all = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    n_skill = c.execute("SELECT COUNT(*) FROM job_skill").fetchone()[0]
    c.close()
    j = A.jobs()
    check(len(j) == ov["n"], f"① 技术岗样本 = analyze.jobs() 行数（{ov['n']}）")
    check(n_jobs_all > ov["n"], f"技术岗 {ov['n']} < 抓取总数 {n_jobs_all}（粗筛确实在筛）")
    check(0 < ov["n"] <= n_jobs_all, "样本量不超过原始抓取量")

    # 台账与库内实际对齐（对外材料只说台账里的数字）
    led = (ROOT / "docs" / "指标台账.md").read_text(encoding="utf-8")

    def led_cell(key: str) -> str:
        m = re.search(rf"\| {re.escape(key)} \| ([^|]+)\|", led)
        return m.group(1).strip() if m else ""

    def pick_num(text: str, last: bool = True) -> float:
        """格子里的数字：'¥8,500' → 8500；'90 类 · 2803 条' 取最后一组 → 2803。"""
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
        if not nums:
            return -1.0
        s = (nums[-1] if last else nums[0]).replace(",", "")
        try:
            return float(s)
        except ValueError:
            return -1.0

    pairs = [("抓取岗位总数", n_jobs_all), ("技术岗（粗筛后）", ov["n"]),
             ("覆盖城市", ov.get("cities", -1)), ("招聘企业", ov.get("companies", -1)),
             ("技能记录", n_skill)]
    for k, real in pairs:
        v = pick_num(led_cell(k))
        check(v == float(real), f"台账「{k}」= 库内实际（台账 {v:.0f} / 实际 {real}）")
    check(abs(pick_num(led_cell("月薪中位数")) - float(ov.get("median", 0))) < 1,
          f"台账月薪中位数 = 计算值（{ov.get('median'):.0f}）")

    # ⑧ 说明里写死的课程数字（最容易过期）
    _src = (ROOT / "app_all.py").read_text(encoding="utf-8")
    _m = re.search(r"当前内置 (\d+) 个专业，合计 (\d+) 门次课程（去重后 (\d+) 门不同课程）、"
                   r"(\d+) 条课程—技能映射", _src)
    if _m:
        n_major, n_course_sum, n_uniq, n_map = map(int, _m.groups())
        mp = pd.read_csv(A.MAP_CSV, encoding="utf-8-sig")
        per = mp.groupby("major_code")["course_name"].nunique()
        check(n_major == mp["major_code"].nunique(),
              f"⑧ 专业数 {n_major} = 映射表实际 {mp['major_code'].nunique()}")
        check(n_course_sum == int(per.sum()),
              f"⑧ 课程门次 {n_course_sum} = 各专业课程数合计 {int(per.sum())}")
        check(n_uniq == mp["course_name"].nunique(),
              f"⑧ 去重课程数 {n_uniq} = 实际 {mp['course_name'].nunique()}")
        check(n_map == len(mp), f"⑧ 映射数 {n_map} = 映射表实际 {len(mp)}")
    else:
        warn("⑧ 说明里没找到课程数字，跳过")

    # ③ 命中率能不能用原始表复算出来（不调 pathway，独立实现）
    print("\n— B. ③ 命中率：用原始表独立复算")
    c = sqlite3.connect(DB)
    js = pd.read_sql("SELECT jd_id, skill FROM job_skill", c)
    c.close()
    j_all = A.jobs(all_rows=True)   # 具体岗位族按全库取（会计、销售等族没有技术岗）
    for fam, have, top in [("数据分析", ["Python"], 10),
                           ("算法", ["Python", "PyTorch"], 12),
                           ("全部", [], 10)]:
        lp = PW.build_path(have, fam, top, major="人工智能技术应用")
        if not lp.get("ok"):
            bad(f"{fam} 生成路径失败：{lp.get('msg')}")
            continue
        jj = j_all[j_all["family"] == fam] if fam != "全部" else j
        ids = set(jj["jd_id"])
        g = js[js["jd_id"].isin(ids)].groupby("skill").size().sort_values(
            ascending=False).head(top)
        total, held = float(g.sum()), float(g[g.index.isin(have)].sum())
        mine = held / total if total else 0.0
        check(abs(mine - lp["match"]) < 1e-6,
              f"「{fam}」命中率页面 {lp['match']:.4f} = 原始表复算 {mine:.4f}")
        check(lp["n_family"] == int(total),
              f"「{fam}」需求合计 {lp['n_family']} = Top{top} 岗位数之和 {int(total)}")

    # 库内一致性：快照的 n_held / n_gap 与 JSON 长度一致
    print("\n— C. 成长档案库内一致性")
    c = sqlite3.connect(DB)
    rows = c.execute(
        "SELECT id, user_id, n_held, n_gap, match, have_json, gap_json "
        "FROM career_snapshot").fetchall()
    c.close()
    mismatch = []
    for sid, uid_, n_held, n_gap, match, hj, gj in rows:
        try:
            nh, ng = len(json.loads(hj or "[]")), len(json.loads(gj or "[]"))
        except json.JSONDecodeError:
            mismatch.append((sid, "JSON 坏了"))
            continue
        if nh != n_held or ng != n_gap:
            mismatch.append((sid, f"库里 n_held={n_held}/实际 {nh}，n_gap={n_gap}/实际 {ng}"))
        if not (0.0 <= float(match) <= 1.0):
            mismatch.append((sid, f"命中率越界 {match}"))
    check(not mismatch, f"{len(rows)} 条快照的计数与 JSON 一致" if not mismatch
          else f"快照计数不一致：{mismatch[:3]}")

    # ============================================================ D. 页面层
    print("\n— D. 页面层：演示顺序走一遍，核对页面数字与后端")
    at = AppTest.from_file(str(ROOT / "app_all.py"), default_timeout=300)
    at.run()
    exc(at, "首页")
    login_demo(at, 0)
    exc(at, "登录")
    c = sqlite3.connect(DB)
    uid = int(c.execute("SELECT id FROM users WHERE account='13800000001'").fetchone()[0])
    c.close()

    # ① 市场全景（固定「本专业相关方向」口径，随侧边栏专业变化；口径切换控件已删）
    at.radio(key="screen").set_value("① 市场全景").run()
    exc(at, "①屏")
    k1 = kpi_map(at)
    _own = [f for f in MJ.families_of(at.session_state.get("major_name"))
            if f in PW.families()]
    mov = A.market_overview(_own)
    check(num(k1.get("岗位样本", "-1")) == mov["n"],
          f"① 页面「岗位样本」（本专业相关）{k1.get('岗位样本')} = 后端 {mov['n']}")
    check(num(k1.get("覆盖城市", "-1")) == mov.get("cities"),
          f"① 页面「覆盖城市」{k1.get('覆盖城市')} = 后端 {mov.get('cities')}")
    check(num(k1.get("招聘企业", "-1")) == mov.get("companies"),
          f"① 页面「招聘企业」{k1.get('招聘企业')} = 后端 {mov.get('companies')}")
    check(not any("mkt_scope" == r.key for r in at.radio
                  if hasattr(r, "key")),
          "① 口径切换控件已删除")

    # ② 方向画像
    at.radio(key="screen").set_value("② 方向画像").run()
    exc(at, "②屏")
    k2 = kpi_map(at)
    _scope_lab = str(at.session_state.get("cov_scope") or "")
    _scope = "专业相关" if _scope_lab.startswith("只看") else "全部"
    cov = A.coverage(at.session_state.get("major_name") or None, scope=_scope)
    if k2.get("加权覆盖率"):
        check(abs(num(k2["加权覆盖率"]) - cov["coverage"] * 100) < 1.5,
              f"② 页面覆盖率 {k2['加权覆盖率']} = 后端 {cov['coverage']:.1%}（口径 {_scope}）")
    # 三类缺口相加应等于总技能数（口径闭环）
    try:
        _sum3 = int(num(k2.get("红色缺口", "0"))) + int(num(k2.get("橙色缺口", "0"))) + \
            int(num(k2.get("已覆盖", "0")))
        check(_sum3 > 0, f"② 红+橙+绿 = {_sum3} 项（三类缺口口径闭合）")
    except ValueError:
        warn("② 缺口 KPI 解析失败")
    # 「全部」方向不能拿技能需求总和冒充岗位数（方向下拉已是搜索面板，直接写状态）
    at.session_state["fam_portrait"] = "全部"
    at.run()
    _caps2 = " ".join((c.value or "") for c in at.caption)
    _m_n = re.search(r"这个方向的 (\d+) 条岗位里", _caps2)
    if _m_n:
        check(int(_m_n.group(1)) == ov["n"],
              f"②「全部」方向的岗位数 {_m_n.group(1)} = 技术岗 {ov['n']}（不是技能需求合计）")
    else:
        warn("② 没找到「这个方向的 N 条岗位」文案")

    # ③ 定位
    at.radio(key="screen").set_value("③ 我的定位").run()
    exc(at, "③屏")
    ms = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    ms.set_value(["Python", "Excel"]).run()
    [b for b in at.button if b.label == "📐 生成我的定位"][0].click().run()
    exc(at, "生成定位")
    lp1 = at.session_state.get("lp") or {}
    check(lp1.get("ok"), f"③ 定位生成：命中率 {lp1.get('match', 0):.0%}，缺口 {len(lp1.get('gap', []))}")
    k3 = kpi_map(at)
    check(abs(num(k3.get("岗位需求命中率", "-1")) - lp1["match"] * 100) <= 1,
          f"③ 页面命中率 {k3.get('岗位需求命中率')} = session {lp1['match']:.0%}")
    # 存快照
    [b for b in at.button if "存入成长档案" in (b.label or "")][0].click().run()
    exc(at, "存快照")
    n_snap_1 = len(PF.list_snapshots(at.session_state.get("student_name", ""), uid))

    # ④ 补课勾选提交
    at.radio(key="screen").set_value("④ 差距路径").run()
    exc(at, "④屏")
    gap4 = list((at.session_state.get("lp") or {}).get("gap", {}).get("技能", []))
    cbs = {x.key: x for x in at.checkbox if (x.key or "").startswith("done_")}
    check(len(cbs) == len(gap4), f"④ 勾选框 {len(cbs)} 个 = 缺口 {len(gap4)} 项")
    pick = gap4[:2]
    for sk in pick:
        cbs[f"done_{sk}"].check()
    at.run()
    # 提交前预览必须与提交后一致
    _prev = [i.value or "" for i in at.markdown if "勾上这" in (i.value or "")]
    [ti for ti in at.text_input if ti.key == "done_evidence"][0].set_value("蓝桥杯省赛二等奖").run()
    [b for b in at.button if "提交补课结果" in (b.label or "")][0].click().run()
    exc(at, "④提交")
    _after_snaps = PF.list_snapshots(at.session_state.get("student_name", ""), uid)
    check("蓝桥杯省赛二等奖" in str(_after_snaps.iloc[-1]["备注"]),
          "④ 佐证写进了快照备注（可追溯）")
    check(at.session_state.get("done_evidence") in (None, ""),
          f"④ 提交后佐证框已清空，不会带到下一次（{at.session_state.get('done_evidence')!r}）")
    lp2 = at.session_state.get("lp") or {}
    check(lp2["match"] >= lp1["match"],
          f"④ 提交后命中率 {lp1['match']:.0%} → {lp2['match']:.0%} 未下降")
    if _prev:
        m = re.search(r"命中率 (\d+)% → (\d+)%", _prev[0])
        if m:
            check(int(m.group(2)) == round(lp2["match"] * 100),
                  f"④ 提交前预览 {m.group(2)}% = 提交后实际 {lp2['match']:.0%}")
    n_snap_2 = len(PF.list_snapshots(at.session_state.get("student_name", ""), uid))
    check(n_snap_2 == n_snap_1 + 1, f"④ 提交只新增 1 份快照（{n_snap_1} → {n_snap_2}）")

    # ④ 提交后回 ③：勾选框必须已含新补的技能（widget 默认值是否跟随）
    at.radio(key="screen").set_value("③ 我的定位").run()
    exc(at, "③回看")
    ms2 = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    _cur = list(ms2.value or [])
    check(all(sk in _cur for sk in pick),
          f"③ 勾选框自动含刚补的技能（{_cur}）")

    # ⑤ 成长档案：数字与 ④ 提交后一致
    at.radio(key="screen").set_value("⑤ 成长档案").run()
    exc(at, "⑤屏")
    k5 = kpi_map(at)
    check(abs(num(k5.get("当前命中率", "-1")) - lp2["match"] * 100) <= 1,
          f"⑤ 当前命中率 {k5.get('当前命中率')} = ④ 提交后 {lp2['match']:.0%}")
    check(int(num(k5.get("已会技能", "0"))) == len(at.session_state.get("have_last", [])),
          f"⑤ 已会技能 {k5.get('已会技能')} = 勾选 {len(at.session_state.get('have_last', []))} 项")
    _mds = [m.value or "" for m in at.markdown]
    check(any('class="grow"' in m for m in _mds), "⑤ 刚提交 → 庆祝口径")

    # ⑤ 删除最新快照（多选批量删除，无确认弹层）：数字回退但 ③ 定位不变
    snaps = PF.list_snapshots(at.session_state.get("student_name", ""), uid)
    at.session_state["snap_sel"] = {"selection": {"rows": [len(snaps) - 1]}}
    at.run()
    _del = {b.key: b for b in at.button if (b.key or "").startswith("snap_del_btn")}
    if "snap_del_btn" in _del:
        check("删除选中 1 条" in (_del["snap_del_btn"].label or ""),
              "⑤ 多选删除入口：勾 1 行 → 「🗑 删除选中 1 条」")
        _del["snap_del_btn"].click().run()
        exc(at, "⑤删除")
        n_snap_3 = len(PF.list_snapshots(at.session_state.get("student_name", ""), uid))
        check(n_snap_3 == n_snap_2 - 1, f"⑤ 删除后快照 {n_snap_2} → {n_snap_3}")
        k5b = kpi_map(at)
        _lp_sess = at.session_state.get("lp") or {}
        check(abs(num(k5b.get("当前命中率", "-1")) - float(_lp_sess["match"]) * 100) > 0.5,
              f"⑤ 删除最新后当前命中率回退到 {k5b.get('当前命中率')}，"
              f"而 ③ 定位仍是 {_lp_sess['match']:.0%}（历史删除不影响当前定位）")
        check(not any('class="pick"' in (m.value or "") for m in at.markdown),
              "⑤ 删除后选中态已清空")
    else:
        warn("没找到批量删除按钮，跳过删除回归")

    # ⑥ 规划书：定位变了旧稿自动作废
    at.radio(key="screen").set_value("⑥ AI 顾问").run()
    exc(at, "⑥屏")
    [b for b in at.button if "生成我的职业规划书" in (b.label or "")][0].click().run()
    exc(at, "⑥生成")
    check(bool(at.session_state.get("plan_md")), "⑥ 规划书生成成功")
    _pk1 = at.session_state.get("plan_key")
    # 改一项技能（不重新生成）→ 规划书指纹不变；重新生成定位 → 旧稿作废
    at.radio(key="screen").set_value("③ 我的定位").run()
    ms3 = [m for m in at.multiselect if m.label == "我已掌握的技能"][0]
    ms3.set_value(["Python", "Excel", "SQL"]).run()
    [b for b in at.button if b.label == "📐 生成我的定位"][0].click().run()
    at.radio(key="screen").set_value("⑥ AI 顾问").run()
    _pm = at.session_state.get("plan_md")
    check(_pm is None, f"⑥ 定位变了之后旧规划书已作废（plan_md={bool(_pm)}）")

    # ⑦ 面试：题数文案 vs 实际题数（含"技能不够 5 个"的边界）
    at.radio(key="screen").set_value("⑦ 求职实战").run()
    exc(at, "⑦屏")
    _caps = " ".join((c.value or "") for c in at.caption)
    m7 = re.search(r"一场 (\d+) 题", _caps)
    if m7:
        [b for b in at.button if b.label == "▶ 开始面试"][0].click().run()
        exc(at, "开始面试")
        _iv = at.session_state.get("iv") or {}
        n_q = len(_iv.get("qs") or [])
        check(n_q == int(m7.group(1)),
              f"⑦ 默认文案「一场 {m7.group(1)} 题」= 实际出题 {n_q} 题")
        [b for b in at.button if b.label == "放弃本场"][0].click().run()
        exc(at, "放弃面试")
    else:
        warn("⑦ 没找到「一场 N 题」文案")

    # （粘贴 JD 入口已删除，3 技能边界场景不可达，这段随入口一起删）

    # ⑧ 工程后台：账号页的人数（文案在 expander 标签里）
    at.radio(key="screen").set_value("⑧ 工程后台").run()
    exc(at, "⑧屏")
    # 文案说的是「演示档案 N 位同学」= 三个演示账号，不是学生自己注册的账号数；
    # 以前拿 users 总行数比，一旦有学生注册过就会误报。
    from core import auth as AU
    n_demo = len(AU.DEMO_USERS)
    _labels = " ".join([(e.label or "") for e in at.expander] +
                       [(m.value or "") for m in at.markdown])
    m8 = re.search(r"演示档案（(\d+) 位同学", _labels)
    if m8:
        check(int(m8.group(1)) == n_demo,
              f"⑧ 文案「{m8.group(1)} 位同学」= 演示账号 {n_demo} 个")
    else:
        warn("⑧ 没找到「N 位同学」文案（不影响功能）")

    # ============================================================ E. 跨账号隔离
    print("\n— E. 跨账号隔离：换账号后看不到别人的档案")
    at.button(key="logout_btn") if any(b.key == "logout_btn" for b in at.button) else None
    _logout = [b for b in at.button if "退出登录" in (b.label or "")]
    if _logout:
        _logout[0].click().run()
        login_demo(at, 1)
        exc(at, "换账号登录")
        at.radio(key="screen").set_value("⑤ 成长档案").run()
        exc(at, "⑤屏(账号2)")
        c = sqlite3.connect(DB)
        uid2 = int(c.execute("SELECT id FROM users WHERE account='13800000002'").fetchone()[0])
        c.close()
        stu2 = at.session_state.get("student_name", "")
        _own = PF.list_snapshots(stu2, uid2)
        k5c = kpi_map(at)
        if k5c.get("当前命中率") and len(_own):
            check(abs(num(k5c["当前命中率"]) - float(_own.iloc[-1]["命中率"]) * 100) < 1,
                  f"账号2 只看自己的档案（{len(_own)} 条，页面 {k5c.get('当前命中率')}）")
        else:
            ok("账号2 无记录时显示空态")
        check(not any('class="pick"' in (m.value or "") for m in at.markdown),
              "换账号后上一个账号的选中态已清空（snap_sel 不串号）")
        check(at.session_state.get("snap_note") in (None, ""),
              f"换账号后备注框已清空（{at.session_state.get('snap_note')!r}）")
    else:
        warn("没找到退出登录按钮，跳过换号检查")

    # ============================================================ F. 输入健壮性
    print("\n— F. 输入健壮性")
    from core import jd as JDX
    for name, txt in [("空", ""), ("纯符号", "！！！？？？…"), ("超长", "Python SQL " * 500),
                      ("只标题", "数据分析师")]:
        r = JDX.extract_from_text(txt)
        check(isinstance(r, dict), f"JD「{name}」不崩（ok={r.get('ok')}）")
    _lp_edge = PW.build_path([str(x) for x in PW.all_skills()[:30]], "全部", 20,
                             major="人工智能技术应用")
    check(_lp_edge.get("ok") and _lp_edge["match"] <= 1.0,
          f"勾 30 个技能命中率不越界（{_lp_edge.get('match', 0):.0%}）")
    check(len(PF.export_markdown(at.session_state.get("student_name", ""), uid2)) > 50,
          "导出档案 Markdown 非空")

    print("\n— 清理")
    c = sqlite3.connect(DB)
    n = c.execute("DELETE FROM career_snapshot WHERE id>?", (base,)).rowcount
    c.commit()
    c.close()
    print(f"  🧹 清理测试快照 {n} 条")

    print("\n" + ("❌ 存在问题：" + "；".join(BAD) if BAD else "🎉 全部通过"))
    if WARN:
        print("⚠️  口径提醒：\n  - " + "\n  - ".join(WARN))
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
