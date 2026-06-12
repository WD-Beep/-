SMTP_NOT_CONFIGURED_MSG = "邮件服务未配置，请先在环境变量中配置 SMTP。"
SMTP_AUTH_FAILED_MSG = (
    "SMTP 认证失败：请确认腾讯企业邮箱已开启 SMTP 服务，"
    "并在邮箱后台生成「客户端专用密码」后，将 SMTP_PASSWORD 更新为该授权码（不是网页登录密码）。"
)
APIFY_NOT_CONFIGURED_MSG = "未配置 APIFY_TOKEN，无法采集真实 Instagram 数据。请在 .env 中设置 COLLECTOR_MODE=apify 与 APIFY_TOKEN。"
API_DIRECT_NOT_CONFIGURED_MSG = (
    "未配置 API_DIRECT_API_KEY，无法使用 API Direct 采集。"
    "Instagram 使用 Apify 时无需配置 API Direct；TikTok/Facebook 仍需 API Direct。"
)
MOCK_COLLECTOR_DISABLED_MSG = "已关闭 Mock 采集。请配置 Apify（Instagram/YouTube）或 API Direct（TikTok/Facebook）。"
