from app.schemas.influencer import InfluencerRead


def test_influencer_read_accepts_empty_business_email_string():
    row = {
        "id": 1,
        "platform": "instagram",
        "username": "demo",
        "profile_url": "https://www.instagram.com/demo/",
        "business_email": "",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    model = InfluencerRead.model_validate(row)
    assert model.business_email is None
