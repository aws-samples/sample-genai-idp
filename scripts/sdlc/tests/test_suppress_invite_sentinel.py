"""Guard: the CI 'suppress Cognito invite' sentinel email stays in sync.

The sentinel lives in TWO places that must agree, or invite-suppression silently
breaks (and CI deploys start exhausting Cognito's daily email quota again):
  - SUPPRESS_INVITE_ADMIN_EMAIL in scripts/sdlc/codebuild_deployment.py (what CI
    passes as --admin-email), and
  - the SuppressAdminInvite condition in template.yaml (what the AdminUser
    resource keys off to set MessageAction=SUPPRESS).

This test fails if they drift apart, or if the value stops satisfying the
AdminEmail parameter's AllowedPattern (which would make deploys reject it).
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = _REPO_ROOT / "template.yaml"

# AdminEmail's AllowedPattern in template.yaml — the sentinel must satisfy it.
_ADMIN_EMAIL_PATTERN = r'^[\w.+-]+@([\w-]+\.)+[\w-]{2,6}$'


def test_sentinel_matches_between_harness_and_template(cbd):
    sentinel = cbd.SUPPRESS_INVITE_ADMIN_EMAIL
    template = _TEMPLATE.read_text()
    # The template's condition compares AdminEmail to the exact sentinel string.
    assert f"'{sentinel}'" in template or f'"{sentinel}"' in template, (
        f"SUPPRESS_INVITE_ADMIN_EMAIL ({sentinel!r}) not found in template.yaml's "
        "SuppressAdminInvite condition — the two have drifted; invite suppression "
        "will silently stop working."
    )


def test_sentinel_satisfies_admin_email_allowed_pattern(cbd):
    # If the sentinel doesn't match AdminEmail's AllowedPattern, CloudFormation
    # rejects the parameter and every CI deploy fails at validation.
    assert re.match(_ADMIN_EMAIL_PATTERN, cbd.SUPPRESS_INVITE_ADMIN_EMAIL)


def test_template_condition_and_resource_are_wired(cbd):
    template = _TEMPLATE.read_text()
    # The condition exists and the AdminUser resource uses it to gate MessageAction.
    assert "SuppressAdminInvite:" in template
    assert re.search(
        r"MessageAction:\s*!If\s*\[\s*SuppressAdminInvite\s*,\s*'SUPPRESS'",
        template,
    ), "AdminUser no longer gates MessageAction on the SuppressAdminInvite condition"
