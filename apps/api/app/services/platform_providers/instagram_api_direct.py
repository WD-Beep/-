# 文件说明：后端平台采集服务，负责不同平台的数据获取和标准化；当前文件：instagram api direct
"""Instagram API Direct 平台 provider（复用现有实现，不破坏原流程）。"""

from __future__ import annotations

from app.core.config import settings
from app.services.platform_types import PlatformCapability, PlatformDiscoveryResult

ENDPOINTS = [
    "/v1/instagram/posts",
    "/v1/instagram/users",
    "/v1/instagram/user",
    "/v1/instagram/user/posts",
    "/v1/instagram/post",
]


class InstagramApiDirectProvider:
    platform = "instagram"

    @staticmethod
    def capability() -> PlatformCapability:
        configured = settings.is_api_direct_configured
        if configured:
            return PlatformCapability(
                platform="instagram",
                label="Instagram",
                status="supported",
                message="API Direct 已支持",
                endpoints=ENDPOINTS,
            )
        return PlatformCapability(
            platform="instagram",
            label="Instagram",
            status="not_configured",
            message="API Direct 暂未配置（缺少 API_DIRECT_API_KEY）",
            endpoints=ENDPOINTS,
        )

    @staticmethod
    def uses_existing_pipeline() -> bool:
        return True

    @staticmethod
    async def discover(*args, **kwargs) -> PlatformDiscoveryResult:
        raise RuntimeError("Instagram 采集应走 InstagramCollectionPipeline，不应调用此 discover")
