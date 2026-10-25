# Changelog

## v1.1.0（2026-08-26）

### ✨ 新增：GitHub 日升榜板块

- 免费免 Key 多源降级链（按顺序尝试，全部失败则该板块省略并记日志）：
  1. **OSS Insight**：`https://api.ossinsight.io/v1/trends/repos/?period=past_7_days&limit=10`
  2. **GitHub Search API**（官方）：`https://api.github.com/search/repositories?q=created:>{近N天}&sort=stars&order=desc&per_page=10`
  3. **gitterapp**：`https://api.gitterapp.com/repositories/trending?since=daily`
- 容错解析器：从响应的 `items / repos / results / data` 或顶层 list 中找数组，兼容三种 API 字段差异；
- 展示标题如 `owner/repo ⭐1234（近7天+56）`，可配最低 star 过滤；
- 新配置项：`github_trending_enabled`（true）、`github_trending_days`（7）、
  `github_trending_count`（10）、`github_trending_min_stars`（0）。

### ✨ 新增：天气多城市 + 防高并发

- `weather_city` 默认改为「上海」，支持多城市（换行 / 逗号 / 顿号分隔），逐城市输出；
- **防高并发**（防止触发 Open-Meteo 限流）：
  - 天气结果 KV 缓存 30 分钟（`weather_cache_minutes` 可配）；
  - 地理编码结果 KV 缓存 7 天（city → lat/lon，避免反复调 geocoding）；
  - 每城市一把 asyncio 单飞锁（同城市并发只发一个请求）；
  - 全局请求间隔节流 ≥3 秒（`weather_interval_seconds` 可配）+ 每日 120 次调用上限保险；
  - 失败隔离：单城市失败只在该城市输出「获取失败」，不影响其他城市与其余板块。
- 新配置项：`weather_cache_minutes`（30）、`weather_interval_seconds`（3）。

## v1.1.1（2026-08-27）

### 🐛 修复：定时任务未显式指定时区（默认 UTC 导致日报凌晨误发）

- **根因**：`_setup_scheduler` 注册 cron 时未指定 timezone，系统时区为 UTC 的部署上
  `0 8 * * *` 会在 UTC 8 点（北京时间 16 点）或按错误时区触发，导致日报没有在早 8 点发出。
- **修复**：新增 `timezone` 配置项（默认 `Asia/Shanghai`），cron_manager 与
  APScheduler 兜底两条路径都显式传时区；旧版 cron_manager 不支持 timezone 参数时自动回退。
- **数据源调整**：GitHub 日升榜源顺序改为 **GitHub Search API 优先**
  （官方、最稳），OSS Insight（当前 500）与 gitterapp 作降级，避免依赖挂掉的源。

## v1.1.2（2026-08-28）

### 🐛 修复：死源把去年旧闻当「昨日」展示

- **根因**：人民网官方 RSS（时政/社会/国际/健康）已于 **2025-06-05 停更**，但默认源仍在使用；
  且 `_filter_yesterday` 在「没有昨日/近 24h 条目」时回退到「最新 10 条」，导致 2025 年的旧闻被当成「昨日」发出。
- **修复**：
  - 默认数据源全面替换为**实时免费源**：央视新闻 JSONP（`cctv:china` 国内 / `cctv:world` 国际 / `cctv:news` 要闻）、
    腾讯新闻热榜（`tencent:hot`）、百度热搜（`baidu:hot`）、中国日报世界频道 RSS、WHO / Nature Medicine RSS；
  - `_filter_yesterday` 移除 `dated[:10]` 兜底——**没有昨日/近 24h 条目时该板块直接留空**，
    停更源（如人民网）的陈旧内容永远不会再被当作「昨日」新闻；
  - 支持新的数据源语法：配置里每行可写 RSS URL，或 `cctv:频道` / `tencent:hot` / `baidu:hot`。

### 🚀 增强：GitHub 日升榜国内网络可用性

- GitHub Search API 超时放宽到 **30 秒**并**自动重试 1 次**（国内网络下 api.github.com 常慢于默认 15s 超时），
  提高该板块在手机/国内网络下的成功率；失败时日志明确记录各源原因。

### ✨ 新增数据源 token

- `cctv:china` / `cctv:world` / `cctv:news`：央视新闻 JSONP（免费免 Key，实时，带原文链接）
- `tencent:hot`：腾讯新闻热榜（免费免 Key，标题级热榜，自动过滤占位条目）
- `baidu:hot`：百度热搜（免费免 Key，含搜索链接）

### 🔄 自动迁移：旧版人民网配置

