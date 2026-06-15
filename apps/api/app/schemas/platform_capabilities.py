from pydantic import BaseModel, Field


class PlatformCapabilityRead(BaseModel):
    platform: str
    label: str
    status: str
    message: str
    endpoints: list[str] = Field(default_factory=list)
    keyword_discovery: bool = False
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
