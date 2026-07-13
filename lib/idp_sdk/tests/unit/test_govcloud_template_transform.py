# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the GovCloud CloudFormation template transformer.

The GovCloud transform must remove every ``AWS::CloudFront::*`` resource (those
types do not exist in GovCloud and produce ``E3006 Resource type
'AWS::CloudFront::Distribution' does not exist in 'us-gov-west-1'`` errors), and
must leave NO dangling reference to a removed CloudFront resource or the removed
``UseCloudFrontHosting`` condition. It must also force ``WebUIHosting=APIGateway``
while keeping the rest of the UI intact.
"""

from pathlib import Path

import pytest
from idp_sdk._core.template_transform import GovCloudTemplateTransformer

pytestmark = pytest.mark.unit


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "template.yaml").is_file() and (parent / "publish.py").is_file():
            return parent
    raise RuntimeError("Could not locate repo root containing template.yaml")


def _template_with_cloudfront():
    """A synthetic template exercising the CloudFront Fn::If / resource shapes."""
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Test",
        "Parameters": {
            "WebUIHosting": {
                "Type": "String",
                "Default": "CloudFront",
                "AllowedValues": ["CloudFront", "APIGateway"],
            },
            "CloudFrontPriceClass": {"Type": "String", "Default": "PriceClass_100"},
            "CloudFrontAllowedGeos": {"Type": "String", "Default": ""},
        },
        "Conditions": {
            "UseCloudFrontHosting": {
                "Fn::Equals": [{"Ref": "WebUIHosting"}, "CloudFront"]
            },
            "UseApiGatewayHosting": {
                "Fn::Equals": [{"Ref": "WebUIHosting"}, "APIGateway"]
            },
            "ShouldEnableGeoRestriction": {
                "Fn::Not": [{"Fn::Equals": [{"Ref": "CloudFrontAllowedGeos"}, ""]}]
            },
        },
        "Resources": {
            # Core resources the transform must keep.
            "InputBucket": {"Type": "AWS::S3::Bucket"},
            "OutputBucket": {"Type": "AWS::S3::Bucket"},
            "WorkingBucket": {"Type": "AWS::S3::Bucket"},
            "TrackingTable": {"Type": "AWS::DynamoDB::Table"},
            "ConfigurationTable": {"Type": "AWS::DynamoDB::Table"},
            "CustomerManagedEncryptionKey": {"Type": "AWS::KMS::Key"},
            "PATTERNSTACK": {"Type": "AWS::CloudFormation::Stack"},
            "WebUIBucket": {"Type": "AWS::S3::Bucket"},
            "WebUIProxyRole": {
                "Type": "AWS::IAM::Role",
                "Condition": "UseApiGatewayHosting",
            },
            # CloudFront resources — must all be removed.
            "CloudFrontOriginAccessControl": {
                "Type": "AWS::CloudFront::OriginAccessControl",
                "Condition": "UseCloudFrontHosting",
            },
            "SecurityHeadersPolicy": {
                "Type": "AWS::CloudFront::ResponseHeadersPolicy",
                "Condition": "UseCloudFrontHosting",
            },
            "CloudFrontDistribution": {
                "Type": "AWS::CloudFront::Distribution",
                "Condition": "UseCloudFrontHosting",
                "Properties": {"Foo": {"Ref": "SecurityHeadersPolicy"}},
            },
            # A kept resource whose CORS origin uses the CloudFront Fn::If shape.
            "SomeBucket": {
                "Type": "AWS::S3::Bucket",
                "Properties": {
                    "CorsConfiguration": {
                        "CorsRules": [
                            {
                                "AllowedOrigins": [
                                    {
                                        "Fn::If": [
                                            "UseCloudFrontHosting",
                                            {
                                                "Fn::Sub": "https://${CloudFrontDistribution.DomainName}"
                                            },
                                            "https://api.example.com",
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                },
            },
            # A LoggingBucket policy with the CloudFront-service statement.
            "LoggingBucketPolicy": {
                "Type": "AWS::S3::BucketPolicy",
                "Properties": {
                    "PolicyDocument": {
                        "Statement": [
                            {
                                "Sid": "AllowCloudFrontLogs",
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": {
                                        "Fn::Sub": "cloudfront.${AWS::URLSuffix}"
                                    }
                                },
                                "Action": ["s3:PutObject"],
                            },
                            {
                                "Sid": "KeepThis",
                                "Effect": "Allow",
                                "Principal": {"Service": "logging.s3.amazonaws.com"},
                                "Action": ["s3:PutObject"],
                            },
                        ]
                    }
                },
            },
        },
        "Outputs": {
            "ApplicationWebURL": {
                "Value": {
                    "Fn::If": [
                        "UseCloudFrontHosting",
                        {"Fn::Sub": "https://${CloudFrontDistribution.DomainName}/"},
                        {"Fn::Sub": "${APIRESOLVERSTACK.Outputs.HttpApiEndpoint}/"},
                    ]
                }
            }
        },
    }


def _all_cloudfront_types(template):
    return [
        name
        for name, res in template.get("Resources", {}).items()
        if isinstance(res, dict)
        and str(res.get("Type", "")).startswith("AWS::CloudFront::")
    ]


def test_cloudfront_resources_removed():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    assert _all_cloudfront_types(result) == []
    for name in (
        "CloudFrontDistribution",
        "CloudFrontOriginAccessControl",
        "SecurityHeadersPolicy",
    ):
        assert name not in result["Resources"]


def test_use_cloudfront_condition_removed():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    assert "UseCloudFrontHosting" not in result.get("Conditions", {})
    # UseApiGatewayHosting must survive (the UI is still served via API Gateway).
    assert "UseApiGatewayHosting" in result["Conditions"]


def test_webui_hosting_forced_to_apigateway():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    param = result["Parameters"]["WebUIHosting"]
    assert param["AllowedValues"] == ["APIGateway"]
    assert param["Default"] == "APIGateway"


def test_cloudfront_only_parameters_removed():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    assert "CloudFrontPriceClass" not in result["Parameters"]
    assert "CloudFrontAllowedGeos" not in result["Parameters"]


def test_hosting_if_collapsed_to_else_branch():
    """Fn::If[UseCloudFrontHosting] collapses to the API-Gateway (else) value."""
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    cors = result["Resources"]["SomeBucket"]["Properties"]["CorsConfiguration"]
    origin = cors["CorsRules"][0]["AllowedOrigins"][0]
    assert origin == "https://api.example.com"
    web_url = result["Outputs"]["ApplicationWebURL"]["Value"]
    assert web_url == {"Fn::Sub": "${APIRESOLVERSTACK.Outputs.HttpApiEndpoint}/"}


def test_cloudfront_service_policy_statement_removed():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    stmts = result["Resources"]["LoggingBucketPolicy"]["Properties"]["PolicyDocument"][
        "Statement"
    ]
    sids = {s.get("Sid") for s in stmts}
    assert "AllowCloudFrontLogs" not in sids
    assert "KeepThis" in sids


def test_no_dangling_cloudfront_references():
    """Nothing may reference a removed CloudFront resource or the removed condition."""
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    assert t.validate_no_cloudfront(result) is True


def test_description_marked_govcloud():
    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(_template_with_cloudfront())
    assert "GovCloud" in result["Description"]


def test_real_template_has_no_cloudfront_after_transform():
    """Transform the ACTUAL committed template.yaml; assert zero CloudFront left.

    Uses cfn-lint's CloudFormation-aware YAML decoder to parse the shorthand
    !Ref/!GetAtt/!If tags in the source template.
    """
    cfnlint_decode = pytest.importorskip("cfnlint.decode.cfn_yaml")

    def _plain(node):
        if isinstance(node, dict):
            return {str(k): _plain(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_plain(x) for x in node]
        if isinstance(node, str):
            return str(node)
        return node

    template = _plain(cfnlint_decode.load(str(_repo_root() / "template.yaml")))
    assert isinstance(template, dict) and "Resources" in template

    t = GovCloudTemplateTransformer()
    result = t.apply_transforms(template)

    # No CloudFront resource types remain.
    assert _all_cloudfront_types(result) == []
    # No dangling refs / condition (the transform's own validator).
    assert t.validate_no_cloudfront(result) is True
    # Hosting forced to APIGateway; the API-Gateway hosting wiring survives.
    assert result["Parameters"]["WebUIHosting"]["AllowedValues"] == ["APIGateway"]
    assert "UseApiGatewayHosting" in result["Conditions"]
    assert "WebUIProxyRole" in result["Resources"]