- 老用户插件配置里若某板块仍全是已停更的人民网 RSS（旧版默认值），插件会自动切换到新的实时默认源，
  无需手动改配置；自定义混合源（含其他活源）会原样保留。

## v1.1.3（2026-08-28）

### 🐛 修复：AI 总结漏板块 / 截断（手机上「昨日国际」「GitHub 日升榜」消失）

- **根因**：手机端保存的旧版提示词带「总长度控制在 1200 字内」，AI 为了控制长度把部分板块（国际、GitHub）直接省略。
- **修复**：
  - 默认提示词升级为 **1800 字内 + 有数据的板块必须全部输出**（运行时自动规范化旧版提示词，
    无需手动重置配置，旧「1200 字内」会被自动替换升级）；
  - 新增**发送方式**配置 `digest_send_mode`：`text`（纯文本分条）/ `image`（渲染为图片发送）/
    `file`（保存为 `.md` 文件发送）/ `auto`（默认：短文本直接发，超过 `digest_long_threshold` 自动转图片，
    失败逐级回退 md 文件 → 文本）——长简报不再受消息长度限制。

### 🚀 增强：GitHub 日升榜 6 路降级链（提高手机端成功率）

- 尝试顺序：
  1. GitHub Search API（新建仓库 `created:>N天` 按 star 排序）= 真·日升榜
  2. **gh-proxy.com 镜像**（api.github.com 被墙/超时时的国内代理）
  3. GitHub Search API（全站热门 `stars:>1000` 排序，如 freeCodeCamp / react 等知名项目）
  4. gh-proxy.com 镜像的同上查询
  5. OSS Insight / gitterapp（历史遗留，最后兜底）
- 每个源 25s 超时，命中即返回并在日志记录命中源；全部失败才省略板块。

### 🐛 修复：新闻源抖动重试

- `_fetch_category` 对每个源失败自动重试 1 次，降低手机网络抖动导致的板块缺失。

## v1.1.4（2026-08-28）

### 🐛 修复：AI 以「GitHub 日升榜未列入上述板块」为由不输出

- **根因**：手机配置里保存的旧版提示词，其板块清单只有天气/国内/国际/科技/医药/政策，
  不含 🚀 GitHub 日升榜；AI 严格按「仅输出实际有的板块」清单执行，看到 {data} 里的 GitHub 板块
  却判定「未列入上述板块」而拒绝输出。
- **修复**：提示词规范化（`_normalize_prompt`）在运行时对旧版提示词做三重升级，**无需重置配置**：
  1. 「1200 字内」→「1800 字内」；
  2. 「（仅输出实际有的板块）」→「（有数据的板块必须全部输出，不要遗漏任何板块）」；
  3. 末尾强制追加指令：{data} 中出现的每一个板块（含 🚀 GitHub 日升榜 等）都必须输出，
     只有完全无数据才可跳过——AI 不再能以「未列入板块」为由漏掉 GitHub 日升榜。

## v1.1.5（2026-08-28）

### ✨ 增强：GitHub 日升榜由 AI 说明每个仓库「是什么、有什么功能」

- **根因**：此前传给 AI 的 GitHub 条目只有 `owner/repo ⭐星数 + 链接`，没有仓库描述，
  AI 无从判断项目用途，只能罗列名字。
- **修复**：
  - `_parse_trending_repos` 增加捕获 `language`（语言）字段；
  - `_ai_summarize` 把每条仓库的**描述（description）+ 语言**一并喂给 AI，
    数据行格式：`- owner/repo ⭐…（近N天+…）：仓库描述（语言：Python）（链接）`；
  - 默认提示词新增要求：**每个仓库结合描述用一句话说明「是什么、有什么功能」**
    （如：XX —— 一个用于……的开源项目，提供……能力）；
  - 模板输出同步展示描述与语言（无 AI 时的降级路径）。

## v1.1.6（2026-08-28）

### 🐛 修复：到点没触发日报（手机休眠 / cron misfire / 被门禁拦截）

- **根因一（被拦截）**：proactive_guard 门禁默认只放行白名单与本插件，daily_digest 的定时推送
  在用户未活跃时被判定为「非白名单主动消息」而丢弃——已由 proactive_guard v1.0.4 默认放行
  `daily_digest` 解决（见该插件更新日志）。
- **根因二（misfire 无补发）**：手机在 08:00 休眠/断网时 cron 任务 misfire 被跳过，且没有补发机制。
- **修复**：
  - 新增**每 5 分钟兜底检查任务**（`*/5 * * * *`，含时区）：一旦到达发送时间且当天未发送，
    自动补发，直到 `send_deadline`（默认 13:00）为止——手机唤醒后最迟几分钟内就会补上；
  - 新增 KV 标记 `last_digest_date`：**每天最多发送一次**，08:00 定时与兜底检查不会重复发；
  - 生成失败不记录日期 → 5 分钟后自动重试；
  - 新配置项：`send_deadline`（补发截止 HH:MM，默认 `13:00`，避免深夜误发）。

