import pytest
from reven.domain import TargetChannel, parse_target_channels


def test_empty_channels_default_to_blog_and_wechat() -> None:
    result = parse_target_channels([])
    assert result.channels == frozenset({TargetChannel.BLOG, TargetChannel.WECHAT})
    assert result.used_default is True


def test_unsupported_channel_is_explicit() -> None:
    result = parse_target_channels(["个人博客", "掘金"])
    assert result.channels == frozenset({TargetChannel.BLOG})
    assert result.unsupported == ("掘金",)


@pytest.mark.parametrize("raw", [["微信公众号"], ["个人博客", "微信公众号"]])
def test_supported_channels_are_preserved(raw: list[str]) -> None:
    assert parse_target_channels(raw).unsupported == ()
