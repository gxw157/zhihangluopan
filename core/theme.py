"""全站主题 CSS：学生端七屏与内嵌 ⑧ 工程后台共用同一份。"""

THEME_CSS = r'''<style>
  /* ============ 全局主题：浅色 · 低饱和淡蓝 · 扁平轻量 ============ */
  :root{
    --blue:#6c9bd1;          /* 低饱和淡蓝主色 */
    --blue-deep:#5586bd;     /* 加深一档：hover / 强调文字 */
    --blue-dark:#3f6a9e;     /* 再深一档：数值 */
    --blue-soft:#eaf2fb;     /* 淡蓝底 */
    --blue-border:#c9dbf0;   /* 淡蓝描边 */
    --ink-1:#2b3a4d;         /* 标题深灰 */
    --ink-2:#52637a;         /* 正文浅深灰 */
    --ink-3:#8a99ad;         /* 辅助灰 */
    --line:#e8eef6;          /* 柔和纤细浅灰分割线 */
    --bg:#f8fbff;            /* 纯净米白页面底 */
    --shadow:0 2px 12px rgba(46,84,138,.06),0 1px 3px rgba(46,84,138,.04);
    --shadow-hover:0 8px 24px rgba(46,84,138,.10);
  }
  .stApp{background:var(--bg);color:var(--ink-2);
         font-family:"PingFang SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif}
  .block-container{padding-top:1.6rem;padding-bottom:4.5rem;max-width:1500px}
  h1,h2,h3,h4{color:var(--ink-1);letter-spacing:.3px}
  h2{border-left:3px solid var(--blue-border);padding-left:12px;margin-top:.5em!important}
  h3{color:var(--ink-1)}
  header[data-testid="stHeader"]{background:rgba(248,251,255,.92)}

  /* 顶部品牌头图：白卡扁平，无重渐变 */
  .hero{position:relative;border-radius:16px;padding:22px 30px;
        background:#fff;border:1px solid var(--line);
        box-shadow:var(--shadow);margin-bottom:14px}
  .hero:after,.hero:before{display:none}
  .hero .brand{font-size:12px;letter-spacing:3px;color:var(--blue-deep);font-weight:700}
  .hero h1{color:var(--ink-1);font-size:26px;margin:6px 0 0;line-height:1.4}
  .hero .sub{color:var(--ink-2);font-size:14px;margin-top:8px;line-height:1.75}
  .hero .chips{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap}
  .hero .chip{background:var(--blue-soft);border:1px solid var(--blue-border);
              border-radius:999px;padding:6px 14px;font-size:12.5px;color:var(--ink-2)}
  .hero .chip b{font-size:15px;color:var(--blue-dark);margin-left:4px}

  /* 四问导航：市场在要什么 → 专业学什么 → 我差在哪里 → 我接下来做什么 */
  .qflow{display:flex;align-items:center;gap:8px;margin-top:16px;flex-wrap:wrap}
  .qflow .q{background:var(--blue-soft);border:1px solid var(--blue-border);
            border-radius:11px;padding:8px 14px;color:var(--ink-2);font-size:12.5px;line-height:1.55}
  .qflow .q b{color:var(--ink-1);font-size:14px;display:block;margin-bottom:2px}
  .qflow .arr{color:var(--blue);font-size:18px;font-weight:700}
  .qflow .q .go{color:var(--blue-deep);font-weight:700}

  /* 屏头：屏名与内容说明 */
  .screen-head{display:flex;align-items:center;gap:12px;margin:2px 0 6px;flex-wrap:wrap}
  .screen-head .no{background:var(--blue);color:#fff;border-radius:9px;
                   padding:4px 14px;font-weight:700;font-size:15px;letter-spacing:1px}
  .screen-head .ans{font-size:14px;color:var(--ink-3)}
  .screen-head .ans b{color:var(--blue-deep)}

  /* 空状态提示：无底色、无边框，仅一条淡线，随页面文字风格 */
  .hint{color:var(--ink-3);font-size:13.5px;line-height:1.75;
        margin:6px 0 10px;padding:1px 0 1px 11px;border-left:2px solid var(--line)}
  .hint b{color:var(--ink-2);font-weight:600}

  /* 上传控件：只保留拖放区与按钮，隐藏大小/格式说明文字 */
  [data-testid="stFileUploaderDropzoneInstructions"] span{display:none!important}

  /* 行动条 */
  .act{background:var(--blue-soft);border:1px solid var(--blue-border);border-radius:11px;
       padding:11px 16px;font-size:13.5px;color:var(--ink-2);margin-top:16px;line-height:1.7}
  .act b{color:var(--ink-1)}

  /* 行动卡：语义色左条（红橙绿降饱和，统一轻量描边） */
  .todo{border-radius:11px;padding:11px 14px;font-size:13px;line-height:1.75;height:100%}
  .todo b{font-size:14px}
  .todo.red{background:#fef6f6;border:1px solid #f3d8d8;border-left:4px solid #d97c7c;color:#8a4a4a}
  .todo.orange{background:#fdf8f2;border:1px solid #f0dfc8;border-left:4px solid #d9a15c;color:#8a6430}
  .todo.green{background:#f4faf5;border:1px solid #d4e8d8;border-left:4px solid #7fb98c;color:#4a7a58}

  /* 岗位卡：一岗一页逐条翻（⑦ 库内岗位模式） */
  .jobcard{background:#fff;border:1px solid var(--line);border-radius:15px;
           padding:18px 22px 16px;box-shadow:var(--shadow);margin:6px 0 4px}
  .jobcard .jc-top{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}
  .jobcard .jc-title{font-size:19px;font-weight:700;color:var(--ink-1);line-height:1.4}
  .jobcard .jc-co{font-size:13.5px;color:var(--blue-deep);margin-top:5px;font-weight:600}
  .jobcard .jc-meta{font-size:12.5px;color:var(--ink-3);margin-top:6px}
  .jobcard .jc-hit{text-align:right;min-width:96px}
  .jobcard .jc-hit b{font-size:26px;color:var(--blue-dark);line-height:1}
  .jobcard .jc-hit span{display:block;font-size:11.5px;color:var(--ink-3);margin-top:3px}
  .jobcard .jc-bar{height:6px;border-radius:99px;background:var(--blue-soft);margin:14px 0 12px;overflow:hidden}
  .jobcard .jc-bar i{display:block;height:100%;border-radius:99px;background:var(--blue)}
  .jobcard .jc-skills{display:flex;flex-wrap:wrap;gap:7px}
  .jobcard .sk{font-size:12px;padding:4px 11px;border-radius:999px;border:1px solid var(--line);
               background:#fbfdff;color:var(--ink-2)}
  .jobcard .sk.on{background:#f2f8f3;border-color:#d4e8d8;color:#4a7a58;font-weight:600}
  .jobcard .sk.off{background:#fdf7f4;border-color:#f0dcd2;color:#8a6455}
  .jobcard .jc-load{font-size:11.5px;color:var(--ink-3);margin-top:10px}

  /* 成长对比卡 */
  .grow{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:13px;
        padding:15px 18px;font-size:14px;line-height:1.9;color:var(--ink-1)}
  .grow .big{font-size:20px;font-weight:700;color:var(--blue-dark)}
  /* 历史变化卡：中性蓝灰 */
  .hist{background:#fbfdff;border:1px solid var(--line);border-left:4px solid var(--blue-border);border-radius:13px;
        padding:13px 18px;font-size:13.6px;line-height:1.9;color:var(--ink-2)}
  .hist b{color:var(--ink-1)}
  .hist .hint{display:block;margin-top:7px;font-size:12px;color:var(--ink-3);line-height:1.8}
  /* ⑤ 选中某次记录 */
  .pick{background:#fff;border:1px solid var(--blue-border);border-left:4px solid var(--blue);border-radius:11px;
        padding:11px 15px;font-size:13.2px;line-height:1.85;color:var(--ink-1)}
  .pick b{color:var(--ink-1)}
  .pick .tag{display:inline-block;background:var(--blue-soft);color:var(--blue-deep);border-radius:999px;
        padding:1px 9px;font-size:11.5px;font-weight:600;margin-left:6px;vertical-align:1px}
  .pick .warn{display:block;margin-top:6px;font-size:12px;color:#a15c00}

  /* ===== 成果文档：面试反馈 / 职业规划书 ===== */
  .ivhero{display:flex;align-items:center;gap:20px;border-radius:16px;padding:18px 22px;
      background:#fff;border:1px solid var(--line);
      box-shadow:var(--shadow);color:var(--ink-1);flex-wrap:wrap}
  .ivhero .sc{font-size:44px;font-weight:800;line-height:1;letter-spacing:-1px;color:var(--blue-dark)}
  .ivhero .sc span{font-size:14px;font-weight:600;color:var(--ink-3);margin-left:2px}
  .ivhero .scbox{min-width:132px;text-align:center;border-right:1px solid var(--line);
      padding-right:20px}
  .ivhero .scbox .cap{font-size:12px;color:var(--ink-3);margin-top:6px;letter-spacing:1px}
  .ivhero .lv{font-size:19px;font-weight:700;color:var(--ink-1)}
  .ivhero .meta{font-size:12.8px;color:var(--ink-2);line-height:1.85;margin-top:6px}
  .ivhero .meta b{color:var(--ink-1)}
  .dimgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0 2px}
  .dimcard{border:1px solid var(--line);border-radius:11px;padding:9px 13px;background:#fff;
      box-shadow:var(--shadow)}
  .dimcard .k{font-size:12px;color:var(--ink-3);font-weight:600}
  .dimcard .bar{height:5px;background:#f0f5fb;border-radius:4px;margin:7px 0 5px;overflow:hidden}
  .dimcard .bar i{display:block;height:100%;border-radius:4px;background:var(--blue)}
  .dimcard .v{font-size:15px;font-weight:700;color:var(--ink-1)}
  .dimcard .v span{font-size:11.5px;color:var(--ink-3);font-weight:500}
  .dochead{border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;
      background:#fff;padding:13px 18px;margin-bottom:12px}
  .dochead .t{font-size:18px;font-weight:700;color:var(--ink-1);line-height:1.5}
  .dochead .m{font-size:12.5px;color:var(--ink-3);margin-top:5px;line-height:1.8}
  .sechead{display:flex;align-items:center;gap:9px;font-size:15.5px;font-weight:700;
      color:var(--ink-1);margin:0 0 8px}
  .sechead .num{background:var(--blue);color:#fff;border-radius:8px;
      font-size:12px;font-weight:700;padding:3px 8px;letter-spacing:.5px}
  .qhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0 6px}
  .qhead .qn{background:var(--blue-soft);color:var(--blue-deep);border-radius:8px;font-size:12px;font-weight:700;
      padding:3px 9px}
  .qhead .qk{font-size:15px;font-weight:700;color:var(--ink-1)}
  .qhead .qs{margin-left:auto;font-size:12.5px;font-weight:700;color:#a06a1e;
      background:#fdf8f2;border:1px solid #f0dfc8;border-radius:20px;padding:2px 11px}

  /* 文档正文排版：表格轻、引用块浅 */
  div[data-testid="stMarkdownContainer"] h2{font-size:19px;margin:18px 0 8px;color:var(--ink-1)}
  div[data-testid="stMarkdownContainer"] h3{font-size:15.5px;margin:14px 0 6px;color:var(--ink-1)}
  div[data-testid="stMarkdownContainer"] h4{font-size:14.5px;margin:12px 0 5px;color:var(--ink-2)}
  div[data-testid="stMarkdownContainer"] table{width:100%;border-collapse:collapse;
      font-size:12.8px;margin:10px 0 12px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  div[data-testid="stMarkdownContainer"] thead th{background:#f2f7fc;color:var(--ink-1);
      font-weight:700;text-align:left;padding:8px 11px;border-bottom:1px solid var(--line);
      white-space:nowrap}
  div[data-testid="stMarkdownContainer"] tbody td{padding:8px 11px;border-bottom:1px solid #f0f5fb;
      color:var(--ink-2);line-height:1.7;vertical-align:top}
  div[data-testid="stMarkdownContainer"] tbody tr:last-child td{border-bottom:none}
  div[data-testid="stMarkdownContainer"] tbody tr:nth-child(even){background:#fbfdff}
  div[data-testid="stMarkdownContainer"] blockquote{border-left:3px solid var(--blue-border);background:#f7fafe;
      border-radius:0 9px 9px 0;padding:9px 14px;margin:10px 0;color:var(--ink-2);font-size:13px}
  div[data-testid="stMarkdownContainer"] blockquote p{margin:0;line-height:1.8}
  div[data-testid="stMarkdownContainer"] hr{margin:16px 0}
  div[data-testid="stMarkdownContainer"] ul,div[data-testid="stMarkdownContainer"] ol{
      padding-left:1.35em;margin:6px 0}

  /* 侧边栏：浅色，与页面同底 */
  [data-testid="stSidebar"]{background:#fbfdff;border-right:1px solid var(--line)}
  [data-testid="stSidebar"] h3,[data-testid="stSidebar"] h2{color:var(--ink-1)}
  [data-testid="stSidebar"] .flat{color:var(--ink-2)}
  [data-testid="stSidebar"] label{color:var(--ink-2)!important}
  [data-testid="stSidebar"] .stTextInput div[data-baseweb="input"]>div,
  [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"]>div{
      background:#fff;border:1px solid var(--line);border-radius:9px}
  [data-testid="stSidebar"] [data-baseweb="select"] *,
  [data-testid="stSidebar"] [data-baseweb="input"] *{color:var(--ink-1)!important}
  [data-testid="stSidebar"] .stButton>button{background:#fff;color:var(--blue-deep);
      border:1px solid var(--blue-border)}
  [data-testid="stSidebar"] .stButton>button:hover{background:var(--blue-soft);color:var(--blue-dark);
      border-color:var(--blue)}
  .major-chip{background:#fff;border:1px solid var(--line);
      border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.75;color:var(--ink-2);margin-top:4px}
  .major-chip b{color:var(--ink-1)}

  /* 屏导航（单选做成胶囊条，隐藏左侧圆圈，单击即切换） */
  div[role="radiogroup"]{display:flex;flex-wrap:wrap;gap:5px;background:#eef4fb;
      padding:5px;border-radius:13px;margin-bottom:12px;border:1px solid var(--line)}
  div[role="radiogroup"] label[data-testid="stRadioOption"]{display:flex;align-items:center;
      background:#fff;border:1px solid var(--line);border-radius:9px;
      padding:6px 14px;margin:0;cursor:pointer;transition:all .18s ease}
  div[role="radiogroup"] label[data-testid="stRadioOption"] > div > div:first-of-type{
      display:none!important}
  div[role="radiogroup"] label[data-testid="stRadioOption"] p{
      font-size:13.5px;font-weight:600;color:var(--ink-2);margin:0;line-height:1.6}
  div[role="radiogroup"] label[data-testid="stRadioOption"]:hover{
      background:var(--blue-soft);border-color:var(--blue-border)}
  div[role="radiogroup"] label[data-testid="stRadioOption"]:hover p{color:var(--blue-dark)}
  div[role="radiogroup"] label[data-testid="stRadioOption"]:has(input:checked){
      background:linear-gradient(135deg,#6c9bd1,#4c7cad);border-color:transparent;
      box-shadow:0 4px 12px rgba(76,124,173,.30)}
  div[role="radiogroup"] label[data-testid="stRadioOption"]:has(input:checked) p{color:#fff}
  .st-key-screennav{margin-bottom:-6px}
  .st-key-screennav div[role="radiogroup"]{background:#e8f0fa;padding:5px;border-radius:14px}
  .st-key-screennav label[data-testid="stRadioOption"]{padding:7px 17px;border-radius:10px}
  .st-key-screennav label[data-testid="stRadioOption"] p{font-size:14px}
  .hero .tag{font-size:15px;color:var(--ink-3);margin-top:10px;line-height:1.7}

  /* 开发者入口：未登录首页 lp-hero 卡片内右上角（popover 内嵌登录表单） */
  .st-key-dev_entry{position:absolute;top:64px;right:40px;z-index:80;width:fit-content}
  .st-key-dev_entry > div{gap:0!important}
  .st-key-dev_entry button{background:#fff;border:1px solid var(--blue-border);color:var(--blue-dark);
      border-radius:999px;padding:5px 16px;box-shadow:var(--shadow)}
  .st-key-dev_entry button p{font-size:12.5px;font-weight:600;color:var(--blue-dark)!important}
  .st-key-dev_entry button:hover{background:var(--blue-soft);border-color:var(--blue)}
  .st-key-dev_entry [data-baseweb="popover"] [data-baseweb="card"]{min-width:260px}

  /* 选项卡 */
  .stTabs [data-baseweb="tab-list"]{gap:6px;background:#f0f5fb;padding:6px;border-radius:12px;
      border:1px solid var(--line)}
  .stTabs [data-baseweb="tab"]{height:40px;border-radius:8px;color:var(--ink-2);font-weight:600;
      padding:0 15px;background:transparent}
  .stTabs [data-baseweb="tab"]:hover{background:var(--blue-soft);color:var(--blue-dark)}
  .stTabs [aria-selected="true"]{background:#fff!important;color:var(--blue-dark)!important;
      box-shadow:0 2px 8px rgba(46,84,138,.10)}
  .stTabs [data-baseweb="tab-highlight"]{background:transparent}

  /* KPI 卡片 */
  .kpi{background:#fff;border:1px solid var(--line);
       border-radius:12px;padding:13px 16px;height:100%;
       box-shadow:var(--shadow);transition:transform .2s ease,box-shadow .2s ease}
  .kpi:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
  .kpi .k{font-size:12px;color:var(--ink-3);font-weight:600}
  .kpi .v{font-size:25px;font-weight:700;color:var(--ink-1);line-height:1.35}
  .kpi .s{font-size:11.5px;color:var(--ink-3)}

  .note{background:#fdf8f2;border-left:3px solid #d9a15c;padding:10px 14px;border-radius:0 8px 8px 0;
        font-size:13px;color:#8a6430;line-height:1.7}
  .flat{color:var(--ink-2);font-size:13px;line-height:1.8}
  .blk{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fff;font-size:13.5px}
  .mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.7;
        white-space:pre-wrap;color:var(--ink-2);margin-top:8px;
        background:#f7fafe;border:1px solid var(--line);border-radius:8px;padding:8px 10px}
  .tag{display:inline-block;padding:1px 9px;border-radius:20px;font-size:12px;font-weight:600}
  .run{background:var(--blue-soft);color:var(--blue-dark)}
  .stop{background:#fdf8f2;color:#a06a1e}
  .idle{background:#f0f3f7;color:#6a7a8e}
  .warn{background:#fef6f6;color:#8a4a4a}
  .live{background:#f4faf5;color:#4a7a58}

  /* 图表卡片 */
  .fig{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px;
       box-shadow:var(--shadow)}
  .fig svg{display:block;margin:0 auto;max-width:100%!important}
  .fig .cap{font-size:12.5px;color:var(--ink-3);margin-top:6px;line-height:1.7}

  /* 按钮：淡蓝填充 / 描边 两种，hover 柔和微动效 */
  .stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{
       border-radius:9px;border:1px solid var(--blue-border);
       background:#fff;color:var(--blue-deep);font-weight:600;
       transition:all .22s ease}
  .stButton>button:hover,.stDownloadButton>button:hover,
  [data-testid="stFormSubmitButton"]>button:hover{border-color:var(--blue);color:var(--blue-dark);
       background:var(--blue-soft);transform:translateY(-1px)}
  .stButton>button[kind="primary"],button[kind="primaryFormSubmit"]{
       background:var(--blue);color:#fff;border:none;
       box-shadow:0 3px 10px rgba(108,155,209,.30)}
  .stButton>button[kind="primary"]:hover,button[kind="primaryFormSubmit"]:hover{
       background:var(--blue-deep);color:#fff;transform:translateY(-1px);
       box-shadow:0 6px 16px rgba(108,155,209,.36)}

  /* ===== 带搜索的下拉（search_select）：触发按钮做成输入框样式 ===== */
  [class*="st-key-ssbox_"] button[data-testid="stPopoverButton"]{
       width:100%;justify-content:flex-start;gap:6px;min-height:0;
       background:#fff;border:1px solid rgba(49,51,63,.16);border-radius:9px;
       padding:7px 11px;box-shadow:none;color:var(--ink-1);font-weight:400}
  [class*="st-key-ssbox_"] button[data-testid="stPopoverButton"]:hover{
       background:#fff;border-color:var(--blue);transform:none;box-shadow:none}
  [class*="st-key-ssbox_"] button[data-testid="stPopoverButton"] p{
       font-size:13.5px;font-weight:400;color:var(--ink-1);margin:0;
       overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  [class*="st-key-ssbox_"] button[data-testid="stPopoverButton"]::after{
       content:"▾";margin-left:auto;color:var(--ink-3);font-size:12px}
  [class*="st-key-ssbox_"] [data-testid="stPopoverBody"]{padding:6px}

  /* 面板内部：搜索框在最上面，选项按列表项排（细行、左对齐、悬停淡蓝） */
  [data-testid="stPopoverBody"]:has(.ss-panel){min-width:270px;max-width:360px;
       max-height:65vh;overflow-y:auto}
  [data-testid="stPopoverBody"]:has(.ss-panel) .stButton>button{
       width:100%;justify-content:flex-start;text-align:left;min-height:0;
       background:transparent;border:none;border-radius:8px;box-shadow:none;
       padding:5px 9px;color:var(--ink-2);font-weight:400}
  [data-testid="stPopoverBody"]:has(.ss-panel) .stButton>button p{
       font-size:13px;font-weight:400;color:inherit}
  [data-testid="stPopoverBody"]:has(.ss-panel) .stButton>button:hover{
       background:var(--blue-soft);color:var(--blue-dark);transform:none;border:none}
  [data-testid="stPopoverBody"]:has(.ss-panel) .stButton>button[kind="primary"]{
       background:var(--blue-soft);color:var(--blue-dark);box-shadow:none;
       font-weight:600;border:none}
  [data-testid="stPopoverBody"]:has(.ss-panel) [data-testid="stCaptionContainer"] p{
       font-size:11.5px;color:var(--ink-3);line-height:1.6}

  /* 数据表 / 展开面板 / 提示 / 聊天 */
  [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:12px;overflow:hidden}
  div[data-testid="stExpander"]{border:1px solid var(--line);border-radius:12px;background:#fff}
  div[data-testid="stExpander"] summary{font-size:13.5px;color:var(--ink-1);font-weight:600}
  div[data-testid="stVerticalBlockBorderWrapper"]{background:#fff;border-radius:14px!important;
       border:1px solid var(--line)!important;box-shadow:var(--shadow)}
  div[data-testid="stVerticalBlockBorderWrapper"] p{line-height:1.85;margin-bottom:.4em;color:var(--ink-2)}
  div[data-testid="stVerticalBlockBorderWrapper"] li{line-height:1.8;color:var(--ink-2)}
  div[data-testid="stVerticalBlockBorderWrapper"] h3{margin-top:1em}
  div[data-testid="stAlert"]{border-radius:10px;border:1px solid var(--line)}
  [data-testid="stChatMessage"]{background:#fff;border:1px solid var(--line);border-radius:12px;
      box-shadow:var(--shadow)}
  [data-testid="stChatInput"] textarea{border-radius:12px}
  hr{border-color:var(--line)}
  [data-testid="stSidebar"] hr{border-color:var(--line)}
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
  [data-testid="stSidebar"] .stCaption{color:var(--ink-3)!important}
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:var(--ink-2)}
  .stTabs [data-baseweb="tab"] p{color:inherit!important;font-weight:600}

  /* ================= 首页 / 登录（未登录态） ================= */
  .lp-hero{position:relative;border-radius:18px;padding:40px 44px 36px;
        background:#fff;border:1px solid var(--line);
        box-shadow:var(--shadow);margin-bottom:18px}
  .lp-hero:after{display:none}
  .lp-hero .brand{font-size:12px;letter-spacing:4px;color:var(--blue-deep);font-weight:700}
  .lp-hero h1{color:var(--ink-1);font-size:34px;line-height:1.3;margin:12px 0 0;font-weight:700}
  .lp-hero .lead{color:var(--ink-2);font-size:15px;line-height:1.9;margin-top:14px;max-width:34em}
  .lp-hero .stats{display:flex;gap:26px;margin-top:24px;flex-wrap:wrap}
  .lp-hero .stat b{display:block;font-size:25px;color:var(--ink-1);line-height:1.2}
  .lp-hero .stat span{font-size:12.5px;color:var(--ink-3)}
  .lp-hero .flow{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:22px}
  .lp-hero .flow i{font-style:normal;background:var(--blue-soft);
        border:1px solid var(--blue-border);border-radius:999px;padding:6px 13px;
        font-size:12.5px;color:var(--ink-2)}
  .lp-hero .flow u{text-decoration:none;color:var(--blue);font-weight:700}

  .lp-auth{background:#fff;border:1px solid var(--line);border-radius:18px;padding:6px 4px 2px;
        box-shadow:var(--shadow)}
  .lp-auth .head{font-size:19px;font-weight:700;color:var(--ink-1);margin:10px 0 2px}
  .lp-auth .sub{font-size:12.5px;color:var(--ink-3);line-height:1.7;margin-bottom:6px}

  .lp-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px 22px;
        height:100%;box-shadow:var(--shadow);transition:transform .2s ease,box-shadow .2s ease}
  .lp-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
  .lp-card .n{font-size:12px;font-weight:700;color:var(--blue-deep);letter-spacing:1px}
  .lp-card h4{margin:8px 0 6px;font-size:16px;color:var(--ink-1)}
  .lp-card p{margin:0;font-size:13px;color:var(--ink-2);line-height:1.85}

  .lp-step{display:flex;gap:14px;padding:13px 0;border-bottom:1px solid var(--line)}
  .lp-step:last-child{border-bottom:none}
  .lp-step .no{flex:0 0 30px;height:30px;border-radius:9px;background:var(--blue-soft);color:var(--blue-deep);
        font-weight:700;display:flex;align-items:center;justify-content:center;font-size:13px}
  .lp-step .tx b{display:block;color:var(--ink-1);font-size:14px;margin-bottom:3px}
  .lp-step .tx span{color:var(--ink-2);font-size:12.5px;line-height:1.7}

  .lp-foot{text-align:center;color:var(--ink-3);font-size:12px;line-height:2;padding:18px 0 4px}
  .acct{background:var(--blue-soft);border:1px solid var(--blue-border);
        border-radius:12px;padding:10px 12px;margin-bottom:10px}
  .acct .nm{color:var(--ink-1);font-size:14.5px;font-weight:700}
  .acct .ph{color:var(--ink-2);font-size:11.5px;margin-top:2px;letter-spacing:.5px}

  /* 页脚 */
  .page-foot{margin-top:56px;padding:18px 0 8px;border-top:1px solid var(--line);
        text-align:center;font-size:12px;color:var(--ink-3);letter-spacing:.5px;line-height:2}
</style>
'''
