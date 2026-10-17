"""
daily_digest —— AstrBot 每日简报插件

功能：
- 定时（可配置 cron）抓取天气与多类新闻源（全部为免费、免 Key 的公开 API / RSS）
- 调用 AstrBot 当前 LLM 生成中文每日简报（AI 不可用时自动降级为模板）
- 推送给所有用户（数据库会话枚举 + 订阅会话 + 手动指定目标）
- 手动指令 /digest（/日报）可即时生成

要求：AstrBot >= 3.5.19（推荐 4.x，依赖 apscheduler，AstrBot 自带）
"""

from __future__ import annotations

import asyncio
import html
import inspect
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File, Plain
from astrbot.api.star import Context, Star

try:
    from astrbot.api.event import MessageChain
except ImportError:  # 旧版本兼容
    from astrbot.api.message_components import MessageChain

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 政府官方网站数据源（政策板块用；全部免费、免 Key）
#   gov:zuixin  -> 中国政府网「最新政策」列表 JSON（含中共中央/国务院最新政策文件）
#   gov:yaowen  -> 中国政府网「要闻」推送 JSON
#   ndrc:xwfb   -> 国家发改委「新闻发布」列表页
# 说明：gov.cn 的政策栏目页面本身是 JS 空壳，条目由同目录下的 JSON 填充，
#      因此这里直接抓 JSON（ZUIXINZHENGCE.json / pushinfo.json），更稳更快。
GOV_SOURCES = ("gov:zuixin", "gov:yaowen", "ndrc:xwfb")

GOV_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.gov.cn/",
}

# WMO 天气代码 -> 中文描述（Open-Meteo）
WMO_CODES = {
    0: "晴", 1: "基本晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "雷暴伴冰雹",
}

# 各板块默认数据源（全部免费、免 Key；可在插件配置中自定义）
# 支持四类条目：
#   - URL             ：RSS/Atom 源
#   - "cctv:频道"     ：央视新闻 JSONP（china/world/news 等）
#   - "tencent:hot"   ：腾讯新闻热榜 JSON
#   - "baidu:hot"     ：百度热搜 JSON
#   - "gov:zuixin"    ：中国政府网「最新政策」（gov.cn 政府官网，政策板块专用）
#   - "gov:yaowen"    ：中国政府网「要闻」（gov.cn 政府官网）
#   - "ndrc:xwfb"     ：国家发改委「新闻发布」（ndrc.gov.cn 政府官网）
# 注：人民网官方 RSS 已于 2025 年停更（内容停留在 2025-06-05），默认不再使用；
#     若自行配置 RSS，务必确认源仍在更新（插件有严格时效过滤，陈旧条目不会显示）。
DEFAULT_FEEDS = {
    "feeds_cn": [
        "cctv:china",
        "tencent:hot",
        "baidu:hot",
    ],
    "feeds_intl": [
        "cctv:world",
        # chinadaily 的 world_rss.xml 已 404（实测），换成中国新闻网与 CGTN
        "https://www.chinanews.com.cn/rss/world.xml",
        "https://www.cgtn.com/subscribe/rss/section/world.xml",
    ],
    "feeds_tech": [
        "https://www.ithome.com/rss/",
        "https://sspai.com/feed",
        "https://www.ifanr.com/feed",
        "https://www.geekpark.net/rss",
    ],
    "feeds_medical": [
        "https://www.who.int/rss-feeds/news-english.xml",
        "https://www.nature.com/nm.rss",
    ],
    "feeds_policy": [
        "gov:zuixin",
        "ndrc:xwfb",
        "gov:yaowen",
    ],
}

# 板块顺序：(启用开关配置项, feed 配置项, 板块名, 图标)
SECTIONS = [
    ("news_cn_enabled", "feeds_cn", "昨日国内", "🇨🇳"),
    ("news_intl_enabled", "feeds_intl", "昨日国际", "🌍"),
    ("tech_enabled", "feeds_tech", "科技前沿", "💻"),
    ("medical_enabled", "feeds_medical", "医药前沿", "💊"),
    ("policy_enabled", "feeds_policy", "政策前沿", "📜"),
    ("github_trending_enabled", "github_trending", "GitHub 日升榜", "🚀"),
]

# GitHub 日升榜抓取尝试顺序（免费免 Key，依次降级，全部失败则省略板块）：
# 1) GitHub Search API 新建仓库（created:>N 天，按 star 排序）= 真正的「日升榜」
# 2) gh-proxy.com 镜像（api.github.com 被墙/超时时的国内代理）
# 3) GitHub Search API 全站热门（stars 排序，如 freeCodeCamp/react 等知名项目）
# 4) gh-proxy.com 镜像的同上查询
# 5) OSS Insight / gitterapp（历史遗留，通常不可达，仅作最后兜底）
GITHUB_TRENDING_SOURCES = (
    "github_search_created",
    "ghproxy_search_created",
    "github_search_alltime",
    "ghproxy_search_alltime",
    "ossinsight",
    "gitterapp",
)

# 天气：每日 Open-Meteo 调用次数上限（保险，防止误触发限流）
WEATHER_DAILY_CALL_LIMIT = 120

DEFAULT_PROMPT = """你是一名严谨、简洁的中文每日简报编辑。今天是 {date}。
请根据下面的原始资讯生成【每日简报】，要求：
1. 按板块输出：🌤️ 天气、🇨🇳 昨日国内、🌍 昨日国际、💻 科技前沿、💊 医药前沿、📜 政策前沿、🚀 GitHub 日升榜（有数据的板块必须全部输出，不要遗漏任何板块）
2. 每个板块先用 1-2 句话概括，再列 3-5 条要点（标题 + 一句话说明），重要条目附原文链接
3. 🚀 GitHub 日升榜的每个仓库要结合给出的描述，用一句话说明它「是什么、有什么功能」（如：XX —— 一个用于……的开源项目，提供……能力）
4. 客观简洁、不夸张、不编造；总长度控制在 1800 字内
原始资讯：
{data}"""


def _local_name(tag: str) -> str:
    """取 XML 标签本地名（去掉命名空间）。"""
    return tag.rsplit("}", 1)[-1]


