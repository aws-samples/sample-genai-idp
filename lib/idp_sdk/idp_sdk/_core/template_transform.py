# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Headless template transformation for IDP CloudFormation templates.

Transforms a standard IDP CloudFormation template into a headless version
by removing UI, the UI REST API, Cognito, WAF, Agent, HITL, and Knowledge
Base resources. The resulting template is suitable for API-only deployments
(e.g., GovCloud regions or headless use cases).
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


class HeadlessTemplateTransformer:
    """Transform IDP CloudFormation templates for headless (no-UI) deployment.

    This class extracts and removes AWS services that are not needed for
    headless/API-only deployments: CloudFront, the UI REST API, Cognito, WAF,
    Agent/MCP, HITL/A2I, and Knowledge Base resources.

    Usage:
        transformer = HeadlessTemplateTransformer()
        success = transformer.transform(input_path, output_path)

        # Or transform in-memory:
        template = transformer.load_template(input_path)
        template = transformer.apply_transforms(template)
        transformer.save_template(template, output_path)
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        if verbose:
            logging.basicConfig(
                level=logging.DEBUG, format="%(levelname)s: %(message)s"
            )
        else:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

        # ---- Resource sets to remove ----

        self.ui_resources: Set[str] = {
            "CloudFrontDistribution",
            "CloudFrontOriginAccessControl",
            "SecurityHeadersPolicy",
            "WebUIBucket",
            "WebUIBucketPolicy",
            "UICodeBuildProject",
            "UICodeBuildServiceRole",
            "StartUICodeBuild",
            "StartUICodeBuildExecutionRole",
            "StartUICodeBuildLogGroup",
            "CodeBuildRun",
        }

        # UI-API resources to strip for headless. AWS AppSync has been removed;
        # the interactive UI API is now an API Gateway REST API hosted in the
        # APIRESOLVERSTACK nested stack (its dispatcher invokes these resolver
        # Lambdas). Headless = no UI API, so strip the nested stack and the
        # UI-only resolver Lambdas it fronts. (The former AppSync
        # DataSource/Resolver/GraphQLApi resources no longer exist in the base
        # template, so they are not listed here anymore.)
        self.appsync_resources: Set[str] = {
            # Nested stack hosting the REST API dispatcher + UI resolver Lambdas.
            "APIRESOLVERSTACK",
            # UI-only resolver Lambdas defined in the main template (capacity
            # planning, version check, fine-tuning) — only reachable via the
            # (stripped) UI API, so remove them in headless mode.
            "CalculateCapacityResolverFunction",
            "CalculateCapacityResolverFunctionLogGroup",
            "VersionCheckResolverFunction",
            "VersionCheckResolverFunctionLogGroup",
        }

        self.auth_resources: Set[str] = {
            "UserPool",
            "UserPoolClient",
            "UserPoolDomain",
            "IdentityPool",
            "CognitoIdentityPoolSetRole",
            "CognitoAuthorizedRole",
            "AdminUser",
            "AdminGroup",
            "AuthorGroup",
            "ViewerGroup",
            "ReviewerGroup",
            "AdminUserToGroupAttachment",
            "GetDomain",
            "CognitoUserPoolEmailDomainVerifyFunction",
            "CognitoUserPoolEmailDomainVerifyFunctionLogGroup",
            "CognitoUserPoolEmailDomainVerifyPermission",
            "CognitoUserPoolEmailDomainVerifyPermissionReady",
            # External Identity Provider (SAML/OIDC) — depends on UserPool
            "ExternalIdentityProvider",
            "ExternalIdentityProviderReady",
            "ExternalIdPGroupMappingFunction",
            "ExternalIdPGroupMappingFunctionLogGroup",
            "ExternalIdPGroupMappingCognitoPolicy",
            "ExternalIdPGroupMappingPermission",
        }

        self.waf_resources: Set[str] = {
            "WAFIPV4Set",
            "WAFLambdaServiceIPSet",
            "WAFWebACL",
            "WAFWebACLAssociation",
            "IPSetUpdaterFunction",
            "IPSetUpdaterCustomResource",
        }

        self.agent_resources: Set[str] = {
            "AgentTable",
            "AgentRequestHandlerFunction",
            "AgentRequestHandlerLogGroup",
            "AgentProcessorFunction",
            "AgentProcessorLogGroup",
            "ExternalMCPAgentsSecret",
            "ListAvailableAgentsFunction",
            "ListAvailableAgentsLogGroup",
            "AgentCoreAnalyticsLambdaFunction",
            "AgentCoreAnalyticsLambdaLogGroup",
            "AgentCoreGatewayManagerFunction",
            "AgentCoreGatewayManagerLogGroup",
            "AgentCoreGatewayExecutionRole",
            "AgentCoreGateway",
            "ExternalAppClient",
            "AgentCoreMCPHandlerFunction",
            "AgentCoreMCPHandlerLogGroup",
            "MCPConnectorClient",
            "MCPResourceServer",
        }

        self.hitl_resources: Set[str] = {
            "UserPoolClienta2i",
            "PrivateWorkteam",
            "CognitoClientUpdaterRole",
            "CognitoClientUpdaterFunctionLogGroup",
            "CognitoClientUpdaterFunction",
            "CognitoClientCustomResource",
            "A2IFlowDefinitionRole",
            "A2IHumanTaskUILambdaRole",
            "CreateA2IResourcesLambda",
            "A2IResourcesCustomResource",
            "GetWorkforceURLFunction",
            "WorkforceURLResource",
            "UsersTable",
            "UserManagementFunctionLogGroup",
            "UserManagementFunction",
            "UserSyncFunctionLogGroup",
            "UserSyncFunction",
            "CompleteSectionReviewFunctionLogGroup",
            "CompleteSectionReviewFunction",
            "UserManagementDataSource",
            "CreateUserResolver",
            "DeleteUserResolver",
            "ListUsersResolver",
            "CompleteSectionReviewDataSource",
            "CompleteSectionReviewResolver",
            "SkipAllSectionsReviewResolver",
            "ClaimReviewResolver",
            "ReleaseReviewResolver",
            "GetMyProfileResolver",
            "UpdateUserResolver",
        }

        self.kb_resources: Set[str] = {
            "DOCUMENTKB",
        }

        # Feature Platform nested stack — gated on EnableFeaturePlatform=true.
        # Its parameters wire in the UI REST API (in APIRESOLVERSTACK), UserPool,
        # UserPoolClient, WebUIBucket, and DiscoveryBucket — all removed in
        # headless mode — and it DependsOn the (removed) APIRESOLVERSTACK. Left in
        # place, its references to those removed resources would fail at deploy
        # time ("Fn::GetAtt references undefined resource"). EnableFeaturePlatform
        # is forced to 'false' in _remove_parameters so the
        # IsFeaturePlatformDisabled-gated TrackingTableName export stays active.
        self.feature_platform_resources: Set[str] = {
            "FeaturePlatformStack",
        }

        self.discovery_resources: Set[str] = {
            "DiscoveryBucket",
            "DiscoveryBucketPolicy",
            "DiscoveryDLQ",
            "DiscoveryQueue",
            "DiscoveryTrackingTable",
            "DiscoveryProcessorFunction",
            "DiscoveryProcessorFunctionLogGroup",
            "BlueprintOptimizationFunction",
            "BlueprintOptimizationFunctionLogGroup",
            "MultiDocDiscoveryPrepareFunction",
            "MultiDocDiscoveryPrepareFunctionLogGroup",
            "MultiDocDiscoveryStateMachine",
            "MultiDocDiscoveryStateMachineRole",
            "MULTIDOCDISCOVERYSTACK",
        }

        self.appsync_dependent_resources: Set[str] = {
            "StepFunctionSubscriptionPublisher",
            "StepFunctionSubscriptionPublisherLogGroup",
            "StepFunctionSubscriptionRule",
            "StepFunctionSubscriptionPublisherPermission",
            # Invoked async only by the UI REST API dispatcher in the (removed)
            # APIRESOLVERSTACK; with no caller, the function and its log group are
            # dead weight in headless mode and their dangling refs to removed
            # UI resources (e.g. UsersTable) would block stack updates.
            "ChatWithDocumentProcessorFunction",
            "ChatWithDocumentProcessorLogGroup",
            # Chat streaming endpoint (Function URL + LWA). UI-only: reached
            # directly by the browser via VITE_STREAM_URL (emitted only by the
            # removed UI CodeBuild/WebUITestEnvFile), invoked by the removed
            # CognitoAuthorizedRole, and it references the removed UsersTable
            # (RBAC scope) — so a dangling "Fn::GetAtt UsersTable" would block
            # headless deploys. Strip the whole family.
            "ChatStreamProcessorFunction",
            "ChatStreamProcessorLogGroup",
            "ChatStreamProcessorUrl",
            "ChatStreamProcessorUrlPermission",
        }

        # ---- Parameters to remove ----

        self.parameters_to_remove: Set[str] = {
            "AdminEmail",
            "AllowedSignUpEmailDomain",
            "CloudFrontPriceClass",
            "CloudFrontAllowedGeos",
            "WAFAllowedIPv4Ranges",
            "DocumentKnowledgeBase",
            "KnowledgeBaseVectorStore",
            "KnowledgeBaseModelId",
            "ChatCompanionModelId",
            "EnableHITL",
            "ExistingPrivateWorkforceArn",
            # External Identity Provider (SAML/OIDC) — depends on Cognito
            "ExternalIdPType",
            "ExternalIdPName",
            "ExternalIdPMetadataURL",
            "ExternalIdPOIDCIssuer",
            "ExternalIdPOIDCClientId",
            "ExternalIdPOIDCClientSecretArn",
            "ExternalIdPGroupAttributeName",
            "ExternalIdPAdminGroupName",
            "ExternalIdPAuthorGroupName",
            "ExternalIdPReviewerGroupName",
            "ExternalIdPViewerGroupName",
            "ExternalIdPAutoLogin",
            # Public-template version-check (UI-only feature — resolver
            # removed above in self.appsync_resources). Drop the params so
            # the headless template doesn't expose unused UI configuration.
            "PublicArtifactsBucket",
            "PublicArtifactsPrefix",
        }

        # ---- Outputs to remove ----

        self.outputs_to_remove: Set[str] = {
            "ApplicationWebURL",
            "WebUIBucketName",
            "WebUITestEnvFile",
            "SageMakerA2IReviewPortalURL",
            "LabelingConsoleURL",
            "ExternalMCPAgentsSecretName",
            "PrivateWorkteamArn",
            "MCPServerEndpoint",
            "MCPClientId",
            "MCPClientSecret",
            "MCPUserPool",
            "MCPTokenURL",
            "MCPAuthorizationURL",
            "DynamoDBAgentTableName",
            "DynamoDBAgentTableConsoleURL",
            "ExternalMCPAgentsSecretConsoleURL",
            "MCPConnectorClientId",
            "MCPConnectorClientSecret",
            "S3DiscoveryBucketName",
            "S3DiscoveryBucketConsoleURL",
            # UI-API DNS helper output (named for the former AppSync endpoint).
            # AppSync is gone — the UI API is now an API Gateway REST API in the
            # (stripped) APIRESOLVERSTACK — so this UI-only output has no place in a
            # headless deployment. Kept here as a defensive strip in case the
            # base template still emits it.
            "AppSyncEndpointForDNS",
        }

        # ---- Conditions to remove ----

        self.conditions_to_remove: Set[str] = {
            "ShouldAllowSignUpEmailDomain",
            "ShouldEnableGeoRestriction",
            "IsWafEnabled",
            "ShouldCreateDocumentKnowledgeBase",
            "ShouldUseDocumentKnowledgeBase",
            "IsHITLEnabled",
            "ShouldCreatePrivateWorkteam",
            "ShouldUseExistingPrivateWorkteam",
            # External Identity Provider (SAML/OIDC) — depends on Cognito
            "HasExternalIdP",
            "IsExternalIdPSAML",
            "IsExternalIdPOIDC",
            "HasExternalIdPGroupMapping",
            "ShouldMapExternalIdPGroups",
            "CreateExternalAppClient",
            # Used only by the removed VersionCheckResolverFunction (AppSync UI feature)
            "HasPublicArtifactsBucket",
        }

        # ---- Rules to remove ----

        self.rules_to_remove: Set[str] = {
            "ValidateExistingPrivateWorkforceArn",
        }

        # ---- Parameter groups to remove ----

        self.parameter_groups_to_remove: Set[str] = {
            "User Authentication",
            "Security Configuration",
            "Document Knowledge Base",
            "Agentic Analysis",
            "HITL (A2I) Configuration",
            "External Identity Provider",
        }

    @property
    def all_resources_to_remove(self) -> Set[str]:
        """Combined set of all resources that should be removed."""
        return (
            self.ui_resources
            | self.appsync_resources
            | self.appsync_dependent_resources
            | self.auth_resources
            | self.waf_resources
            | self.agent_resources
            | self.hitl_resources
            | self.kb_resources
            | self.discovery_resources
            | self.feature_platform_resources
        )

    # ---- Public API ----

    def transform(
        self,
        input_path: str,
        output_path: str,
        *,
        update_govcloud_config: bool = False,
    ) -> bool:
        """Transform a template file to headless and save to output_path.

        Args:
            input_path: Path to the source CloudFormation YAML template.
            output_path: Path to write the headless template.
            update_govcloud_config: If True, update configuration maps and
                defaults for GovCloud-specific config presets.

        Returns:
            True if transformation and basic validation succeeded.
        """
        try:
            logger.info("🔧 Starting headless template transformation")
            template = self.load_template(input_path)
            template = self.apply_transforms(
                template, update_govcloud_config=update_govcloud_config
            )
            self.save_template(template, output_path)

            if not self.validate_template_basic(template):
                return False

            logger.info("🎉 Headless template transformation completed successfully!")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to generate headless template: {e}")
            if self.verbose:
                import traceback

                logger.debug(traceback.format_exc())
            return False

    def apply_transforms(
        self,
        template: Dict[str, Any],
        *,
        update_govcloud_config: bool = False,
    ) -> Dict[str, Any]:
        """Apply all headless transformations to an in-memory template dict.

        Args:
            template: Parsed CloudFormation template dictionary.
            update_govcloud_config: If True, update config maps for GovCloud.

        Returns:
            The transformed template dictionary.
        """
        template = self._remove_resources(template)
        template = self._remove_parameters(template)
        template = self._remove_outputs(template)
        template = self._remove_conditions(template)
        template = self._remove_rules(template)
        template = self._clean_for_headless_deployment(template)
        template = self._clean_parameter_groups(template)
        if update_govcloud_config:
            template = self._update_configuration_maps_for_govcloud(template)
        template = self._update_arn_partitions(template)
        template = self._update_description(template)
        return template

    # ---- I/O helpers ----

    def load_template(self, input_file: str) -> Dict[str, Any]:
        """Load CloudFormation template from YAML file."""
        logger.info(f"Loading template from {input_file}")
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input template file not found: {input_file}")
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                template = yaml.safe_load(f)
            logger.debug(
                f"Loaded template with {len(template.get('Resources', {}))} resources"
            )
            return template
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML template: {e}")

    def save_template(self, template: Dict[str, Any], output_file: str) -> None:
        """Save CloudFormation template to YAML file."""
        logger.info(f"Saving headless template to {output_file}")
        os.makedirs(
            os.path.dirname(output_file) if os.path.dirname(output_file) else ".",
            exist_ok=True,
        )
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                yaml.dump(template, f, default_flow_style=False, width=120, indent=2)
            logger.info("✅ Headless template saved successfully")
        except Exception as e:
            raise ValueError(f"Failed to save template: {e}")

    # ---- Validation ----

    def validate_template_basic(self, template: Dict[str, Any]) -> bool:
        """Perform basic template validation."""
        logger.info("Validating generated template")
        issues: List[str] = []

        required_sections = ["AWSTemplateFormatVersion", "Resources"]
        for section in required_sections:
            if section not in template:
                issues.append(f"Missing required section: {section}")

        resources = template.get("Resources", {})
        core_resources = {
            "InputBucket",
            "OutputBucket",
            "WorkingBucket",
            "TrackingTable",
            "ConfigurationTable",
            "CustomerManagedEncryptionKey",
        }
        missing_core = core_resources - set(resources.keys())
        if missing_core:
            issues.append(f"Missing core resources: {', '.join(missing_core)}")

        if "PATTERNSTACK" not in resources:
            issues.append(
                "Missing PATTERNSTACK - unified pattern nested stack should be present"
            )

        if issues:
            logger.error("Basic template validation failed:")
            for issue in issues:
                logger.error(f"  - {issue}")
            return False

        logger.info("✅ Basic template validation passed")
        return True

    # ---- Internal transformation methods ----

    def _remove_resources(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove resources not supported in headless deployment."""
        resources = template.get("Resources", {})
        original_count = len(resources)

        removed_resources: List[str] = []
        for resource_name in list(resources.keys()):
            resource_def = resources[resource_name]

            if resource_name in self.all_resources_to_remove:
                del resources[resource_name]
                removed_resources.append(resource_name)
                continue

            # Remove if resource depends on a condition that we're removing
            if isinstance(resource_def, dict) and "Condition" in resource_def:
                condition_name = resource_def["Condition"]
                if condition_name in self.conditions_to_remove:
                    del resources[resource_name]
                    removed_resources.append(
                        f"{resource_name} (depends on removed condition: {condition_name})"
                    )

        logger.info(
            f"Removed {len(removed_resources)} resources ({original_count} → {len(resources)})"
        )
        logger.debug(f"Removed resources: {', '.join(removed_resources)}")
        return template

    def _remove_parameters(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove parameters related to unsupported services."""
        parameters = template.get("Parameters", {})
        original_count = len(parameters)

        removed: List[str] = []
        for param_name in list(parameters.keys()):
            if param_name in self.parameters_to_remove:
                del parameters[param_name]
                removed.append(param_name)

        # Set EnableMCP default to false (MCP depends on Cognito/AgentCore)
        if "EnableMCP" in parameters:
            parameters["EnableMCP"]["Default"] = "false"
            logger.info("Modified EnableMCP parameter default to 'false'")

        # Force Feature Platform off — its nested stack (removed above) wires
        # in AppSync/Cognito/WebUI/Discovery resources that don't exist in
        # headless mode. Setting the default to 'false' keeps
        # IsFeaturePlatformDisabled true so the main stack's
        # TrackingTableName export (gated on that condition) stays active.
        if "EnableFeaturePlatform" in parameters:
            parameters["EnableFeaturePlatform"]["Default"] = "false"
            logger.info("Modified EnableFeaturePlatform parameter default to 'false'")

        logger.info(
            f"Removed {len(removed)} parameters ({original_count} → {len(parameters)})"
        )
        return template

    def _remove_outputs(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove outputs related to unsupported services."""
        outputs = template.get("Outputs", {})
        original_count = len(outputs)

        removed: List[str] = []
        for output_name in list(outputs.keys()):
            if output_name in self.outputs_to_remove:
                del outputs[output_name]
                removed.append(output_name)

        logger.info(
            f"Removed {len(removed)} outputs ({original_count} → {len(outputs)})"
        )
        return template

    def _remove_conditions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove conditions related to unsupported services."""
        conditions = template.get("Conditions", {})
        original_count = len(conditions)

        # Force IsS3VectorsVectorStore to always false (S3 Vectors not available headless)
        if "IsS3VectorsVectorStore" in conditions:
            conditions["IsS3VectorsVectorStore"] = {"Fn::Equals": ["false", "true"]}
            logger.info("Forced IsS3VectorsVectorStore to always False")

        removed: List[str] = []
        for condition_name in list(conditions.keys()):
            if condition_name in self.conditions_to_remove:
                del conditions[condition_name]
                removed.append(condition_name)

        if removed:
            logger.info(
                f"Removed {len(removed)} conditions ({original_count} → {len(conditions)})"
            )
        return template

    def _remove_rules(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove rules that validate removed parameters."""
        rules = template.get("Rules", {})
        if not rules:
            return template

        original_count = len(rules)
        removed: List[str] = []
        for rule_name in list(rules.keys()):
            if rule_name in self.rules_to_remove:
                del rules[rule_name]
                removed.append(rule_name)

        if removed:
            logger.info(
                f"Removed {len(removed)} rules ({original_count} → {len(rules)})"
            )

        if not rules:
            del template["Rules"]
            logger.debug("Removed empty Rules section")

        return template

    def _clean_for_headless_deployment(
        self, template: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean template for headless deployment.

        - Remove CloudFront policy statements
        - Remove CORS from S3 buckets
        - Strip dangling references to removed resources from kept Lambda
          functions (e.g. ExternalMCPAgentsSecret policy statements)
        - Clean nested stack parameters
        - Fix Knowledge Base condition references
        - Clean UpdateSettingsValues custom resource
        - Clean outputs referencing removed resources
        """
        logger.info("Cleaning template for headless deployment")
        resources = template.get("Resources", {})

        # Remove CloudFront policy statements
        template = self._clean_cloudfront_policy_statements(template)

        # Remove CORS from all S3 buckets (no web UI)
        for resource_name, resource_def in resources.items():
            if (
                isinstance(resource_def, dict)
                and resource_def.get("Type") == "AWS::S3::Bucket"
            ):
                properties = resource_def.get("Properties", {})
                if "CorsConfiguration" in properties:
                    del properties["CorsConfiguration"]
                    logger.debug(f"Removed CORS configuration from {resource_name}")

        # Tidy backend functions that survive in headless mode. The base
        # template already tracks via DynamoDB (DOCUMENT_TRACKING_MODE=dynamodb,
        # APPSYNC_API_URL=""), so there is no AppSync→DynamoDB conversion to do.
        # What still matters: drop the now-empty APPSYNC_API_URL env var and
        # strip any policy statements that reference resources we removed (e.g.
        # the ExternalMCPAgentsSecret on the agent-chat function, or a stray
        # appsync:GraphQL action) so no dangling refs remain.
        functions_to_clean = [
            "QueueSender",
            "QueueProcessor",
            "WorkflowTracker",
            "EvaluationFunction",
            "AgentChatProcessorFunction",
            "AgentProcessorFunction",
            "DiscoveryProcessorFunction",
            # The circuit-breaker manager still does real work in headless mode
            # (state management, alarm processing); we keep it but drop the
            # empty APPSYNC_API_URL env var and any appsync:GraphQL policy.
            "CircuitBreakerManagerFunction",
        ]
        for func_name in functions_to_clean:
            if func_name in resources:
                self._clean_tracking_function(resources, func_name)

        # Clean ALB hosting nested stack parameters
        if "ALBHOSTINGSTACK" in resources:
            alb_stack_params = (
                resources["ALBHOSTINGSTACK"].get("Properties", {}).get("Parameters", {})
            )
            if "WebUIBucketName" in alb_stack_params:
                alb_stack_params["WebUIBucketName"] = ""
                logger.debug(
                    "Replaced WebUIBucketName with empty string in ALBHOSTINGSTACK"
                )

        # Clean nested stack parameters (PATTERNSTACK)
        for stack_name in ["PATTERNSTACK"]:
            if stack_name in resources:
                self._clean_nested_stack_params(resources, stack_name)

        # Fix ShouldUseDocumentKnowledgeBase condition references
        template = self._fix_kb_condition_references(template)

        # Re-fetch resources after potential yaml reload
        resources = template.get("Resources", {})

        # Clean outputs referencing removed resources
        self._clean_orphaned_outputs(template)

        # Fix UpdateSettingsValues custom resource
        self._clean_update_settings_values(template)

        return template

    def _clean_tracking_function(
        self, resources: Dict[str, Any], func_name: str
    ) -> None:
        """Tidy a kept Lambda function for headless deployment.

        The base template already tracks documents via DynamoDB directly
        (DOCUMENT_TRACKING_MODE=dynamodb, TRACKING_TABLE set, APPSYNC_API_URL=""),
        so this is no longer an AppSync→DynamoDB conversion. It just drops the
        now-empty APPSYNC_API_URL env var, ensures a DynamoDB CRUD policy is
        present, and strips any policy statements that reference removed
        resources (ExternalMCPAgentsSecret) or stale appsync:GraphQL actions.
        """
        func_def = resources[func_name]
        env_vars = (
            func_def.get("Properties", {}).get("Environment", {}).get("Variables", {})
        )

        # Drop the leftover (empty) APPSYNC_API_URL env var. The base template
        # already sets DOCUMENT_TRACKING_MODE=dynamodb and TRACKING_TABLE, so we
        # only backfill them defensively if they are somehow missing.
        if "APPSYNC_API_URL" in env_vars:
            del env_vars["APPSYNC_API_URL"]
            env_vars.setdefault("DOCUMENT_TRACKING_MODE", "dynamodb")
            env_vars.setdefault("TRACKING_TABLE", {"Ref": "TrackingTable"})
            logger.debug(f"Removed empty APPSYNC_API_URL env var from {func_name}")

        # Add DynamoDB CRUD policy if not present
        policies = func_def.get("Properties", {}).get("Policies", [])
        has_dynamodb = any(
            isinstance(p, dict) and "DynamoDBCrudPolicy" in p for p in policies
        )
        if not has_dynamodb:
            policies.append(
                {"DynamoDBCrudPolicy": {"TableName": {"Ref": "TrackingTable"}}}
            )
            logger.debug(f"Added DynamoDB CRUD permissions for {func_name}")

        # Clean AppSync and MCP-related policy statements
        cleaned_policies: List[Any] = []
        for policy in policies:
            if isinstance(policy, dict) and "Statement" in policy:
                cleaned = self._clean_policy_statements(policy, func_name)
                if cleaned is not None:
                    cleaned_policies.append(cleaned)
            else:
                cleaned_policies.append(policy)
        func_def["Properties"]["Policies"] = cleaned_policies

    def _clean_policy_statements(
        self, policy: Dict[str, Any], func_name: str
    ) -> Optional[Dict[str, Any]]:
        """Clean AppSync/MCP policy statements. Returns None if policy should be removed entirely."""
        statement = policy["Statement"]

        if isinstance(statement, dict):
            if self._should_remove_statement(statement):
                logger.debug(f"Removed AppSync/MCP policy statement from {func_name}")
                return None
            return policy

        if isinstance(statement, list):
            cleaned = [
                s
                for s in statement
                if isinstance(s, dict) and not self._should_remove_statement(s)
            ]
            if not cleaned:
                logger.debug(f"Removed AppSync/MCP permissions from {func_name} policy")
                return None
            policy["Statement"] = cleaned
            return policy

        return policy

    def _should_remove_statement(self, stmt: Dict[str, Any]) -> bool:
        """Check if a policy statement references AppSync or removed resources."""
        action = stmt.get("Action")
        resource = stmt.get("Resource")

        # Remove if action contains appsync:GraphQL
        if isinstance(action, str) and "appsync:GraphQL" in action:
            return True
        if isinstance(action, list) and any(
            "appsync:GraphQL" in str(a) for a in action
        ):
            return True

        # Remove if references ExternalMCPAgentsSecret (removed resource)
        if self._references_removed_resource(resource, "ExternalMCPAgentsSecret"):
            return True

        return False

    def _references_removed_resource(self, resource: Any, ref_name: str) -> bool:
        """Check if a resource reference points to a removed resource."""
        if isinstance(resource, dict) and resource.get("Ref") == ref_name:
            return True
        if isinstance(resource, list):
            return any(
                isinstance(r, dict) and r.get("Ref") == ref_name for r in resource
            )
        return False

    def _clean_nested_stack_params(
        self, resources: Dict[str, Any], stack_name: str
    ) -> None:
        """Clean nested stack parameters for headless deployment."""
        stack_params = resources[stack_name].get("Properties", {}).get("Parameters", {})

        if "EnableHITL" in stack_params:
            stack_params["EnableHITL"] = "false"
            logger.debug(f"Hardcoded EnableHITL to false in {stack_name}")

        if "SageMakerA2IReviewPortalURL" in stack_params:
            stack_params["SageMakerA2IReviewPortalURL"] = '""'
            logger.debug(
                f"Hardcoded SageMakerA2IReviewPortalURL to empty in {stack_name}"
            )

        if "AppSyncApiUrl" in stack_params:
            del stack_params["AppSyncApiUrl"]
            logger.debug(f"Removed AppSyncApiUrl parameter from {stack_name}")

        if "AppSyncApiArn" in stack_params:
            del stack_params["AppSyncApiArn"]
            logger.debug(f"Removed AppSyncApiArn parameter from {stack_name}")

        # Discovery-related parameters (resources removed in headless)
        # The nested stack declares Default: "" for DiscoveryBucket and
        # DiscoveryTrackingTable, so we can simply delete the parameters
        # and let CloudFormation use the defaults.
        for param in [
            "DiscoveryBucket",
            "DiscoveryTrackingTable",
            "DiscoveryBucketName",
            "DiscoveryTrackingTableName",
            "MultiDocDiscoveryStateMachineArn",
        ]:
            if param in stack_params:
                del stack_params[param]
                logger.debug(f"Removed {param} parameter from {stack_name}")

        # Remove dependencies on GraphQLApi
        stack_deps = resources[stack_name].get("DependsOn", [])
        if isinstance(stack_deps, list) and "GraphQLApi" in stack_deps:
            resources[stack_name]["DependsOn"] = [
                dep for dep in stack_deps if dep != "GraphQLApi"
            ]
            logger.debug(f"Removed GraphQLApi dependency from {stack_name}")
        elif stack_deps == "GraphQLApi":
            del resources[stack_name]["DependsOn"]
            logger.debug(f"Removed GraphQLApi dependency from {stack_name}")

    def _fix_kb_condition_references(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Fix ShouldUseDocumentKnowledgeBase condition references."""
        template_str = yaml.dump(template, default_flow_style=False)
        if "ShouldUseDocumentKnowledgeBase" in template_str:
            template_str = re.sub(
                r"ShouldUseDocumentKnowledgeBase:\s*\n\s*Fn::If:\s*\n\s*-\s*ShouldUseDocumentKnowledgeBase\s*\n\s*-\s*true\s*\n\s*-\s*false",
                "ShouldUseDocumentKnowledgeBase: false",
                template_str,
                flags=re.MULTILINE,
            )
            template = yaml.safe_load(template_str)
            logger.warning(
                "⚠️  Fixed ShouldUseDocumentKnowledgeBase condition reference"
            )
            logger.warning(
                "   Note: Knowledge Base functionality disabled for headless deployment"
            )
        return template

    def _clean_orphaned_outputs(self, template: Dict[str, Any]) -> None:
        """Remove outputs that reference removed resources."""
        outputs = template.get("Outputs", {})
        outputs_to_clean: List[str] = []

        for output_name, output_def in outputs.items():
            if isinstance(output_def, dict):
                output_value = output_def.get("Value", {})
                if isinstance(output_value, dict):
                    if output_value.get("Ref") in ("AgentTable", "WebUIBucket"):
                        outputs_to_clean.append(output_name)
                    elif "AgentTable" in str(output_value):
                        outputs_to_clean.append(output_name)

        for output_name in outputs_to_clean:
            if output_name in outputs:
                del outputs[output_name]
                logger.debug(
                    f"Removed output {output_name} (references removed resource)"
                )

    def _clean_update_settings_values(self, template: Dict[str, Any]) -> None:
        """Fix UpdateSettingsValues custom resource — remove references to removed resources."""
        resources = template.get("Resources", {})
        if "UpdateSettingsValues" not in resources:
            return

        update_settings = resources["UpdateSettingsValues"]
        settings_kvp = update_settings.get("Properties", {}).get(
            "SettingsKeyValuePairs", {}
        )

        if "KnowledgeBaseId" in settings_kvp:
            settings_kvp["KnowledgeBaseId"] = ""
            logger.debug("Replaced KnowledgeBaseId with empty string")

        if "ShouldUseDocumentKnowledgeBase" in settings_kvp:
            settings_kvp["ShouldUseDocumentKnowledgeBase"] = False
            logger.debug("Set ShouldUseDocumentKnowledgeBase to False")

        if "AllowedSignUpEmailDomains" in settings_kvp:
            del settings_kvp["AllowedSignUpEmailDomains"]
            logger.debug("Removed AllowedSignUpEmailDomains from UpdateSettingsValues")

        # Remove Discovery-related settings (resources removed in headless)
        # plus the public-template version-check settings (UI-only feature
        # whose resolver and parameters are removed in headless mode).
        for key in [
            "DiscoveryBucket",
            "PublicArtifactsBucket",
            "PublicArtifactsPrefix",
        ]:
            if key in settings_kvp:
                del settings_kvp[key]
                logger.debug(f"Removed {key} from UpdateSettingsValues")

    def _clean_cloudfront_policy_statements(
        self, template: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Remove CloudFront-related policy statements from remaining resources."""
        logger.info("Removing CloudFront policy statements from remaining resources")
        resources = template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            if not isinstance(resource_def, dict):
                continue

            if resource_def.get("Type") == "AWS::S3::BucketPolicy":
                policy_doc = resource_def.get("Properties", {}).get(
                    "PolicyDocument", {}
                )
                self._clean_policy_document_cloudfront(policy_doc, resource_name)

            elif resource_def.get("Type") == "AWS::IAM::Role":
                policies = resource_def.get("Properties", {}).get("Policies", [])
                for policy in policies:
                    if isinstance(policy, dict) and "PolicyDocument" in policy:
                        policy_name = policy.get("PolicyName", "unnamed")
                        self._clean_policy_document_cloudfront(
                            policy["PolicyDocument"],
                            f"{resource_name}.{policy_name}",
                        )

        return template

    def _clean_policy_document_cloudfront(
        self, policy_doc: Dict[str, Any], resource_identifier: str
    ) -> None:
        """Clean CloudFront-related statements from a policy document."""
        if not isinstance(policy_doc, dict) or "Statement" not in policy_doc:
            return

        statements = policy_doc["Statement"]
        if not isinstance(statements, list):
            return

        cleaned_statements: List[Any] = []
        for statement in statements:
            if not isinstance(statement, dict):
                cleaned_statements.append(statement)
                continue

            principal = statement.get("Principal", {})
            should_remove = False

            if isinstance(principal, dict):
                service = principal.get("Service")
                if isinstance(service, str) and "cloudfront." in service.lower():
                    should_remove = True
                elif isinstance(service, dict) and "Fn::Sub" in service:
                    fn_sub_value = service["Fn::Sub"]
                    if (
                        isinstance(fn_sub_value, str)
                        and "cloudfront." in fn_sub_value.lower()
                    ):
                        should_remove = True
                elif isinstance(service, list):
                    filtered = []
                    for s in service:
                        keep = True
                        if isinstance(s, str) and "cloudfront." in s.lower():
                            keep = False
                        elif isinstance(s, dict) and "Fn::Sub" in s:
                            fn_sub = s["Fn::Sub"]
                            if (
                                isinstance(fn_sub, str)
                                and "cloudfront." in fn_sub.lower()
                            ):
                                keep = False
                        if keep:
                            filtered.append(s)
                    if not filtered:
                        should_remove = True
                    elif len(filtered) != len(service):
                        statement = statement.copy()
                        statement["Principal"] = principal.copy()
                        statement["Principal"]["Service"] = filtered

            if not should_remove:
                cleaned_statements.append(statement)

        policy_doc["Statement"] = cleaned_statements

    def _clean_parameter_groups(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Clean parameter groups in Metadata to remove references to deleted parameters."""
        metadata = template.get("Metadata", {})
        interface = metadata.get("AWS::CloudFormation::Interface", {})
        parameter_groups = interface.get("ParameterGroups", [])

        if not parameter_groups:
            return template

        cleaned_groups: List[Any] = []
        for group in parameter_groups:
            group_label = group.get("Label", {}).get("default", "")
            if group_label in self.parameter_groups_to_remove:
                logger.debug(f"Removing parameter group: {group_label}")
                continue

            original_params = group.get("Parameters", [])
            cleaned_params = [
                p for p in original_params if p not in self.parameters_to_remove
            ]
            if cleaned_params:
                group["Parameters"] = cleaned_params
                cleaned_groups.append(group)

        interface["ParameterGroups"] = cleaned_groups

        # Clean parameter labels
        parameter_labels = interface.get("ParameterLabels", {})
        for param_name in list(parameter_labels.keys()):
            if param_name in self.parameters_to_remove:
                del parameter_labels[param_name]

        return template

    def _update_configuration_maps_for_govcloud(
        self, template: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update configuration maps and parameters for GovCloud defaults."""
        logger.info("Updating configuration maps for GovCloud deployment")

        mappings = template.get("Mappings", {})
        parameters = template.get("Parameters", {})

        if "ConfigurationMap" in mappings:
            mappings["ConfigurationMap"]["lending-package-sample-govcloud"] = {
                "ConfigPath": "lending-package-sample-govcloud"
            }
            logger.debug("Added lending-package-sample-govcloud to ConfigurationMap")

        if "ConfigurationPreset" in parameters:
            parameters["ConfigurationPreset"]["Default"] = (
                "lending-package-sample-govcloud"
            )
            allowed_values = parameters["ConfigurationPreset"].get("AllowedValues", [])
            if "lending-package-sample-govcloud" not in allowed_values:
                allowed_values.insert(0, "lending-package-sample-govcloud")
                parameters["ConfigurationPreset"]["AllowedValues"] = allowed_values
            logger.info(
                "Updated ConfigurationPreset default to 'lending-package-sample-govcloud'"
            )

        return template

    def _update_arn_partitions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Check and fix any hard-coded ARN partitions."""
        logger.info("Checking ARN partitions")
        template_str = yaml.dump(template, default_flow_style=False)

        remaining_arns = len(
            re.findall(r"arn:aws:(?!\$\{AWS::Partition\})", template_str)
        )
        if remaining_arns > 0:
            logger.warning(f"Found {remaining_arns} hard-coded ARN references — fixing")
            template_str = re.sub(
                r"arn:aws:(?!\$\{AWS::Partition\})",
                "arn:${AWS::Partition}:",
                template_str,
            )
            template = yaml.safe_load(template_str)
            logger.info(f"Fixed {remaining_arns} hard-coded ARN references")
        else:
            logger.info("✅ All ARN references are already partition-aware")

        return template

    def _update_description(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Update template description to indicate headless version."""
        current_description = template.get("Description", "")
        if (
            "Headless" not in current_description
            and "GovCloud" not in current_description
        ):
            template["Description"] = current_description + " (Headless)"
            logger.debug("Updated template description for headless deployment")
        return template
