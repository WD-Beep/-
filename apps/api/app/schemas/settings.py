# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：settings
from pydantic import BaseModel, Field



from app.schemas.ai import AiStatusResponse

from app.schemas.email import KlaviyoStatus, MailchimpStatus, SmtpStatus
from app.schemas.email_reply import InboundEmailStatus





class IntegrationStatus(BaseModel):

    configured: bool

    message: str





class CollectorStatus(BaseModel):

    mode: str

    message: str





class CollectionConfigStatus(BaseModel):

    collector_mode: str

    instagram_data_provider: str

    youtube_data_provider: str

    tiktok_data_provider: str = ""

    facebook_data_provider: str = ""

    apify_configured: bool

    api_direct_configured: bool

    instagram_collector_configured: bool

    facebook_collector_configured: bool = False

    instagram_message: str

    facebook_message: str = ""





class SettingsStatusResponse(BaseModel):

    smtp: SmtpStatus

    mailchimp: MailchimpStatus

    klaviyo: KlaviyoStatus

    inbound_email: InboundEmailStatus

    ai: AiStatusResponse

    apify: IntegrationStatus

    api_direct: IntegrationStatus

    collection: CollectionConfigStatus

    collector: CollectorStatus

