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