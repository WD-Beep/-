# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：settings
from fastapi import APIRouter

from app.core.config import settings
from app.schemas.ai import AiStatusResponse
from app.schemas.email import KlaviyoStatus, MailchimpStatus
from app.schemas.email_reply import InboundEmailStatus
from app.schemas.settings import (
    CollectionConfigStatus,
    CollectorStatus,
    IntegrationStatus,
    SettingsStatusResponse,
)
from app.services.collection_sources import facebook_collector_status, platform_data_source_label
from app.services.email import EmailService

router = APIRouter(prefix="/settings", tags=["settings"])

COLLECTOR_MESSAGES = {
    "apify": "采集器模式 Apify：Instagram / YouTube / TikTok / Facebook 优先走 Apify。",
    "mock": "Mock 采集器已关闭，请配置 Apify 或 API Direct。",
    "auto": "自动使用已配置的 Instagram / YouTube / TikTok / Facebook 数据源采集。",
}


@router.get("/status", response_model=SettingsStatusResponse)
async def get_settings_status() -> SettingsStatusResponse:
    mode = settings.collector_mode.lower()
    if mode not in ("api_direct", "apify", "auto"):
        mode = "api_direct"

    ig_provider = settings.active_instagram_provider
    ig_configured = settings.is_instagram_collector_configured
    if ig_provider == "apify":
        ig_message = (
            f"Instagram 数据源：Apify（{platform_data_source_label('instagram')}，APIFY_TOKEN 已配置）"
            if ig_configured
            else "Instagram 数据源：Apify，但未配置 APIFY_TOKEN"
        )
    elif ig_provider == "api_direct":
        ig_message = (
            "Instagram 数据源：API Direct（API_DIRECT_API_KEY 已配置）"
            if ig_configured
            else "Instagram 数据源：API Direct，但未配置 API_DIRECT_API_KEY"
        )
    else:
        ig_message = (
            f"Instagram 数据源：{ig_provider}（已就绪）"
            if ig_configured
            else f"Instagram 数据源：{ig_provider}（未配置完整）"
        )

    apify_message = (
        "Apify Token 已配置，可用于 Instagram / YouTube / TikTok / Facebook 采集。"
        if settings.is_apify_configured
        else "未配置 APIFY_TOKEN，Instagram / YouTube / TikTok / Facebook（Apify 模式）将不可用。"
    )
    api_direct_message = (
        "API Direct 密钥已配置，可用于 Instagram / TikTok / Facebook 的 API Direct 模式；YouTube 不使用 API Direct。"
        if settings.is_api_direct_configured
        else "未配置 API_DIRECT_API_KEY；Facebook 默认走 Apify（FACEBOOK_DATA_PROVIDER=apify + APIFY_TOKEN），无需 API Direct。"
    )

    fb_configured, fb_message = facebook_collector_status()

    return SettingsStatusResponse(
        smtp=EmailService.get_smtp_status(),
        mailchimp=MailchimpStatus(**settings.get_mailchimp_status()),
        klaviyo=KlaviyoStatus(**settings.get_klaviyo_status()),
        inbound_email=InboundEmailStatus(**settings.get_inbound_email_status()),
        ai=AiStatusResponse(
            provider=settings.active_ai_provider,
            model=settings.active_ai_model,
            configured=settings.is_openai_configured,
            mode=settings.ai_mode,
        ),
        apify=IntegrationStatus(
            configured=settings.is_apify_configured,
            message=apify_message,
        ),
        api_direct=IntegrationStatus(
            configured=settings.is_api_direct_configured,
            message=api_direct_message,
        ),
        collection=CollectionConfigStatus(
            collector_mode=mode,
            instagram_data_provider=ig_provider,
            youtube_data_provider=settings.active_youtube_provider,
            tiktok_data_provider=settings.active_tiktok_provider,
            facebook_data_provider=settings.active_facebook_provider,
            apify_configured=settings.is_apify_configured,
            api_direct_configured=settings.is_api_direct_configured,
            instagram_collector_configured=ig_configured,
            facebook_collector_configured=fb_configured,
            instagram_message=ig_message,
            facebook_message=fb_message,
        ),
        collector=CollectorStatus(
            mode=mode,
            message=COLLECTOR_MESSAGES.get(mode, "当前支持 Instagram / YouTube / TikTok / Facebook 等平台采集。"),
        ),
    )
