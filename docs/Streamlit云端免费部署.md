# 职航罗盘 · Streamlit Community Cloud 免费云端部署指南

> 结论先行：**可以免费**。不需要营业执照、不需要域名、不需要 ICP 备案、不需要买服务器。
> 代价是：代码与数据公开在 GitHub、数据重启即回滚、国内访问慢。适合参赛演示/给评委看链接，**不适合当正式对外服务**。

---

## 一、方案可行性对照

| 你关心的 | 答案 |
|---|---|
| 费用 | ¥0（永久免费档） |
| 营业执照 | 不需要，GitHub + Streamlit 账号邮箱注册即可 |
| 域名 | 不需要，送 `https://<应用名>.streamlit.app` 子域名 |
| ICP 备案 | 不需要（服务器在美国） |
| 内存/算力 | 约 1 GB 内存 / 1 vCPU，本平台体量够用 |
| 国内访问 | 能打开但慢（1–5 秒），偶发不稳定；正式演示建议备本机版兜底 |
| 闲置休眠 | 长时间没人访问会休眠，下次打开等 1–2 分钟唤醒 |

**两个必须想清楚的硬限制：**

1. **仓库必须公开（public）**——项目代码、docs 文档、data/jobs.db 里的岗位数据（4,600+ 条智联采集数据）任何人都能下载。推之前跑 `tools/export_cloud_db.py` 清掉非演示账号，真实学生数据绝不上云。
2. **容器是"一次性"的**——学生在云端注册的账号、填的成长档案、投递记录，在应用重启（改代码推送/平台维护/休眠回收）后全部回滚到仓库里的快照。演示完全够用，存档不行。

---

## 二、已为本项目准备好的部署套件

| 文件 | 作用 |
|---|---|
| `core/cloud_secrets.py` | 启动时把 Streamlit 后台 Secrets 里的 `[coze]/[llm]/[dify]/[sms]` 段自动落成 `config/*.json`，core 里四个模块一行不用改；本机运行不受影响 |
| `.gitignore` | 排除 .venv、备份库、exports、真实密钥文件等 30+ MB 不该进仓库的内容 |
| `tools/export_cloud_db.py` | 推送前清理 users 表（只留 3 个演示账号）+ 清 token + VACUUM 压缩 |
| `app_all.py`（已插入 2 行） | 导入并调用 `sync_cloud_secrets()` |

---

## 三、部署步骤（全程约 30 分钟）

### 第 0 步：清理数据库（本机，1 分钟）

```bash
cd D:\WorkBuddyP\outputs\zhihang-luopan
.venv\Scripts\python tools\export_cloud_db.py
```

输出应显示 `users: 6 -> 3`，并自动备份到 `data/_bak_jobs_before_cloud_*.db`。

### 第 1 步：注册 GitHub（免费）

1. 打开 https://github.com → Sign up → 用邮箱注册（无需任何企业资质）。
2. 记住用户名，下一步要用。

### 第 2 步：建公开仓库

1. 登录后右上角 **+** → **New repository**。
2. Repository name：`zhihang-luopan`（可自定）；选 **Public**；不要勾选任何初始化文件（README/.gitignore/license 都不勾）。
3. 点 **Create repository**，页面先放着不用关。

### 第 3 步：本地推送到 GitHub

在项目目录打开 Git Bash（没装 Git 就去 https://git-scm.com 装一下）：

```bash
cd /d/WorkBuddyP/outputs/zhihang-luopan
git init
git add .
git commit -m "职航罗盘 · 云端部署初始快照"
git branch -M main
git remote add origin https://github.com/<你的用户名>/zhihang-luopan.git
git push -u origin main
```

> 首次 push 会弹浏览器让你登录 GitHub 授权一次。
> `.gitignore` 会自动挡掉 .venv、备份库、真实密钥文件；确认 `config/` 下只有 `*.json.example` 和 `admin.json / crawl.json / agent_flow.json` 进了仓库。

