"""采集任务入库前的质量筛选（硬拦截 vs 质量偏好）。"""



from __future__ import annotations



import re

from dataclasses import dataclass
from urllib.parse import urlparse



from app.collectors.base import CollectedInfluencer

from app.models.collection_task import CollectionTask



USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")
TIKTOK_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?tiktok\.com/@[\w.\-]+/?$", re.I)
YOUTUBE_PROFILE_URL_RE = re.compile(
    r"^https?://(www\.)?youtube\.com/(channel/[\w\-]+|@[\w.\-]+)/?$",
    re.I,
)
FACEBOOK_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?facebook\.com/[\w.\-]+/?$", re.I)
FACEBOOK_RESERVED_PATHS = ("watch", "groups", "pages", "profile.php", "login", "share", "reel", "video")
PINTEREST_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?pinterest\.com/[A-Za-z0-9_.-]+/?$", re.I)
PINTEREST_PIN_URL_RE = re.compile(r"^https?://(www\.)?pinterest\.com/pin/[A-Za-z0-9_-]+/?$", re.I)
PINTEREST_PIN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PINTEREST_RESERVED_PATHS = ("about", "business", "categories", "ideas", "login", "pin", "search", "settings", "today")
LTK_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?shopltk\.com/explore/[A-Za-z0-9_.-]+/?$", re.I)
SHOPMY_PROFILE_URL_RE = re.compile(r"^https?://(www\.)?shopmy\.us/[A-Za-z0-9_.-]+/?$", re.I)
SHOPMY_RESERVED_PATHS = ("collections", "discover", "explore", "login", "products", "shop", "stores")

DISCOVERY_HARD_MIN_FOLLOWERS = 30000

RESERVED_USERNAMES = {

    "p",

    "reel",

    "reels",

    "explore",

    "accounts",

    "stories",

    "tv",

    "about",

    "legal",

    "direct",

    "nametag",

}





@dataclass(frozen=True)

class PostHydrationHardFilterResult:

    passed: bool

    reason: str | None = None





def _normalize_keywords(keywords: list | None) -> list[str]:

    if not keywords:

        return []

    return [str(k).strip().lower() for k in keywords if k and str(k).strip()]





def is_valid_instagram_username(username: str | None) -> bool:

    if not username:

        return False

    value = username.strip().lstrip("@").lower()

    if not value or value in RESERVED_USERNAMES:

        return False

    return bool(USERNAME_RE.match(value))





def is_valid_profile_url(url: str | None) -> bool:
    from app.services.instagram_urls import is_instagram_profile_url

    return is_instagram_profile_url(url)


def _normalize_platform(platform: str | None) -> str:
    return (platform or "instagram").strip().lower()


def _first_url_path_part(url: str) -> str:
    return next((part.lower() for part in urlparse(url).path.split("/") if part), "")


def is_valid_platform_username(platform: str | None, username: str | None) -> bool:
    name = _normalize_platform(platform)
    if name == "instagram":
        return is_valid_instagram_username(username)
    if name == "pinterest" and username and str(username).strip().startswith("pin:"):
        pin_id = str(username).strip()[4:]
        return bool(PINTEREST_PIN_ID_RE.match(pin_id))
    if not username or not str(username).strip():
        return False
    value = str(username).strip().lstrip("@")
    if not value or " " in value or len(value) > 100:
        return False
    return True


