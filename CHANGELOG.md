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