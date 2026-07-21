# 文件说明：后端核心配置和通用异常处理；当前文件：config
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
    smtp_from_name: str = ""
    outreach_daily_send_limit: int = 50
    smtp_test_recipient: str = ""
    smtp_test_schedule_enabled: bool = False
    smtp_test_interval_minutes: int = 1440
    # Optional SOCKS/HTTP proxy for Gmail SMTP when direct connect is blocked.
    # Example: socks5://127.0.0.1:7890
    smtp_proxy_url: str = ""

    inbound_email_address: str = Field(
        default="",
        validation_alias=AliasChoices("INBOUND_EMAIL_ADDRESS", "IMAP_INBOX_ADDRESS"),
    )
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_folder: str = "INBOX"
    imap_poll_enabled: bool = False
    imap_poll_interval_minutes: int = 5
    email_inbound_webhook_secret: str = ""

    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    openai_api_base: str = "https://code.codingplay.top"

    scandihome_pdf_path: str = r"C:\Users\Administrator\Desktop\ScandiHome_视觉手册_v1_2.pdf"
    scandihome_pptx_path: str = r"C:\Users\Administrator\Desktop\ScandiHome 2026 视觉升级 PPT新.pptx"

    collector_mode: str = "api_direct"
    instagram_data_provider: str = "api_direct"
    youtube_data_provider: str = "api_direct"
    tiktok_data_provider: str = "api_direct"
    facebook_data_provider: str = "api_direct"

    youtube_api_key: str = ""
    youtube_official_timeout_seconds: int = 30
    youtube_official_max_retries: int = 2
    youtube_official_retry_backoff_seconds: float = 2.0
    youtube_official_search_max_pages: int = 1
    youtube_official_max_results_per_keyword: int = 25
    api_direct_api_key: str = ""
    api_direct_api_base: str = "https://apidirect.io"
    api_direct_timeout_seconds: int = 30
    api_direct_max_retries: int = 2
    api_direct_retry_backoff_seconds: float = 1.5
    api_direct_max_requests_per_platform: int = 20
    api_direct_min_interval_seconds: float = 0.35
    api_direct_rate_limit_cooldown_seconds: float = 5.0
    collection_search_concurrency: int = 4
    collection_profile_concurrency: int = 8
    collection_profile_enrich_concurrency: int = 3
    collection_profile_request_timeout_seconds: int = 20
    collection_max_running_tasks: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "COLLECTION_MAX_CONCURRENCY",
            "COLLECTION_MAX_RUNNING_TASKS",
            "collection_max_concurrency",
            "collection_max_running_tasks",
        ),
    )
    collection_max_concurrency_per_user: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "COLLECTION_MAX_CONCURRENCY_PER_USER",
            "collection_max_concurrency_per_user",
        ),
    )
    collection_max_concurrency_per_platform: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "COLLECTION_MAX_CONCURRENCY_PER_PLATFORM",
            "collection_max_concurrency_per_platform",
        ),
    )
    collection_worker_count: int = Field(
        default=4,
        validation_alias=AliasChoices(
            "COLLECTION_WORKER_COUNT",
            "collection_worker_count",
        ),
    )
    collection_api_embedded_worker_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "COLLECTION_API_EMBEDDED_WORKER_ENABLED",
            "collection_api_embedded_worker_enabled",
        ),
    )
    collection_worker_poll_interval_seconds: float = Field(
        default=1.0,
        validation_alias=AliasChoices(
            "COLLECTION_WORKER_POLL_INTERVAL_SECONDS",
            "collection_worker_poll_interval_seconds",
        ),
    )
    collection_heartbeat_interval_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "COLLECTION_HEARTBEAT_INTERVAL_SECONDS",
            "collection_heartbeat_interval_seconds",
        ),
    )
    collection_contact_concurrency: int = 2
    collection_ai_concurrency: int = 1
    collection_batch_commit_size: int = 20
    collection_cross_platform_instagram_enrichment_limit: int = 8
    collection_cross_platform_instagram_enrichment_timeout_seconds: int = 8
    collection_running_stale_seconds: int = Field(
        default=180,
        validation_alias=AliasChoices(
            "COLLECTION_RUNNING_STALE_SECONDS",
            "collection_running_stale_seconds",
            "collection_task_stale_after_seconds",
        ),
    )
    api_direct_max_pages_per_request: int = 1
    api_direct_tiktok_default_pages: int = 1
    apify_token: str = ""
    apify_instagram_actor_id: str = "logical_scrapers~instagram-profile-scraper"
    apify_instagram_profile_fallback_actor_id: str = "coderx~instagram-profile-scraper-api"
    apify_instagram_profile_fallback_enabled: bool = True
    apify_instagram_hashtag_actor_id: str = "apify~instagram-hashtag-scraper"
    apify_instagram_related_actor_id: str = ""
    apify_instagram_comment_actor_id: str = "apify~instagram-comment-scraper"
    apify_instagram_post_actor_id: str = "apify~instagram-post-scraper"
    apify_youtube_actor_id: str = "streamers~youtube-scraper"
    apify_youtube_email_actor_id: str = "dataovercoffee/Youtube-Channel-Business-Email-Scraper"
    apify_tiktok_actor_id: str = "clockworks~tiktok-scraper"
    apify_tiktok_scraper_actor_id: str = "clockworks/tiktok-scraper"
    apify_tiktok_profile_actor_id: str = "clockworks/tiktok-profile-scraper"
    apify_tiktok_video_actor_id: str = "clockworks/tiktok-video-scraper"
    apify_tiktok_hashtag_actor_id: str = "clockworks/tiktok-hashtag-scraper"
    apify_tiktok_fallback_actor_id: str = "clockworks/free-tiktok-scraper"
    apify_facebook_search_actor_id: str = "parseforge~facebook-search-scraper"
    apify_facebook_pages_actor_id: str = "apify/facebook-pages-scraper"
    apify_facebook_posts_actor_id: str = "apify/facebook-posts-scraper"
    apify_facebook_comments_actor_id: str = "apify/facebook-comments-scraper"
    apify_facebook_reels_actor_id: str = "apify/facebook-reels-scraper"
    apify_timeout_seconds: int = 180
    apify_youtube_timeout_seconds: int = 90
    apify_youtube_max_retries: int = 2
    apify_tiktok_timeout_seconds: int = 90
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
    facebook_apify_keyword_concurrency: int = 1
    facebook_apify_profile_concurrency: int = 1

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
    klaviyo_api_key: str = ""
    klaviyo_list_id: str = ""
    klaviyo_timeout_seconds: int = 30

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
            return self.active_ai_provider
        return "heuristic"

    @property
    def active_ai_provider(self) -> str:
        if not self.is_openai_configured:
            return "heuristic"
        base = self.openai_api_base.strip().lower()
        model = self.openai_model.strip().lower()
        if "deepseek" in base or model.startswith("deepseek"):
            return "deepseek"
        if "moonshot" in base or model.startswith("kimi"):
            return "kimi"
        return "openai"

    @property
    def ai_provider_display_name(self) -> str:
        names = {
            "deepseek": "DeepSeek",
            "kimi": "Kimi",
            "openai": "OpenAI",
            "heuristic": "规则评分",
        }
        return names.get(self.active_ai_provider, self.active_ai_provider)

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
        reachable = None
        if configured and self.smtp_host:
            import socket

            sock = socket.socket()
            sock.settimeout(3)
            try:
                sock.connect((self.smtp_host.strip(), int(self.smtp_port)))
                reachable = True
            except OSError:
                reachable = False
                host_port = f"{self.smtp_host.strip()}:{self.smtp_port}"
                unreachable_msg = (
                    f"当前网络无法连通 {host_port}，发送会失败；"
                    "请开启可访问 Google 的代理/VPN，并在 .env 设置 SMTP_PROXY_URL（如 socks5://127.0.0.1:7890），或打通 smtp.gmail.com。"
                )
                warning = f"{warning} {unreachable_msg}".strip() if warning else unreachable_msg
            finally:
                sock.close()
        if configured:
            if reachable is False:
                message = "SMTP 已配置但当前网络不可达，发送会失败。"
            else:
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
            "from_name": self.smtp_from_name.strip() or None,
            "from_user_mismatch": self.smtp_from_user_mismatch,
            "warning": warning,
            "use_tls": self.smtp_use_tls,
            "message": message,
            "outreach_daily_send_limit": self.outreach_daily_send_limit,
            "test_recipient": self.smtp_test_recipient.strip() or None,
            "test_schedule_enabled": self.smtp_test_schedule_enabled,
            "test_interval_minutes": max(1, int(self.smtp_test_interval_minutes or 1440)),
        }

    @property
    def is_imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @property
    def is_inbound_webhook_configured(self) -> bool:
        return bool(self.email_inbound_webhook_secret.strip())

    def get_inbound_email_status(self) -> dict:
        imap_configured = self.is_imap_configured
        webhook_configured = self.is_inbound_webhook_configured
        configured = imap_configured or webhook_configured
        if imap_configured and webhook_configured:
            message = "IMAP 与 inbound webhook 均已配置，可接收红人回复。"
        elif imap_configured:
            message = "IMAP 已配置，可轮询收件箱接收红人回复。"
        elif webhook_configured:
            message = "Inbound webhook 已配置，可接收邮件服务商推送的回复。"
        else:
            message = "未配置收信能力。请配置 IMAP_* 或 EMAIL_INBOUND_WEBHOOK_SECRET。"
        return {
            "configured": configured,
            "imap_configured": imap_configured,
            "webhook_configured": webhook_configured,
            "inbound_address": self.inbound_email_address.strip() or self.imap_user.strip() or None,
            "imap_host": self.imap_host or None,
            "imap_port": self.imap_port if self.imap_host else None,
            "imap_folder": self.imap_folder or None,
            "imap_poll_enabled": self.imap_poll_enabled,
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
        name = (self.instagram_data_provider or "api_direct").strip().lower()
        if name in {"scrape_creators", "apify"}:
            return "api_direct"
        return name

    @property
    def active_youtube_provider(self) -> str:
        name = (self.youtube_data_provider or "api_direct").strip().lower()
        if name in {"api_direct", "auto", "apify"}:
            return "api_direct"
        if name == "official":
            return name
        return "api_direct"

    @property
    def active_tiktok_provider(self) -> str:
        name = (self.tiktok_data_provider or "api_direct").strip().lower()
        if name == "apify":
            return "api_direct"
        return name

    @property
    def active_facebook_provider(self) -> str:
        preferred = (self.facebook_data_provider or "api_direct").strip().lower()
        if preferred == "apify":
            return "api_direct"
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

    @property
    def is_klaviyo_configured(self) -> bool:
        return bool(self.klaviyo_api_key.strip() and self.klaviyo_list_id.strip())

    def get_klaviyo_status(self) -> dict:
        configured = self.is_klaviyo_configured
        return {
            "configured": configured,
            "list_id": self.klaviyo_list_id.strip() or None,
            "message": (
                "Klaviyo configured for audience sync."
                if configured
                else "KLAVIYO_API_KEY / KLAVIYO_LIST_ID not configured."
            ),
        }


settings = Settings()
