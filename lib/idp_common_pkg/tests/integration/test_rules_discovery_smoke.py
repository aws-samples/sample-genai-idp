# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Smoke test: run RulesDiscovery with the current defaults in
base-rule-discovery.yaml against the medicare_respiratory_pa_packet.pdf
sample and assert the extracted rules pass shape validation.

This test is marked 'integration' because it actually calls Bedrock. Skip
it in CI unless AWS_REGION and Bedrock access are available; the
TestClient sets up its own session.

Run with:
    pytest -m integration lib/idp_common_pkg/tests/integration/test_rules_discovery_smoke.py -s
"""

# ruff: noqa: E402, I001

import os
from pathlib import Path

# conftest.py at lib/idp_common_pkg/tests/conftest.py sets AWS_ACCESS_KEY_ID
# and friends to "testing" for the unit suite. Integration tests need real
# IMDS-provided credentials, so strip the fakes before any boto3 client is
# created. This must run at module import time (before the idp_common imports
# below cache a client).
for _fake_env in (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SECURITY_TOKEN",
    "AWS_SESSION_TOKEN",
):
    if os.environ.get(_fake_env) == "testing":
        del os.environ[_fake_env]

import pytest  # noqa: E402
import yaml  # noqa: E402

from idp_common.config.models import IDPConfig  # noqa: E402
from idp_common.discovery.rules_discovery import RulesDiscovery  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[3].parent
DEFAULT_CFG_YAML = (
    REPO_ROOT
    / "lib"
    / "idp_common_pkg"
    / "idp_common"
    / "config"
    / "system_defaults"
    / "base-rule-discovery.yaml"
)
SAMPLE_PDF = (
    REPO_ROOT / "samples" / "rule-validation" / "medicare_respiratory_pa_packet.pdf"
)


def _load_defaults_into_config() -> IDPConfig:
    """Build an IDPConfig populated only from base-rule-discovery.yaml defaults."""
    raw = yaml.safe_load(DEFAULT_CFG_YAML.read_text())
    cfg = IDPConfig()
    # Apply each default onto the pydantic model. The YAML uses string-typed
    # numeric fields (matching the CFN schema presentation format); the
    # RuleDiscoveryConfig field validators coerce them.
    rules = raw["discovery"]["rules"]
    cfg.discovery.rules.model = rules["model"]
    cfg.discovery.rules.temperature = rules["temperature"]
    cfg.discovery.rules.top_p = rules["top_p"]
    cfg.discovery.rules.top_k = rules["top_k"]
    cfg.discovery.rules.max_tokens = rules["max_tokens"]
    cfg.discovery.rules.system_prompt = rules["system_prompt"]
    cfg.discovery.rules.task_prompt = rules["task_prompt"]
    cfg.discovery.rules.agentic.enabled = rules["agentic"]["enabled"]
    cfg.discovery.rules.agentic.review_agent = rules["agentic"]["review_agent"]
    return cfg


@pytest.mark.integration
def test_rules_discovery_with_defaults_against_medicare_sample():
    """Confirm base-rule-discovery.yaml defaults produce valid rules for a real
    medicare PA packet sample."""
    assert SAMPLE_PDF.exists(), f"Sample PDF missing: {SAMPLE_PDF}"
    cfg = _load_defaults_into_config()

    # Bypass DynamoDB config load by passing config directly. input_bucket /
    # input_prefix are required by the constructor but unused by the
    # _local path; use placeholder values.
    discovery = RulesDiscovery(
        input_bucket="placeholder",
        input_prefix=SAMPLE_PDF.name,
        region=os.environ.get("AWS_REGION", "us-east-1"),
        config=cfg,
    )

    result = discovery.discovery_rules_from_document_local(str(SAMPLE_PDF))

    assert result["status"] == "SUCCESS", f"Unexpected status: {result.get('status')}"
    rules = result["rules"]
    assert isinstance(rules, list) and len(rules) >= 1, (
        "Expected at least one rule class"
    )

    # The flat task_prompt produces a single rule_class containing all rules.
    # Validate shape via the same helper the production path uses.
    ok, err = discovery._validate_rules_response(rules)
    assert ok, f"Extracted rules failed shape validation: {err}"

    # Sanity: medicare policy manuals typically yield dozens of rules;
    # anything under 10 suggests the prompt or model defaults regressed.
    total_rules = sum(len(rc.get("rule_properties", {})) for rc in rules)
    print(
        f"\nSmoke test result: {len(rules)} rule class(es), {total_rules} total rules"
    )
    assert total_rules >= 10, (
        f"Only {total_rules} rules extracted from medicare PA packet; "
        "the default prompt/model may have regressed."
    )
