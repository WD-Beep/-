# 文件说明：后端平台采集服务，负责不同平台的数据获取和标准化；当前文件：init
from app.services.platform_providers.facebook_api_direct import FacebookApiDirectProvider
from app.services.platform_providers.facebook_apify import FacebookApifyProvider
from app.services.platform_providers.instagram_api_direct import InstagramApiDirectProvider
from app.services.platform_providers.tiktok_api_direct import TikTokApiDirectProvider
from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider

__all__ = [
    "FacebookApiDirectProvider",
    "FacebookApifyProvider",
    "InstagramApiDirectProvider",
    "TikTokApiDirectProvider",
    "YouTubeApiDirectProvider",
]
