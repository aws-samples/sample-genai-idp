# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the headless CloudFormation template transformer.

Regression coverage for the class of bug that produced
"Template error: instance of Fn::GetAtt references undefined resource
GraphQLApi" at deploy time: a resource/output that survives the transform
while still referencing a resource the transform removed (AppSync, Cognito,
WebUI, Discovery, Feature Platform, ...).
"""

import re

import pytest
from idp_sdk._core.template_transform import HeadlessTemplateTransformer

pytestmark = pytest.mark.unit


def _minimal_template():
    """A template carrying the resources/outputs that broke headless deploys."""
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Test",
        "Parameters": {
            "EnableMCP": {"Type": "String", "Default": "true"},
            "EnableFeaturePlatform": {"Type": "String", "Default": "true"},
            "AppSyncVisibility": {"Type": "String", "Default": "PUBLIC"},
        },
        "Conditions": {
            "IsFeaturePlatformEnabled": {
                "Fn::Equals": [{"Ref": "EnableFeaturePlatform"}, "true"]
            },
            "IsFeaturePlatformDisabled": {
                "Fn::Equals": [{"Ref": "EnableFeaturePlatform"}, "false"]
            },
            "UsePrivateAppSync": {
                "Fn::Equals": [{"Ref": "AppSyncVisibility"}, "PRIVATE"]
            },
        },
        "Resources": {
            # Core resources the validator requires to survive.
            "InputBucket": {"Type": "AWS::S3::Bucket"},
            "OutputBucket": {"Type": "AWS::S3::Bucket"},
            "WorkingBucket": {"Type": "AWS::S3::Bucket"},
            "TrackingTable": {"Type": "AWS::DynamoDB::Table"},
            "ConfigurationTable": {"Type": "AWS::DynamoDB::Table"},
            "CustomerManagedEncryptionKey": {"Type": "AWS::KMS::Key"},
            "PATTERNSTACK": {"Type": "AWS::CloudFormation::Stack"},
            # Resources the transform removes.
            "GraphQLApi": {"Type": "AWS::AppSync::GraphQLApi"},
            "UserPool": {"Type": "AWS::Cognito::UserPool"},
            "WebUIBucket": {"Type": "AWS::S3::Bucket"},
            "DiscoveryBucket": {"Type": "AWS::S3::Bucket"},
            # The Feature Platform nested stack — the regression source.
            "FeaturePlatformStack": {
                "Type": "AWS::CloudFormation::Stack",
                "Condition": "IsFeaturePlatformEnabled",
                "DependsOn": ["APPSYNCSTACK"],
                "Properties": {
                    "Parameters": {
                        "GraphQLApiId": {"Fn::GetAtt": ["GraphQLApi", "ApiId"]},
                        "GraphQLApiArn": {"Fn::GetAtt": ["GraphQLApi", "Arn"]},
                        "UserPoolId": {"Ref": "UserPool"},
                        "WebUIBucketName": {"Ref": "WebUIBucket"},
                        "DiscoveryBucketName": {"Ref": "DiscoveryBucket"},
                    }
                },
            },
        },
        "Outputs": {
            "AppSyncEndpointForDNS": {
                "Condition": "UsePrivateAppSync",
                "Value": {
                    "Fn::Select": [
                        2,
                        {
                            "Fn::Split": [
                                "/",
                                {"Fn::GetAtt": ["GraphQLApi", "GraphQLUrl"]},
                            ]
                        },
                    ]
                },
            },
            "TrackingTableName": {
                "Condition": "IsFeaturePlatformDisabled",
                "Value": {"Ref": "TrackingTable"},
            },
        },
    }


def _dangling_refs(template, removed):
    """Return (kind, name, path) tuples referencing a removed resource."""
    findings = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "Ref" and isinstance(v, str) and v.split(".")[0] in removed:
                    findings.append(("Ref", v, path))
                elif k == "Fn::GetAtt":
                    name = v[0] if isinstance(v, list) else str(v).split(".")[0]
                    if name in removed:
                        findings.append(("Fn::GetAtt", name, path))
                elif k == "Fn::Sub":
                    s = v[0] if isinstance(v, list) else v
                    if isinstance(s, str):
                        for m in re.findall(r"\$\{([^}]+)\}", s):
                            if m.split(".")[0] in removed:
                                findings.append(("Fn::Sub", m, path))
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, x in enumerate(node):
                walk(x, f"{path}[{i}]")

    walk(template.get("Resources", {}), "Resources")
    walk(template.get("Outputs", {}), "Outputs")
    return findings


def test_feature_platform_stack_removed():
    """FeaturePlatformStack must be stripped — it refs removed AppSync/Cognito."""
    t = HeadlessTemplateTransformer()
    result = t.apply_transforms(_minimal_template())
    assert "FeaturePlatformStack" in t.all_resources_to_remove
    assert "FeaturePlatformStack" not in result["Resources"]


def test_appsync_dns_output_removed():
    """AppSyncEndpointForDNS refs GraphQLApi.GraphQLUrl and must be removed."""
    t = HeadlessTemplateTransformer()
    result = t.apply_transforms(_minimal_template())
    assert "AppSyncEndpointForDNS" not in result.get("Outputs", {})


def test_enable_feature_platform_forced_false():
    """EnableFeaturePlatform default flips to 'false' so the export stays live."""
    t = HeadlessTemplateTransformer()
    result = t.apply_transforms(_minimal_template())
    assert result["Parameters"]["EnableFeaturePlatform"]["Default"] == "false"
    # TrackingTableName export (gated on IsFeaturePlatformDisabled) must survive.
    assert "TrackingTableName" in result["Outputs"]


def test_no_dangling_references_to_removed_resources():
    """The whole point: nothing left references a removed resource."""
    t = HeadlessTemplateTransformer()
    result = t.apply_transforms(_minimal_template())
    findings = _dangling_refs(result, t.all_resources_to_remove)
    assert findings == [], f"Dangling references remain: {findings}"
