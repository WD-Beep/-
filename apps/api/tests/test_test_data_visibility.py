from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.email_log import EmailLog
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.email_log import EmailLogService
from app.services.product_influencer_service import ProductInfluencerService
from app.services.test_data_visibility import business_email_log_filter, business_influencer_filter


def _sql(query) -> str:
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_business_influencer_filter_excludes_obvious_simulated_rows():
    query = select(ProductInfluencer, GlobalInfluencerProfile).join(
        GlobalInfluencerProfile,
        ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
    )

    sql = _sql(query.where(business_influencer_filter()))

    assert "example.com" in sql
    assert "mock" in sql
    assert "reply" in sql
    assert "shared" in sql


def test_influencer_list_applies_business_filter_by_default():
    sql = _sql(
        ProductInfluencerService._base_join(1).where(business_influencer_filter())
    )

    assert "example.com" in sql


def test_email_log_service_excludes_test_outreach_records_by_default():
    sql = _sql(EmailLogService._business_base_query())

    assert "example.com" in sql
    assert "acceptance" in sql
    assert "test" in sql
    assert _sql(select(EmailLog).where(business_email_log_filter()))
