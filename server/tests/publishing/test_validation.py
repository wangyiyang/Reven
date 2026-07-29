from dataclasses import replace

import pytest
from reven.domain import TargetChannel
from reven.publishing.validation import PublicationCandidate, validate_candidate


@pytest.fixture
def valid_candidate() -> PublicationCandidate:
    return PublicationCandidate(
        title="标题",
        markdown="正文",
        summary="摘要",
        author="作者",
        cover=object(),
        image_count=0,
        materialized_image_count=0,
        channels=(TargetChannel.BLOG, TargetChannel.WECHAT),
        integration_status={"github": True, "wechat": True},
    )


def test_missing_cover_blocks_all_channels(valid_candidate: PublicationCandidate) -> None:
    candidate = replace(valid_candidate, cover=None)
    result = validate_candidate(candidate)
    assert result.is_valid is False
    assert result.errors[0].code == "cover_missing"


def test_validation_aggregates_all_errors() -> None:
    candidate = PublicationCandidate(
        title="",
        markdown="",
        summary="",
        author="",
        cover=None,
        image_count=2,
        materialized_image_count=1,
        channels=(),
        unsupported_channels=("未知",),
        integration_status={},
    )

    result = validate_candidate(candidate)

    assert {"title_empty", "body_empty", "cover_missing", "image_download_failed", "channel_unsupported"} <= {
        error.code for error in result.errors
    }


def test_feishu_failure_is_warning_only(valid_candidate: PublicationCandidate) -> None:
    candidate = replace(valid_candidate, feishu_error="timeout")

    result = validate_candidate(candidate)

    assert result.is_valid is True
    assert result.warnings[0].code == "feishu_unavailable"


def test_empty_channels_use_blog_and_wechat_defaults(valid_candidate: PublicationCandidate) -> None:
    candidate = replace(valid_candidate, channels=(), integration_status={"github": True, "wechat": False})

    result = validate_candidate(candidate)

    assert [error.field for error in result.errors] == ["wechat"]
