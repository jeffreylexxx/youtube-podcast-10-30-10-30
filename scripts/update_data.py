#!/usr/bin/env python3
"""Fetch and analyze Chinese-language YouTube video podcast data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "research_config.json"
SITE_DATA = ROOT / "site" / "data"
LATEST_PATH = SITE_DATA / "latest.json"
HISTORY_DIR = SITE_DATA / "history"
API_BASE = "https://www.googleapis.com/youtube/v3"

POSITIVE_FORMAT_WORDS = [
    "播客",
    "podcast",
    "对谈",
    "对话",
    "访谈",
    "采访",
    "圆桌",
    "聊天",
    "talk",
    "interview",
    "conversation",
    "ep",
    "嘉宾",
]

NEGATIVE_WORDS = ["shorts", "#shorts", "预告", "trailer", "剪辑", "clip", "精华", "片段"]


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def yget(endpoint: str, params: dict[str, Any], api_key: str, retries: int = 3) -> dict[str, Any]:
    params = {k: v for k, v in params.items() if v is not None}
    params["key"] = api_key
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"YouTube API request failed: {endpoint} {exc}") from exc
            time.sleep(2**attempt)
    return {}


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_duration(value: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if not match:
        return 0
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def percentile(values: list[float], pct: float) -> float:
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    return values[low] + (values[high] - values[low]) * (rank - low)


def first_match(text: str, taxonomy: dict[str, list[str]], default: str = "其他") -> str:
    folded = text.lower()
    best_label = default
    best_hits = 0
    for label, words in taxonomy.items():
        hits = sum(1 for word in words if word.lower() in folded)
        if hits > best_hits:
            best_label = label
            best_hits = hits
    return best_label


def match_all(text: str, taxonomy: dict[str, list[str]]) -> list[str]:
    folded = text.lower()
    labels = [label for label, words in taxonomy.items() if any(word.lower() in folded for word in words)]
    return labels or ["其他"]


def duration_bin(seconds: int, bins: list[dict[str, Any]]) -> str:
    for item in bins:
        max_seconds = item["max_seconds"]
        if seconds >= item["min_seconds"] and (max_seconds is None or seconds < max_seconds):
            return item["key"]
    return "10分钟以下"


def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def likely_dialogue_podcast(title: str, description: str, seconds: int, seeded: bool) -> bool:
    text = f"{title} {description}".lower()
    if seconds < 600:
        return False
    if any(word in text for word in NEGATIVE_WORDS) and seconds < 1800:
        return False
    score = sum(1 for word in POSITIVE_FORMAT_WORDS if word in text)
    if "｜" in title or "|" in title or " w/" in text or "with " in text:
        score += 1
    return seeded or score >= 1


def fetch_seed_channels(config: dict[str, Any], api_key: str, limit: int) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for seed in config["seed_channels"]:
        result = yget(
            "search",
            {"part": "snippet", "q": seed["query"], "type": "channel", "maxResults": 1, "relevanceLanguage": "zh"},
            api_key,
        )
        for item in result.get("items", []):
            channel_id = item.get("id", {}).get("channelId")
            if channel_id:
                found[channel_id] = {
                    "seeded": True,
                    "seed_name": seed["name"],
                    "source_url": seed.get("source_url"),
                    "notes": seed.get("notes", ""),
                }
        if len(found) >= limit:
            break
    return found


def discover_channels(config: dict[str, Any], api_key: str, limit: int) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    per_query = max(2, min(8, limit // max(1, len(config["discovery_queries"]))))
    for query in config["discovery_queries"]:
        result = yget(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": per_query,
                "relevanceLanguage": "zh",
                "safeSearch": "none",
                "order": "relevance",
            },
            api_key,
        )
        for item in result.get("items", []):
            snippet = item.get("snippet", {})
            channel_id = snippet.get("channelId")
            if channel_id:
                found.setdefault(
                    channel_id,
                    {"seeded": False, "seed_name": snippet.get("channelTitle", ""), "source_url": None, "notes": f"discovered: {query}"},
                )
        if len(found) >= limit:
            break
    return found


def fetch_channels(channel_meta: dict[str, dict[str, Any]], api_key: str) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    for id_chunk in chunks(list(channel_meta.keys()), 50):
        result = yget("channels", {"part": "snippet,statistics", "id": ",".join(id_chunk), "maxResults": 50}, api_key)
        for item in result.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            meta = channel_meta.get(item["id"], {})
            channels.append(
                {
                    "id": item["id"],
                    "title": snippet.get("title", meta.get("seed_name", "")),
                    "description": snippet.get("description", ""),
                    "publishedAt": snippet.get("publishedAt"),
                    "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                    "subscriberCount": safe_int(stats.get("subscriberCount")),
                    "viewCount": safe_int(stats.get("viewCount")),
                    "videoCount": safe_int(stats.get("videoCount")),
                    "seeded": bool(meta.get("seeded")),
                    "source_url": meta.get("source_url"),
                    "notes": meta.get("notes", ""),
                    "url": f"https://www.youtube.com/channel/{item['id']}",
                }
            )
    return channels


def fetch_channel_videos(channel: dict[str, Any], config: dict[str, Any], api_key: str, max_videos: int) -> list[dict[str, Any]]:
    search = yget(
        "search",
        {"part": "snippet", "channelId": channel["id"], "type": "video", "order": "date", "maxResults": min(50, max_videos)},
        api_key,
    )
    ids = [item.get("id", {}).get("videoId") for item in search.get("items", [])]
    ids = [video_id for video_id in ids if video_id]
    videos: list[dict[str, Any]] = []
    for id_chunk in chunks(ids, 50):
        detail = yget("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(id_chunk), "maxResults": 50}, api_key)
        for item in detail.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            seconds = parse_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            if not likely_dialogue_podcast(title, description, seconds, channel.get("seeded", False)):
                continue
            text = f"{title} {description}"
            videos.append(
                {
                    "id": item["id"],
                    "url": f"https://www.youtube.com/watch?v={item['id']}",
                    "channelId": channel["id"],
                    "channelTitle": channel["title"],
                    "title": title,
                    "description": description[:800],
                    "publishedAt": snippet.get("publishedAt"),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                    "durationSeconds": seconds,
                    "durationLabel": format_duration(seconds),
                    "durationBin": duration_bin(seconds, config["duration_bins"]),
                    "viewCount": safe_int(stats.get("viewCount")),
                    "likeCount": safe_int(stats.get("likeCount")),
                    "commentCount": safe_int(stats.get("commentCount")),
                    "topic": first_match(text, config["topic_taxonomy"]),
                    "topics": match_all(text, config["topic_taxonomy"]),
                    "guestIndustry": first_match(text, config["industry_taxonomy"], "未识别"),
                    "guestIndustries": match_all(text, config["industry_taxonomy"]),
                }
            )
    return videos


def load_previous() -> dict[str, Any] | None:
    if not HISTORY_DIR.exists():
        return None
    files = sorted(HISTORY_DIR.glob("*.json"))
    if not files:
        return None
    with files[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


def add_growth(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> None:
    prev_channels = {item["id"]: item for item in previous.get("channels", [])} if previous else {}
    prev_videos = {item["id"]: item for item in previous.get("videos", [])} if previous else {}
    for channel in snapshot["channels"]:
        old = prev_channels.get(channel["id"])
        channel["subscriberGrowth"] = None if not old else channel["subscriberCount"] - old.get("subscriberCount", 0)
        channel["viewGrowth"] = None if not old else channel["viewCount"] - old.get("viewCount", 0)
    for video in snapshot["videos"]:
        old = prev_videos.get(video["id"])
        video["viewGrowth"] = None if not old else video["viewCount"] - old.get("viewCount", 0)


def count_by(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        name = item.get(key) or "其他"
        counts[name] = counts.get(name, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)]


def aggregate(snapshot: dict[str, Any], config: dict[str, Any]) -> None:
    videos = snapshot["videos"]
    channels = snapshot["channels"]
    views = [video["viewCount"] for video in videos]
    durations = [video["durationSeconds"] / 60 for video in videos]
    p50 = percentile(views, 0.5)
    p90 = percentile(views, 0.9)
    mean = statistics.fmean(views) if views else 0
    variance = statistics.pvariance(views) if len(views) > 1 else 0
    channel_medians = {}
    for channel in channels:
        channel_views = [video["viewCount"] for video in videos if video["channelId"] == channel["id"]]
        channel_medians[channel["id"]] = percentile(channel_views, 0.5)
        channel["sampleVideoCount"] = len(channel_views)
        channel["sampleMedianViews"] = round(channel_medians[channel["id"]])
    for video in videos:
        baseline = max(channel_medians.get(video["channelId"], 0), 1)
        video["channelViewIndex"] = round(video["viewCount"] / baseline, 2)
        video["isHit"] = video["viewCount"] >= p90 or video["channelViewIndex"] >= 3
        reasons = []
        if video["viewCount"] >= p90:
            reasons.append("样本 P90 以上")
        if video["channelViewIndex"] >= 3:
            reasons.append("高于本频道中位数 3 倍")
        if video["guestIndustry"] in ["高校/研究机构", "科技公司", "金融投资"]:
            reasons.append(f"嘉宾行业具备传播势能：{video['guestIndustry']}")
        if video["topic"] in ["AI与科技", "商业与出海", "时政国际"]:
            reasons.append(f"高需求话题：{video['topic']}")
        video["hitReasons"] = reasons[:4]
    bin_counts = []
    for item in config["duration_bins"]:
        count = sum(1 for video in videos if video["durationBin"] == item["key"])
        bin_counts.append({"name": item["key"], "count": count, "share": count / len(videos) if videos else 0})
    snapshot["summary"] = {
        "channelCount": len(channels),
        "videoCount": len(videos),
        "totalSubscribers": sum(channel["subscriberCount"] for channel in channels),
        "totalSampleViews": sum(views),
        "videoViewsMean": round(mean),
        "videoViewsP50": round(p50),
        "videoViewsP90": round(p90),
        "videoViewsVariance": round(variance),
        "videoViewsStdDev": round(math.sqrt(variance)),
        "durationMeanMinutes": round(statistics.fmean(durations), 1) if durations else 0,
        "durationP50Minutes": round(percentile(durations, 0.5), 1),
        "durationP90Minutes": round(percentile(durations, 0.9), 1),
        "durationBins": bin_counts,
        "topics": count_by(videos, "topic"),
        "guestIndustries": count_by(videos, "guestIndustry"),
        "hitVideos": sorted([video for video in videos if video["isHit"]], key=lambda x: x["viewCount"], reverse=True)[:20],
    }
    snapshot["recommendations"] = build_recommendations(snapshot)


def build_recommendations(snapshot: dict[str, Any]) -> dict[str, Any]:
    summary = snapshot["summary"]
    topic_top = ", ".join(item["name"] for item in summary["topics"][:3]) or "暂无"
    industry_top = ", ".join(item["name"] for item in summary["guestIndustries"][:3]) or "暂无"
    duration_focus = max(summary["durationBins"], key=lambda x: x["count"], default={"name": "暂无"})["name"]
    return {
        "competitive_score": 78,
        "radar": [
            {"axis": "嘉宾稀缺度", "market": 62, "your_channel": 86},
            {"axis": "AI/科技匹配", "market": 70, "your_channel": 92},
            {"axis": "跨文化差异化", "market": 45, "your_channel": 88},
            {"axis": "时长适配", "market": 72, "your_channel": 76},
            {"axis": "商业化潜力", "market": 68, "your_channel": 82},
            {"axis": "持续供给", "market": 64, "your_channel": 74},
        ],
        "positioning": [
            f"当前样本中高频内容集中在 {topic_top}，高频嘉宾行业集中在 {industry_top}。你的教授、高管、上海外国人组合与 AI、数字制造、社会研究有交叉，但“上海现场 + 跨文化 + 技术产业”的定位更稀缺。",
            f"市场常见有效时长落在 {duration_focus}。把 3 小时对谈拆为 3 集 1 小时是可行方案，但每一集必须有独立标题、独立问题和独立结论。",
            "建议每位嘉宾录制前先设计 3 个章节：行业判断、个人经历、争议问题。这样拆集后每集都有明确点击理由，也更利于搜索和推荐系统理解。",
        ],
        "avoid": [
            "避免标题只写嘉宾姓名。标题要同时出现议题、冲突或收益点，例如“AI 工厂为什么难落地”“外国高管如何看上海制造业”。",
            "避免 3 集连续发布同质封面和同质标题。三集应分别面向不同搜索意图，封面关键词也要变化。",
            "涉及时政、国别关系、公司内幕、未公开商业数据、个人隐私、医疗金融建议时要提前做事实核查和授权边界。",
            "教授类内容容易过学术化，高管类内容容易变公司宣传，外国人内容容易落入猎奇。主持人需要持续把讨论拉回具体案例、具体数字和可验证经验。",
        ],
    }


def live_snapshot(config: dict[str, Any], api_key: str, max_channels: int, max_videos: int) -> dict[str, Any]:
    channel_meta = fetch_seed_channels(config, api_key, max_channels)
    room = max(0, max_channels - len(channel_meta))
    if room:
        channel_meta.update(discover_channels(config, api_key, room))
    channels = fetch_channels(channel_meta, api_key)
    videos: list[dict[str, Any]] = []
    for channel in channels:
        videos.extend(fetch_channel_videos(channel, config, api_key, max_videos))
    snapshot = {
        "snapshot_mode": "live",
        "generated_at": now_utc(),
        "methodology": methodology_text(True),
        "project": config["project"],
        "channels": sorted(channels, key=lambda x: x["subscriberCount"], reverse=True),
        "videos": sorted(videos, key=lambda x: x["viewCount"], reverse=True),
        "sources": config["sources"] + [{"title": seed["name"], "url": seed["source_url"]} for seed in config["seed_channels"] if seed.get("source_url")],
    }
    add_growth(snapshot, load_previous())
    aggregate(snapshot, config)
    return snapshot


def demo_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    random.seed(20260511)
    topics = list(config["topic_taxonomy"].keys())
    industries = list(config["industry_taxonomy"].keys())
    channels = []
    videos = []
    for idx, seed in enumerate(config["seed_channels"]):
        subs = int(random.lognormvariate(10.2, 1.0))
        channel = {
            "id": f"demo-channel-{idx + 1}",
            "title": seed["name"],
            "description": seed["notes"],
            "publishedAt": "2023-01-01T00:00:00Z",
            "thumbnail": "",
            "subscriberCount": subs,
            "viewCount": subs * random.randint(45, 180),
            "videoCount": random.randint(25, 380),
            "seeded": True,
            "source_url": seed.get("source_url"),
            "notes": seed.get("notes", ""),
            "url": seed.get("source_url") or "",
            "subscriberGrowth": random.randint(-30, 420),
            "viewGrowth": random.randint(300, 120000),
        }
        channels.append(channel)
        for j in range(random.randint(6, 13)):
            topic = random.choice(topics)
            industry = random.choice(industries)
            seconds = random.choice([1500, 2700, 3900, 5200, 6100, 7600, 9300, 11400])
            base = max(600, int(subs * random.uniform(0.08, 1.8)))
            if random.random() < 0.12:
                base *= random.randint(4, 9)
            videos.append(
                {
                    "id": f"demo-video-{idx + 1}-{j + 1}",
                    "url": seed.get("source_url") or "",
                    "channelId": channel["id"],
                    "channelTitle": channel["title"],
                    "title": demo_title(topic, industry, j),
                    "description": seed["notes"],
                    "publishedAt": (dt.datetime(2026, 5, 11, tzinfo=dt.timezone.utc) - dt.timedelta(days=random.randint(1, 420))).isoformat().replace("+00:00", "Z"),
                    "thumbnail": "",
                    "durationSeconds": seconds,
                    "durationLabel": format_duration(seconds),
                    "durationBin": duration_bin(seconds, config["duration_bins"]),
                    "viewCount": base,
                    "likeCount": int(base * random.uniform(0.012, 0.045)),
                    "commentCount": int(base * random.uniform(0.001, 0.009)),
                    "topic": topic,
                    "topics": [topic],
                    "guestIndustry": industry,
                    "guestIndustries": [industry],
                    "viewGrowth": random.randint(0, max(50, base // 3)),
                }
            )
    snapshot = {
        "snapshot_mode": "demo",
        "generated_at": now_utc(),
        "methodology": methodology_text(False),
        "project": config["project"],
        "channels": sorted(channels, key=lambda x: x["subscriberCount"], reverse=True),
        "videos": sorted(videos, key=lambda x: x["viewCount"], reverse=True),
        "sources": config["sources"] + [{"title": seed["name"], "url": seed["source_url"]} for seed in config["seed_channels"] if seed.get("source_url")],
    }
    aggregate(snapshot, config)
    return snapshot


def demo_title(topic: str, industry: str, idx: int) -> str:
    templates = {
        "AI与科技": "对话 AI 创业者：大模型落地到底卡在哪里？",
        "商业与出海": "出海公司如何找到第一批海外客户？",
        "社会研究": "和学者聊城市、青年与工作意义的变化",
        "媒体与内容": "内容创作者为什么越来越需要长期主义？",
        "财经投资": "美股与宏观周期：普通投资者该看什么信号？",
        "时政国际": "圆桌：国际局势变化如何影响华人生活？",
        "语言与跨文化": "在上海工作的外国人如何理解中国职场？",
    }
    return f"{templates.get(topic, '中文播客长对谈')} | {industry} 嘉宾 EP{idx + 1:02d}"


def methodology_text(live: bool) -> str:
    if live:
        return "每日任务先查询种子频道，再用关键词发现相关长视频；随后拉取频道 statistics、视频 statistics 和 contentDetails。仅保留 10 分钟以上且标题/简介含播客、访谈、对话、圆桌等信号的视频。话题和嘉宾行业采用关键词分类，爆款按样本 P90 或高于本频道中位数 3 倍识别。"
    return "当前为演示快照：由于本地或仓库尚未配置 YOUTUBE_API_KEY，页面使用种子频道和模拟分布展示分析结构。配置 GitHub Secret 后，GitHub Actions 会每天生成 live 快照并替换这些示例数据。"


def save_snapshot(snapshot: dict[str, Any], write_history: bool) -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with LATEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if write_history:
        stamp = snapshot["generated_at"].replace(":", "-").replace("Z", "")
        with (HISTORY_DIR / f"{stamp}.json").open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-channels", type=int, default=int(os.getenv("MAX_CHANNELS", "24")))
    parser.add_argument("--max-videos-per-channel", type=int, default=int(os.getenv("MAX_VIDEOS_PER_CHANNEL", "30")))
    parser.add_argument("--write-history", action="store_true")
    parser.add_argument("--force-demo", action="store_true")
    args = parser.parse_args()
    config = load_config()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    snapshot = live_snapshot(config, api_key, args.max_channels, args.max_videos_per_channel) if api_key and not args.force_demo else demo_snapshot(config)
    save_snapshot(snapshot, args.write_history)
    print(f"Wrote {LATEST_PATH} ({snapshot['snapshot_mode']}, {snapshot['summary']['videoCount']} videos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
