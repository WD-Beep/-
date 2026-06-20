"""邮件发送状态筛选与标记逻辑测试。"""

from sqlalchemy.dialects import postgresql

from app.schemas.influencer import InfluencerFilter
from app.services.email_sent_status import SUCCESS_EMAIL_STATUSES, successful_email_sent_exists
from app.services.influencer_lead import (
    AUTO_CONTACT_ON_EMAIL,
    PRESERVE_FOLLOW_ON_EMAIL,
)
from app.services.product_influencer_service import ProductInfluencerService


def test_influencer_filter_accepts_email_status():
    sent = InfluencerFilter(email_status="sent")
    unsent = InfluencerFilter(email_status="unsent")
    assert sent.email_status == "sent"
    assert unsent.email_status == "unsent"


def test_email_status_sent_filter_compiles():
    query = ProductInfluencerService._apply_filters(
        ProductInfluencerService._base_join(product_id=1),
        InfluencerFilter(email_status="sent"),
        product_id=1,
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "email_logs" in sql
    assert "product_influencer_id" in sql


def test_email_status_unsent_filter_compiles():
    query = ProductInfluencerService._apply_filters(
        ProductInfluencerService._base_join(product_id=1),
        InfluencerFilter(email_status="unsent"),
        product_id=1,
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "NOT EXISTS" in sql or "NOT (" in sql


def test_successful_email_sent_exists_only_uses_email_logs():
    from app.models.global_influencer_profile import GlobalInfluencerProfile
    from app.models.product_influencer import ProductInfluencer

    clause = successful_email_sent_exists(1, PI=ProductInfluencer, GP=GlobalInfluencerProfile)
    sql = str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "email_logs" in sql
    assert "influencer_followups" not in sql


def test_success_email_statuses_include_legacy_success_values():
    assert "sent" in SUCCESS_EMAIL_STATUSES
    assert "success" in SUCCESS_EMAIL_STATUSES
    assert "delivered" in SUCCESS_EMAIL_STATUSES
    assert "failed" not in SUCCESS_EMAIL_STATUSES
    assert "pending" not in SUCCESS_EMAIL_STATUSES


def test_preserve_follow_statuses_include_replied_and_blacklisted():
    assert "replied" in PRESERVE_FOLLOW_ON_EMAIL
    assert "blacklisted" in PRESERVE_FOLLOW_ON_EMAIL
    assert "invalid" in PRESERVE_FOLLOW_ON_EMAIL


def test_auto_contact_on_email_includes_new_and_to_contact():
    assert "new" in AUTO_CONTACT_ON_EMAIL
    assert "to_contact" in AUTO_CONTACT_ON_EMAIL