def _strip_html(text: str) -> str:
    """去除 HTML 标签并反转义实体，压缩空白。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _sanitize_for_image(text: str) -> str:
    """净化用于 t2i 渲染的文本，去掉会导致「划线」的内联 markdown 标记。

    背景（AstrBot 两个渲染路径都会出错）：
      1) 本地 PIL 渲染器 astrbot/core/utils/t2i/local_strategy.py 的行内样式表里
         `__(.*?)__` 被同时注册为 BoldTextElement 与 UnderlineTextElement（两条正则
         完全相同），匹配结果未做重叠去重，导致同一段文字被画两遍、多出一条线；
         且 `~~x~~` 会真的在文字中间画一条删除线。
      2) 网络渲染路径（template/base.html + marked.js）会把 `~~x~~` 渲染成 <del> 删除线。
    日报是资讯文本，不需要删除线/下划线/斜体这些修饰，直接剥掉标记最稳。
    """
    if not text:
        return ""
    # 删除线：~~文字~~ -> 文字
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # 下划线 / 粗体：__文字__ -> 文字
    text = re.sub(r"__(.+?)__", r"\1", text)
    # 粗体：**文字** -> 文字
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # 斜体：*文字* -> 文字（先处理粗体，避免误伤）
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # 单下划线斜体：_文字_ -> 文字
    text = re.sub(r"(?<![A-Za-z0-9_])_(.+?)_(?![A-Za-z0-9_])", r"\1", text)
    return text


def _image_chain(render_result) -> "MessageChain":
    """把 text_to_image(return_url=True) 的返回值转成可发送的图片消息链。

    AstrBot 的 render_t2i 先走网络渲染（成功时返回 https URL），网络不可用或超时时
    回退到本地 PIL 渲染，此时返回的是**容器内的文件路径**
    （例如 /AstrBot/data/temp/io_temp_img_1792221389_8477ba.jpg）。
    旧代码一律 MessageChain().url_image(...)，本地路径会被 Image.fromURL 判为非法 URL
    并抛 "not a valid url"，导致日报图片 100% 发送失败、静默退回纯文本。
    """
    if render_result is None:
        raise ValueError("渲染结果为空")
    r = str(render_result).strip()
    if not r:
        raise ValueError("渲染结果为空")
    low = r.lower()
    if low.startswith(("http://", "https://")):
        return MessageChain().url_image(r)
    if low.startswith("file://"):
        return MessageChain().file_image(urllib.parse.unquote(r[len("file://"):]))
    if low.startswith("base64://"):
        return MessageChain().base64_image(r[len("base64://"):])
    if low.startswith("data:image") and ";base64," in r:
        return MessageChain().base64_image(r.split(";base64,", 1)[1])
    if os.path.isfile(r):
        return MessageChain().file_image(r)
    return MessageChain().url_image(r)


def _parse_date(text: str) -> datetime | None:
    """解析 RSS(RFC822)/Atom(ISO8601) 日期。"""
    if not text:
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


class DailyDigestPlugin(Star):
    """每日简报插件"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._fallback_sched = None
        self._cron_job_id = None
        self._cron_check_job_id = None
        # 天气防高并发状态：每城市单飞锁 + 全局请求节流 + 每日调用计数
        self._weather_locks: dict[str, asyncio.Lock] = {}
        self._last_weather_call = 0.0
        self._weather_call_day = ""
        self._weather_call_count = 0
        # 发送防重：08:00 定时任务与 5 分钟兜底检查会同时触发，
        # 生成一份简报要 1~2 分钟，旧写法两个协程都会通过「今天没发过」的检查 -> 一天发两遍
        self._digest_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def initialize(self) -> None:
        """插件被激活时调用：注册定时任务。"""
        await self._setup_scheduler()

    async def terminate(self) -> None:
        """插件被禁用/重载时调用：清理定时任务。"""
        try:
            cm = getattr(self.context, "cron_manager", None)
            if cm is not None and hasattr(cm, "delete_job"):
                for jid in (self._cron_job_id, self._cron_check_job_id):
                    if jid:
                        try:
                            await cm.delete_job(jid)
                        except Exception:
                            pass
                self._cron_job_id = None
                self._cron_check_job_id = None
        except Exception as e:
            logger.warning(f"[daily_digest] 注销 cron 任务失败: {e}")
        try:
            if self._fallback_sched is not None:
                self._fallback_sched.shutdown(wait=False)
                self._fallback_sched = None
        except Exception as e:
            logger.warning(f"[daily_digest] 关闭调度器失败: {e}")

    # ------------------------------------------------------------------ #
    # 定时任务注册
    # ------------------------------------------------------------------ #
    async def _setup_scheduler(self) -> None:
        cron = str(self.config.get("send_cron") or "0 8 * * *").strip()
        tz = str(self.config.get("timezone") or "Asia/Shanghai").strip()
        # 优先使用 AstrBot 内置 cron_manager（AstrBot 4.x）
        try:
            cm = getattr(self.context, "cron_manager", None)
            if cm is not None and hasattr(cm, "add_basic_job"):
                try:
                    job = await cm.add_basic_job(
                        name="daily_digest",
                        cron_expression=cron,
                        handler=self._on_schedule,
                        description="每日简报定时发送",
                        enabled=True,
                        persistent=False,
                        timezone=tz,
                    )
                    j2 = await cm.add_basic_job(
                        name="daily_digest_check",
                        cron_expression="*/5 * * * *",
                        handler=self._on_check,
                        description="每日简报兜底补发检查（每 5 分钟）",
                        enabled=True,
                        persistent=False,
                        timezone=tz,
                    )
                except TypeError:
                    # 旧版 cron_manager 不支持 timezone 参数
                    job = await cm.add_basic_job(
                        name="daily_digest",
                        cron_expression=cron,
                        handler=self._on_schedule,
                        description="每日简报定时发送",
                        enabled=True,
                        persistent=False,
                    )
                    j2 = await cm.add_basic_job(
                        name="daily_digest_check",
                        cron_expression="*/5 * * * *",
                        handler=self._on_check,
                        description="每日简报兜底补发检查（每 5 分钟）",
                        enabled=True,
                        persistent=False,
                    )
                self._cron_job_id = getattr(job, "job_id", None)
                self._cron_check_job_id = getattr(j2, "job_id", None)
                logger.info(
                    f"[daily_digest] 已注册定时任务（cron_manager）: {cron} + 每5分钟兜底检查（时区 {tz}）"
                )
                return
        except Exception as e:
            logger.warning(
                f"[daily_digest] cron_manager 注册失败，回退 APScheduler: {e}"
            )
        # 回退：直接使用 APScheduler（AstrBot 自带依赖，显式指定时区）
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self._fallback_sched = AsyncIOScheduler(timezone=tz)
            self._fallback_sched.add_job(
                self._on_schedule,
                CronTrigger.from_crontab(cron, timezone=tz),
                id="daily_digest",
                misfire_grace_time=60,
            )
            self._fallback_sched.add_job(
                self._on_check,
                CronTrigger.from_crontab("*/5 * * * *", timezone=tz),
                id="daily_digest_check",
                misfire_grace_time=60,
            )
            self._fallback_sched.start()
            logger.info(
                f"[daily_digest] 已注册定时任务（APScheduler）: {cron} + 每5分钟兜底检查（时区 {tz}）"
            )
        except Exception as e:
            logger.error(f"[daily_digest] 定时任务注册失败: {e}")

    # ------------------------------------------------------------------ #
    # 指令
    # ------------------------------------------------------------------ #
    @filter.command("digest", alias={"日报"})
    async def digest_command(self, event: AstrMessageEvent):
        """立即生成并推送一份每日简报"""
        await self._remember_session(event.unified_msg_origin)
        asyncio.create_task(self._generate_and_send([event.unified_msg_origin]))
        yield event.plain_result("⏳ 正在抓取数据并生成今日简报，请稍候…")

    @filter.command("订阅日报")
    async def subscribe_command(self, event: AstrMessageEvent):
        """订阅每日简报（定时推送到当前会话）"""
        await self._remember_session(event.unified_msg_origin)
        yield event.plain_result("✅ 已订阅每日简报，将按配置时间推送到当前会话。")

    @filter.command("退订日报")
    async def unsubscribe_command(self, event: AstrMessageEvent):
        """退订每日简报"""
        await self._forget_session(event.unified_msg_origin)
        yield event.plain_result("✅ 已退订每日简报。")

    # ------------------------------------------------------------------ #
    # 定时任务入口（08:00 cron + 每 5 分钟兜底补发，每天最多发一次）
    # ------------------------------------------------------------------ #
    async def _on_schedule(self) -> None:
        """定时任务入口（cron_manager 以 handler() 方式调用，无需参数）"""
        await self._maybe_send_digest()

    async def _on_check(self) -> None:
        """兜底检查（每 5 分钟）：错过 08:00（设备休眠/网络中断/cron misfire）时补发"""
        await self._maybe_send_digest()

    async def _maybe_send_digest(self, force: bool = False) -> None:
        """每天最多发送一次：到达发送时间且在补发窗口内则生成并发送，成功后记录已发日期。

        force=True 时忽略「今天已发」与时间窗（供手动 /每日简报 使用）。

        并发防护分两层（缺一不可）：
        1. ``self._digest_lock``：08:00 定时任务与每 5 分钟兜底检查会**同时**触发，
           生成一份简报要 1~2 分钟，旧的「先读 KV 再写回」会让两个协程都通过检查，
           实测就是早上收到两遍简报。锁内二次读 KV 才能真正挡掉第二个。
        2. **先占位再生成**：进锁后立刻把今天的日期写进 KV，异常时清空回滚。
           这样即使进程在生成途中被重启，也不会在同一天重复发送。
        """
        try:
            now = self._now_local()
            today = now.strftime("%Y-%m-%d")
            if not force:
                start_h, start_m = self._send_window_start()
                deadline_h, deadline_m = self._send_deadline()
                now_min = now.hour * 60 + now.minute
                if now_min < start_h * 60 + start_m:
                    return  # 还没到发送时间
                if now_min > deadline_h * 60 + deadline_m:
                    return  # 超过补发截止时间，今天放弃（避免深夜误发）
            async with self._digest_lock:
                if not force:
                    try:
                        last = (await self.get_kv_data("last_digest_date", "")) or ""
                    except Exception:
                        last = ""
                    if last == today:
                        return  # 别的协程刚发完
                targets = await self._collect_target_sessions()
                if not targets:
                    logger.warning("[daily_digest] 没有可推送的会话，跳过本次发送")
                    return
                # 原子占位：先写 KV 再生成，避免第二个协程在生成期间挤进来
                try:
                    await self.put_kv_data("last_digest_date", today)
                except Exception as e:
                    logger.debug(f"[daily_digest] 预占发送日期失败: {e}")
                try:
                    await self._generate_and_send(targets)
                except Exception:
                    # 生成/发送失败必须回滚，否则今天不会再补发
                    try:
                        await self.put_kv_data("last_digest_date", "")
                    except Exception:
                        pass
                    raise
                logger.info(f"[daily_digest] 今日简报已发送（{today}）")
        except Exception as e:
            logger.error(f"[daily_digest] 定时发送失败: {e}", exc_info=True)

    def _now_local(self) -> datetime:
        """按配置时区取当前时间（zoneinfo 失败时回退系统本地时间）。"""
        tz_name = str(self.config.get("timezone") or "Asia/Shanghai").strip()
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            return datetime.now().astimezone()

    def _send_window_start(self) -> tuple[int, int]:
        """从 send_cron 解析发送时刻 (hour, minute)。"""
        cron = str(self.config.get("send_cron") or "0 8 * * *").strip()
        parts = cron.split()
        try:
            minute = int(parts[0]) if parts[0].isdigit() else 0
            hour = int(parts[1]) if parts[1].isdigit() else 8
            return (hour, minute)
        except Exception:
            return (8, 0)

    def _send_deadline(self) -> tuple[int, int]:
        """补发截止时刻 (hour, minute)，默认 13:00。"""
        dl = str(self.config.get("send_deadline") or "13:00").strip()
        try:
            h, m = dl.split(":")
            return (int(h), int(m))
        except Exception:
            return (13, 0)

    # ------------------------------------------------------------------ #
    # 生成与发送
    # ------------------------------------------------------------------ #
    async def _generate_and_send(self, targets: list[str]) -> None:
        try:
            digest = await self._build_digest()
        except Exception as e:
            logger.error(f"[daily_digest] 生成简报失败: {e}", exc_info=True)
            digest = f"⚠️ 每日简报生成失败：{e}"
        await self._send_digest(digest, targets)

    async def _send_digest(self, text: str, targets: list[str]) -> None:
        """按 digest_send_mode 发送简报：
        text   -> 纯文本分条发送
        image  -> 渲染为图片发送（AstrBot t2i）
        file   -> 保存为 .md 文件发送（需平台支持本地文件）
        both   -> 同时发送图片 + .md 文件（图片失败则自动降级为「md + 文本」）
        auto   -> 短文本直接发文本；超过 digest_long_threshold 时按 both 发送
                  （即图片与 .md 都发；图片失败回退 md/文本）

        注：只要发送方式包含图片，就**同时**补发一份 .md 文件——图片便于手机阅读，
        md 文件便于保存/检索/二次加工，两者互补。
        """
        mode = str(self.config.get("digest_send_mode") or "auto").strip().lower()
        threshold = self._cfg_int("digest_long_threshold", 2000)
        if mode not in ("text", "image", "file", "both", "auto"):
            mode = "auto"

        send_image = False
        send_md = False
        if mode == "text":
            pass
        elif mode == "image":
            send_image = True
            send_md = bool(self._cfg_bool("digest_also_send_md", True))
        elif mode == "file":
            send_md = True
        elif mode == "both":
            send_image = True
            send_md = True
        elif mode == "auto":
            if len(text) > threshold:
                send_image = True
                send_md = bool(self._cfg_bool("digest_also_send_md", True))

        if not send_image and not send_md:
            for umo in targets:
                await self._send_text(umo, text)
            return

        img_ok = await self._send_image(text, targets) if send_image else False
        md_ok = await self._send_md(text, targets) if send_md else False

        # 图片与文件都失败 -> 回退纯文本，保证简报一定送达
        if not img_ok and not md_ok:
            logger.warning("[daily_digest] 图片与 md 文件均发送失败，回退纯文本")
            for umo in targets:
                await self._send_text(umo, text)

    async def _send_image(self, text: str, targets: list[str]) -> bool:
        """渲染为图片并发送；任一目标成功即返回 True。

        注意：图片发送时 QQ 官方等平台的媒体上传可能长时间重试（如
        upload_group_and_c2c_image 5 次指数退避约 90s），这里加超时与「全目标失败回退」，
        避免日报因图片上传失败而整体丢失。"""
        try:
            render_text = _sanitize_for_image(text)
            url = await self.text_to_image(render_text, return_url=True)
            if not url:
                logger.warning("[daily_digest] 简报渲染图片返回空")
                return False
            try:
                chain = _image_chain(url)
            except Exception as e:
                logger.error(
                    f"[daily_digest] 渲染结果无法转成图片消息链: {e}（原始值={str(url)[:120]}）"
                )
                return False
            ok_cnt = 0
            for umo in targets:
                try:
                    await asyncio.wait_for(
                        self.context.send_message(umo, chain),
                        timeout=90,
                    )
                    ok_cnt += 1
                except Exception as e:
                    logger.error(f"[daily_digest] 图片发送到 {umo} 失败: {e}")
                await asyncio.sleep(0.3)
            if ok_cnt == 0:
                logger.warning(
                    "[daily_digest] 图片发送全部失败（可能为平台媒体上传问题）"
                )
                return False
            logger.info(
                f"[daily_digest] 简报已渲染为图片发送（成功 {ok_cnt}/{len(targets)}）"
            )
            return True
        except Exception as e:
            logger.warning(f"[daily_digest] 简报渲染图片失败: {e}")
            return False

    async def _send_md(self, text: str, targets: list[str]) -> bool:
        """保存为 .md 文件并发送；任一目标成功即返回 True。"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            data_dir = get_astrbot_data_path()
            temp_dir = os.path.join(data_dir, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            fpath = os.path.join(
                temp_dir,
                f"daily_digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            )
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(text)
            ok_cnt = 0
            for umo in targets:
                try:
                    chain = MessageChain(chain=[File(name="每日简报.md", file=fpath)])
                    await asyncio.wait_for(
                        self.context.send_message(umo, chain), timeout=90
                    )
                    ok_cnt += 1
                except Exception as e:
                    logger.error(f"[daily_digest] 文件发送到 {umo} 失败: {e}")
                await asyncio.sleep(0.3)
            if ok_cnt:
                logger.info(
                    f"[daily_digest] 简报已作为 md 文件发送（成功 {ok_cnt}/{len(targets)}）"
                )
                return True
            logger.warning("[daily_digest] md 文件发送全部失败")
            return False
        except Exception as e:
            logger.warning(f"[daily_digest] 发送 md 文件失败: {e}")
            return False

    async def _build_digest(self) -> str:
        weather = None
        if self._cfg_bool("weather_enabled", True):
            try:
                weather = await self._fetch_weather()
            except Exception as e:
                logger.warning(f"[daily_digest] 天气获取失败: {e}")

        max_items = self._cfg_int("max_items_per_section", 5)
        sections: dict[str, list[dict]] = {}
        for enabled_key, feed_key, _label, _emoji in SECTIONS:
            if not self._cfg_bool(enabled_key, True):
                continue
            if feed_key == "github_trending":
                items = await self._fetch_github_trending()
            else:
                items = await self._fetch_category(feed_key, max_items)
            if items:
                sections[feed_key] = items

        if self._cfg_bool("ai_summary_enabled", True):
            try:
                ai_text = await self._ai_summarize(weather, sections)
                if ai_text:
                    return ai_text
            except Exception as e:
                logger.warning(f"[daily_digest] AI 总结失败，使用模板: {e}")

        return self._template_digest(weather, sections)

    # ------------------------------------------------------------------ #
    # 会话收集
    # ------------------------------------------------------------------ #
    async def _collect_target_sessions(self) -> list[str]:
        """收集推送目标：手动指定 > 数据库枚举（所有用户）> 订阅会话。"""
        sessions: set[str] = set()

        cfg_targets = self.config.get("target_sessions")
        if cfg_targets:
            for line in str(cfg_targets).splitlines():
                line = line.strip()
                if line and ":" in line:
                    sessions.add(line)
            if sessions:
                return sorted(sessions)

        # 与 AstrBot 面板「会话管理」同源的数据库枚举
        try:
            db = self.context.get_db()
            from sqlalchemy import select

            from astrbot.core.db.po import ConversationV2

            async with db.get_db() as sess:
                res = await sess.execute(select(ConversationV2.user_id).distinct())
                for row in res:
                    v = row[0]
                    if v and ":" in str(v):
                        sessions.add(str(v))
            logger.info(f"[daily_digest] 数据库枚举到 {len(sessions)} 个会话")
        except Exception as e:
            logger.warning(f"[daily_digest] 数据库枚举会话失败: {e}")

        try:
            tracked = await self.get_kv_data("subscribed_sessions", []) or []
            for s in tracked:
                if ":" in str(s):
                    sessions.add(str(s))
        except Exception as e:
            logger.debug(f"[daily_digest] 读取订阅会话失败: {e}")

        return sorted(sessions)

    async def _remember_session(self, umo: str) -> None:
        if not umo or ":" not in umo:
            return
        try:
            tracked = await self.get_kv_data("subscribed_sessions", []) or []
            if umo not in tracked:
                tracked.append(umo)
                await self.put_kv_data("subscribed_sessions", tracked)
                logger.info(f"[daily_digest] 已记录订阅会话 {umo}")
        except Exception as e:
            logger.debug(f"[daily_digest] 记录订阅会话失败: {e}")

    async def _forget_session(self, umo: str) -> None:
        try:
            tracked = await self.get_kv_data("subscribed_sessions", []) or []
            if umo in tracked:
                tracked.remove(umo)
                await self.put_kv_data("subscribed_sessions", tracked)
                logger.info(f"[daily_digest] 已移除订阅会话 {umo}")
        except Exception as e:
            logger.debug(f"[daily_digest] 移除订阅会话失败: {e}")

    # ------------------------------------------------------------------ #
    # 数据抓取
    # ------------------------------------------------------------------ #
    async def _fetch_category(self, feed_key: str, max_items: int) -> list[dict]:
        items: list[dict] = []
        for entry in self._feed_urls(feed_key):
            for attempt in (1, 2):  # 抖动网络重试一次
                try:
                    if self._is_json_source(entry):
                        items.extend(await self._fetch_json_source(entry, max_items))
                    else:
                        data = await asyncio.to_thread(self._http_get_bytes, entry)
                        items.extend(self._parse_feed(data))
                    break
                except Exception as e:
                    if attempt == 1:
                        logger.warning(
                            f"[daily_digest] 抓取 {feed_key} 源失败 {entry}，重试一次: {e}"
                        )
                    else:
                        logger.warning(
                            f"[daily_digest] 抓取 {feed_key} 源失败 {entry}: {e}"
                        )
        # 政策板块来自政府官网，发文频率低（可能数日才有一条），
        # 因此放宽时效窗口，避免「政策前沿」整块空白；其余板块仍严格卡「昨日」。
        recent_days = 0
        if feed_key == "feeds_policy":
            recent_days = max(1, self._cfg_int("gov_policy_recent_days", 30))
        return self._filter_yesterday(items, recent_days)[:max_items]

    @staticmethod
    def _is_json_source(entry: str) -> bool:
        return (
            entry.startswith("cctv:")
            or entry in ("tencent:hot", "baidu:hot")
            or entry in GOV_SOURCES
        )

    async def _fetch_json_source(self, token: str, max_items: int) -> list[dict]:
        """抓取免费中文 JSON 新闻源（央视 / 腾讯热榜 / 百度热搜 / 政府官网）。
        热榜类条目按「最新」处理（pub_date=当前时间），通过时效过滤；
        政府官网条目带真实发布日期，按真实日期参与时效过滤。"""
        now = datetime.now().astimezone()
        if token in GOV_SOURCES:
            return await self._fetch_gov_source(token, max_items)
        if token.startswith("cctv:"):
            channel = token.split(":", 1)[1].strip() or "news"
            url = (
                "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/"
                f"{channel}_1.jsonp"
            )
            text = (await asyncio.to_thread(self._http_get_bytes, url, 20)).decode(
                "utf-8", "replace"
            )
            m = re.search(r"\(\s*(\{.*\})\s*\)\s*$", text, re.S)
            payload = json.loads(m.group(1)) if m else json.loads(text)
            out: list[dict] = []
            for it in payload.get("data", {}).get("list") or []:
                title = _strip_html(str(it.get("title") or it.get("brief") or ""))
                if not title:
                    continue
                link = str(it.get("url") or "").strip()
                pub = _parse_date(str(it.get("focus_date") or "")) or now
                out.append(
                    {
                        "title": title,
                        "link": link,
                        "pub_date": pub,
                        "summary": _strip_html(str(it.get("brief") or ""))[:200],
                    }
                )
            return out
        if token == "tencent:hot":
            url = "https://r.inews.qq.com/gw/event/hot_ranking_list?page_size=30"
            payload = json.loads(
                (await asyncio.to_thread(self._http_get_bytes, url, 20)).decode(
                    "utf-8", "replace"
                )
            )
            out = []
            for it in (payload.get("idlist") or [{}])[0].get("newslist") or []:
                title = _strip_html(str(it.get("title") or ""))
                if not title:
                    continue
                if "腾讯新闻用户最关注" in title:  # 过滤占位头条目
                    continue
                out.append(
                    {
                        "title": title,
                        "link": "",
                        "pub_date": now,
                        "summary": "",
                    }
                )
            return out
        if token == "baidu:hot":
            url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
            payload = json.loads(
                (await asyncio.to_thread(self._http_get_bytes, url, 20)).decode(
                    "utf-8", "replace"
                )
            )
            out = []
            for it in self._walk_keyed_items(payload):
                word = str(it.get("word") or it.get("query") or "").strip()
                if not word:
                    continue
                link = str(it.get("url") or "").strip() or (
                    "https://www.baidu.com/s?wd=" + urllib.parse.quote(word)
                )
                out.append(
                    {
                        "title": word,
                        "link": link,
                        "pub_date": now,
                        "summary": str(it.get("desc") or "")[:200],
                    }
                )
            return out
        return []

    async def _fetch_gov_source(self, token: str, max_items: int) -> list[dict]:
        """政府官方网站源（政策板块）：
        - gov:zuixin  中国政府网「最新政策」ZUIXINZHENGCE.json（字段 TITLE/URL/DOCRELPUBTIME）
        - gov:yaowen  中国政府网「要闻」pushinfo.json（字段 title/link/pubDate/description）
        - ndrc:xwfb   国家发改委「新闻发布」列表页（HTML 静态 li/a/span）
        政策文件发布频率低（可能数日才有一条），所以这里不做「昨日」硬过滤，
        而是取「最近 gov_policy_recent_days 天内」，交由上层时效过滤统一处理。
        """
        days = max(1, self._cfg_int("gov_policy_recent_days", 30))
        now = datetime.now().astimezone()
        cutoff = now - timedelta(days=days)
        out: list[dict] = []

        if token == "gov:zuixin":
            url = "https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json"
            raw = await asyncio.to_thread(
                self._http_get_bytes, url, 20, GOV_HEADERS
            )
            payload = json.loads(raw.decode("utf-8", "replace"))
            for it in payload if isinstance(payload, list) else []:
                title = _strip_html(str(it.get("TITLE") or ""))
                if not title:
                    continue
                pub = _parse_date(str(it.get("DOCRELPUBTIME") or ""))
                out.append(
                    {
                        "title": title,
                        "link": str(it.get("URL") or "").strip(),
                        "pub_date": pub,
                        "summary": _strip_html(str(it.get("SUB_TITLE") or ""))[:200],
                        "source": "中国政府网",
                    }
                )
        elif token == "gov:yaowen":
            url = "https://www.gov.cn/pushinfo/v150203/pushinfo.json"
            raw = await asyncio.to_thread(
                self._http_get_bytes, url, 20, GOV_HEADERS
            )
            payload = json.loads(raw.decode("utf-8", "replace"))
            items = payload if isinstance(payload, list) else []
            for it in items:
                title = _strip_html(str(it.get("title") or ""))
                if not title:
                    continue
                out.append(
                    {
                        "title": title,
                        "link": str(it.get("link") or "").strip(),
                        "pub_date": _parse_date(str(it.get("pubDate") or "")),
                        "summary": _strip_html(str(it.get("description") or ""))[:200],
                        "source": "中国政府网",
                    }
                )
        elif token == "ndrc:xwfb":
            base = "https://www.ndrc.gov.cn/xwdt/xwfb/"
            raw = await asyncio.to_thread(
                self._http_get_bytes, base, 20, GOV_HEADERS
            )
            html_text = raw.decode("utf-8", "replace")
            for m in re.finditer(
                r'<li[^>]*>\s*<a\s+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>'
                r'[^<]*</a>\s*<span[^>]*>([\d/]+)</span>',
                html_text,
            ):
                href, title, date_s = m.group(1), m.group(2), m.group(3)
                title = _strip_html(title)
                if not title:
                    continue
                if href.startswith("//"):
                    link = "https:" + href
                elif href.startswith("http"):
                    link = href
                else:
                    link = urllib.parse.urljoin(base, href)
                out.append(
                    {
                        "title": title,
                        "link": link,
                        "pub_date": _parse_date(date_s.replace("/", "-")),
                        "summary": "",
                        "source": "国家发改委",
                    }
                )

        # 政策文件更新慢：优先保留窗口内条目；窗口内为空则退回最新几条，
        # 避免「政策前沿」板块因为近期无新政策而整块消失。
        recent = []
        for it in out:
            d = it.get("pub_date")
            if d is not None and d.tzinfo is None:
                d = d.replace(tzinfo=now.tzinfo)
                it["pub_date"] = d
            if d is None or d >= cutoff:
                recent.append(it)
        if not recent:
            recent = out[: max(1, max_items)]
            if recent:
                logger.info(
                    f"[daily_digest] {token} 近 {days} 天无新政策，退回最新 {len(recent)} 条"
                )
        return recent[: max(1, max_items * 3)]

    @staticmethod
    def _walk_keyed_items(node):
        """递归收集含 word/query 键的条目（适配百度热搜等多层嵌套结构）。"""
        out: list[dict] = []
        if isinstance(node, dict):
            if node.get("word") or node.get("query"):
                out.append(node)
            for v in node.values():
                out.extend(DailyDigestPlugin._walk_keyed_items(v))
        elif isinstance(node, list):
            for v in node:
                out.extend(DailyDigestPlugin._walk_keyed_items(v))
        return out

    def _feed_urls(self, feed_key: str) -> list[str]:
        val = self.config.get(feed_key)
        if val:
            urls = [u.strip() for u in str(val).splitlines() if u.strip()]
            if urls:
                # 自动迁移：若某板块配置的源全部是已停更的人民网 RSS（2025-06 停更），
                # 说明是旧版默认配置，自动切换到新的实时默认源
                if all("people.com.cn" in u for u in urls):
                    logger.info(
                        f"[daily_digest] {feed_key} 仍在使用已停更的人民网源，已自动迁移到实时默认源"
                    )
                    return DEFAULT_FEEDS.get(feed_key, [])
                return urls
        return DEFAULT_FEEDS.get(feed_key, [])

    # ------------------------------------------------------------------ #
    # GitHub 日升榜（免费免 Key 多源降级）
    # ------------------------------------------------------------------ #
    async def _fetch_github_trending(self) -> list[dict]:
        """近 N 天 star 增长最快的仓库 TopN（多源降级，全部失败则省略板块并记日志）。"""
        days = max(1, self._cfg_int("github_trending_days", 7))
        limit = max(1, self._cfg_int("github_trending_count", 10))
        min_stars = max(0, self._cfg_int("github_trending_min_stars", 0))
        for source in GITHUB_TRENDING_SOURCES:
            try:
                url = self._github_trending_url(source, days, limit)
                timeout = 25
                data = json.loads(
                    await asyncio.to_thread(self._http_get_bytes, url, timeout)
                )
                items = self._parse_trending_repos(data, days)
                if min_stars > 0:
                    items = [
                        it for it in items if int(it.get("stars") or 0) >= min_stars
                    ]
                if items:
                    logger.info(f"[daily_digest] GitHub 日升榜命中数据源: {source}")
                    return items[:limit]
                logger.warning(f"[daily_digest] GitHub 日升榜源 {source} 返回空结果")
            except Exception as e:
                logger.warning(
                    f"[daily_digest] GitHub 日升榜源 {source} 失败: {e}"
                )
        logger.warning("[daily_digest] GitHub 日升榜全部数据源失败，该板块省略")
        return []

    @staticmethod
    def _github_trending_url(source: str, days: int, limit: int) -> str:
        if source == "ossinsight":
            return (
                "https://api.ossinsight.io/v1/trends/repos/?period="
                f"past_7_days&limit={limit}"
            )
        if source == "gitterapp":
            return "https://api.gitterapp.com/repositories/trending?since=daily"
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        if source.endswith("_created"):
            q = f"created%3A%3E{since}"
        else:  # _alltime：全站热门（stars 排序），国内网络下作为日升榜的降级数据
            q = "stars%3A%3E1000"
        base = (
            "https://api.github.com/search/repositories"
            if source.startswith("github_search")
            else "https://gh-proxy.com/https://api.github.com/search/repositories"
        )
        return f"{base}?q={q}&sort=stars&order=desc&per_page={limit}"

    @staticmethod
    def _parse_trending_repos(data, days: int) -> list[dict]:
        """容错解析三种 API 的仓库列表（dict 的 items/repos/results/data 或顶层 list）。"""
        raw = DailyDigestPlugin._find_repo_list(data)
        out: list[dict] = []
        for obj in raw:
            if not isinstance(obj, dict):
                continue
            name = (
                obj.get("repo_name")
                or obj.get("full_name")
                or obj.get("name")
                or ""
            )
            name = str(name).strip().lstrip("/")
            if "/" not in name:
                # gitterapp 等源把 author 与 name 分开给
                author = str(obj.get("author") or "").strip().lstrip("@")
                repo = str(obj.get("name") or "").strip()
                if author and repo:
                    name = f"{author}/{repo}"
            if not name or "/" not in name:
                continue
            url = (
                obj.get("html_url")
                or obj.get("url")
                or f"https://github.com/{name}"
            )
            total_raw = (
                obj.get("current_total_stars")
                or obj.get("currentTotalStars")
                or obj.get("stargazers_count")
                or obj.get("total_stars")
            )
            period_raw = (
                obj.get("current_period_stars")
                or obj.get("currentPeriodStars")
                or obj.get("period_stars")
                or obj.get("added_stars")
                or obj.get("stars_today")
            )
            stars = DailyDigestPlugin._to_int(total_raw)
            period = DailyDigestPlugin._to_int(period_raw)
            if total_raw is None and obj.get("stars") is not None:
                # 部分源只给 stars（=总数）
                stars = DailyDigestPlugin._to_int(obj.get("stars"))
            elif period_raw is None and obj.get("stars") is not None:
                # OSS Insight：total_stars 为总数、stars 为周期增量
                period = DailyDigestPlugin._to_int(obj.get("stars"))
            desc = str(obj.get("description") or "").strip()
            language = str(obj.get("language") or "").strip()
            title = f"{name} ⭐{stars}（近{days}天+{period}）" if period else f"{name} ⭐{stars}"
            out.append(
                {
                    "name": name,
                    "title": title,
                    "link": str(url).strip(),
                    "description": desc[:200],
                    "language": language,
                    "stars": stars,
                    "period_stars": period,
                }
            )
        return out

    @staticmethod
    def _find_repo_list(data) -> list:
        """从 dict 的 items/repos/results/data 或顶层 list 中找数组。"""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "repos", "results"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
            for key in ("data", "payload"):
                v = data.get(key)
                if isinstance(v, dict):
                    for key2 in ("items", "repos", "results"):
                        v2 = v.get(key2)
                        if isinstance(v2, list):
                            return v2
                    if isinstance(v, list):
                        return v
        return []

    @staticmethod
    def _to_int(v) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _http_get_bytes(url: str, timeout: int = 15, headers: dict | None = None) -> bytes:
        hdrs = {
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _parse_feed(self, data: bytes) -> list[dict]:
        """解析 RSS 2.0 / RDF / Atom，返回条目列表。"""
        root = ET.fromstring(data)
        items: list[dict] = []
        for el in root.iter():
            if _local_name(el.tag) not in ("item", "entry"):
                continue
            item: dict = {"title": "", "link": "", "pub_date": None, "summary": ""}
            for child in el:
                name = _local_name(child.tag)
                if name == "title":
                    item["title"] = _strip_html(child.text or "")
                elif name == "link":
                    href = child.get("href")
                    if href:
                        item["link"] = href.strip()
                    elif child.text and child.text.strip():
                        item["link"] = child.text.strip()
                elif name in ("pubDate", "published", "updated", "date"):
                    if item["pub_date"] is None:
                        item["pub_date"] = _parse_date(child.text or "")
                elif name in ("description", "summary", "encoded", "content"):
                    item["summary"] = _strip_html(child.text or "")[:200]
            if item["title"]:
                items.append(item)
        return items

    def _filter_yesterday(self, items: list[dict], recent_days: int = 0) -> list[dict]:
        """严格时效过滤：只保留「昨日」条目；不足时回退到近 24 小时。
        recent_days > 0 时（政策等低频板块）放宽为「最近 N 天」，因为政策文件
        不是每天都有，硬卡「昨日」会让整个板块经常空白。
        注意：不回退到更早的条目——死源（如停更的 RSS）不会把陈旧内容当「昨日」展示。"""
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        cutoff_24h = now - timedelta(hours=24)
        if recent_days > 0:
            yesterday_start = now - timedelta(days=recent_days)

        dated: list[dict] = []
        undated: list[dict] = []
        for it in items:
            d = it.get("pub_date")
            if d is None:
                undated.append(it)
                continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=now.tzinfo)
            it["pub_date"] = d
            dated.append(it)
        dated.sort(key=lambda x: x["pub_date"], reverse=True)

        hit = [it for it in dated if yesterday_start <= it["pub_date"] < today_start]
        if recent_days <= 0 and len(hit) < 2:
            hit24 = [it for it in dated if it["pub_date"] >= cutoff_24h]
            if len(hit24) > len(hit):
                hit = hit24
        return hit + undated

    # ------------------------------------------------------------------ #
    # 天气（Open-Meteo，免费免 Key；多城市 + 防高并发）
    #   - 天气结果 KV 缓存 weather_cache_minutes 分钟
    #   - 地理编码结果 KV 缓存 7 天
    #   - 每城市一把 asyncio 单飞锁（同城市并发去重）
    #   - 全局请求间隔节流 weather_interval_seconds 秒 + 每日上限
    #   - 失败隔离：单城市失败只在该城市输出「获取失败」
    # ------------------------------------------------------------------ #
    def _weather_cities(self) -> list[str]:
        raw = str(self.config.get("weather_city") or "上海").strip()
        parts = re.split(r"[\n,，、;；]+", raw)
        return [p.strip() for p in parts if p.strip()] or ["上海"]

    async def _fetch_weather(self) -> str | None:
        cities = self._weather_cities()
        if not cities:
            return None
        cache_minutes = self._cfg_int("weather_cache_minutes", 30)
        try:
            cache = (await self.get_kv_data("weather_cache", None)) or {}
            if (
                cache.get("cities") == cities
                and time.time() - (cache.get("ts") or 0) < cache_minutes * 60
                and cache.get("text")
            ):
                return cache["text"]
        except Exception:
            pass

        lines = ["🌤️ 天气"]
        ok = False
        for city in cities:
            try:
                block = await self._fetch_city_weather(city)
            except Exception as e:
                logger.warning(f"[daily_digest] 天气获取失败（{city}）: {e}")
                block = None
            if block:
                lines.append(block)
                ok = True
            else:
                lines.append(f"→【{city}】获取失败")
        if not ok:
            return None  # 全部城市失败 -> 板块省略
        text = "\n".join(lines)
        try:
            await self.put_kv_data(
                "weather_cache", {"cities": cities, "ts": time.time(), "text": text}
            )
        except Exception:
            pass
        return text

    async def _fetch_city_weather(self, city: str) -> str | None:
        """单城市天气。失败抛异常或返回 None，由调用方做失败隔离。"""
        lock = self._weather_locks.setdefault(city, asyncio.Lock())
        async with lock:  # 单飞锁：同城市并发只发一个请求
            loc = await self._geocode(city)
            if loc is None:
                return None
            await self._weather_throttle()
            fc_url = (
                "https://api.open-meteo.com/v1/forecast?"
                + urllib.parse.urlencode(
                    {
                        "latitude": loc["lat"],
                        "longitude": loc["lon"],
                        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                        "timezone": "auto",
                        "forecast_days": 2,
                    }
                )
            )
            fc = json.loads(await asyncio.to_thread(self._http_get_bytes, fc_url))
            cur = fc.get("current") or {}
            daily = fc.get("daily") or {}
            times = daily.get("time") or []

            parts = [
                f"现在：{self._wmo(cur.get('weather_code'))}，"
                f"{cur.get('temperature_2m')}°C（体感 {cur.get('apparent_temperature')}°C），"
                f"湿度 {cur.get('relative_humidity_2m')}%，"
                f"风速 {cur.get('wind_speed_10m')}km/h"
            ]
            if len(times) >= 1:
                parts.append(
                    f"今日：{self._wmo(daily.get('weather_code', [None])[0])}，"
                    f"{daily.get('temperature_2m_min', [None])[0]}~"
                    f"{daily.get('temperature_2m_max', [None])[0]}°C，"
                    f"降水概率 {daily.get('precipitation_probability_max', [None])[0]}%"
                )
            if len(times) >= 2:
                parts.append(
                    f"明日：{self._wmo(daily.get('weather_code', [None])[1])}，"
                    f"{daily.get('temperature_2m_min', [None])[1]}~"
                    f"{daily.get('temperature_2m_max', [None])[1]}°C"
                )
            return f"→【{loc.get('name', city)}】" + "；".join(parts)

    async def _geocode(self, city: str) -> dict | None:
        """地理编码（KV 缓存 7 天），返回 {"lat","lon","name"} 或 None。"""
        try:
            geo_cache = (await self.get_kv_data("geo_cache", None)) or {}
        except Exception:
            geo_cache = {}
        entry = geo_cache.get(city)
        if entry and time.time() - (entry.get("ts") or 0) < 7 * 86400:
            return entry

        await self._weather_throttle()
        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode(
                {"name": city, "count": 1, "language": "zh", "format": "json"}
            )
        )
        geo = json.loads(await asyncio.to_thread(self._http_get_bytes, geo_url))
        results = geo.get("results") or []
        if not results:
            return None
        loc = results[0]
        entry = {
            "lat": loc["latitude"],
            "lon": loc["longitude"],
            "name": loc.get("name", city),
            "ts": time.time(),
        }
        try:
            geo_cache[city] = entry
            await self.put_kv_data("geo_cache", geo_cache)
        except Exception:
            pass
        return entry

    async def _weather_throttle(self) -> None:
        """全局节流：相邻两次 Open-Meteo 调用间隔 >= interval 秒，并计入每日上限。"""
        interval = max(0, self._cfg_int("weather_interval_seconds", 3))
        today = datetime.now().strftime("%Y-%m-%d")
        if self._weather_call_day != today:
            self._weather_call_day = today
            self._weather_call_count = 0
        if self._weather_call_count >= WEATHER_DAILY_CALL_LIMIT:
            raise RuntimeError("今日天气 API 调用次数已达上限")
        wait = self._last_weather_call + interval - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_weather_call = time.time()
        self._weather_call_count += 1

    @staticmethod
    def _wmo(code) -> str:
        try:
            code = int(code)
        except (TypeError, ValueError):
            return "未知"
        return WMO_CODES.get(code, f"天气代码{code}")

    # ------------------------------------------------------------------ #
    # AI 总结（优先新 API，回退旧 API）
    # ------------------------------------------------------------------ #
    async def _ai_summarize(self, weather: str | None, sections: dict) -> str:
        lines: list[str] = []
        if weather:
            lines.append(weather)
            lines.append("")
        for _enabled_key, feed_key, label, _emoji in SECTIONS:
            items = sections.get(feed_key) or []
            if not items:
                continue
            lines.append(f"## {label}")
            for it in items:
                line = f"- {it['title']}"
                detail = str(it.get("description") or it.get("summary") or "").strip()
                if detail:
                    line += f"：{detail[:200]}"
                lang = str(it.get("language") or "").strip()
                if lang:
                    line += f"（语言：{lang}）"
                if it.get("link"):
                    line += f"（{it['link']}）"
                lines.append(line)
        if not lines:
            raise RuntimeError("没有抓到任何内容")

        prompt = (self.config.get("llm_prompt") or DEFAULT_PROMPT).replace(
            "{date}", datetime.now().strftime("%Y-%m-%d")
        ).replace("{data}", "\n".join(lines))
        prompt = self._normalize_prompt(prompt)
        text = await self._llm_chat(prompt)
        if not text:
            raise RuntimeError("LLM 返回为空")
        if self._is_rejection(text):
            # 内容安全拦截：用「仅标题+链接」的精简数据重试一次（去掉描述/摘要，降低触发概率）
            logger.warning("[daily_digest] AI 返回被内容安全拦截，改用精简数据重试一次")
            reduced = self._build_reduced_data(weather, sections)
            if reduced:
                prompt2 = (self.config.get("llm_prompt") or DEFAULT_PROMPT).replace(
                    "{date}", datetime.now().strftime("%Y-%m-%d")
                ).replace("{data}", reduced)
                prompt2 = self._normalize_prompt(prompt2)
                text2 = await self._llm_chat(prompt2)
                if text2 and not self._is_rejection(text2):
                    return text2
            raise RuntimeError("LLM 连续被内容安全拦截，降级为模板日报")
        return text

    @staticmethod
    def _build_reduced_data(weather: str | None, sections: dict) -> str:
        """精简数据：只保留标题+链接，每板块最多 3 条（降低被内容安全拦截的概率）。"""
        lines: list[str] = []
        if weather:
            lines.append(weather)
            lines.append("")
        for _enabled_key, feed_key, label, _emoji in SECTIONS:
            items = sections.get(feed_key) or []
            if not items:
                continue
            lines.append(f"## {label}")
            for it in items[:3]:
                line = f"- {it['title']}"
                if it.get("link"):
                    line += f"（{it['link']}）"
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _is_rejection(text: str) -> bool:
        """检测 LLM 返回是否为内容安全拦截/拒绝（大小写不敏感）。"""
        low = (text or "").lower()
        markers = (
            "high risk",
            "was rejected",
            "rejected because",
            "content policy",
            "moderation",
            "risk control",
            "safety check",
            "safe check",
            "the request was rejected",
        )
        if any(m in low for m in markers):
            return True
        # 中文安全拦截常见表述
        cn_markers = (
            "安全风险", "内容安全", "被拒绝", "违规", "敏感内容",
            "不予处理", "拒绝回答", "无法满足该请求", "无法处理该请求",
        )
        return any(m in text for m in cn_markers)

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """规范化提示词：兼容旧版配置。
        - 旧版「1200 字内」升级为「1800 字内」；
        - 旧版「（仅输出实际有的板块）」替换为「必须全部输出」；
        - 末尾强制追加一条指令：{data} 里出现的每个板块（含 🚀 GitHub 日升榜 等）都必须输出，
          防止旧提示词板块清单缺失时 AI 以「未列入板块」为由漏掉 GitHub 等板块。
        """
        p = prompt.replace(
            "总长度控制在 1200 字内",
            "总长度控制在 1800 字内",
        )
        p = p.replace(
            "（仅输出实际有的板块）",
            "（有数据的板块必须全部输出，不要遗漏任何板块）",
        )
        p = p.rstrip() + (
            "\n\n【强制要求】下方 {data} 中出现的每一个板块（包括但不限于："
            "🌤️ 天气、🇨🇳 昨日国内、🌍 昨日国际、💻 科技前沿、💊 医药前沿、"
            "📜 政策前沿、🚀 GitHub 日升榜）都必须输出；只有某个板块在 {data} 中完全无数据时才可跳过。"
        )
        return p

    async def _llm_chat(self, prompt: str) -> str:
        ctx = self.context

        # 1) AstrBot 4.x：context.llm_generate(chat_provider_id=...)
        try:
            prov_id = None
            get_using = getattr(ctx, "get_using_provider_async", None)
            if callable(get_using):
                prov = await get_using()
                meta = getattr(prov, "meta", None) if prov else None
                if callable(meta):
                    prov_id = getattr(meta(), "id", None)
            if prov_id and callable(getattr(ctx, "llm_generate", None)):
                resp = await ctx.llm_generate(
                    chat_provider_id=prov_id,
                    prompt=prompt,
                    system_prompt="你是一名严谨、简洁的中文每日简报编辑。",
                )
                text = self._llm_text(resp)
                if text:
                    return text
        except Exception as e:
            logger.debug(f"[daily_digest] llm_generate 调用失败: {e}")

        # 2) 旧版：context.get_using_provider() + provider.text_chat()
        try:
            get_prov = getattr(ctx, "get_using_provider", None)
            if callable(get_prov):
                prov = get_prov()
                if prov is not None and callable(getattr(prov, "text_chat", None)):
                    resp = await prov.text_chat(
                        prompt=prompt, session_id=None, image_urls=[]
                    )
                    text = self._llm_text(resp)
                    if text:
                        return text
        except Exception as e:
            logger.debug(f"[daily_digest] text_chat 调用失败: {e}")

        raise RuntimeError("无法获取可用的 LLM 提供商")

    @staticmethod
    def _llm_text(resp) -> str:
        if resp is None:
            return ""
        for attr in ("completion_text", "result", "text"):
            try:
                v = getattr(resp, attr, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            except Exception:
                continue
        try:
            rc = getattr(resp, "result_chain", None)
            if rc is not None and hasattr(rc, "get_plain_text"):
                t = rc.get_plain_text()
                if t:
                    return t
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------ #
    # 模板简报（AI 不可用时的降级方案）
    # ------------------------------------------------------------------ #
    def _template_digest(self, weather: str | None, sections: dict) -> str:
        lines = [f"📰 每日简报 · {datetime.now().strftime('%Y-%m-%d %A')}"]
        if weather:
            lines.append("")
            lines.append(weather)
        max_items = self._cfg_int("max_items_per_section", 5)
        for _enabled_key, feed_key, label, emoji in SECTIONS:
            items = sections.get(feed_key) or []
            if not items:
                continue
            lines.append("")
            lines.append(f"{emoji} {label}")
            for i, it in enumerate(items[:max_items], 1):
                lines.append(f"{i}. {it['title']}")
                detail = str(it.get("description") or it.get("summary") or "").strip()
                lang = str(it.get("language") or "").strip()
                tail_parts = []
                if detail:
                    tail_parts.append(detail[:120])
                if lang:
                    tail_parts.append(f"语言：{lang}")
                if tail_parts:
                    lines.append("   " + "；".join(tail_parts))
                if it.get("link"):
                    lines.append(f"   🔗 {it['link']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 发送
    # ------------------------------------------------------------------ #
    async def _send_text(self, umo: str, text: str) -> None:
        chunks = self._split_text(text)
        for idx, chunk in enumerate(chunks):
            try:
                chain = MessageChain().message(chunk)
                ok = await self._send_to_session(umo, chain)
                if not ok:
                    logger.warning(
                        f"[daily_digest] 发送到 {umo} 失败：未找到对应平台"
                    )
            except Exception as e:
                logger.error(f"[daily_digest] 发送到 {umo} 失败: {e}")
            if idx < len(chunks) - 1:
                await asyncio.sleep(0.8)

    async def _send_to_session(self, umo: str, chain: MessageChain) -> bool:
        """发送消息。兼容新旧两种 send_message 签名：
        新（AstrBot 4.x）: send_message(session: str|MessageSesion, chain)
        旧（AstrBot 3.x）: send_message(platform_name, chain, target_id, is_group=...)
        """
        ctx = self.context
        try:
            sig = inspect.signature(ctx.send_message)
            positional = [
                p
                for p in sig.parameters.values()
                if p.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if len(positional) >= 4:
                parts = umo.split(":")
                platform_name = parts[0] if parts else umo
                target = parts[2] if len(parts) > 2 else ""
                is_group = "group" in umo.lower() or len(parts) > 3
                return bool(await ctx.send_message(platform_name, chain, target, is_group))
        except Exception as e:
            logger.debug(f"[daily_digest] 旧版 send_message 适配失败，改用新版调用: {e}")
        return bool(await ctx.send_message(umo, chain))

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #
    def _cfg_bool(self, key: str, default: bool) -> bool:
        v = self.config.get(key, default)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _split_text(text: str, limit: int = 3800) -> list[str]:
        text = text.strip()
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        cur = ""
        for line in text.splitlines(keepends=True):
            while len(line) > limit:
                # 单行超长：先补满当前块，再按 limit 拆行
                if cur:
                    chunks.append(cur)
                    cur = ""
                chunks.append(line[:limit])
                line = line[limit:]
            if cur and len(cur) + len(line) > limit:
                chunks.append(cur)
                cur = line
            else:
                cur += line
        if cur:
            chunks.append(cur)
        return chunks