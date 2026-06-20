from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG

SMTP_FROM_USER_MISMATCH_MSG = (
    "当前 SMTP_FROM 与 SMTP_USER 不一致，腾讯企业邮箱可能拒绝代发。"
    "请将 SMTP_USER 配置为 amazon03@ptraveldesign.com 并使用该邮箱的客户端专用密码，"
    "或将 SMTP_FROM 改为授权登录账号。"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/influencer_intel"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = Field(
        default="amazon03@ptraveldesign.com",
        validation_alias=AliasChoices("SMTP_FROM", "SMTP_FROM_EMAIL"),
    )
    smtp_use_tls: bool = True

    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    openai_api_base: str = "https://code.codingplay.top"

    scandihome_pdf_path: str = r"C:\Users\Administrator\Desktop\ScandiHome_视觉手册_v1_2.pdf"
    scandihome_pptx_path: str = r"C:\Users\Administrator\Desktop\ScandiHome 2026 视觉升级 PPT新.pptx"

    collector_mode: str = "apify"
    instagram_data_provider: str = "apify"
    youtube_data_provider: str = "apify"
    tiktok_data_provider: str = "apify"
    facebook_data_provider: str = "apify"

    youtube_api_key: str = ""
    api_direct_api_key: str = ""
    api_direct_api_base: str = "https://apidirect.io"
    api_direct_timeout_seconds: int = 30
    api_direct_max_retries: int = 2
    api_direct_retry_backoff_seconds: float = 1.5
    api_direct_max_requests_per_platform: int = 20
    collection_search_concurrency: int = 4
    collection_profile_concurrency: int = 8
    collection_profile_enrich_concurrency: int = 3
    collection_profile_request_timeout_seconds: int = 20
    collection_max_running_tasks: int = 2
    collection_contact_concurrency: int = 5
    collection_ai_concurrency: int = 2
    collection_batch_commit_size: int = 20
    collection_running_stale_seconds: int = Field(
        default=180,
        validation_alias=AliasChoices(
            "collection_running_stale_seconds",
            "collection_task_stale_after_seconds",
        ),
    )
    api_direct_max_pages_per_request: int = 1
    api_direct_tiktok_default_pages: int = 1
    apify_token: str = ""
    apify_instagram_actor_id: str = "logical_scrapers~instagram-profile-scraper"
    apify_instagram_hashtag_actor_id: str = "apify~instagram-hashtag-scraper"
    apify_instagram_related_actor_id: str = ""
    apify_instagram_comment_actor_id: str = "apify~instagram-comment-scraper"
    apify_instagram_post_actor_id: str = "apify~instagram-post-scraper"
    apify_youtube_actor_id: str = "streamers~youtube-scraper"
    apify_tiktok_actor_id: str = "clockworks~tiktok-scraper"
    apify_facebook_search_actor_id: str = "parseforge~facebook-search-scraper"
    apify_facebook_pages_actor_id: str = "apify~facebook-pages-scraper"
    apify_timeout_seconds: int = 180
    apify_youtube_timeout_seconds: int = 90
    apify_youtube_max_retries: int = 1
    apify_tiktok_timeout_seconds: int = 120
    apify_tiktok_max_retries: int = 1
    tiktok_apify_keyword_concurrency: int = 2
    tiktok_apify_memory_mbytes: int = 2048
    youtube_discovery_keyword_timeout_seconds: int = 90
    youtube_discovery_slow_threshold_seconds: int = 45
    youtube_discovery_max_duration_seconds: int = 300
    youtube_apify_keyword_concurrency: int = 2
    youtube_api_direct_keyword_concurrency: int = 2
    apify_facebook_timeout_seconds: int = 90
    apify_facebook_max_retries: int = 0
    facebook_discovery_keyword_timeout_seconds: int = 90
    facebook_apify_profile_timeout_seconds: int = 90
    facebook_discovery_slow_threshold_seconds: int = 45
    facebook_discovery_max_duration_seconds: int = 300
    facebook_apify_keyword_concurrency: int = 2
    facebook_apify_profile_concurrency: int = 2

    # Amazon competitor_product：缩短等待、限制关键词、平台/任务超时
    competitor_product_task_timeout_seconds: int = 300
    competitor_product_platform_timeout_seconds: int = 90
    competitor_product_keyword_timeout_seconds: int = 25
    competitor_product_max_search_keywords: int = 8
    competitor_product_max_hashtags: int = 6

    shopping_seed_search_provider: str = "public_web,pinterest_apify"
    shopping_seed_social_search_platforms: str = ""
    shopping_seed_public_search_engines: str = "bing,ltk,shopmy"
    shopping_seed_search_timeout_seconds: int = 12
    shopping_seed_search_max_results: int = 20
    shopping_seed_search_concurrency: int = 3
    shopping_seed_search_max_queries: int = 10
    shopping_seed_empty_query_stop_count: int = 4
    link_seed_enrich_concurrency: int = 3
    link_seed_enrich_timeout_seconds: int = 60
    platform_detail_concurrency: int = 3
    shopping_seed_task_timeout_seconds: int = 300
    apify_pinterest_search_actor_id: str = "easyapi/pinterest-search-scraper"
    apify_pinterest_search_timeout_seconds: int = 35
    apify_pinterest_search_max_retries: int = 0
    apify_pinterest_search_memory_mbytes: int = 2048
    apify_shopmy_creator_actor_id: str = "vsekar91/shopmy-creator-scraper"
    apify_shopmy_creator_timeout_seconds: int = 45
    apify_shopmy_creator_max_retries: int = 0
    apify_shopmy_creator_memory_mbytes: int = 1024
    apify_shopmy_creator_max_collections: int = 10
    apify_shopmy_creator_max_concurrency: int = 5

    hikerapi_api_key: str = ""
    hikerapi_base_url: str = "https://api.hikerapi.com"
    yepapi_api_key: str = ""
    yepapi_base_url: str = "https://api.yepapi.com"
    instagram_provider_timeout_seconds: int = 120

    @property
    def api_direct_request_timeout(self) -> int:
        return self.api_direct_timeout_seconds or self.instagram_provider_timeout_seconds

    mailchimp_api_key: str = ""
    mailchimp_server_prefix: str = ""
    mailchimp_list_id: str = ""
    mailchimp_status_if_new: str = "pending"
    mailchimp_timeout_seconds: int = 30

    contact_discovery_enabled: bool = True
    contact_discovery_max_pages: int = 5
    contact_discovery_timeout_seconds: int = 10
    contact_discovery_max_bytes: int = 512_000
    contact_discovery_user_agent: str = "InfluencerIntel/1.0 (contact-discovery)"

    def _mailchimp_server(self) -> str | None:
        prefix = self.mailchimp_server_prefix.strip()
        if prefix:
            return prefix

        api_key = self.mailchimp_api_key.strip()
        if "-" not in api_key:
            return None

        inferred = api_key.rsplit("-", 1)[-1].strip()
        return inferred or None

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def ai_mode(self) -> str:
        if self.is_openai_configured:
            return "openai"
        return "heuristic"

    @property
    def active_ai_provider(self) -> str:
        if self.is_openai_configured:
            return "openai"
        return "heuristic"

    @property
    def active_ai_model(self) -> str | None:
        if self.is_openai_configured:
            return self.openai_model.strip() or None
        return None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_from)

    @property
    def smtp_from_user_mismatch(self) -> bool:
        user = self.smtp_user.strip().lower()
        from_addr = self.smtp_from.strip().lower()
        return bool(user and from_addr and user != from_addr)

    def get_smtp_status(self) -> dict:
        configured = self.is_smtp_configured
        warning = SMTP_FROM_USER_MISMATCH_MSG if self.smtp_from_user_mismatch else None
        if configured:
            message = "SMTP configured, ready to send emails."
            if warning:
                message = f"{message} {warning}"
        else:
            message = SMTP_NOT_CONFIGURED_MSG
        return {
            "configured": configured,
            "host": self.smtp_host or None,
            "port": self.smtp_port if self.smtp_host else None,
            "user_address": self.smtp_user.strip() or None,
            "from_address": self.smtp_from or None,
            "from_user_mismatch": self.smtp_from_user_mismatch,
            "warning": warning,
            "use_tls": self.smtp_use_tls,
            "message": message,
        }

    @property
    def is_youtube_configured(self) -> bool:
        return bool(self.youtube_api_key.strip())

    @property
    def is_apify_configured(self) -> bool:
        return bool(self.apify_token.strip())

    @property
    def effective_profile_enrich_concurrency(self) -> int:
        """Instagram 主页补采并发上限（优先 enrich 配置，兼容旧 profile_concurrency）。"""
        raw = self.collection_profile_enrich_concurrency
        if raw and raw > 0:
            return max(1, raw)
        return max(1, self.collection_profile_concurrency or 1)

    @property
    def is_api_direct_configured(self) -> bool:
        return bool(self.api_direct_api_key.strip())

    @property
    def active_instagram_provider(self) -> str:
        name = (self.instagram_data_provider or "apify").strip().lower()
        if name == "scrape_creators":
            return "api_direct"
        return name

    @property
    def active_youtube_provider(self) -> str:
        return (self.youtube_data_provider or "apify").strip().lower()

    @property
    def active_tiktok_provider(self) -> str:
        return (self.tiktok_data_provider or "apify").strip().lower()

    @property
    def active_facebook_provider(self) -> str:
        preferred = (self.facebook_data_provider or "apify").strip().lower()
        if preferred == "apify":
            return "apify"
        if preferred == "api_direct":
            return self._resolve_platform_data_provider(
                preferred,
                apify_available=self.is_apify_configured,
                api_direct_available=self.is_api_direct_configured,
            )
        return preferred

    @staticmethod
    def _resolve_platform_data_provider(
        preferred: str | None,
        *,
        apify_available: bool,
        api_direct_available: bool,
    ) -> str:
        """在 Apify / API Direct 之间按配置与可用性选择实际 provider。"""
        name = (preferred or "apify").strip().lower()
        if name == "apify":
            if apify_available or not api_direct_available:
                return "apify"
            return "api_direct"
        if name == "api_direct":
            if api_direct_available:
                return "api_direct"
            if apify_available:
                return "apify"
            return "api_direct"
        return name

    @property
    def is_facebook_collector_configured(self) -> bool:
        provider = self.active_facebook_provider
        if provider == "apify":
            return self.is_apify_configured
        if provider == "api_direct":
            return self.is_api_direct_configured
        return False

    @property
    def is_instagram_collector_configured(self) -> bool:
        provider = self.active_instagram_provider
        if provider == "api_direct":
            return self.is_api_direct_configured
        if provider == "apify":
            return self.is_apify_configured
        if provider == "hikerapi":
            return bool(self.hikerapi_api_key.strip())
        if provider == "yepapi":
            return bool(self.yepapi_api_key.strip())
        return False

    @property
    def uses_mock_collector(self) -> bool:
        return self.collector_mode.lower() == "mock"

    @property
    def is_mailchimp_configured(self) -> bool:
        return bool(self.mailchimp_api_key.strip() and self.mailchimp_list_id.strip() and self._mailchimp_server())

    @property
    def mailchimp_api_base_url(self) -> str | None:
        server = self._mailchimp_server()
        if not server:
            return None
        return f"https://{server}.api.mailchimp.com/3.0"

    def get_mailchimp_status(self) -> dict:
        configured = self.is_mailchimp_configured
        return {
            "configured": configured,
            "server_prefix": self._mailchimp_server(),
            "list_id": self.mailchimp_list_id.strip() or None,
            "message": (
                "Mailchimp configured, ready for audience sync."
                if configured
                else "MAILCHIMP_API_KEY / MAILCHIMP_LIST_ID not configured."
            ),
        }


settings = Settings()
