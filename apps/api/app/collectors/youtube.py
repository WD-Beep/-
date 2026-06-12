from __future__ import annotations

import re
from datetime import UTC, datetime
from statistics import mean
from urllib.parse import parse_qs, urlparse

import httpx

from app.collectors.base import BaseCollector, CollectedInfluencer
from app.core.config import settings
from app.models.collection_task import CollectionTask


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_KEYWORD_CHANNELS = 12
MAX_RECENT_VIDEOS = 8


class YouTubeCollector(BaseCollector):
    """Collect creator-level data from the YouTube Data API v3."""

    async def collect(self, task: CollectionTask) -> list[CollectedInfluencer]:
        if not settings.is_youtube_configured:
            raise RuntimeError("YouTube 采集需要先在 .env 配置 YOUTUBE_API_KEY。")

        if (task.platform or "").lower() != "youtube":
            raise NotImplementedError("YouTube 采集器只支持 platform=youtube 的任务。")

        channel_ids: list[str] = []
        async with httpx.AsyncClient(timeout=30) as client:
            if task.collection_mode in ("urls", "mixed") and task.input_urls:
                channel_ids.extend(await self._resolve_urls(client, task.input_urls))

            if task.collection_mode in ("keyword", "mixed") and task.keywords:
                channel_ids.extend(await self._search_channels(client, task.keywords))

            channel_ids = self._dedupe(channel_ids)
            if not channel_ids:
                return []

            channels = await self._fetch_channels(client, channel_ids)
            return [
                await self._build_influencer(client, item, task)
                for item in channels
                if item.get("id")
            ]

    async def _request(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        query = {**params, "key": settings.youtube_api_key}
        response = await client.get(f"{YOUTUBE_API_BASE}/{path}", params=query)
        if response.status_code == 403:
            raise RuntimeError("YouTube API 拒绝访问，请检查 API Key、配额或是否已启用 YouTube Data API v3。")
        if response.status_code == 400:
            raise RuntimeError(f"YouTube API 请求参数有误：{response.text[:300]}")
        response.raise_for_status()
        return response.json()

    async def _search_channels(self, client: httpx.AsyncClient, keywords: list[str]) -> list[str]:
        channel_ids: list[str] = []
        for keyword in keywords[:5]:
            data = await self._request(
                client,
                "search",
                {
                    "part": "snippet",
                    "q": keyword,
                    "type": "channel",
                    "maxResults": MAX_KEYWORD_CHANNELS,
                    "order": "relevance",
                },
            )
            for item in data.get("items", []):
                channel_id = item.get("id", {}).get("channelId")
                if channel_id:
                    channel_ids.append(channel_id)
        return channel_ids

    async def _resolve_urls(self, client: httpx.AsyncClient, urls: list[str]) -> list[str]:
        channel_ids: list[str] = []
        custom_handles: list[str] = []

        for url in urls:
            parsed = self._parse_youtube_url(url)
            if parsed["channel_id"]:
                channel_ids.append(parsed["channel_id"])
            elif parsed["handle"]:
                custom_handles.append(parsed["handle"])
            elif parsed["video_id"]:
                video_channel = await self._channel_from_video(client, parsed["video_id"])
                if video_channel:
                    channel_ids.append(video_channel)

        for handle in custom_handles:
            channel_id = await self._channel_from_handle(client, handle)
            if channel_id:
                channel_ids.append(channel_id)

        return channel_ids

    def _parse_youtube_url(self, raw_url: str) -> dict[str, str | None]:
        text = raw_url.strip()
        if not re.match(r"^https?://", text, re.I):
            text = f"https://{text}"

        parsed = urlparse(text)
        host = parsed.netloc.lower()
        path_parts = [part for part in parsed.path.split("/") if part]
        video_id = None
        channel_id = None
        handle = None

        if "youtu.be" in host and path_parts:
            video_id = path_parts[0]
        elif "youtube.com" in host:
            query = parse_qs(parsed.query)
            video_id = (query.get("v") or [None])[0]
            if len(path_parts) >= 2 and path_parts[0].lower() == "channel":
                channel_id = path_parts[1]
            elif path_parts and path_parts[0].startswith("@"):
                handle = path_parts[0]
            elif len(path_parts) >= 2 and path_parts[0].lower() in {"c", "user"}:
                handle = path_parts[1]

        return {"video_id": video_id, "channel_id": channel_id, "handle": handle}

    async def _channel_from_video(self, client: httpx.AsyncClient, video_id: str) -> str | None:
        data = await self._request(
            client,
            "videos",
            {"part": "snippet", "id": video_id, "maxResults": 1},
        )
        items = data.get("items", [])
        if not items:
            return None
        return items[0].get("snippet", {}).get("channelId")

    async def _channel_from_handle(self, client: httpx.AsyncClient, handle: str) -> str | None:
        normalized = handle.lstrip("@")
        data = await self._request(
            client,
            "search",
            {
                "part": "snippet",
                "q": normalized,
                "type": "channel",
                "maxResults": 5,
            },
        )
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            custom_url = (snippet.get("customUrl") or "").lstrip("@").lower()
            title = (snippet.get("channelTitle") or "").lower()
            if custom_url == normalized.lower() or title == normalized.lower():
                return item.get("id", {}).get("channelId")
        first = next(iter(data.get("items", [])), None)
        return first.get("id", {}).get("channelId") if first else None

    async def _fetch_channels(self, client: httpx.AsyncClient, channel_ids: list[str]) -> list[dict]:
        items: list[dict] = []
        for chunk in self._chunks(channel_ids, 50):
            data = await self._request(
                client,
                "channels",
                {
                    "part": "snippet,statistics,contentDetails,brandingSettings,topicDetails",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )
            items.extend(data.get("items", []))
        return items

    async def _build_influencer(
        self,
        client: httpx.AsyncClient,
        channel: dict,
        task: CollectionTask,
    ) -> CollectedInfluencer:
        channel_id = channel["id"]
        snippet = channel.get("snippet", {})
        statistics = channel.get("statistics", {})
        branding = channel.get("brandingSettings", {}).get("channel", {})
        topics = channel.get("topicDetails", {}).get("topicCategories", [])
        uploads_playlist = (
            channel.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        recent = await self._fetch_recent_video_stats(client, uploads_playlist)
        description = snippet.get("description") or ""
        email = self._extract_email(description)
        subscribers = self._to_int(statistics.get("subscriberCount"))
        avg_views = self._mean_int([item["views"] for item in recent])
        avg_likes = self._mean_int([item["likes"] for item in recent])
        avg_comments = self._mean_int([item["comments"] for item in recent])
        engagement_rate = self._engagement_rate(avg_likes, avg_comments, avg_views)
        title = snippet.get("title") or channel_id

        return CollectedInfluencer(
            platform="youtube",
            username=branding.get("customUrl") or title,
            display_name=title,
            profile_url=f"https://www.youtube.com/channel/{channel_id}",
            avatar_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
            country=snippet.get("country") or task.country,
            language=snippet.get("defaultLanguage") or task.country,
            category=task.category,
            niche=task.category or self._clean_topic(topics[0]) if topics else task.category,
            bio=description,
            followers_count=subscribers,
            avg_views=avg_views,
            avg_likes=avg_likes,
            avg_comments=avg_comments,
            engagement_rate=engagement_rate,
            email=email,
            final_email=email,
            public_email=email,
            email_source="youtube_description" if email else None,
            contact_credibility=0.85 if email else None,
            contact_score=90 if email else 35,
            product_fit=70 if task.category else None,
            data_completeness=self._data_completeness(subscribers, avg_views, email, recent),
            has_brand_collaboration=self._has_brand_signal(description),
            collaboration_formats=self._collaboration_formats(description),
            content_topics=[self._clean_topic(topic) for topic in topics[:5]],
            audience_country=snippet.get("country") or task.country,
            audience_language=snippet.get("defaultLanguage"),
            recent_post_titles=[item["title"] for item in recent],
            recent_post_urls=[item["url"] for item in recent],
            last_post_at=recent[0]["published_at"] if recent else None,
            posting_frequency=self._posting_frequency(recent),
            tags=self._tags(task, subscribers, email, engagement_rate),
        )

    async def _fetch_recent_video_stats(
        self,
        client: httpx.AsyncClient,
        uploads_playlist: str | None,
    ) -> list[dict]:
        if not uploads_playlist:
            return []

        playlist = await self._request(
            client,
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist,
                "maxResults": MAX_RECENT_VIDEOS,
            },
        )
        video_refs = [
            {
                "id": item.get("contentDetails", {}).get("videoId"),
                "title": item.get("snippet", {}).get("title"),
                "published_at": item.get("contentDetails", {}).get("videoPublishedAt"),
            }
            for item in playlist.get("items", [])
        ]
        video_ids = [item["id"] for item in video_refs if item["id"]]
        if not video_ids:
            return []

        videos = await self._request(
            client,
            "videos",
            {"part": "statistics,snippet", "id": ",".join(video_ids)},
        )
        stats_by_id = {item["id"]: item for item in videos.get("items", [])}
        recent: list[dict] = []
        for ref in video_refs:
            video = stats_by_id.get(ref["id"])
            if not video:
                continue
            stats = video.get("statistics", {})
            published_at = self._parse_datetime(ref.get("published_at"))
            recent.append(
                {
                    "title": ref.get("title") or video.get("snippet", {}).get("title") or "",
                    "url": f"https://www.youtube.com/watch?v={ref['id']}",
                    "published_at": published_at,
                    "views": self._to_int(stats.get("viewCount")) or 0,
                    "likes": self._to_int(stats.get("likeCount")) or 0,
                    "comments": self._to_int(stats.get("commentCount")) or 0,
                }
            )
        return recent

    def _extract_email(self, text: str) -> str | None:
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        return match.group(0) if match else None

    def _has_brand_signal(self, text: str) -> bool:
        return bool(re.search(r"brand|sponsor|collab|partnership|business|合作|商务|广告", text, re.I))

    def _collaboration_formats(self, text: str) -> list[str]:
        formats = []
        checks = {
            "sponsored_video": r"sponsor|ad|广告|赞助",
            "review": r"review|测评|开箱",
            "affiliate": r"affiliate|coupon|折扣|佣金",
            "brand_partnership": r"collab|partnership|合作|商务",
        }
        for label, pattern in checks.items():
            if re.search(pattern, text, re.I):
                formats.append(label)
        return formats

    def _posting_frequency(self, recent: list[dict]) -> str | None:
        dates = [item["published_at"] for item in recent if item["published_at"]]
        if len(dates) < 2:
            return None
        span_days = max((dates[0] - dates[-1]).days, 1)
        videos_per_week = round((len(dates) - 1) / span_days * 7, 1)
        return f"{videos_per_week}/week"

    def _tags(
        self,
        task: CollectionTask,
        subscribers: int | None,
        email: str | None,
        engagement_rate: float | None,
    ) -> list[str]:
        tags = ["youtube"]
        if task.category:
            tags.append(task.category)
        if subscribers and subscribers >= 100000:
            tags.append("large_creator")
        elif subscribers and subscribers >= 10000:
            tags.append("mid_creator")
        if email:
            tags.append("contactable")
        if engagement_rate and engagement_rate >= 5:
            tags.append("high_engagement")
        return tags

    def _data_completeness(
        self,
        subscribers: int | None,
        avg_views: int | None,
        email: str | None,
        recent: list[dict],
    ) -> float:
        filled = sum(bool(value) for value in [subscribers, avg_views, email, recent])
        return round(filled / 4 * 100, 1)

    def _engagement_rate(
        self,
        avg_likes: int | None,
        avg_comments: int | None,
        avg_views: int | None,
    ) -> float | None:
        if not avg_views:
            return None
        return round(((avg_likes or 0) + (avg_comments or 0)) / avg_views * 100, 2)

    def _clean_topic(self, topic: str) -> str:
        return topic.rstrip("/").split("/")[-1].replace("_", " ")

    def _mean_int(self, values: list[int]) -> int | None:
        filtered = [value for value in values if value is not None]
        return int(mean(filtered)) if filtered else None

    def _to_int(self, value: str | int | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _chunks(self, values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]
