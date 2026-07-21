# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：collection sources
"""采集数据源与平台能力说明（Apify / API Direct）。"""



from __future__ import annotations



from app.core.config import settings

from app.services.instagram_provider import PROVIDER_APIFY, PROVIDER_API_DIRECT

from app.services.platform_types import PlatformCapability



APIFY_SUPPORTED_PLATFORMS = frozenset({"instagram", "youtube", "tiktok", "facebook"})





def platform_data_source(platform: str) -> str:

    name = platform.strip().lower()

    if name == "instagram":

        return settings.active_instagram_provider

    if name == "youtube":

        return settings.active_youtube_provider

    if name == "tiktok":

        return settings.active_tiktok_provider

    if name == "facebook":

        return settings.active_facebook_provider

    return "url_only"





def platform_data_source_label(platform: str) -> str:

    source = platform_data_source(platform)

    if source == PROVIDER_APIFY:

        return "Apify"

    if source == PROVIDER_API_DIRECT:

        return "API Direct"

    if source == "url_only":

        return "URL 导入"

    return source





def facebook_collector_status() -> tuple[bool, str]:
    provider = platform_data_source("facebook")
    if provider == PROVIDER_APIFY:
        configured = settings.is_apify_configured
        message = (
            "Facebook 数据源：Apify Search + Pages Scraper（APIFY_TOKEN 已配置）"
            if configured
            else "Facebook 数据源：Apify，但未配置 APIFY_TOKEN"
        )
        return configured, message
    if provider == PROVIDER_API_DIRECT:
        configured = settings.is_api_direct_configured
        message = (
            "Facebook 数据源：API Direct（API_DIRECT_API_KEY 已配置）"
            if configured
            else "Facebook 数据源：API Direct，但未配置 API_DIRECT_API_KEY"
        )
        return configured, message
    return False, f"Facebook 数据源：{provider}（未识别）"


def enrich_platform_capability(cap: PlatformCapability) -> PlatformCapability:

    platform = cap.platform.lower()

    source = platform_data_source(platform)



    if platform == "instagram" and source == PROVIDER_API_DIRECT:

        configured = settings.is_api_direct_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "Instagram 数据源：API Direct（API_DIRECT_API_KEY 已配置）"

                if configured

                else "Instagram 数据源：API Direct，但未配置 API_DIRECT_API_KEY"

            ),

            endpoints=cap.endpoints,

        )



    if platform == "instagram" and source == PROVIDER_APIFY:

        configured = settings.is_apify_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "Instagram 数据源：Apify（APIFY_TOKEN 已配置）"

                if configured

                else "Instagram 数据源：Apify，但未配置 APIFY_TOKEN"

            ),

            endpoints=[

                settings.apify_instagram_actor_id,

                settings.apify_instagram_hashtag_actor_id,

            ],

        )



    if platform == "youtube" and source == PROVIDER_APIFY:

        configured = settings.is_apify_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "YouTube 数据源：Apify YouTube Scraper（APIFY_TOKEN 已配置）"

                if configured

                else "YouTube 数据源：Apify，但未配置 APIFY_TOKEN"

            ),

            endpoints=[settings.apify_youtube_actor_id],

        )



    if platform == "tiktok" and source == PROVIDER_APIFY:

        configured = settings.is_apify_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "TikTok 数据源：Apify TikTok Scraper（APIFY_TOKEN 已配置）"

                if configured

                else "TikTok 数据源：Apify，但未配置 APIFY_TOKEN"

            ),

            endpoints=[settings.apify_tiktok_actor_id],

        )



    if platform == "facebook" and source == PROVIDER_APIFY:

        configured = settings.is_apify_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "Facebook 数据源：Apify Search + Pages Scraper（APIFY_TOKEN 已配置）"

                if configured

                else "Facebook 数据源：Apify，但未配置 APIFY_TOKEN"

            ),

            endpoints=[

                settings.apify_facebook_search_actor_id,

                settings.apify_facebook_pages_actor_id,

            ],

        )



    if platform == "facebook" and source == PROVIDER_API_DIRECT:

        configured = settings.is_api_direct_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "Facebook 数据源：API Direct（API_DIRECT_API_KEY 已配置）"

                if configured

                else "Facebook 数据源：API Direct，但未配置 API_DIRECT_API_KEY"

            ),

            endpoints=cap.endpoints,

        )



    if platform == "youtube" and source == PROVIDER_API_DIRECT:

        configured = settings.is_api_direct_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "YouTube 数据源：API Direct（API_DIRECT_API_KEY 已配置）"

                if configured

                else "YouTube 数据源：API Direct，但未配置 API_DIRECT_API_KEY"

            ),

            endpoints=cap.endpoints,

        )



    if platform == "tiktok" and source == PROVIDER_API_DIRECT:

        configured = settings.is_api_direct_configured

        return PlatformCapability(

            platform=cap.platform,

            label=cap.label,

            status="supported" if configured else "not_configured",

            message=(

                "TikTok 数据源：API Direct（API_DIRECT_API_KEY 已配置）"

                if configured

                else "TikTok 数据源：API Direct，但未配置 API_DIRECT_API_KEY"

            ),

            endpoints=cap.endpoints,

        )



    return cap

