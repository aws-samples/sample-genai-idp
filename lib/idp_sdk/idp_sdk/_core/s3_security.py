# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""S3 bucket hardening helpers for buckets created by CLI tooling.

Buckets created by CloudFormation (``template.yaml`` and the SDLC templates)
each get an ``AWS::S3::BucketPolicy`` with an ``EnforceSSLOnly`` statement.
Buckets created imperatively by the CLIs (``idp-cli publish``,
``idp-cli deploy``, ``idp-feature-cli``) need the same statement applied via
the API — that's what this module does.

The statement is the same shape as the CloudFormation one: deny ``s3:*`` for
every principal when ``aws:SecureTransport`` is false, on both the bucket ARN
and its objects.

.. note::
   ``idp_feature_sdk.pack`` carries a **duplicate** of this logic
   (``_partition`` / ``_enforce_ssl_statement`` / ``_statement_list`` /
   ``apply_enforce_ssl_only``) because that module is deliberately
   self-contained — boto3 only, no ``idp_sdk`` dependency. Fix both copies
   together; a bug fixed in only one has already happened once.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import boto3

logger = logging.getLogger(__name__)

ENFORCE_SSL_SID = "EnforceSSLOnly"


def get_partition(region: Optional[str]) -> str:
    """Return the ARN partition for ``region`` (``aws``, ``aws-us-gov``, …).

    Mirrors the ``arn:${AWS::Partition}:`` convention the templates use so
    GovCloud deploys build correct ARNs.
    """
    if not region:
        return "aws"
    try:
        return boto3.Session().get_partition_for_region(region)
    except Exception:
        # Older botocore, or a region name it doesn't know. Fall back to the
        # documented prefixes rather than silently emitting a wrong partition.
        if region.startswith("us-gov-"):
            return "aws-us-gov"
        if region.startswith("cn-"):
            return "aws-cn"
        return "aws"


def enforce_ssl_only_statement(bucket: str, region: Optional[str] = None) -> Dict:
    """Build the ``EnforceSSLOnly`` bucket-policy statement for ``bucket``."""
    partition = get_partition(region)
    bucket_arn = f"arn:{partition}:s3:::{bucket}"
    return {
        "Sid": ENFORCE_SSL_SID,
        "Effect": "Deny",
        "Principal": "*",
        "Action": "s3:*",
        "Resource": [bucket_arn, f"{bucket_arn}/*"],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
    }


def enforce_ssl_only_policy(bucket: str, region: Optional[str] = None) -> Dict:
    """Build a complete bucket policy document containing only ``EnforceSSLOnly``."""
    return {
        "Version": "2012-10-17",
        "Statement": [enforce_ssl_only_statement(bucket, region)],
    }


def statement_list(policy: Optional[Dict]) -> list:
    """Return ``policy``'s statements as a list, whatever form they took.

    The IAM grammar allows ``Statement`` to be **either** a single statement
    object **or** an array of them ("The Statement element can contain a single
    statement or an array of individual statements" —
    https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_statement.html).
    Iterating the single-object form directly would yield its *keys*, silently
    replacing an operator's statement with the strings ``"Sid"``, ``"Effect"``,
    … — so normalize before touching it.
    """
    if not policy:
        return []
    raw = policy.get("Statement", [])
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return list(raw)
    # A malformed Statement (string, None, …). Don't guess at its meaning and
    # don't drop it silently — refuse, so the caller reports rather than
    # writing a policy that discards whatever was there.
    raise ValueError(
        f"Unsupported S3 bucket-policy Statement type {type(raw).__name__!r}: "
        f"expected an object or a list of objects."
    )


def merge_enforce_ssl_only(existing: Optional[Dict], bucket: str, region: str) -> Dict:
    """Return ``existing`` with a fresh ``EnforceSSLOnly`` statement.

    Any statement already carrying that Sid is replaced (so re-running is
    idempotent and picks up ARN fixes); every other statement is preserved
    verbatim, so this never removes an operator's own grants. Handles both
    forms the IAM grammar allows for ``Statement`` — see :func:`statement_list`.
    """
    desired = enforce_ssl_only_statement(bucket, region)
    if not existing:
        return {"Version": "2012-10-17", "Statement": [desired]}
    statements = [
        s
        for s in statement_list(existing)
        if not (isinstance(s, dict) and s.get("Sid") == ENFORCE_SSL_SID)
    ]
    statements.append(desired)
    return {"Version": existing.get("Version", "2012-10-17"), "Statement": statements}


def apply_enforce_ssl_only(
    s3_client: Any,
    bucket: str,
    region: str,
    *,
    raise_on_error: bool = True,
) -> bool:
    """Add (or refresh) the ``EnforceSSLOnly`` statement on ``bucket``.

    Strictly additive hardening: existing statements are preserved, so this is
    safe to run against a bucket an operator manages (unlike Block Public
    Access, which we never touch on a pre-existing bucket because relaxing it
    could revert a manual remediation).

    Returns True if the policy is in place. With ``raise_on_error=False`` a
    failure is logged and False returned — used for pre-existing buckets, where
    the caller may not own the bucket policy.
    """
    try:
        try:
            existing = json.loads(s3_client.get_bucket_policy(Bucket=bucket)["Policy"])
        except Exception as exc:
            if "NoSuchBucketPolicy" not in str(exc):
                raise
            existing = None

        merged = merge_enforce_ssl_only(existing, bucket, region)
        if merged != existing:
            s3_client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(merged))
        return True
    except Exception as exc:
        message = (
            f"Could not apply the {ENFORCE_SSL_SID} bucket policy to {bucket!r}: {exc}. "
            f"This policy denies any non-TLS request to the bucket; add it manually "
            f"if your account restricts s3:PutBucketPolicy."
        )
        if raise_on_error:
            raise RuntimeError(message) from exc
        logger.warning(message)
        return False