## v1.1.7（2026-08-30）

### 🐛 修复：图片/文件发送在 QQ 官方平台卡死重试导致日报丢失

- **问题**：QQ 官方适配器媒体上传接口（`upload_group_and_c2c_image`，base64 上传
  `/v2/users/{openid}/files`）返回 None 时会指数退避重试约 5 次（约 90 秒）后放弃；
  此前 `_send_long` 无超时且「部分失败也算成功」，一旦图片上传失败，日报整条丢失
  （还占用定时任务 1-2 分钟）。
- **修复**：
  - 图片/文件发送加 **90 秒超时**（`asyncio.wait_for`），不会无限挂起；
  - **全部目标发送失败时自动回退为纯文本**（分条发送），保证日报不因平台媒体上传失败而丢失；
  - 成功/失败按目标计数并写日志（成功 N/M）。

## v1.1.8（2026-08-30）

### 🐛 修复：日报出现「The request was rejected because it was considered high risk」

- **根因**：AI 总结请求被 LLM 服务商**内容安全拦截**（新闻原文含敏感内容如反腐/事故细节时
  易触发），拦截文本被当作日报内容原样发出。
- **修复**（`_ai_summarize`）：
  - **拦截检测**：识别中英文安全拦截特征（high risk / rejected / content policy / 敏感内容 /
    被拒绝 / 违规 等）；
  - **精简重试**：被拦后自动用「仅标题+链接、每板块最多 3 条」的精简数据重试一次
    （去掉描述/摘要，降低触发概率）；
  - **模板兜底**：仍被拦则抛错，由 `_build_digest` 降级为**模板日报**（无 AI 也能正常发出），
    拦截文本永远不会再出现在日报里。

## v1.2.0（2026-10-15）

### ✨ 新增：政策前沿改接政府官方网站

- 「政策前沿」板块默认数据源从 `cctv:news` + `baidu:hot`（新闻站二手转述）改为**政府官方网站一手来源**：
  - `gov:zuixin` —— 中国政府网「最新政策」，含**中共中央 / 国务院政策文件**（如《中共中央 国务院关于发展新质生产力的意见》）；
  - `ndrc:xwfb` —— 国家发改委「新闻发布」，含价格、区域、民营经济等宏观政策动态；
  - `gov:yaowen` —— 中国政府网「要闻」推送。
- **实现要点**：gov.cn 的政策栏目页面本身是 JS 空壳（`<ul id="list-1-ajax-id">` 由 jQuery 异步填充），
  直接抓 HTML 拿不到条目，因此改为**抓同目录下的 JSON**：
  - `https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json`（字段 `TITLE` / `URL` / `DOCRELPUBTIME` / `SUB_TITLE`，1100+ 条全量按时间倒序）；
  - `https://www.gov.cn/pushinfo/v150203/pushinfo.json`（字段 `title` / `link` / `pubDate` / `description`）；
  - `https://www.ndrc.gov.cn/xwdt/xwfb/`（静态 HTML，正则解析 `<li><a title=...><span>日期</span>`，25 条/页）。
- 新增 `GOV_SOURCES` / `GOV_HEADERS` 常量；`_http_get_bytes()` 支持自定义请求头（不再固定 RSS 的 `Accept`）。
- **时效窗口放宽**：政策文件不是每天发布（实测近 30 天仅约 10 条），沿用「昨日」硬过滤会让政策板块
  **绝大多数时候空白**。因此新增配置 `gov_policy_recent_days`（默认 **30**），
  `_filter_yesterday(items, recent_days)` 支持按板块放宽；窗口内确实没有新政策时，
  `_fetch_gov_source` 会退回最新几条并记录日志（`近 N 天无新政策，退回最新 M 条`）。
  其余板块仍严格卡「昨日 / 近 24 小时」。
- 条目新增 `source` 字段（`中国政府网` / `国家发改委`），便于简报标注出处。

### ✨ 新增：图片与 .md 文件「两份都给」

