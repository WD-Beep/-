from pydantic import BaseModel, Field


class PlatformCapabilityRead(BaseModel):
    platform: str
    label: str
    status: str
    message: str
    endpoints: list[str] = Field(default_factory=list)


class PlatformCapabilitiesResponse(BaseModel):
    items: list[PlatformCapabilityRead]
    api_direct_configured: bool
    apify_configured: bool
    instagram_data_provider: str
    youtube_data_provider: str
    tiktok_data_provider: str = ""
    facebook_data_provider: str = ""
