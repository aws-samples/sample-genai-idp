# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for Feature Platform catalog.json generation in IDPPublisher.

Covers the pure (no-AWS) catalog logic:
- merging OSS bundled-feature entries with the curated extensions-marketplace.yaml
- de-duplication (OSS wins over a same-id marketplace entry)
- malformed marketplace entries are skipped, not fatal
- missing marketplace file → OSS-only catalog
"""

from __future__ import annotations

import json
import os

import pytest
from idp_sdk._core.publish import IDPPublisher


@pytest.fixture
def publisher_in_tmp(tmp_path, monkeypatch):
    """An IDPPublisher rooted in a temp dir with a config_library/ subdir."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("config_library", exist_ok=True)
    pub = IDPPublisher(verbose=False)
    return pub, tmp_path


def _write_marketplace(tmp_path, body: str):
    (tmp_path / "config_library" / "extensions-marketplace.yaml").write_text(
        body, encoding="utf-8"
    )


def _read_catalog(tmp_path):
    return json.loads(
        (tmp_path / "config_library" / "catalog.json").read_text(encoding="utf-8")
    )


def test_oss_only_when_no_marketplace_file(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    oss = [
        {
            "featureId": "docs-by-status",
            "displayName": "Docs By Status",
            "description": "",
            "iconUrl": "",
            "source": "oss",
            "latestVersion": "1.0.2",
        }
    ]
    catalog = pub.write_catalog_file(oss)
    assert catalog["schemaVersion"] == "1.0"
    assert [f["featureId"] for f in catalog["features"]] == ["docs-by-status"]
    # Written to disk too.
    on_disk = _read_catalog(tmp_path)
    assert on_disk == catalog


def test_merges_marketplace_and_oss_sorted(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_marketplace(
        tmp_path,
        """
schemaVersion: "1.0"
features:
  - featureId: idp-monitor
    displayName: "IDP Monitor"
    productCode: "prod-xyz"
    marketplaceListingUrl: "https://aws.amazon.com/marketplace/pp/x"
    sellerBucket: "seller-prod"
    sellerBucketRegion: "us-east-1"
    latestVersion: "0.1.4"
    templateKey: "features/idp-monitor/v0.1.4/template.yaml"
""",
    )
    oss = [
        {
            "featureId": "docs-by-status",
            "displayName": "Zzz Docs",
            "description": "",
            "iconUrl": "",
            "source": "oss",
            "latestVersion": "1.0.2",
        }
    ]
    catalog = pub.write_catalog_file(oss)
    # Sorted by displayName: "IDP Monitor" < "Zzz Docs".
    assert [f["featureId"] for f in catalog["features"]] == [
        "idp-monitor",
        "docs-by-status",
    ]
    mp = catalog["features"][0]
    assert mp["source"] == "marketplace"
    assert mp["productCode"] == "prod-xyz"
    assert mp["sellerBucket"] == "seller-prod"


def test_oss_wins_over_same_id_marketplace_entry(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_marketplace(
        tmp_path,
        """
features:
  - featureId: dup
    displayName: "Marketplace Dup"
    productCode: "p"
    sellerBucket: "b"
    latestVersion: "9.9.9"
    templateKey: "k"
""",
    )
    oss = [
        {
            "featureId": "dup",
            "displayName": "OSS Dup",
            "description": "",
            "iconUrl": "",
            "source": "oss",
            "latestVersion": "1.0.0",
        }
    ]
    catalog = pub.write_catalog_file(oss)
    assert len(catalog["features"]) == 1
    assert catalog["features"][0]["source"] == "oss"
    assert catalog["features"][0]["latestVersion"] == "1.0.0"


def test_skips_malformed_marketplace_entries(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_marketplace(
        tmp_path,
        """
features:
  - displayName: "No featureId"      # dropped
  - "not even a mapping"             # dropped
  - featureId: good
    displayName: "Good"
    productCode: "p"
    sellerBucket: "b"
    latestVersion: "1.0.0"
    templateKey: "k"
""",
    )
    catalog = pub.write_catalog_file([])
    assert [f["featureId"] for f in catalog["features"]] == ["good"]


def test_empty_marketplace_list(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_marketplace(tmp_path, 'schemaVersion: "1.0"\nfeatures: []\n')
    catalog = pub.write_catalog_file([])
    assert catalog["features"] == []


# ---------------------------------------------------------------------------
# extensions-oss.yaml parsing (which OSS feature dirs to bundle).
# ---------------------------------------------------------------------------


def _write_oss(tmp_path, body: str):
    (tmp_path / "config_library" / "extensions-oss.yaml").write_text(
        body, encoding="utf-8"
    )


def test_oss_features_file_parsed(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_oss(
        tmp_path,
        """
schemaVersion: "1.0"
features:
  - path: feature-platform/sample-feature
  - path: feature-platform/another
""",
    )
    assert pub._bundled_feature_dirs() == [
        "feature-platform/sample-feature",
        "feature-platform/another",
    ]


def test_oss_features_missing_file_uses_default(publisher_in_tmp):
    pub, _ = publisher_in_tmp
    assert pub._bundled_feature_dirs() == pub._DEFAULT_BUNDLED_FEATURE_DIRS


def test_oss_features_entry_without_path_is_fatal(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    _write_oss(tmp_path, "features:\n  - notpath: x\n")
    with pytest.raises(SystemExit):
        pub._bundled_feature_dirs()