- 此前 `_send_long` 是**二选一**：图片发送成功就直接 `return True`，**永远不会再发 .md 文件**。
- 现在拆分为 `_send_image()` 与 `_send_md()` 两个独立方法，`_send_digest()` 按模式调度：
  - `both`（**新默认**）——同时发送渲染图片 + `.md` 文件；
  - `auto` —— 短文本仍直接发文本，超阈值时按 `both` 发送；
  - `image` —— 发图片，并默认同时补发 `.md`（由 `digest_also_send_md` 控制，可关）；
  - `file` —— 只发 `.md` 文件；`text` —— 只发纯文本。
- **容错**：图片与 md 任一路径成功即算送达；**两者都失败**才回退纯文本（保留 v1.1.7 的「全目标失败回退」语义）。
- 新配置项：`digest_also_send_md`（bool，默认 `true`）。

### 🐛 修复：渲染图片上出现「划去线」（删除线 / 多余下划线）

- **根因**（AstrBot 渲染链路，两条路径都会出错）：
  - 本地 PIL 渲染器 `astrbot/core/utils/t2i/local_strategy.py` 的行内样式表里，
    `__(.*?)__` 被**同时注册**为 `BoldTextElement` 与 `UnderlineTextElement`（两条正则完全相同），
    而 `MarkdownParser.parse` 对匹配结果**未做重叠去重**、按 start 排序后全部 append，
    导致同一段文字被画两遍并多画一条线；`~~x~~` 则会真的在文字中部画一条删除线
    （`strike_y = y + font_size // 2`）；
  - 网络渲染路径（`template/base.html` + marked.js）会把 `~~x~~` 渲染成 `<del>`。
- **修复**：新增长度函数 `_sanitize_for_image()`，在调用 `text_to_image()` **之前**剥掉
  `~~删除线~~` / `__下划线__` / `**粗体**` / `*斜体*` / `_斜体_` 内联标记
  （日报是资讯文本，不需要这些修饰），同时规避本地与网络两条渲染路径。
  对 `a_b_c` 这类变量名风格的下划线做了边界保护，不会被误伤。

### 🧪 测试

- 新增本地桩测试（AstrBot API 全量打桩，不依赖真实 AstrBot 实例）：
  - `_sanitize_for_image` 8 组用例（删除线 / 下划线 / 粗体 / 斜体 / 混合 / 变量名保护 / 无标记）**全部通过**；
  - `_send_digest` 10 组场景断言**全部通过**：`both` → 图片+文件、`text` → 纯文本、`file` → 仅文件、
    `image`+`digest_also_send_md` 开/关、`auto` 阈值上下、图片渲染失败时 md 仍送达、多目标各自成对发送。
- 政府源联网实测：`gov:zuixin` 返回 10 条（近 30 天）、`gov:yaowen` 返回 10 条、`ndrc:xwfb` 返回 9 条；
  `_fetch_category("feeds_policy", 5)` 端到端产出 5 条真实政府官网政策条目。

## v1.2.1

### 🐛 修复

- **日报图片 100% 发送失败（日志刷 `not a valid url`）**：`text_to_image(return_url=True)`
  在 AstrBot 网络渲染不可用/超时时会回退到**本地 PIL 渲染**，此时返回的是容器内文件路径
  （如 `/AstrBot/data/temp/io_temp_img_1792221389_8477ba.jpg`）而不是 URL。旧代码一律
  `MessageChain().url_image(...)`，平台侧 `Image.fromURL` 判为非法 → 图片全部失败后静默
  退回纯文本，`digest_also_send_md` 的「一份图片 + 一份 md」实际永远只到 md。
  新增模块级 `_image_chain()`，按 `http(s)://` / `file://` / `base64://` /
  `data:image;base64,` / 本地路径 分流构造消息链。
- **国际新闻源 404**：`feeds_intl` 默认的 `chinadaily.com.cn/rss/world_rss.xml` 已 404，
  换成 `chinanews.com.cn/rss/world.xml`（实测 30 条）+ `cgtn.com/.../world.xml`（50 条）。

### 🔧 其它

- `metadata.yaml` 版本 → 1.2.1。

## v1.2.2（2026-10-17）

### 🐛 修复：同一天收到两遍简报

真机日志：08:01:54 / 08:01:58 发完一组「图片 + md」后，08:03:00 / 08:03:03 又发一组。
根因是防重靠「读 KV `last_digest_date` → 生成（1~2 分钟）→ 写回 KV」，而 08:00 定时任务
（`_on_schedule`）与每 5 分钟兜底检查（`_on_check`）会**同时**触发，两个协程都能在写回之前
通过「今天还没发过」的检查。

- 新增 `self._digest_lock`（`asyncio.Lock`）：拿到锁后再查一次 KV，真正挡住第二个协程；
- **先占位再生成**：进锁即把今天日期写入 KV，生成/发送抛异常时回滚，避免当天彻底不再补发；
- 新增 `force` 参数（手动 `/每日简报` 不受「今天已发」与时间窗限制）。

