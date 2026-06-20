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


def test_influencer_read_serializes_email_sent_status_fields():
    row = {
        "id": 1,
        "platform": "instagram",
        "username": "demo",
        "profile_url": "https://www.instagram.com/demo/",
        "email_sent": True,
        "last_email_sent_at": "2026-01-01T08:00:00Z",
        "last_email_subject": "Collaboration opportunity",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    payload = InfluencerRead.model_validate(row).model_dump(mode="json")

    assert payload["email_sent"] is True
    assert payload["last_email_sent_at"] == "2026-01-01T08:00:00Z"
    assert payload["last_email_subject"] == "Collaboration opportunity"
