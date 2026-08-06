# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the per-agent page-image cap (oversized-request guard)."""

import pytest

from idp_common.extraction.service import ExtractionService

pytestmark = pytest.mark.unit


def _service(cap: int) -> ExtractionService:
    return ExtractionService(
        region="us-west-2",
        config={
            "extraction": {"agentic": {"enabled": True, "max_images_per_agent": cap}},
            "classes": [],
        },
    )


def _imgs(n: int) -> list[bytes]:
    return [f"img{i}".encode() for i in range(n)]


class TestCapAgentImages:
    def test_caps_when_over_limit(self):
        svc = _service(cap=20)
        out = svc._cap_agent_images(_imgs(25))
        assert len(out) == 20
        assert out == _imgs(25)[:20]  # keeps the first N, in order

    def test_no_cap_when_under_limit(self):
        svc = _service(cap=20)
        imgs = _imgs(5)
        assert svc._cap_agent_images(imgs) is imgs  # unchanged, same object

    def test_zero_means_unlimited(self):
        svc = _service(cap=0)
        imgs = _imgs(50)
        assert svc._cap_agent_images(imgs) is imgs

    def test_empty_list(self):
        svc = _service(cap=20)
        assert svc._cap_agent_images([]) == []

    def test_default_cap_is_twenty(self):
        # Config default should be 20 (the documented backstop).
        svc = ExtractionService(
            region="us-west-2",
            config={"extraction": {"agentic": {"enabled": True}}, "classes": []},
        )
        assert svc.config.extraction.agentic.max_images_per_agent == 20
        assert len(svc._cap_agent_images(_imgs(25))) == 20