### 🔧 其它

- `metadata.yaml` 版本 → 1.2.2；整合包 `astrbot-plugin-elaina-suite` v1.1.3 同步本版修复。

## v1.2.3（2026-10-25）

> 版本号与整合包 `astrbot-plugin-elaina-suite` v1.1.7 对齐（本仓库此前为 1.2.2，本次顺延到 1.2.3（功能与整合包 v1.1.7 对齐））。
> 本版改动从整合包移植，两侧语义一致。

### 🐛 问题

- **简报图片全是乱码（中文全渲染成方框 □，英文数字正常）**：AstrBot 的 t2i 先走网络渲染
  （`t2i.soulter.top` 等），实测连续 `HTTP 503` / 连接超时后回退到**本地 PIL 渲染**；而 AstrBot
  官方 Docker 镜像里**没有任何 CJK 字体**（容器内 `fc-list :lang=zh` 为空，Debian 13 trixie），
  PIL 只能用内置位图字体，中文一律画成方框。
- **缺少「AI」「网安」两个板块**：原只有科技前沿，AI 进展与漏洞情报混在科技源里，经常被漏掉。
- **放宽时效窗口时当天条目被整体丢弃**：`_filter_yesterday(recent_days>0)` 的窗口末端取的是
  「今天 0 点」，早上 8 点跑的日报会把**当天 0 点之后发布的所有条目**全过滤掉，放宽窗口等于白放宽。

### ✨ 改动

- **新增板块「🤖 AI 界的新变化」**：默认源量子位 `https://www.qbitai.com/feed` + InfoQ 中文
  `https://www.infoq.cn/feed`（配置键 `feeds_ai` / 开关 `ai_enabled`），时效 `ai_recent_days`（默认 2 天）。
- **新增板块「🛡️ 网安漏洞与情报」**：默认源 FreeBuf `https://www.freebuf.com/feed`、安全客
  `https://api.anquanke.com/data/v1/rss`、先知社区 `https://xz.aliyun.com/feed`，外加 **CISA KEV
  已知被利用漏洞目录**（`cisa:kev`，配置里的特殊 token）；时效 `security_recent_days`（默认 2 天）。
  - KEV 单文件约 1.8MB（JSON），因此单独走 `security_kev_days`（默认 7 天，KEV 新增节奏不均匀，
    卡「昨日」会经常整块空白），并有 **6 小时下载缓存**（缓存的是已解析的全量条目，窗口每次重算）；
    条目标题为 `CVE-xxxx：厂商 产品 —— 漏洞名`，`knownRansomwareCampaignUse=known` 时摘要追加
    「⚠️ 已用于勒索软件」，链接指向 NVD 详情页 `https://nvd.nist.gov/vuln/detail/<CVE>`。
  - KEV 结果走 `prewindowed` 通道，不再被二次时效过滤，只参与合并排序。
  - 抓取失败只 warning 且返回空列表，绝不拖垮整份日报。
- **修复放宽窗口末端**：`recent_days>0` 时窗口末端改为 `now + 5 分钟`，当天发布的条目能正常进入板块
  （政策前沿同样受益）。
- **中文字体自愈**：插件自带 GB2312 子集字体 `assets/fonts/digest_cjk.ttf`（6763 汉字 + 符号，
  约 2MB）。启动时与渲染图片前调用 `_ensure_cjk_font()`，目标 `<data>/font.ttf` 缺失才写入
  （**不覆盖**用户已有字体），写完打日志；字体资源缺失时静默跳过，不影响其它功能。
- **提示词同步**：`DEFAULT_PROMPT` 与 `_normalize_prompt` 的【强制要求】板块清单都加入新的两块，
  旧版 `llm_prompt` 配置无需手动改。

### 🔧 其它

- `_conf_schema.json` 29 → 36 键：`ai_enabled` / `security_enabled` / `feeds_ai` / `feeds_security` /
  `ai_recent_days` / `security_recent_days` / `security_kev_days`（`llm_prompt` 默认值同步）。
- 新增 `tests/test_digest_v117.py`：板块顺序与默认源、KEV 解析（7 天窗口 / 勒索标记 / NVD 链接 /
  6 小时缓存 / 窗口收窄重算 / 失败隔离）、`feeds_ai` 与 `feeds_security` 时效窗口、放宽窗口含当天条目、
  模板渲染新标题、schema 新键、字体自愈（缺失补 / 不覆盖 / 资源缺失静默）。
- `metadata.yaml` 版本 → 1.1.7。
