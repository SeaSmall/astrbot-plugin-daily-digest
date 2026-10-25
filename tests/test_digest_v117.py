"""daily_digest v1.1.7 回归测试：AI / 网安新板块 + KEV + 放宽窗口 + 中文字体自愈。

跑法（仓库根目录）：
    PYTHONIOENCODING=utf-8 python tests/test_digest_v117.py

测试用 tests/stubs 里的最小 astrbot 桩加载 main.py，不需要真实 AstrBot。
"""
from __future__ import annotations

import asyncio
import datetime
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "stubs"))

spec = importlib.util.spec_from_file_location(
    "daily_digest_plugin_main", os.path.join(_ROOT, "main.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SCHEMA = json.load(open(os.path.join(_ROOT, "_conf_schema.json"), encoding="utf-8"))

# 用 schema 默认值构造一份「刚装好插件」的配置，再按用例覆盖
CONFIG = {k: v.get("default") for k, v in SCHEMA.items()}

# 夹具：真实插件目录是 <data>/plugins/<plugin>/main.py，直接实例化会把字体写到
# 本仓库的「祖父目录」（开发机上就是 D:\font.ttf），因此构造期临时禁用字体自愈，
# 字体行为另有 24e 用临时目录专测。
_orig_ensure = mod._ensure_cjk_font
mod._ensure_cjk_font = lambda: None
try:
    dd = mod.DailyDigestPlugin(context=object(), config=CONFIG)
finally:
    mod._ensure_cjk_font = _orig_ensure

NOW = datetime.datetime.now().astimezone()


def _fail(msg):
    raise AssertionError(msg)


async def main() -> None:
    # ---------------------------------------------------------------- #
    # 1) 板块注册：顺序 / 标题 / emoji / 默认源 / KEV token
    # ---------------------------------------------------------------- #
    sec_by_feed = {x[1]: x for x in mod.SECTIONS}
    assert "feeds_ai" in sec_by_feed and "feeds_security" in sec_by_feed, mod.SECTIONS
    assert sec_by_feed["feeds_ai"][2] == "AI 界的新变化", sec_by_feed["feeds_ai"]
    assert sec_by_feed["feeds_security"][2] == "网安漏洞与情报", sec_by_feed["feeds_security"]
    assert sec_by_feed["feeds_ai"][3] == "🤖", sec_by_feed["feeds_ai"]
    assert sec_by_feed["feeds_security"][3] == "🛡️", sec_by_feed["feeds_security"]
    assert sec_by_feed["feeds_ai"][0] == "ai_enabled", sec_by_feed["feeds_ai"]
    assert sec_by_feed["feeds_security"][0] == "security_enabled", sec_by_feed["feeds_security"]
    order = [x[1] for x in mod.SECTIONS]
    assert (
        order.index("feeds_tech")
        < order.index("feeds_ai")
        < order.index("feeds_security")
        < order.index("feeds_medical")
    ), order
    assert mod.DEFAULT_FEEDS["feeds_ai"] == [
        "https://www.qbitai.com/feed",
        "https://www.infoq.cn/feed",
    ], mod.DEFAULT_FEEDS["feeds_ai"]
    _sec = mod.DEFAULT_FEEDS["feeds_security"]
    assert _sec[:3] == [
        "https://www.freebuf.com/feed",
        "https://api.anquanke.com/data/v1/rss",
        "https://xz.aliyun.com/feed",
    ], _sec
    assert _sec[-1] == "cisa:kev", _sec
    assert mod.KEV_SOURCES == ("cisa:kev",), mod.KEV_SOURCES
    assert dd._is_json_source("cisa:kev") is True
    assert dd._is_json_source("gov:zuixin") is True  # 原有 JSON 源不受影响
    assert dd._is_json_source("https://www.qbitai.com/feed") is False
    assert mod.KEV_CACHE_TTL_SECONDS == 6 * 3600, mod.KEV_CACHE_TTL_SECONDS
    assert mod.CISA_KEV_URL.endswith("known_exploited_vulnerabilities.json"), mod.CISA_KEV_URL
    assert "Referer" in mod.CISA_HEADERS and "cisa.gov" in mod.CISA_HEADERS["Referer"], mod.CISA_HEADERS
    print("[1] 板块顺序 / 标题 / emoji / 默认源 / KEV token OK")

    # ---------------------------------------------------------------- #
    # 2) cisa:kev 解析：窗口 / 勒索标记 / NVD 链接 / 6 小时缓存 / 失败隔离
    # ---------------------------------------------------------------- #
    d = lambda n: (NOW - datetime.timedelta(days=n)).strftime("%Y-%m-%d")

    def kev_payload():
        return json.dumps({
            "title": "CISA KEV",
            "vulnerabilities": [
                {"cveID": "CVE-2099-0001", "vendorProject": "Acme", "product": "Router",
                 "vulnerabilityName": "命令注入", "dateAdded": d(1),
                 "shortDescription": "Acme 路由器存在命令注入，可远程执行任意命令。",
                 "knownRansomwareCampaignUse": "Known"},
                {"cveID": "CVE-2099-0002", "vendorProject": "Beta", "product": "Panel",
                 "vulnerabilityName": "未授权访问", "dateAdded": d(5),
                 "shortDescription": "Beta 面板缺少鉴权。",
                 "knownRansomwareCampaignUse": "Unknown"},
                {"cveID": "CVE-2099-0003", "vendorProject": "Gamma", "product": "Old",
                 "vulnerabilityName": "越界写", "dateAdded": d(30),
                 "shortDescription": "太老了，应被窗口过滤掉。",
                 "knownRansomwareCampaignUse": "Unknown"},
            ],
        }).encode("utf-8")

    orig_hgb = dd._http_get_bytes
    calls = {"n": 0}

    def fake_hgb(url, *a, **k):
        calls["n"] += 1
        assert "known_exploited_vulnerabilities.json" in url, url
        return kev_payload()

    CONFIG["security_kev_days"] = 7
    dd._http_get_bytes = fake_hgb
    dd._kev_cache = None
    kev = await dd._fetch_cisa_kev(20)
    assert [it["title"].split("：")[0] for it in kev] == ["CVE-2099-0001", "CVE-2099-0002"], kev
    assert kev[0]["title"] == "CVE-2099-0001：Acme Router —— 命令注入", kev[0]["title"]
    assert "⚠️ 已用于勒索软件" in kev[0]["summary"], kev[0]["summary"]
    assert "⚠️" not in kev[1]["summary"], kev[1]["summary"]
    assert kev[0]["url"] == "https://nvd.nist.gov/vuln/detail/CVE-2099-0001"
    assert kev[0]["link"] == kev[0]["url"]
    assert calls["n"] == 1, calls

    # 6 小时内重复调用不应该重新下载 1.8MB
    kev2 = await dd._fetch_cisa_kev(20)
    assert len(kev2) == 2 and calls["n"] == 1, (calls, len(kev2))

    # 窗口收窄只重算过滤，不重新下载（缓存的是全量已解析条目）
    CONFIG["security_kev_days"] = 2
    kev3 = await dd._fetch_cisa_kev(20)
    assert len(kev3) == 1 and kev3[0]["title"].startswith("CVE-2099-0001"), kev3
    assert calls["n"] == 1, "窗口收窄不应重新下载"

    # 缓存过期（> 6 小时）后必须重新下载
    dd._kev_cache = (time.time() - 7 * 3600, list(dd._kev_cache[1]))
    CONFIG["security_kev_days"] = 7
    await dd._fetch_cisa_kev(20)
    assert calls["n"] == 2, "缓存过期后应重新下载"

    # 失败隔离：任何异常只返回空列表
    def boom_hgb(url, *a, **k):
        raise RuntimeError("mock 网络挂了")

    dd._http_get_bytes = boom_hgb
    dd._kev_cache = None
    assert await dd._fetch_cisa_kev(20) == [], "抓取失败必须返回空列表"
    # 结构异常（缺 vulnerabilities）同样只返回空列表
    dd._http_get_bytes = lambda url, *a, **k: b'{"title": "CISA KEV"}'
    dd._kev_cache = None
    assert await dd._fetch_cisa_kev(20) == [], "结构异常必须返回空列表"
    dd._http_get_bytes = orig_hgb
    CONFIG["security_kev_days"] = 7
    print("[2] cisa:kev 解析（7 天窗口/勒索标记/NVD/6 小时缓存/窗口收窄/失败隔离）OK")

    # ---------------------------------------------------------------- #
    # 3) 新板块时效窗口：feeds_ai→ai_recent_days，feeds_security→security_recent_days
    # ---------------------------------------------------------------- #
    from email.utils import format_datetime as fmt_dt

    def rss(pairs, link_prefix="https://example.org/"):
        body = "".join(
            "<item><title>%s</title><link>%s%s</link>"
            "<pubDate>%s</pubDate><description>d</description></item>"
            % (t, link_prefix, t, fmt_dt(when))
            for t, when in pairs
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            "<title>x</title>%s</channel></rss>" % body
        ).encode("utf-8")

    orig_hgb2 = dd._http_get_bytes
    body_ai = rss([
        ("AI 新模型发布，推理成本再降", NOW - datetime.timedelta(hours=6)),
        ("十天后才该出现的旧闻", NOW - datetime.timedelta(days=10)),
    ])
    dd._http_get_bytes = lambda url, *a, **k: body_ai
    try:
        CONFIG["ai_recent_days"] = 2
        ai_items = await dd._fetch_category("feeds_ai", 5)
        titles = [it["title"] for it in ai_items]
        assert "AI 新模型发布，推理成本再降" in titles, titles
        assert "十天后才该出现的旧闻" not in titles, titles
        CONFIG["ai_recent_days"] = 1
        ai_items2 = await dd._fetch_category("feeds_ai", 5)
        assert {it["title"] for it in ai_items2} == {"AI 新模型发布，推理成本再降"}, ai_items2
    finally:
        dd._http_get_bytes = orig_hgb2

    # feeds_security 的 RSS 源走 security_recent_days
    body_sec = rss([
        ("某中间件爆出反序列化漏洞", NOW - datetime.timedelta(hours=8)),
        ("三十天前的旧漏洞", NOW - datetime.timedelta(days=30)),
    ])
    dd._http_get_bytes = lambda url, *a, **k: body_sec
    orig_cfg_feeds = CONFIG.get("feeds_security")
    CONFIG["feeds_security"] = "https://sec.example.org/rss\n"
    try:
        CONFIG["security_recent_days"] = 2
        sec_items = await dd._fetch_category("feeds_security", 5)
        sec_titles = [it["title"] for it in sec_items]
        assert "某中间件爆出反序列化漏洞" in sec_titles, sec_titles
        assert "三十天前的旧漏洞" not in sec_titles, sec_titles
    finally:
        dd._http_get_bytes = orig_hgb2
        CONFIG["feeds_security"] = orig_cfg_feeds

    # ---------------------------------------------------------------- #
    # 4) prewindowed：cisa:kev 结果不再被二次时效过滤（只合并排序）
    # ---------------------------------------------------------------- #
    CONFIG["feeds_security"] = "cisa:kev\n"
    CONFIG["security_recent_days"] = 2  # 比 KEV 窗口窄：旧实现会把 7 天窗口压成 2 天
    orig_kev = dd._fetch_cisa_kev
    kev_item = {
        "title": "CVE-2099-0009：Old Vendor Product —— 五天了但仍在 KEV 窗口内",
        "link": "https://nvd.nist.gov/vuln/detail/CVE-2099-0009",
        "url": "https://nvd.nist.gov/vuln/detail/CVE-2099-0009",
        "pub_date": NOW - datetime.timedelta(days=5),
        "summary": "五天后仍然会被安全团队关注。",
    }

    async def fake_kev(max_items):
        return [dict(kev_item)]

    dd._fetch_cisa_kev = fake_kev
    try:
        got = await dd._fetch_category("feeds_security", 5)
        assert [it["title"] for it in got] == [kev_item["title"]], got
    finally:
        dd._fetch_cisa_kev = orig_kev
        CONFIG["feeds_security"] = orig_cfg_feeds
    print("[3] feeds_ai / feeds_security 时效窗口 OK")
    print("[4] cisa:kev 结果 prewindowed、不被二次时效过滤 OK")

    # ---------------------------------------------------------------- #
    # 5) _filter_yesterday 放宽窗口末端修复（早上 8 点也能收到当天条目）
    # ---------------------------------------------------------------- #
    today_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    today_item = {"title": "今天 00:01 刚发", "link": "", "pub_date": today_start + datetime.timedelta(minutes=1)}
    y1 = {"title": "昨天上午", "link": "", "pub_date": today_start - datetime.timedelta(hours=6)}
    y2 = {"title": "昨天下午", "link": "", "pub_date": today_start - datetime.timedelta(hours=18)}
    # 严格模式（recent_days=0）：窗口末端是今天 0 点，当天条目被排除（旧行为，用于对照）
    strict = [it["title"] for it in dd._filter_yesterday([dict(today_item), dict(y1), dict(y2)], 0)]
    assert "今天 00:01 刚发" not in strict, strict
    assert {"昨天上午", "昨天下午"} <= set(strict), strict
    # 放宽模式（recent_days=2）：窗口末端 = now + 5 分钟，当天条目必须保留
    relaxed = [it["title"] for it in dd._filter_yesterday([dict(today_item), dict(y1), dict(y2)], 2)]
    assert "今天 00:01 刚发" in relaxed, relaxed
    # 窗口起点仍严格按 N 天算，更早的条目不能被捞回来
    old_item = {"title": "十天前的旧闻", "link": "", "pub_date": NOW - datetime.timedelta(days=10)}
    relaxed2 = [it["title"] for it in dd._filter_yesterday([dict(old_item), dict(today_item)], 2)]
    assert relaxed2 == ["今天 00:01 刚发"], relaxed2
    # 没有日期的条目保持原有行为（原样保留）
    undated = {"title": "无日期", "link": ""}
    assert [it["title"] for it in dd._filter_yesterday([dict(undated)], 2)] == ["无日期"]
    print("[5] _filter_yesterday 放宽窗口包含当天条目、起点仍按 N 天 OK")

    # ---------------------------------------------------------------- #
    # 6) 模板渲染：新板块标题必须出现
    # ---------------------------------------------------------------- #
    sec_items = [{"title": "示例条目", "link": "https://e.x/1", "url": "https://e.x/1",
                  "pub_date": NOW, "summary": "摘要"}]
    md = dd._template_digest(None, {"feeds_ai": list(sec_items), "feeds_security": list(sec_items)})
    assert "🤖 AI 界的新变化" in md, md[:400]
    assert "🛡️ 网安漏洞与情报" in md, md[:400]
    assert md.index("🤖 AI 界的新变化") < md.index("🛡️ 网安漏洞与情报"), md[:400]
    print("[6] 模板渲染新板块标题 OK")

    # ---------------------------------------------------------------- #
    # 7) 配置 schema 7 个新键 + 提示词默认值
    # ---------------------------------------------------------------- #
    for k, t, dv in (
        ("ai_enabled", "bool", True),
        ("security_enabled", "bool", True),
        ("ai_recent_days", "int", 2),
        ("security_recent_days", "int", 2),
        ("security_kev_days", "int", 7),
    ):
        assert k in SCHEMA, "schema 缺少 " + k
        assert SCHEMA[k]["type"] == t, (k, SCHEMA[k]["type"])
        assert SCHEMA[k]["default"] == dv, (k, SCHEMA[k]["default"])
    for k in ("feeds_ai", "feeds_security"):
        assert k in SCHEMA, "schema 缺少 " + k
        assert SCHEMA[k]["type"] == "text", (k, SCHEMA[k])
    assert "cisa:kev" in str(SCHEMA["feeds_security"]["default"])
    assert "freebuf.com" in str(SCHEMA["feeds_security"]["default"])
    assert "qbitai" in str(SCHEMA["feeds_ai"]["default"])
    assert "infoq" in str(SCHEMA["feeds_ai"]["default"])
    assert "AI 界的新变化" in SCHEMA["llm_prompt"]["default"]
    assert "网安漏洞与情报" in SCHEMA["llm_prompt"]["default"]
    assert "AI 界的新变化" in mod.DEFAULT_PROMPT, "DEFAULT_PROMPT 缺 AI 板块"
    assert "网安漏洞与情报" in mod.DEFAULT_PROMPT, "DEFAULT_PROMPT 缺网安板块"
    norm = dd._normalize_prompt("旧的提示词，总长度控制在 1200 字内（仅输出实际有的板块）")
    assert "AI 界的新变化" in norm and "网安漏洞与情报" in norm, norm[-300:]
    assert "1800 字内" in norm, norm[:200]
    assert "有数据的板块必须全部输出" in norm
    print("[7] schema 7 个新键 + DEFAULT_PROMPT / _normalize_prompt 板块清单 OK")

    # ---------------------------------------------------------------- #
    # 8) 中文字体自愈：缺失补 + 不覆盖 + 资源缺失静默
    # ---------------------------------------------------------------- #
    assert mod.CJK_FONT_ASSET == os.path.join("assets", "fonts", "digest_cjk.ttf"), mod.CJK_FONT_ASSET
    repo_font = os.path.join(_ROOT, "assets", "fonts", "digest_cjk.ttf")
    assert os.path.exists(repo_font), "自带中文字体缺失: " + repo_font
    assert os.path.getsize(repo_font) > 2_000_000, "自带中文字体过小: %d" % os.path.getsize(repo_font)
    from PIL import ImageFont as IF

    rf = IF.truetype(repo_font, 24)
    assert bytes(rf.getmask("中")) != bytes(rf.getmask("国")), "自带字体把中文画成方框"
    assert rf.getbbox("每日简报")[2] > 50, "自带字体量不到中文宽度"

    tmp_data = tempfile.mkdtemp(prefix="dd_v117_")
    tmp_plug = os.path.join(tmp_data, "plugins", "astrbot_plugin_daily_digest")
    tmp_asset_dir = os.path.join(tmp_plug, "assets", "fonts")
    os.makedirs(tmp_asset_dir, exist_ok=True)
    open(os.path.join(tmp_plug, "main.py"), "w").close()
    with open(repo_font, "rb") as fs:
        font_bytes = fs.read()
    tmp_asset = os.path.join(tmp_asset_dir, "digest_cjk.ttf")
    with open(tmp_asset, "wb") as fd:
        fd.write(font_bytes)
    orig_mod_file = mod.__file__
    mod.__file__ = os.path.join(tmp_plug, "main.py")
    try:
        assert mod._plugin_data_dir() == tmp_data, mod._plugin_data_dir()
        p1 = mod._ensure_cjk_font()
        assert p1 == os.path.join(tmp_data, "font.ttf"), p1
        assert os.path.getsize(p1) == len(font_bytes), "字体未完整写入"
        # 已存在则不覆盖用户字体
        with open(p1, "wb") as fu:
            fu.write(b"USERFONT")
        assert mod._ensure_cjk_font() == p1
        with open(p1, "rb") as fr:
            assert fr.read() == b"USERFONT", "不应覆盖用户已有 font.ttf"
        # 自带字体资源缺失 -> 静默返回 None，不抛异常
        os.remove(tmp_asset)
        os.remove(p1)
        assert mod._ensure_cjk_font() is None, "资源缺失应静默返回 None"
    finally:
        mod.__file__ = orig_mod_file
    assert "_ensure_cjk_font()" in inspect.getsource(mod.DailyDigestPlugin.__init__), \
        "__init__ 未调用字体自愈"
    assert "_ensure_cjk_font()" in inspect.getsource(mod.DailyDigestPlugin._send_image), \
        "_send_image 未调用字体自愈"
    print("[8] 中文字体自愈（缺失补/不覆盖/资源缺失静默/两处调用）OK")

    # ---------------------------------------------------------------- #
    # 9) 交付物：metadata 版本 / CHANGELOG 条目 / 字体文件
    # ---------------------------------------------------------------- #
    meta = open(os.path.join(_ROOT, "metadata.yaml"), encoding="utf-8").read()
    assert "\nversion: 1.2.4" in meta, meta[:400]
    changelog = open(os.path.join(_ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert "## v1.2.4" in changelog, "CHANGELOG 缺 v1.2.3 段落"
    assert changelog.rstrip().rindex("## v1.2.4") > len(changelog) // 2, "v1.2.3 应追加在文件末尾附近"
    assert "CISA KEV" in changelog
    assert os.path.getsize(os.path.join(_ROOT, "assets", "fonts", "digest_cjk.ttf")) == 2104208
    print("[9] metadata 1.2.4 / CHANGELOG 末尾 v1.2.4 / 字体 2104208 字节 OK")

    # 10) 图片文本剔除 emoji（本地字体无 emoji 字形，留着会画方框）
    clean = mod._sanitize_for_image("🤖 AI 界的新变化 ✅ 抓取成功 🛡️ 网安 ⏳ 等待 ⭐ 精选")
    codes = [ord(c) for c in clean]
    assert not [c for c in codes if c >= 0x1F000], clean
    assert 0xFE0F not in codes and 0x200D not in codes, clean
    assert 0x2705 not in codes and 0x23F3 not in codes and 0x2B50 not in codes, clean
    for keep in ("AI 界的新变化", "抓取成功", "网安", "精选"):
        assert keep in clean, (keep, clean)
    print("[10] 图片文本剔除 emoji（保留正文）OK")

    assert hasattr(dd, "_digest_lock")
    assert hasattr(dd, "_kev_cache"), "实例上应有 _kev_cache（6 小时下载缓存）"
    print("\n全部 10 组测试通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
