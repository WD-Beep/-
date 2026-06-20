from pydantic import BaseModel, Field


class PlatformCapabilityRead(BaseModel):
    platform: str
    label: str
    status: str
    message: str
    endpoints: list[str] = Field(default_factory=list)
    keyword_discovery: bool = False
    native_keyword_discovery: bool = False
    external_seed_discovery: bool = False
    reverse_link_expansion: bool = False
    link_import: bool = False
    product_seed: bool = False
    link_import_hint: str | None = None
    discovery_category: str = "link_completion"
    external_link_discovery: bool = False


class PlatformCapabilitiesResponse(BaseModel):
    items: list[PlatformCapabilityRead]
    api_direct_configured: bool
    apify_configured: bool
    instagram_data_provider: str
    youtube_data_provider: str
    tiktok_data_provider: str = ""
    facebook_data_provider: str = ""
    collection_max_running_tasks: int = Field(default=2, ge=1)
    collection_profile_enrich_concurrency: int = Field(default=3, ge=1)
    collection_profile_request_timeout_seconds: int = Field(default=20, ge=5)
    collection_running_stale_seconds: int = Field(default=180, ge=30)
