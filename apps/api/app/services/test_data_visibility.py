from sqlalchemy import String, and_, cast, func, not_, or_

from app.models.email_log import EmailLog
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer


SIMULATED_TEXT_PATTERNS = (
    "%example.com%",
    "%company.com%",
    "%test@example.com%",
    "%acceptance%",
    "%mock%",
    "%demo%",
)

SIMULATED_HANDLE_PATTERNS = (
    "mock%",
    "%mock_%",
    "reply_%",
    "reply\\_%",  # kept for SQL dialects that honor escapes in LIKE patterns
    "shared_%",
    "black_%",
    "camp_%",
    "scope_%",
    "route_%",
    "%acceptance%",
)


def _lower_text(column):
    return func.lower(func.coalesce(cast(column, String), ""))


def _none_match(columns, patterns):
    checks = []
    for column in columns:
        lowered = _lower_text(column)
        checks.extend(lowered.ilike(pattern) for pattern in patterns)
    return not_(or_(*checks))


def business_influencer_filter(
    *,
    PI=ProductInfluencer,
    GP=GlobalInfluencerProfile,
):
    return and_(
        _none_match(
            (
                GP.username,
                GP.display_name,
                GP.profile_url,
                PI.owner,
                PI.note,
            ),
            SIMULATED_TEXT_PATTERNS,
        ),
        _none_match(
            (
                GP.username,
                GP.display_name,
                GP.profile_url,
            ),
            SIMULATED_HANDLE_PATTERNS,
        ),
    )


def business_email_log_filter(*, EL=EmailLog):
    return and_(
        _none_match(
            (
                EL.sender_email,
                EL.influencer_username,
                EL.recipients,
                EL.subject,
                EL.body,
                EL.error_message,
                EL.reply_summary,
                EL.message_id,
            ),
            SIMULATED_TEXT_PATTERNS,
        ),
        _none_match(
            (
                EL.influencer_username,
                EL.subject,
                EL.body,
                EL.message_id,
            ),
            SIMULATED_HANDLE_PATTERNS,
        ),
    )