def is_valid_platform_profile_url(platform: str | None, url: str | None) -> bool:
    name = _normalize_platform(platform)
    if not url or not str(url).strip():
        return False
    text = str(url).strip()
    if name == "instagram":
        return is_valid_profile_url(text)
    if name == "tiktok":
        return bool(TIKTOK_PROFILE_URL_RE.match(text))
    if name == "youtube":
        return bool(YOUTUBE_PROFILE_URL_RE.match(text))
    if name == "facebook":
        lowered = text.lower()
        if "facebook.com" not in lowered:
            return False
        if any(f"/{part}" in lowered for part in FACEBOOK_RESERVED_PATHS):
            return False
        return bool(FACEBOOK_PROFILE_URL_RE.match(text))
    if name == "pinterest":
        lowered = text.lower()
        if "pinterest.com" not in lowered:
            return False
        if PINTEREST_PIN_URL_RE.match(text):
            parts = [part for part in urlparse(text).path.split("/") if part]
            if len(parts) == 2 and parts[0].lower() == "pin":
                return bool(PINTEREST_PIN_ID_RE.match(parts[1]))
            return False
        if _first_url_path_part(text) in PINTEREST_RESERVED_PATHS:
            return False
        return bool(PINTEREST_PROFILE_URL_RE.match(text))
    if name == "ltk":
        return bool(LTK_PROFILE_URL_RE.match(text))
    if name == "shopmy":
        lowered = text.lower()
        if "shopmy.us" not in lowered:
            return False
        if _first_url_path_part(text) in SHOPMY_RESERVED_PATHS:
            return False
        return bool(SHOPMY_PROFILE_URL_RE.match(text))
    return False


def uses_discovery_hard_min_followers_for_item(item: CollectedInfluencer, task: CollectionTask) -> bool:
    """Instagram item 始终执行 3 万粉硬筛；multi 任务也按 item.platform 判断。"""
    del task
    return _normalize_platform(item.platform) == "instagram"


def required_min_followers_for_item(item: CollectedInfluencer, task: CollectionTask) -> int | None:
    """任务对单个候选生效的最低粉丝门槛；未设置则返回 None。"""
    if uses_discovery_hard_min_followers_for_item(item, task):
        return discovery_hard_min_followers(task)
    if task.min_followers_count is not None:
        return task.min_followers_count
    return None





def _task_relevance_keywords(task: CollectionTask | None) -> list[str]:

    if not task:

        return []

    keywords: list[str] = []

    keywords.extend(_normalize_keywords(task.keywords))

    keywords.extend(_normalize_keywords(task.filter_include_keywords))

    if task.category:

        keywords.append(task.category.strip().lower())

    return [k.lstrip("#") for k in keywords if k]





def is_content_relevant_to_task(*texts: str | None, task: CollectionTask | None) -> bool:

    keywords = _task_relevance_keywords(task)

    if not keywords:

        return True

    haystack = " ".join(t for t in texts if t).lower()

    if not haystack.strip():

        return True

    return any(kw in haystack for kw in keywords)





def passes_early_candidate_filter(

    *,

    username: str | None,

    profile_url: str | None,

    source_caption: str | None = None,

    source_hashtag: str | None = None,

    task: CollectionTask | None,

) -> bool:

    """第一阶段：仅校验账号有效性与内容相关性，不依赖粉丝/互动率。"""

    if not is_valid_instagram_username(username):

        return False

    if not is_valid_profile_url(profile_url):

        return False

    if not source_caption and not source_hashtag:

        return True

    return is_content_relevant_to_task(

        source_caption,

        source_hashtag,

        username,

        task=task,

    )





def build_searchable_text(data: CollectedInfluencer) -> str:

    parts: list[str] = [

        data.username or "",

        data.display_name or "",

        data.bio or "",

        data.category or "",

        data.niche or "",

        data.country or "",

        data.language or "",

    ]

    if data.content_topics:

        parts.extend(str(t) for t in data.content_topics)

    if data.recent_post_titles:

        parts.extend(str(t) for t in data.recent_post_titles)

    if data.tags:

        parts.extend(str(t) for t in data.tags)

    if data.collaboration_formats:

        parts.extend(str(t) for t in data.collaboration_formats)

    return " ".join(parts).lower()





def discovery_hard_min_followers(task: CollectionTask) -> int:
    """Instagram 统一流水线：硬性最低粉丝 = max(用户填写, 30000)。"""
    return max(task.min_followers_count or 0, DISCOVERY_HARD_MIN_FOLLOWERS)


