"""Facebook API Direct 平台 provider。"""



from __future__ import annotations



import logging

import re



from app.core.config import settings

from app.models.collection_task import CollectionTask

from app.services.api_direct_client import ApiDirectError, ad_get, get_request_count

from app.services.concurrency import map_bounded

from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult

from app.services.collection_targets import (
    discovery_fetch_limit,
    overfetch_pages_for_limit,
    target_qualified_count,
)
from app.services.platform_utils import dedupe_profiles, parse_count_text, profile_to_collected

from app.services.task_run_progress import RunCheckpoint



logger = logging.getLogger(__name__)



ENDPOINTS = [
    "/v1/facebook/posts",
    "/v1/facebook/pages",
    "/v1/facebook/post/comments",

]

FACEBOOK_URL_RE = re.compile(r"facebook\.com/([^/?#]+)", re.I)

RESERVED_SLUGS = {"watch", "groups", "pages", "people", "profile.php", "login", "share", "reel", "video"}


def _api_budget_remaining(platform: str = "facebook") -> int | None:
    limit = settings.api_direct_max_requests_per_platform
    if limit <= 0:
        return None
    return max(0, limit - get_request_count(platform))


def _facebook_keyword_search_cap(task: CollectionTask, keyword_count: int) -> int:
    target = target_qualified_count(task)
    desired = max(2, min(keyword_count, 3 + target // 4))
    remaining = _api_budget_remaining()
    if remaining is None:
        return desired
    max_for_search = max(1, remaining // 3)
    return max(1, min(desired, max_for_search))


def _prioritize_facebook_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in sorted(keywords, key=lambda item: (len(item), item.lower())):
        clean = raw.strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(clean)
    return ordered


def _profile_passes_follower_gate(profile: PlatformCandidateProfile, task: CollectionTask) -> bool:
    required = task.min_followers_count
    if required is None:
        return True
    followers = profile.followers_count
    return followers is not None and followers >= required




# 现代 Facebook 主页/个人页 URL 形态：profile.php?id=、/people/<名>/<id|pfbid>、/p/<slug>
_FB_PROFILE_PHP_RE = re.compile(r"profile\.php\?(?:[^#]*&)?id=(\d+)", re.I)
_FB_PEOPLE_RE = re.compile(r"facebook\.com/people/[^/?#]+/(pfbid[A-Za-z0-9]+|\d+)", re.I)
_FB_P_RE = re.compile(r"facebook\.com/p/([^/?#]+)", re.I)


def _username_from_page_url(url: str | None) -> str | None:
    """从 Facebook URL 提取稳定标识作为 username。

    依次处理 profile.php?id= / /people/<名>/<id> / /p/<slug> / 命名页；
    无法提取标识的保留字路径（watch、groups、裸域等）返回 None。
    """
    if not url:
        return None

    m = _FB_PROFILE_PHP_RE.search(url)
    if m:
        return m.group(1)

    m = _FB_PEOPLE_RE.search(url)
    if m:
        return m.group(1)

    m = _FB_P_RE.search(url)
    if m:
        slug = m.group(1).strip("/")
        if slug:
            return slug

    match = FACEBOOK_URL_RE.search(url)
    if not match:
        return None

    slug = match.group(1).strip("/")
    if slug.lower() in RESERVED_SLUGS:
        return None

    return slug


def _is_supported_page_url(url: str | None) -> bool:

    return _username_from_page_url(url) is not None


def _merge_profile_details(
    profile: PlatformCandidateProfile,
    detail: PlatformCandidateProfile,
) -> PlatformCandidateProfile:

    detail.source_type = profile.source_type
    detail.source_discovery_type = profile.source_discovery_type
    detail.source_meta = {
        **(profile.source_meta or {}),
        **(detail.source_meta or {}),
        "source_keyword": (profile.source_meta or {}).get("source_keyword"),
        "search_endpoint": (profile.source_meta or {}).get("endpoint"),
        "detail_endpoint": (detail.source_meta or {}).get("endpoint"),
    }
    return detail




def _profile_from_search_result(page: dict, *, source_keyword: str) -> PlatformCandidateProfile | None:

    url = (page.get("url") or page.get("profile_url") or "").strip()

    name = (page.get("name") or "").strip()

    page_id = page.get("facebook_id") or page.get("page_id")

    if not url:

        return None

    if not _is_supported_page_url(url):
        return None
    # 关键词搜索里的 /people/ 个人页链接质量差、补采易失败，优先保留命名主页
    if "/people/" in url.lower():
        return None

    username = _username_from_page_url(url) or str(page_id or name).replace(" ", "_")
    return PlatformCandidateProfile(
        platform="facebook",
        username=username,
        profile_url=url,
        display_name=name or None,
        avatar_url=page.get("image_url") or page.get("image"),
        source_type="keyword_page",

        source_discovery_type="page_search",

        source_meta={

            "provider": "api_direct",

            "endpoint": "/v1/facebook/pages",

            "source_keyword": source_keyword,

            "facebook_id": page_id,

            "is_verified": page.get("is_verified"),

        },

    )





def _profile_from_page_details(page: dict, *, input_url: str, endpoint: str) -> PlatformCandidateProfile | None:

    url = (page.get("url") or input_url).strip()

    name = (page.get("name") or "").strip()

    page_id = page.get("page_id") or page.get("facebook_id")

    if not url:

        return None

    username = _username_from_page_url(url) or str(page_id or name).replace(" ", "_")

    followers = page.get("followers")

    if not isinstance(followers, int):

        followers = parse_count_text(followers)

    return PlatformCandidateProfile(

        platform="facebook",

        username=username,

        profile_url=url,

        display_name=name or None,

        avatar_url=page.get("image"),

        bio=page.get("intro"),

        followers_count=followers,

        website=page.get("website"),

        email=page.get("email"),

        source_type="input_url",

        source_discovery_type="url_import",

        source_meta={

            "provider": "api_direct",

            "endpoint": endpoint,

            "input_url": input_url,

            "page_id": page_id,

            "verified": page.get("verified"),

            "delegate_page_id": page.get("delegate_page_id"),

        },

    )





class FacebookApiDirectProvider:

    platform = "facebook"



    @staticmethod

    def capability() -> PlatformCapability:

        if not settings.is_api_direct_configured:

            return PlatformCapability(

                platform="facebook",

                label="Facebook",

                status="not_configured",

                message="API Direct 暂未配置（缺少 API_DIRECT_API_KEY）",

                endpoints=ENDPOINTS,

            )

        return PlatformCapability(

            platform="facebook",

            label="Facebook",

            status="url_only",

            message="API Direct 已支持（关键词 Page 搜索 + 公开 Page URL 导入）",

            endpoints=ENDPOINTS,

        )



    @staticmethod

    async def discover(

        task: CollectionTask,

        *,

        checkpoint: RunCheckpoint | None = None,

    ) -> PlatformDiscoveryResult:

        cap = FacebookApiDirectProvider.capability()

        if cap.status == "not_configured":

            return PlatformDiscoveryResult(

                platform="facebook",

                fatal=True,

                skipped=True,

                skip_reason=cap.message,

                errors=[cap.message],

            )



        checkpoint = checkpoint or RunCheckpoint.from_task(task)

        keywords = [k.strip() for k in (task.keywords or []) if k and str(k).strip()]

        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]

        if not keywords and not input_urls:

            msg = "Facebook 采集需要关键词或公开 Page URL"

            return PlatformDiscoveryResult(platform="facebook", errors=[msg], skip_reason=msg)



        limit = discovery_fetch_limit(task)
        pages = overfetch_pages_for_limit(limit)

        profiles: list[PlatformCandidateProfile] = []

        errors: list[str] = []



        fb_urls = [

            url

            for url in input_urls

            if "facebook.com" in url.lower() and not checkpoint.search_done("facebook", f"url:{url}")

        ]



        async def _fetch_url(url: str):

            try:

                data = await ad_get(

                    "/v1/facebook/pages",

                    params={"query": url, "pages": 1},

                    platform="facebook",

                )

                return url, data, None

            except ApiDirectError as exc:

                return url, None, str(exc)



        url_outcomes = await map_bounded(

            fb_urls,

            _fetch_url,

            concurrency=settings.collection_search_concurrency,

        )

        for outcome in url_outcomes:

            if isinstance(outcome, BaseException):

                errors.append(str(outcome))

                continue

            url, data, err = outcome

            checkpoint.mark_search("facebook", f"url:{url}")

            if err:

                errors.append(f"Facebook URL「{url}」: {err}")

                continue

            page = (data or {}).get("page")
            if not isinstance(page, dict):
                results = (data or {}).get("results") or (data or {}).get("pages") or []
                page = next((row for row in results if isinstance(row, dict)), None)

            if isinstance(page, dict):

                profile = _profile_from_page_details(page, input_url=url, endpoint="/v1/facebook/pages")

                if profile:

                    profiles.append(profile)



        target = target_qualified_count(task)
        search_keywords = _prioritize_facebook_keywords(
            [k for k in keywords if not checkpoint.search_done("facebook", k)]
        )
        keyword_cap = _facebook_keyword_search_cap(task, len(search_keywords))
        search_keywords = search_keywords[:keyword_cap]
        if len(search_keywords) < len(keywords):
            skipped = len(keywords) - len(search_keywords)
            errors.append(
                f"Facebook 为节省 API 额度，仅搜索前 {len(search_keywords)} 个关键词（跳过 {skipped} 个）"
            )

        for keyword in search_keywords:
            if _api_budget_remaining() == 0:
                errors.append("Facebook 关键词搜索：API 额度已用尽")
                break
            if len(profiles) >= limit:
                break
            try:
                data = await ad_get(
                    "/v1/facebook/pages",
                    params={"query": keyword, "pages": pages},
                    platform="facebook",
                )
            except ApiDirectError as exc:
                errors.append(f"Facebook 关键词「{keyword}」: {exc}")
                checkpoint.mark_search("facebook", keyword)
                continue
            checkpoint.mark_search("facebook", keyword)
            for page in (data or {}).get("results") or []:
                if not isinstance(page, dict):
                    continue
                profile = _profile_from_search_result(page, source_keyword=keyword)
                if profile:
                    profiles.append(profile)
                if len(profiles) >= limit:
                    break

        deduped = dedupe_profiles(profiles)[:limit]
        hydration_target = max(target * 2, target + 4) if task.min_followers_count else 0
        detail_candidates = [
            profile
            for profile in deduped
            if profile.source_type == "keyword_page" and _is_supported_page_url(profile.profile_url)
        ]
        qualified_count = sum(1 for p in deduped if _profile_passes_follower_gate(p, task))
        detail_by_url: dict[str, PlatformCandidateProfile] = {}
        hydrated_detail = 0

        for profile in detail_candidates:
            if _api_budget_remaining() == 0:
                errors.append("Facebook 主页补采：API 额度已用尽")
                break
            if hydration_target and qualified_count >= hydration_target:
                break
            try:
                data = await ad_get(
                    "/v1/facebook/pages",
                    params={"query": profile.profile_url, "pages": 1},
                    platform="facebook",
                )
            except ApiDirectError as exc:
                errors.append(f"Facebook Page detail {profile.profile_url}: {exc}")
                continue
            page = (data or {}).get("page")
            if not isinstance(page, dict):
                results = (data or {}).get("results") or (data or {}).get("pages") or []
                page = next((row for row in results if isinstance(row, dict)), None)
            if not isinstance(page, dict):
                continue
            detail = _profile_from_page_details(
                page,
                input_url=profile.profile_url,
                endpoint="/v1/facebook/pages",
            )
            if not detail:
                continue
            detail_url = (detail.profile_url or "").lower().rstrip("/")
            profile_url = profile.profile_url.lower().rstrip("/")
            if detail_url != profile_url:
                continue
            was_qualified = _profile_passes_follower_gate(profile, task)
            merged = _merge_profile_details(profile, detail)
            detail_by_url[merged.profile_url.lower().rstrip("/")] = merged
            hydrated_detail += 1
            if _profile_passes_follower_gate(merged, task) and not was_qualified:
                qualified_count += 1

        if detail_candidates and hydrated_detail < len(detail_candidates):
            errors.append(
                f"Facebook 已优先补采 {hydrated_detail}/{len(detail_candidates)} 个主页详情以节省 API 额度"
            )

        deduped = dedupe_profiles(
            [
                detail_by_url.get(profile.profile_url.lower().rstrip("/"), profile)
                for profile in deduped
            ]
        )

        logger.info(
            "[Facebook] task=%s keywords=%d/%d deduped=%d detail=%d qualified=%d api=%d",
            getattr(task, "id", None),
            len(search_keywords),
            len(keywords),
            len(deduped),
            hydrated_detail,
            qualified_count,
            get_request_count("facebook"),
        )
        items = [profile_to_collected(p) for p in deduped]



        return PlatformDiscoveryResult(

            platform="facebook",

            items=items,

            profiles=deduped,

            discovered_count=len(profiles),

            deduped_count=len(deduped),

            profile_fetched_count=len(deduped),

            api_requests=get_request_count("facebook"),

            errors=errors,

            fatal=bool(errors) and not deduped,

        )

