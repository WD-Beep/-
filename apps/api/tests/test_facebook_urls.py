"""Facebook 主页 URL 解析测试（命名页 / profile.php / people / p 形态）。"""

from app.services.platform_providers.facebook_api_direct import (
    _is_supported_page_url,
    _username_from_page_url,
)


def test_named_page_url():
    assert _username_from_page_url("https://www.facebook.com/Starbucks") == "Starbucks"
    # 命名页带数字后缀（vanity-id）整体作为 username
    assert (
        _username_from_page_url("https://www.facebook.com/Starbucks-279954405993629")
        == "Starbucks-279954405993629"
    )


def test_profile_php_uses_numeric_id():
    # 旧行为：profile.php 被当保留字丢弃；新行为：提取 id 作为 username
    assert (
        _username_from_page_url("https://www.facebook.com/profile.php?id=100064357492464")
        == "100064357492464"
    )
    assert (
        _username_from_page_url("https://www.facebook.com/profile.php?sk=about&id=123")
        == "123"
    )


def test_people_url_uses_trailing_id():
    # /people/<名>/<id> —— 旧行为丢弃，新行为取末段数字 id
    assert (
        _username_from_page_url("https://www.facebook.com/people/Starbucks/100064357492464")
        == "100064357492464"
    )
    # pfbid token 也保留而非丢弃
    assert (
        _username_from_page_url("https://www.facebook.com/people/Some-Name/pfbid0AbcDef123")
        == "pfbid0AbcDef123"
    )


def test_p_url_keeps_slug_not_literal_p():
    # 旧行为：username 被解析成 "p"；新行为：取 /p/ 后的真实 slug
    assert (
        _username_from_page_url("https://www.facebook.com/p/Starbucks-100064695036541")
        == "Starbucks-100064695036541"
    )


def test_reserved_and_bare_urls_rejected():
    assert _username_from_page_url("https://www.facebook.com") is None
    assert _username_from_page_url("https://www.facebook.com/watch") is None
    assert _username_from_page_url("https://www.facebook.com/groups/123") is None
    assert _username_from_page_url("https://www.facebook.com/reel/123") is None
    # /people/ 或 profile.php 无法取出 id 时仍丢弃
    assert _username_from_page_url("https://www.facebook.com/people/") is None
    assert _username_from_page_url("https://www.facebook.com/profile.php") is None


def test_is_supported_matches_username_extraction():
    assert _is_supported_page_url("https://www.facebook.com/profile.php?id=123") is True
    assert _is_supported_page_url("https://www.facebook.com/people/X/100064357492464") is True
    assert _is_supported_page_url("https://www.facebook.com/p/Brand-12345") is True
    assert _is_supported_page_url("https://www.facebook.com/watch") is False
