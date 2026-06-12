"""关键词发现 API 失败判定（仅 hashtag 全失败且无候选）。"""


def _hashtag_fatal(*, hashtags: list[str], hashtag_successes: int, candidates: list) -> bool:
    return bool(hashtags) and hashtag_successes == 0 and len(candidates) == 0


def test_hashtag_all_failed_no_candidates_is_fatal():
    assert _hashtag_fatal(hashtags=["travel"], hashtag_successes=0, candidates=[])


def test_hashtag_partial_success_not_fatal():
    assert not _hashtag_fatal(hashtags=["travel", "tourism"], hashtag_successes=1, candidates=[])


def test_comment_failure_with_authors_not_fatal():
    assert not _hashtag_fatal(hashtags=["travel"], hashtag_successes=1, candidates=[object()])


if __name__ == "__main__":
    test_hashtag_all_failed_no_candidates_is_fatal()
    test_hashtag_partial_success_not_fatal()
    test_comment_failure_with_authors_not_fatal()
    print("ok")
