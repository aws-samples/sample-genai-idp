"""Shared fixtures for idp_feature_sdk tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import boto3
import pytest
from moto import mock_aws


def _bundle_body(feature_id: str, version: str) -> str:
    """Minimum bundle content that passes bundle.validate_bundle()."""
    return dedent(f"""
        (function(){{
            window.IdpFeatures.register('{feature_id}', {{
                Component: function(){{ return null; }},
                version: '{version}',
                displayName: 'demo',
            }});
        }})();
    """).strip()


@pytest.fixture
def demo_feature_project(tmp_path: Path) -> Path:
    """A minimal on-disk feature project that passes manifest + bundle validation."""
    root = tmp_path / "demo-feature"
    root.mkdir()

    # feature.yaml
    (root / "feature.yaml").write_text(
        dedent("""
            featureId: demo-feature
            displayName: Demo Feature
            version: 1.2.3
            template:
              path: template.yaml
              requiresMainStackName: true
            ui:
              bundlePath: feature-ui/dist/ui-bundle.js
            marketplace:
              productCode: prod-demo
              listingUrl: https://aws.amazon.com/marketplace/pp/prodview-XYZ
            defaultParameters:
              LogLevel: INFO
            capabilities:
              - custom-api
        """).strip(),
        encoding="utf-8",
    )

    (root / "template.yaml").write_text(
        "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  Dummy:\n    Type: AWS::SNS::Topic\n",
        encoding="utf-8",
    )
    (root / "feature-ui" / "dist").mkdir(parents=True)
    (root / "feature-ui" / "dist" / "ui-bundle.js").write_text(
        _bundle_body("demo-feature", "1.2.3"), encoding="utf-8"
    )
    return root


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def seller_bucket(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-seller-bucket"
        s3.create_bucket(Bucket=bucket)
        yield bucket