def uses_discovery_hard_min_followers(task: CollectionTask) -> bool:
    """任务是否包含 Instagram（用于摘要/偏好说明）。"""
    platforms = getattr(task, "platforms", None) or []
    normalized = [_normalize_platform(p) for p in platforms if p]
    if normalized:
        return "instagram" in normalized
    return _normalize_platform(task.platform) in ("instagram", "multi")


def find_excluded_keyword(searchable: str, task: CollectionTask) -> str | None:

    exclude_keywords = _normalize_keywords(task.filter_exclude_keywords)

    for kw in exclude_keywords:

        if kw in searchable:

            return kw

    return None





def evaluate_post_hydration_hard_filter(

    item: CollectedInfluencer,

    task: CollectionTask,

) -> PostHydrationHardFilterResult:

    """入库前硬拦截：无效主页、命中排除词。"""

    platform = _normalize_platform(item.platform)

    if not is_valid_platform_username(platform, item.username):

        return PostHydrationHardFilterResult(False, "invalid_profile")

    if not is_valid_platform_profile_url(platform, item.profile_url):

        return PostHydrationHardFilterResult(False, "invalid_profile")



    searchable = build_searchable_text(item)

    excluded = find_excluded_keyword(searchable, task)

    if excluded:

        return PostHydrationHardFilterResult(False, f"excluded_keyword:{excluded}")

    required_min = required_min_followers_for_item(item, task)
    if required_min is not None:
        followers = item.followers_count
        if followers is None or followers < required_min:
            return PostHydrationHardFilterResult(False, "below_min_followers")

    return PostHydrationHardFilterResult(True)





def hard_filter_failure_detail(reason: str | None, *, platform: str | None = None) -> str:

    if not reason:

        return "硬筛选未通过"

    if reason.startswith("excluded_keyword:"):

        kw = reason.split(":", 1)[1]

        return f"命中排除关键词：{kw}"

    if reason == "invalid_profile":
        name = _normalize_platform(platform)
        if name == "instagram":
            return "无效 Instagram 主页或用户名"
        return f"无效 {name} 主页或用户名"

    if reason == "below_min_followers":

        return (
            f"粉丝数未达到真实发现链路最低要求（需 ≥{DISCOVERY_HARD_MIN_FOLLOWERS}，"
            "或任务设置的更高门槛）"
        )

    return reason





def get_quality_preference_mismatch_reasons(

    item: CollectedInfluencer,

    task: CollectionTask,

) -> list[str]:

    """质量偏好（软条件）：用于评分与摘要，不阻止入库。"""

    reasons: list[str] = []

    followers = item.followers_count

    if task.min_followers_count is not None and not uses_discovery_hard_min_followers_for_item(item, task):
        if followers is None or followers < task.min_followers_count:
            reasons.append("below_min_followers")



    if task.max_followers_count is not None:

        if followers is not None and followers > task.max_followers_count:

            reasons.append("above_max_followers")



    if task.min_engagement_rate is not None:

        if item.engagement_rate is None:

            reasons.append("missing_engagement_rate")

        elif item.engagement_rate < task.min_engagement_rate:

            reasons.append("below_min_engagement_rate")



    include_keywords = _normalize_keywords(task.filter_include_keywords)

    if include_keywords:

        searchable = build_searchable_text(item)

        if not any(kw in searchable for kw in include_keywords):

            reasons.append("missing_include_keyword")



    return reasons





def matches_quality_preferences(item: CollectedInfluencer, task: CollectionTask) -> bool:

    return not get_quality_preference_mismatch_reasons(item, task)





def passes_post_hydration_filters(item: CollectedInfluencer, task: CollectionTask) -> bool:

    """兼容旧调用：仅硬拦截。"""

    return evaluate_post_hydration_hard_filter(item, task).passed





def passes_task_quality_filters(item: CollectedInfluencer, task: CollectionTask) -> bool:

    return passes_post_hydration_filters(item, task)


