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