### 第 4 步：Streamlit Community Cloud 一键部署

1. 打开 https://share.streamlit.io → **Continue with GitHub**（用刚注册的 GitHub 账号授权）。
2. 点 **New app**（即截图里的 Deploy now）。
3. 三项填写：
   - Repository：`<你的用户名>/zhihang-luopan`
   - Branch：`main`
   - Main file path：**`app_all.py`**（注意不是 app.py，那个文件不存在会部署失败）
4. 点开 **Advanced settings** → Python version 选 **3.13** → Save。
5. 点 **Deploy**。首次构建装依赖约 5–10 分钟，页面会滚动显示构建日志。

### 第 5 步：配置密钥（Secrets）

部署完成后，左下角 **Manage app** → **Settings** → **Secrets**，粘贴下面的 TOML（改成你自己的值）：

```toml
[coze]
token = "pat_你的Coze令牌"
bot_id = "你的BotID"
user_id = "student-0001"
api_base = "https://api.coze.cn"

[llm]
base_url = "https://api.deepseek.com/v1"
api_key = "sk-你的key"
model = "deepseek-chat"

[sms]
provider = "aliyun"
enabled = true
[sms.aliyun]
access_key_id = "LTAI你的AK"
access_key_secret = "你的SK"
sign_name = "职航罗盘"
template_code = "SMS_xxxxxxx"
```

- 四个段都可以只配其中任意几个；**一个都不配也能跑**——AI 走离线规则兜底、短信退回演示模式（验证码回显页面），只是少了在线 AI。
- 保存后应用自动重启一次，`core/cloud_secrets.py` 会在启动时把它们写成 `config/coze.json` 等文件。

### 第 6 步：验收清单

| 检查项 | 预期 |
|---|---|
| 打开 `https://<应用名>.streamlit.app` | 首页（登录注册卡）出现 |
| 演示账号 `13800000001` 登录 | 能进八屏工作台 |
| ① 市场全景 | 数字与本机版一致（数据来自仓库快照） |
| ⑥ AI 顾问 | 标签显示当前走的通道（Coze/兼容接口/离线） |
| ⑦ 模拟面试 | 全流程可跑 |
| ⑧ 工程后台 | admin 名单账号可见；**采集功能在云端不可用**（美国 IP 会被智联风控挡），只做展示 |

### 第 7 步：以后怎么更新

```bash
git add .
git commit -m "更新说明"
git push
```

推送后 Streamlit 云端**自动重新部署**（约 2–3 分钟）。记住：每次重新部署，云端运行期间产生的注册/档案数据都会回滚到仓库快照——要保留就先在后台下载，或干脆只推数据不推别的改动。

---

## 四、常见问题

| 问题 | 处理 |
|---|---|
| 构建失败 | Manage app 里看日志；99% 是 requirements.txt 某个包装不上，按日志改版本号 |
| 内存超限（App 重启/卡死） | 把 `requirements.txt` 里 `rapidocr_onnxruntime` 那行注释掉（⑦ 截图识别功能退化为手动粘贴文字，主流程不受影响），推上去重新部署 |
| 国内打不开/很慢 | 正常现象，换网络时段再试；正式答辩场合用本机版 `启动_职航罗盘.bat` |
| 休眠唤醒慢 | Manage app → 点一下 Reboot，或访问时多等 1–2 分钟 |
| 想换应用名 | Settings → General 里改 subdomain，链接随之变成 `https://<新名>.streamlit.app` |
| 想真正存住学生数据 | 免费档做不到，回到上一轮方案 B/C（轻量服务器 + 数据盘/RDS） |

## 五、与付费方案的关系

| 场景 | 选择 |
|---|---|
| 参赛答辩、给评委一个在线链接、学生试玩 | **本方案 ¥0**，首选 |
| 校内长期给师生用、数据要留存 | 上一轮方案 B（¥128/年）或学校机房 |
| 商业化运营 | 上一轮方案 C（¥1,174/年 + 资质） |
