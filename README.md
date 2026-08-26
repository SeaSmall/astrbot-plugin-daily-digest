# AstrBot 每日简报插件（daily_digest）

一个基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的每日简报插件：定时抓取**天气**（支持多城市）与**昨日新闻**（国内 / 国际）、**科技 / 医药 / 政策前沿**、**GitHub 日升榜**，由 AI 总结成一份简洁的中文简报，并**自动推送给所有用户**。

> 数据源全部为**免费、免 API Key** 的公开服务（Open-Meteo 天气 API + 公开 RSS 源 + GitHub 趋势 API），插件本身零第三方依赖（仅使用 Python 标准库，AstrBot 自带 apscheduler）。

## ✨ 功能特性

- 🌤️ **天气板块**：基于 [Open-Meteo](https://open-meteo.com/)（免费免 Key），支持**多城市**（换行 / 逗号 / 顿号分隔，逐城市输出），自动地理编码（7 天缓存），输出当前 / 今日 / 明日天气、温度、体感、湿度、风速、降水概率；内置**防高并发**（结果缓存、单飞锁、请求节流、失败隔离）
- 🚀 **GitHub 日升榜**：近 N 天 star 增长最快的仓库 Top10（免费免 Key **多源降级**：OSS Insight → GitHub Search API → gitterapp），可配最低 star 过滤
- 📰 **昨日新闻**：国内 / 国际分板块，自动按「昨日」过滤条目（不足时回退近 24 小时 / 最新）
- 💻 **科技前沿** / 💊 **医药前沿** / 📜 **政策前沿**：各板块可独立开关
- 🤖 **AI 总结**：调用 AstrBot 当前配置的 LLM 生成结构化简报；AI 不可用时**自动降级**为模板格式
- ⏰ **可配置发送时间**：标准 5 段 cron 表达式（默认每天 08:00）
- 📢 **推送给所有用户**：自动枚举数据库中的全部会话（与 AstrBot 面板「会话管理」同源），也支持手动指定会话 / 订阅退订
- 🧩 **可自定义**：每个板块的 RSS 源、条目数量、提示词均可配置

## 📦 安装

### 方式一：通过 Git 地址安装（推荐）

1. AstrBot WebUI →「插件」→「安装插件」→「通过 Git 地址安装」
2. 输入仓库地址：`https://github.com/SeaSmall/astrbot-plugin-daily-digest`
3. 安装完成后启用插件，并按需修改配置（WebUI → 插件 → 每日简报 → 配置）

### 方式二：手动拷贝

将本仓库的 `metadata.yaml`、`_conf_schema.json`、`main.py` 放到 AstrBot 的插件目录：

```
AstrBot/data/plugins/daily_digest/
├── metadata.yaml
├── _conf_schema.json
└── main.py
```

然后重启 AstrBot 或在插件页点击「重载」。

> 要求 **AstrBot 4.x**（本项目按 4.x 插件 API 开发；定时主动消息需要平台适配器支持主动发送，如 `aiocqhttp` / OneBot v11 支持，QQ 官方 API 平台不支持主动消息）。

## ⚙️ 配置说明

在 AstrBot WebUI 的插件配置面板中修改：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `send_cron` | string | `0 8 * * *` | 定时发送时间（标准 5 段 cron，默认每天 08:00；如 `30 7 * * 1-5` 为工作日 07:30） |
| `weather_city` | string | `上海` | 天气城市，**支持多城市**：换行 / 逗号 / 顿号分隔（如 `上海、北京、广州`） |
| `weather_enabled` | bool | `true` | 是否启用天气板块 |
| `weather_cache_minutes` | int | `30` | 天气结果缓存时间（分钟），缓存期内直接复用 |
| `weather_interval_seconds` | int | `3` | 相邻两次 Open-Meteo 请求最小间隔（秒），防限流 |
| `news_cn_enabled` | bool | `true` | 是否启用「昨日国内」板块 |
| `news_intl_enabled` | bool | `true` | 是否启用「昨日国际」板块 |
| `tech_enabled` | bool | `true` | 是否启用「科技前沿」板块 |
| `medical_enabled` | bool | `true` | 是否启用「医药前沿」板块 |
| `policy_enabled` | bool | `true` | 是否启用「政策前沿」板块 |
| `github_trending_enabled` | bool | `true` | 是否启用「GitHub 日升榜」板块（近 N 天 star 增长最快仓库 Top10） |
| `github_trending_days` | int | `7` | GitHub 日升榜统计周期（天） |
| `github_trending_count` | int | `10` | GitHub 日升榜展示仓库数（Top N） |
| `github_trending_min_stars` | int | `0` | GitHub 日升榜最低 star 过滤（0 = 不过滤） |
| `max_items_per_section` | int | `5` | 每个新闻板块最多保留的条目数 |
| `ai_summary_enabled` | bool | `true` | 是否用 AI 总结（关闭或 AI 不可用时自动使用模板格式） |
| `target_sessions` | text | 空 | 指定推送会话（unified_msg_origin，每行一个，如 `aiocqhttp:Group:123456789`）；**留空 = 推送给所有用户** |
| `feeds_cn` / `feeds_intl` / `feeds_tech` / `feeds_medical` / `feeds_policy` | text | 见下 | 各板块 RSS 源 URL，每行一个，可自由增删 |
| `llm_prompt` | text | 见下 | AI 总结提示词（`{date}` 日期、`{data}` 原始资讯会自动替换） |

## 📡 默认数据源（全部免费）

| 板块 | 源 |
| --- | --- |
| 天气 | [Open-Meteo](https://open-meteo.com/) 地理编码 + 天气预报 API（免 Key） |
| 昨日国内 | 人民网时政、人民网社会（RSS） |
| 昨日国际 | 人民网国际、中国日报 China Daily（RSS） |
| 科技前沿 | IT之家、少数派、爱范儿、极客公园（RSS） |
| 医药前沿 | 人民网健康、WHO 新闻、Nature Medicine（RSS） |
| 政策前沿 | 人民网时政（RSS） |
| GitHub 日升榜 | [OSS Insight](https://api.ossinsight.io/v1/trends/repos/) → [GitHub Search API](https://docs.github.com/rest/search) → [gitterapp](https://api.gitterapp.com/repositories/trending)（全部免 Key，多源降级） |

所有 RSS 源均为公开免费源。若个别源不可用，可在配置中替换，也可加入 [RSSHub](https://docs.rsshub.app/) 路由（如 `https://rsshub.app/gov/zhengce/zuixin` 等）以覆盖更多站点。

## 🎮 指令

| 指令 | 说明 |
| --- | --- |
| `/digest` 或 `/日报` | 立即生成并推送一份简报到当前会话 |
| `/订阅日报` | 订阅每日简报（定时推送到当前会话；即使未设置 `target_sessions`，也会被计入推送对象） |
| `/退订日报` | 退订每日简报 |

## 📝 效果示例（模板格式，AI 总结格式类似但更精炼）

```
📰 每日简报 · 2026-08-25 星期二

🌤️ 天气
→【上海】现在：晴，30°C（体感 33°C），湿度 60%，风速 12km/h；今日：多云，26~35°C，降水概率 10%；明日：晴，25~33°C
→【北京】现在：多云，28°C（体感 30°C），湿度 55%，风速 8km/h；今日：阴，22~29°C，降水概率 30%

🇨🇳 昨日国内
1. 标题一
   🔗 https://...
2. 标题二
   🔗 https://...

🚀 GitHub 日升榜
1. openai/whisper ⭐1234（近7天+56）
   🔗 https://github.com/openai/whisper
2. ...

💻 科技前沿
...
```

## ❓ 常见问题

**Q：到点没有推送？**
- 确认插件已启用，且平台适配器支持主动消息（OneBot v11 / aiocqhttp 支持，QQ 官方 API 不支持）。
- 检查 AstrBot 日志（插件日志前缀 `[daily_digest]`）：是否提示「没有可推送的会话」（说明数据库里还没有任何会话，先让用户和机器人聊一句，或使用 `/订阅日报`）。
- 定时使用系统时区；如跨时区部署，请确认服务器时区正确。

**Q：AI 总结没生效？**
- 确认 AstrBot 已配置可用的大语言模型服务商，且 `ai_summary_enabled` 为开启。AI 调用失败会自动降级为模板格式推送。

**Q：某个新闻源抓不到？**
- 在插件配置中替换对应板块的 `feeds_*` 源，或更换网络环境（部分境外源需可访问外网）。

**Q：GitHub 日升榜没显示？**
- 三个数据源（OSS Insight / GitHub Search API / gitterapp）全部不可达时该板块会省略并在日志记录；
- GitHub Search API 无鉴权限速 10 次/分钟，日报每天一次不会触发；
- 可用 `github_trending_min_stars` 过滤低 star 仓库，用 `github_trending_days` 调整周期。

**Q：多城市天气怎么配？**
- 在 `weather_city` 用换行 / 逗号 / 顿号分隔多个城市（如 `上海、北京、广州`），逐城市输出；
- 天气有 30 分钟结果缓存与 3 秒请求间隔（均可配），城市再多也不会打爆 Open-Meteo。

## 📦 更新日志

- [CHANGELOG.md](CHANGELOG.md)

## ⚠️ 免责声明

- 本项目仅用于学习与个人用途；抓取内容版权归原媒体所有。
- 推送内容由 AI 生成，请自行甄别，仅供参考。