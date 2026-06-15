"""候选池 read model：各状态均返回来源作品/输入链接。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models.enums import CandidateStatus
from app.schemas.collection_task import collection_task_candidate_read
from app.services.task_candidate import TaskCandidateService


POST_URL = "https://www.tiktok.com/@creator/video/999"
INPUT_URL = "https://vm.tiktok.com/input999/"


CANDIDATE_STATUSES = (
    CandidateStatus.PROFILE_FAILED,
    CandidateStatus.FILTERED_OUT,
    CandidateStatus.NOT_INSERTED,
    CandidateStatus.DUPLICATE,
    CandidateStatus.INSERTED,
)


@pytest.mark.parametrize("status", CANDIDATE_STATUSES)
def test_candidate_read_exposes_source_urls_for_all_statuses(status: CandidateStatus):
    row = SimpleNamespace(
        id=1,
        task_id=10,
        username="creator",
        profile_url="https://www.tiktok.com/@creator",
        platform="tiktok",
        source_type=None,
        source_keyword=None,
        source_hashtag=None,
        source_post_url=POST_URL,
        source_input_url=None,
        source_caption=None,
        source_comment_url=None,
        source_comment_text=None,
        source_discovery_type=None,
        source_meta={"source_input_url": INPUT_URL},
        followers_count=None,
        engagement_rate=None,
        is_high_value=None,
        has_email=None,
        has_contact=None,
        contact_status=None,
        insert_blocked_reason=None,
        profile_fetched_at=None,
        influencer_id=None,
        status=status.value,
        failure_reason=None,
        failure_detail=None,
        run_at=None,
        created_at=datetime.now(UTC),
        updated_at=None,
    )

    read = collection_task_candidate_read(row)
    assert read.source_post_url == POST_URL
    assert read.source_input_url == INPUT_URL


def test_candidate_read_prefers_column_source_input_url():
    row = SimpleNamespace(
        id=2,
        task_id=10,
        username="creator",
        profile_url="https://www.tiktok.com/@creator",
        platform="tiktok",
        source_type=None,
        source_keyword=None,
        source_hashtag=None,
        source_post_url=POST_URL,
        source_input_url=INPUT_URL,
        source_caption=None,
        source_comment_url=None,
        source_comment_text=None,
        source_discovery_type=None,
        source_meta={"source_input_url": "https://vm.tiktok.com/other/"},
        followers_count=None,
        engagement_rate=None,
        is_high_value=None,
        has_email=None,
        has_contact=None,
        contact_status=None,
        insert_blocked_reason=None,
        profile_fetched_at=None,
        influencer_id=None,
        status=CandidateStatus.INSERTED.value,
        failure_reason=None,
        failure_detail=None,
        run_at=None,
        created_at=datetime.now(UTC),
        updated_at=None,
    )

    read = collection_task_candidate_read(row)
    assert read.source_input_url == INPUT_URL


def test_row_from_not_inserted_accepts_source_input_url():
    row = TaskCandidateService.row_from_not_inserted(
        username="creator",
        profile_url="https://www.shopltk.com/explore/apieceofmyhaven",
        platform="ltk",
        failure_reason="low_value_seed",
        failure_detail="资料不足",
        source_input_url=INPUT_URL,
    )
    assert row["source_input_url"] == INPUT_URL
    assert row["failure_reason"] == "low_value_seed"
