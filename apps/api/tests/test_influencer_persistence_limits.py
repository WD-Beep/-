from datetime import UTC, datetime

from app.collectors.base import CollectedInfluencer
from app.models.product_influencer import ProductInfluencer
from app.services.influencer_persistence import (
    apply_product_influencer_data,
    create_global_profile_from_collected,
)


def test_global_profile_shortens_db_limited_url_fields_before_persisting():
    long_url = "https://cdn.example.com/" + ("a" * 1400)
    item = CollectedInfluencer(
        platform="instagram",
        username="longurl",
        profile_url="https://www.instagram.com/longurl/",
        avatar_url=long_url,
        website=long_url,
        contact_page=long_url,
        linktree_url=long_url,
        whatsapp=long_url,
    )

    profile = create_global_profile_from_collected(item, run_at=datetime.now(UTC))

    assert len(profile.avatar_url or "") == 1024
    assert len(profile.website or "") == 1024
    assert len(profile.contact_page or "") == 1024
    assert len(profile.linktree_url or "") == 1024
    assert len(profile.whatsapp or "") == 1024


def test_product_influencer_shortens_source_url_fields_before_persisting():
    long_url = "https://example.com/post/" + ("b" * 900)
    item = CollectedInfluencer(
        platform="instagram",
        username="sourceurl",
        profile_url="https://www.instagram.com/sourceurl/",
        source_post_url=long_url,
        source_comment_url=long_url,
        source_discovery_type="external_seed_discovery_with_unexpected_extra_suffix",
    )
    record = ProductInfluencer(product_id=1, global_influencer_id=1)

    apply_product_influencer_data(record, item, None, run_at=datetime.now(UTC))

    assert len(record.source_post_url or "") == 512
    assert len(record.source_comment_url or "") == 512
    assert len(record.source_discovery_type or "") == 32
