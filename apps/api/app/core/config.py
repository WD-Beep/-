from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG


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
    smtp_from: str = ""
    smtp_use_tls: bool = True

    openai_api_key: str = ""

    kimi_api_key: str = ""
    kimi_api_base: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2.5"

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
    collection_contact_concurrency: int = 5
    collection_ai_concurrency: int = 2
    collection_batch_commit_size: int = 20
    collection_running_stale_seconds: int = 300
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
    def is_kimi_configured(self) -> bool:
        return bool(self.kimi_api_key.strip())

    @property
    def ai_mode(self) -> str:
        return "kimi" if self.is_kimi_configured else "heuristic"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_from)

    @property
    def is_youtube_configured(self) -> bool:
        return bool(self.youtube_api_key.strip())

    @property
    def is_apify_configured(self) -> bool:
        return bool(self.apify_token.strip())

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

    def get_smtp_status(self) -> dict:
        configured = self.is_smtp_configured
        return {
            "configured": configured,
            "host": self.smtp_host or None,
            "port": self.smtp_port if self.smtp_host else None,
            "from_address": self.smtp_from or None,
            "use_tls": self.smtp_use_tls,
            "message": "SMTP configured, ready to send emails." if configured else SMTP_NOT_CONFIGURED_MSG,
        }

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
