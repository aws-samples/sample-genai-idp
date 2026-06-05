# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Integration-test fixtures.

The package-level ``tests/conftest.py`` injects sentinel AWS credentials
(``AWS_ACCESS_KEY_ID=testing`` etc.) via ``os.environ.setdefault`` so that unit
tests using moto don't accidentally hit AWS. Integration tests, however, need
REAL credentials. This module reconciles the two:

  * If only the sentinel ``testing`` credentials are present (i.e. no real
    credentials were exported and there's no shared credentials profile), the
    whole integration session is skipped with a clear message.
  * If real credentials are available, any leftover sentinel
    ``AWS_SESSION_TOKEN`` / ``AWS_SECURITY_TOKEN`` is cleared so it isn't
    SigV4-signed into the request (a stale ``testing`` token yields HTTP 401).

This runs at collection time for the integration directory only, so unit-test
behavior is unchanged.
"""

import os

import boto3
import pytest

_SENTINEL = "testing"


def _resolve_real_credentials():
    """Return a frozen botocore credentials object, or None if only sentinels."""
    # If the env still holds the sentinel access key, prefer the shared
    # credentials file / profile by temporarily ignoring the env sentinels.
    env_key = os.environ.get("AWS_ACCESS_KEY_ID")
    env_token = os.environ.get("AWS_SESSION_TOKEN")

    saved = {}
    if env_key == _SENTINEL:
        # Hide sentinel env vars so boto3 falls back to the profile/role chain.
        for var in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_SECURITY_TOKEN",
        ):
            saved[var] = os.environ.pop(var, None)
    elif env_token == _SENTINEL:
        # Real key but a leftover sentinel session token — drop the token.
        saved["AWS_SESSION_TOKEN"] = os.environ.pop("AWS_SESSION_TOKEN", None)
        saved["AWS_SECURITY_TOKEN"] = os.environ.pop("AWS_SECURITY_TOKEN", None)

    try:
        creds = boto3.Session().get_credentials()
        frozen = creds.get_frozen_credentials() if creds else None
    except Exception:
        frozen = None

    if frozen is None or frozen.access_key in (None, _SENTINEL):
        # No real credentials — restore env and signal skip.
        for var, val in saved.items():
            if val is not None:
                os.environ[var] = val
        return None

    # Real credentials resolved. If we hid sentinel env vars, leave them hidden
    # so downstream signing uses the real chain. If we dropped a sentinel
    # session token next to a real key, leaving it dropped is correct.
    return frozen


@pytest.fixture(scope="session", autouse=True)
def _require_real_aws_credentials():
    """Skip the integration session unless real AWS credentials are available."""
    frozen = _resolve_real_credentials()
    if frozen is None:
        pytest.skip(
            "Integration tests require real AWS credentials. Configure a profile "
            "or export AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (and "
            "AWS_SESSION_TOKEN if using temporary creds).",
            allow_module_level=False,
        )
    yield
