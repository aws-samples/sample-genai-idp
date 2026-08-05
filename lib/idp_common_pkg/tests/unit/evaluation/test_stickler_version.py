# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Regression test for stickler_version.

R18: the module previously hardcoded ``STICKLER_VERSION = "0.5.0"`` while the
resolved environment could ship a different version (the repo's ``.venv`` had
drifted to 0.4.0 against a 0.5.0 pin). The value now comes from
``importlib.metadata.version("stickler-eval")``; this test asserts the two
agree so env drift or pin/constant drift fails loudly.
"""

from importlib.metadata import version

import pytest

from idp_common.evaluation.stickler_version import (
    STICKLER_INSTALLATION,
    STICKLER_VERSION,
    get_stickler_version_info,
)


@pytest.mark.unit
def test_stickler_version_matches_installed_distribution():
    """The exposed constant must be whatever pip actually installed."""
    assert STICKLER_VERSION == version("stickler-eval")


@pytest.mark.unit
def test_stickler_installation_string_matches_version():
    """``STICKLER_INSTALLATION`` is derived — no way for it to drift."""
    assert STICKLER_INSTALLATION == f"stickler-eval=={STICKLER_VERSION}"


@pytest.mark.unit
def test_get_stickler_version_info_returns_derived_fields():
    info = get_stickler_version_info()
    assert info["version"] == STICKLER_VERSION
    assert info["installation"] == STICKLER_INSTALLATION
    assert info["repository"].startswith("https://")
