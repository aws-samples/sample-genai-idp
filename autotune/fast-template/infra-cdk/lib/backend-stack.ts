import * as cdk from "aws-cdk-lib"
import * as cognito from "aws-cdk-lib/aws-cognito"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as iam from "aws-cdk-lib/aws-iam"
import * as ssm from "aws-cdk-lib/aws-ssm"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import * as dynamodb from "aws-cdk-lib/aws-dynamodb"
import * as apigateway from "aws-cdk-lib/aws-apigateway"
import * as logs from "aws-cdk-lib/aws-logs"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha"
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore"
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets"
import * as cr from "aws-cdk-lib/custom-resources"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"
import { AgentCoreRole } from "./utils/agentcore-role"
import * as path from "path"
import * as fs from "fs"

export interface BackendStackProps extends cdk.NestedStackProps {
  config: AppConfig
  userPoolId: string
  userPoolClientId: string
  userPoolDomain: cognito.UserPoolDomain
  frontendUrl: string
}

export class BackendStack extends cdk.NestedStack {
  public readonly userPoolId: string
  public readonly userPoolClientId: string
  public readonly userPoolDomain: cognito.UserPoolDomain
  public optimizationStateApiUrl: string
  public runtimeArn: string
  // public memoryArn: string  // Disabled — see AgentCore Memory comment in createAgentRuntime()
  private agentName: cdk.CfnParameter
  private userPool: cognito.IUserPool
  private machineClient: cognito.UserPoolClient
  private machineClientSecret: secretsmanager.Secret
  private runtimeCredentialProvider: cdk.CustomResource
  private agentRuntime: agentcore.Runtime
  private optimizationStateTableName: string
  private optimizationStateTableArn: string

  constructor(scope: Construct, id: string, props: BackendStackProps) {
    super(scope, id, props)

    // Store the Cognito values
    this.userPoolId = props.userPoolId
    this.userPoolClientId = props.userPoolClientId
    this.userPoolDomain = props.userPoolDomain

    // Import the Cognito resources from the other stack
    this.userPool = cognito.UserPool.fromUserPoolId(
      this,
      "ImportedUserPoolForBackend",
      props.userPoolId
    )
    // then create the user pool client
    cognito.UserPoolClient.fromUserPoolClientId(
      this,
      "ImportedUserPoolClient",
      props.userPoolClientId
    )

    // Create Machine-to-Machine authentication components
    this.createMachineAuthentication(props.config)

    // DEPLOYMENT ORDER EXPLANATION:
    // 1. Cognito User Pool & Client (created in separate CognitoStack)
    // 2. Machine Client & Resource Server (created above for M2M auth)
    // 3. AgentCore Gateway (created next - uses machine client for auth)
    // 4. AgentCore Runtime (created last - independent of gateway)
    //
    // This order ensures that authentication components are available before
    // the gateway that depends on them, while keeping the runtime separate
    // since it doesn't directly depend on the gateway.

    // Create AutoTune optimization state table (control plane for autonomous agent)
    // Must be created before the runtime so the table name env var is available.
    this.createOptimizationStateTable(props.config)

    // Create AgentCore Gateway (before Runtime)
    this.createAgentCoreGateway(props.config)

    // Create AgentCore Runtime resources
    this.createAgentCoreRuntime(props.config)

    // Store runtime ARN in SSM for frontend stack
    this.createRuntimeSSMParameters(props.config)

    // Store Cognito configuration in SSM for testing and frontend
    this.createCognitoSSMParameters(props.config)

    // Create API for optimization state (cancel + progress polling)
    this.createOptimizationStateApi(props.config, props.frontendUrl)
  }

  private createAgentCoreRuntime(config: AppConfig): void {
    const pattern = config.backend?.pattern || "strands-single-agent"

    // Parameters
    this.agentName = new cdk.CfnParameter(this, "AgentName", {
      type: "String",
      default: "FASTAgent",
      description: "Name for the agent runtime",
    })

    const stack = cdk.Stack.of(this)
    const deploymentType = config.backend.deployment_type

    // Create the agent runtime artifact based on deployment type
    let agentRuntimeArtifact: agentcore.AgentRuntimeArtifact
    let zipPackagerResource: cdk.CustomResource | undefined

    if (
      deploymentType === "zip" &&
      (pattern === "claude-agent-sdk-single-agent" || pattern === "claude-agent-sdk-multi-agent")
    ) {
      throw new Error(
        "claude-agent-sdk patterns require Docker deployment (deployment_type: docker) " +
          "because they need Node.js and the claude-code CLI installed at build time."
      )
    }

    if (deploymentType === "zip") {
      // ZIP DEPLOYMENT: Use Lambda to package and upload to S3 (no Docker required)
      const repoRoot = path.resolve(__dirname, "..", "..") // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      const patternDir = path.join(repoRoot, "patterns", pattern) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal

      // Create S3 bucket for agent code
      const agentCodeBucket = new s3.Bucket(this, "AgentCodeBucket", {
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        autoDeleteObjects: true,
        versioned: true,
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      })

      // Lambda to package agent code
      const packagerLambda = new lambda.Function(this, "ZipPackagerLambda", {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "zip-packager")), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
        timeout: cdk.Duration.minutes(10),
        memorySize: 1024,
        ephemeralStorageSize: cdk.Size.gibibytes(2),
      })

      agentCodeBucket.grantReadWrite(packagerLambda)

      // Read agent code files and encode as base64
      const agentCode: Record<string, string> = {}

      // Read pattern .py files
      for (const file of fs.readdirSync(patternDir)) {
        if (file.endsWith(".py")) {
          const content = fs.readFileSync(path.join(patternDir, file)) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
          agentCode[file] = content.toString("base64")
        }
      }

      // Read shared modules (gateway/, tools/)
      for (const module of ["gateway", "tools"]) {
        const moduleDir = path.join(repoRoot, module) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
        if (fs.existsSync(moduleDir)) {
          this.readDirRecursive(moduleDir, module, agentCode)
        }
      }

      // Read requirements
      const requirementsPath = path.join(patternDir, "requirements.txt") // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      const requirements = fs
        .readFileSync(requirementsPath, "utf-8")
        .split("\n")
        .map(line => line.trim())
        .filter(line => line && !line.startsWith("#"))

      // Create hash for change detection
      // We use this to trigger update when content changes
      const contentHash = this.hashContent(JSON.stringify({ requirements, agentCode }))

      // Custom Resource to trigger packaging
      const provider = new cr.Provider(this, "ZipPackagerProvider", {
        onEventHandler: packagerLambda,
      })

      zipPackagerResource = new cdk.CustomResource(this, "ZipPackager", {
        serviceToken: provider.serviceToken,
        properties: {
          BucketName: agentCodeBucket.bucketName,
          ObjectKey: "deployment_package.zip",
          Requirements: requirements,
          AgentCode: agentCode,
          ContentHash: contentHash,
        },
      })

      // Store bucket name in SSM for updates
      new ssm.StringParameter(this, "AgentCodeBucketNameParam", {
        parameterName: `/${config.stack_name_base}/agent-code-bucket`,
        stringValue: agentCodeBucket.bucketName,
        description: "S3 bucket for agent code deployment packages",
      })

      agentRuntimeArtifact = agentcore.AgentRuntimeArtifact.fromS3(
        {
          bucketName: agentCodeBucket.bucketName,
          objectKey: "deployment_package.zip",
        },
        agentcore.AgentCoreRuntime.PYTHON_3_12,
        ["opentelemetry-instrument", "basic_agent.py"]
      )
    } else {
      // DOCKER DEPLOYMENT: Use container-based deployment
      // Build context is the IDP Accelerator repo root so the Dockerfile can
      // COPY from autotune/agent/ and lib/ without duplicating code.
      // NOTE: The `exclude` list is for CDK's asset hasher, NOT for Docker.
      // Docker uses Dockerfile.dockerignore (already filters to 327KB).
      // Without these excludes, CDK scans the entire repo to compute a
      // change-detection hash, which hangs on large repos.
      agentRuntimeArtifact = agentcore.AgentRuntimeArtifact.fromAsset(
        path.resolve(__dirname, "..", "..", "..", ".."), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
        {
          platform: ecr_assets.Platform.LINUX_ARM64,
          file: `autotune/fast-template/patterns/${pattern}/Dockerfile`,
          exclude: [
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "docs",
            "images",
            "samples",
            "notebooks",
            "src",
            "tests",
            "memory-bank",
            "autotune/fast-template/frontend",
            "autotune/fast-template/infra-cdk/cdk.out",
            "autotune/fast-template/docs",
            "autotune/fast-template/tests",
          ],
        }
      )
    }

    // Configure network mode based on config.yaml settings.
    // PUBLIC: Runtime is accessible over the public internet (default).
    // VPC: Runtime is deployed into a user-provided VPC for private network isolation.
    //      The user must ensure their VPC has the necessary VPC endpoints for AWS services.
    //      See docs/DEPLOYMENT.md for the full list of required VPC endpoints.
    const networkConfiguration = this.buildNetworkConfiguration(config)

    // Configure JWT authorizer with Cognito
    const authorizerConfiguration = agentcore.RuntimeAuthorizerConfiguration.usingJWT(
      `https://cognito-idp.${stack.region}.amazonaws.com/${this.userPoolId}/.well-known/openid-configuration`,
      [this.userPoolClientId]
    )

    // Create AgentCore execution role
    const agentRole = new AgentCoreRole(this, "AgentCoreRole")

    // AgentCore Memory — DISABLED. The agent uses FileSessionManager on /mnt/workspace
    // for conversation history instead of AgentCoreMemorySessionManager.
    // To re-enable for long-term memory (semantic fact extraction across sessions),
    // uncomment this block and the MEMORY_ID env var below.
    // See autotune/docs/state-persistence.md for rationale.
    //
    // const memory = new cdk.CfnResource(this, "AgentMemory", {
    //   type: "AWS::BedrockAgentCore::Memory",
    //   properties: {
    //     Name: cdk.Names.uniqueResourceName(this, { maxLength: 48 }),
    //     EventExpiryDuration: 30,
    //     Description: `Short-term memory for ${config.stack_name_base} agent`,
    //     MemoryStrategies: [
    //       {
    //         SemanticMemoryStrategy: {
    //           Name: "FactExtractor",
    //           Namespaces: ["/facts/{actorId}"],
    //         },
    //       },
    //     ],
    //     MemoryExecutionRoleArn: agentRole.roleArn,
    //     Tags: {
    //       Name: `${config.stack_name_base}_Memory`,
    //       ManagedBy: "CDK",
    //     },
    //   },
    // })
    // const memoryId = memory.getAtt("MemoryId").toString()
    // const memoryArn = memory.getAtt("MemoryArn").toString()
    // this.memoryArn = memoryArn
    //
    // agentRole.addToPolicy(
    //   new iam.PolicyStatement({
    //     sid: "MemoryResourceAccess",
    //     effect: iam.Effect.ALLOW,
    //     actions: [
    //       "bedrock-agentcore:CreateEvent",
    //       "bedrock-agentcore:GetEvent",
    //       "bedrock-agentcore:ListEvents",
    //       "bedrock-agentcore:RetrieveMemoryRecords",
    //     ],
    //     resources: [memoryArn],
    //   })
    // )

    // Add SSM permissions for AgentCore Gateway URL lookup
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SSMParameterAccess",
        effect: iam.Effect.ALLOW,
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/${config.stack_name_base}/*`,
        ],
      })
    )

    // Add Code Interpreter permissions
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CodeInterpreterAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:StartCodeInterpreterSession",
          "bedrock-agentcore:StopCodeInterpreterSession",
          "bedrock-agentcore:InvokeCodeInterpreter",
        ],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:aws:code-interpreter/*`],
      })
    )

    // Add OAuth2 Credential Provider access for AgentCore Runtime
    // The @requires_access_token decorator performs a two-stage process:
    // 1. GetOauth2CredentialProvider - Looks up provider metadata (ARN, vendor config, grant types)
    // 2. GetResourceOauth2Token - Uses metadata to fetch the actual access token from Token Vault
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "OAuth2CredentialProviderAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-agentcore:GetOauth2CredentialProvider",
          "bedrock-agentcore:GetResourceOauth2Token",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:oauth2-credential-provider/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:token-vault/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/*`,
        ],
      })
    )

    // Add Secrets Manager access for OAuth2
    // AgentCore Runtime needs to read two secrets:
    // 1. Machine client secret (created by CDK)
    // 2. Token Vault OAuth2 secret (created by AgentCore Identity)
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SecretsManagerOAuth2Access",
        effect: iam.Effect.ALLOW,
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:/${config.stack_name_base}/machine_client_secret*`,
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:bedrock-agentcore-identity!default/oauth2/${config.stack_name_base}-runtime-gateway-auth*`,
        ],
      })
    )

    // AutoTune: Permissions for the agent to operate an existing IDP Accelerator stack.
    // The idpac tools use these services to manage configs, run inference, evaluate results,
    // and analyze documents. These are operational permissions (not deployment permissions).
    //
    // SECURITY: This policy intentionally EXCLUDES destructive actions:
    //   - No cloudformation:DeleteStack, UpdateStack, CreateStack
    //   - No s3:DeleteObject (agent should never delete IDP data)
    //   - No dynamodb:DeleteTable, DeleteItem on IDP tables
    //   - No lambda:DeleteFunction, UpdateFunctionCode
    //   - No iam:* (cannot escalate privileges)
    //
    // The agent has shell access for debugging (grep, cat, aws cli) but IAM is the
    // hard security boundary — even if the agent runs `aws cloudformation delete-stack`,
    // the API call is denied by IAM.
    //
    // TODO: Scope resource ARNs to specific IDP stack resources once stack name resolution
    //       is available at synth time (currently a runtime-only value from config.yaml).
    // TODO: Restrict network egress — agent container should have no internet access.
    //       Requires VPC configuration on the AgentCore runtime.
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "IDPStackReadAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          // Stack discovery and info (read-only)
          "cloudformation:DescribeStacks",
          "cloudformation:ListStacks",
          "cloudformation:DescribeStackResources",
          "cloudformation:ListStackResources",
          // S3: read configs, test sets, results, documents
          "s3:GetObject",
          "s3:ListBucket",
          "s3:HeadObject",
          "s3:GetBucketLocation",
          // DynamoDB: read document tracking and workflow status
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:DescribeTable",
          // SSM: read stack parameters
          "ssm:GetParameter",
          "ssm:GetParameters",
          // STS: identity verification
          "sts:GetCallerIdentity",
          // CloudWatch: read execution logs for debugging
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
          "logs:FilterLogEvents",
          // Step Functions: monitor document processing workflows
          "states:DescribeExecution",
          "states:ListExecutions",
          "states:DescribeStateMachine",
          // Bedrock: model invocation for discovery/analysis
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          // KMS: decrypt IDP stack's encrypted resources
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ],
        resources: ["*"],
      })
    )

    // AutoTune: Write permissions the agent needs to operate the IDP stack.
    // Separated from read access for clarity. These are the minimum write
    // actions needed for config upload, evaluation runs, and inference.
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "IDPStackWriteAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          // S3: upload configs, test sets, documents for processing
          "s3:PutObject",
          // SQS: submit documents for processing
          "sqs:SendMessage",
          "sqs:GetQueueUrl",
          "sqs:GetQueueAttributes",
          // Lambda: invoke IDP processing functions
          "lambda:InvokeFunction",
          "lambda:ListFunctions",
          "lambda:GetFunction",
          // DynamoDB: write config versions (upload_config uses PutItem)
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
        ],
        resources: ["*"], // TODO: scope to IDP stack resources
      })
    )

    // AutoTune: Explicit deny for destructive actions as defense-in-depth.
    // Even if an Allow is accidentally added elsewhere, these denies take precedence.
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyDestructiveActions",
        effect: iam.Effect.DENY,
        actions: [
          "cloudformation:DeleteStack",
          "cloudformation:CreateStack",
          "cloudformation:UpdateStack",
          "s3:DeleteObject",
          "s3:DeleteBucket",
          "dynamodb:DeleteTable",
          "lambda:DeleteFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "iam:*",
          "organizations:*",
          "account:*",
        ],
        resources: ["*"],
      })
    )

    // AutoTune: Read/write access to the optimization state table (control plane).
    // Separate from IDPStackAccess because this is our own table, not the IDP stack's.
    agentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "OptimizationStateTableAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
        ],
        resources: [this.optimizationStateTableArn],
      })
    )

    // Environment variables for the runtime
    const envVars: { [key: string]: string } = {
      AWS_REGION: stack.region,
      AWS_DEFAULT_REGION: stack.region,
      STACK_NAME: config.stack_name_base,
      GATEWAY_CREDENTIAL_PROVIDER_NAME: `${config.stack_name_base}-runtime-gateway-auth`, // Used by @requires_access_token decorator to look up the correct provider
      // AutoTune: The IDP Accelerator stack that this agent optimizes.
      IDP_STACK_NAME: config.autotune?.idp_stack_name || "",
      // AutoTune: DynamoDB table for optimization state (control plane).
      AUTOTUNE_STATE_TABLE: this.optimizationStateTableName,
      // AutoTune: Bedrock model ID for the optimization agent.
      AUTOTUNE_MODEL_ID: config.autotune?.model_id || "",
      // AgentCore Memory env vars removed (MEMORY_ID, USE_LONG_TERM_MEMORY, LTM_TOP_K,
      // LTM_RELEVANCE_SCORE). Agent uses FileSessionManager on /mnt/workspace instead.
      // Re-add MEMORY_ID here if re-enabling AgentCore Memory for LTM.
    }

    // Add claude-agent-sdk specific environment variable
    if (pattern === "claude-agent-sdk-single-agent" || pattern === "claude-agent-sdk-multi-agent") {
      envVars["CLAUDE_CODE_USE_BEDROCK"] = "1"
    }

    // Create the runtime using L2 construct
    // requestHeaderConfiguration allows the agent to read the Authorization header
    // from RequestContext.request_headers, which is needed to securely extract the
    // user ID from the validated JWT token (sub claim) instead of trusting the payload body.
    this.agentRuntime = new agentcore.Runtime(this, "Runtime", {
      runtimeName: `${config.stack_name_base.replace(/-/g, "_")}_${this.agentName.valueAsString}`,
      agentRuntimeArtifact: agentRuntimeArtifact,
      executionRole: agentRole,
      networkConfiguration: networkConfiguration,
      protocolConfiguration: agentcore.ProtocolType.HTTP,
      environmentVariables: envVars,
      authorizerConfiguration: authorizerConfiguration,
      requestHeaderConfiguration: {
        allowlistedHeaders: ["Authorization"],
      },
      description: `${pattern} agent runtime for ${config.stack_name_base}`,
    })

    // AGUI protocol override — CloudFormation doesn't support AGUI enum yet
    // (only MCP | HTTP | A2A). Runtime deploys as HTTP, which also works properly.
    // if (pattern.startsWith("agui-")) {
    //   const cfnRuntime = this.agentRuntime.node.defaultChild as cdk.CfnResource
    //   cfnRuntime.addPropertyOverride("ProtocolConfiguration", "AGUI")
    // }

    // Make sure that ZIP is uploaded before Runtime is created
    if (zipPackagerResource) {
      this.agentRuntime.node.addDependency(zipPackagerResource)
    }

    // Store the runtime ARN
    this.runtimeArn = this.agentRuntime.agentRuntimeArn

    // AutoTune: Enable persistent filesystem on the runtime (Preview feature).
    // The L2 construct will support `filesystemConfiguration` natively once
    // aws-cdk PR #35478 is released. Until then, use L1 escape hatch.
    // TODO: Replace with L2 prop when @aws-cdk/aws-bedrock-agentcore-alpha >= 2.252
    const cfnRuntime = this.agentRuntime.node.defaultChild as cdk.CfnResource
    cfnRuntime.addPropertyOverride("FilesystemConfigurations", [
      { SessionStorage: { MountPath: "/mnt/workspace" } },
    ])

    // Outputs
    new cdk.CfnOutput(this, "AgentRuntimeId", {
      description: "ID of the created agent runtime",
      value: this.agentRuntime.agentRuntimeId,
    })

    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      description: "ARN of the created agent runtime",
      value: this.agentRuntime.agentRuntimeArn,
      exportName: `${config.stack_name_base}-AgentRuntimeArn`,
    })

    new cdk.CfnOutput(this, "AgentRoleArn", {
      description: "ARN of the agent execution role",
      value: agentRole.roleArn,
    })

    // MemoryArn output — disabled, see AgentCore Memory comment above
    // new cdk.CfnOutput(this, "MemoryArn", {
    //   description: "ARN of the agent memory resource",
    //   value: memoryArn,
    // })
  }

  private createRuntimeSSMParameters(config: AppConfig): void {
    // Store runtime ARN in SSM for frontend stack
    new ssm.StringParameter(this, "RuntimeArnParam", {
      parameterName: `/${config.stack_name_base}/runtime-arn`,
      stringValue: this.runtimeArn,
    })
  }

  private createCognitoSSMParameters(config: AppConfig): void {
    // Store Cognito configuration in SSM for testing and frontend access
    new ssm.StringParameter(this, "CognitoUserPoolIdParam", {
      parameterName: `/${config.stack_name_base}/cognito-user-pool-id`,
      stringValue: this.userPoolId,
      description: "Cognito User Pool ID",
    })

    new ssm.StringParameter(this, "CognitoUserPoolClientIdParam", {
      parameterName: `/${config.stack_name_base}/cognito-user-pool-client-id`,
      stringValue: this.userPoolClientId,
      description: "Cognito User Pool Client ID",
    })

    new ssm.StringParameter(this, "MachineClientIdParam", {
      parameterName: `/${config.stack_name_base}/machine_client_id`,
      stringValue: this.machineClient.userPoolClientId,
      description: "Machine Client ID for M2M authentication",
    })

    // Use the correct Cognito domain format from the passed domain
    new ssm.StringParameter(this, "CognitoDomainParam", {
      parameterName: `/${config.stack_name_base}/cognito_provider`,
      stringValue: `${this.userPoolDomain.domainName}.auth.${cdk.Aws.REGION}.amazoncognito.com`,
      description: "Cognito domain URL for token endpoint",
    })
  }

  // Creates a DynamoDB table for AutoTune optimization state (control plane).
  // Read by hooks (cancel check), frontend (progress polling), and agent (state updates).
  // See autotune/planning-docs/full-autonomy-research.md section 6 for architecture.
  private createOptimizationStateTable(config: AppConfig): void {
    const table = new dynamodb.Table(this, "OptimizationStateTable", {
      tableName: `${config.stack_name_base}-OptimizationState`,
      partitionKey: {
        name: "session_id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    })

    // Store table name in SSM for frontend/external access
    new ssm.StringParameter(this, "OptimizationStateTableParam", {
      parameterName: `/${config.stack_name_base}/optimization-state-table`,
      stringValue: table.tableName,
      description: "DynamoDB table for AutoTune optimization state",
    })

    new cdk.CfnOutput(this, "OptimizationStateTableName", {
      description: "DynamoDB table for AutoTune optimization state",
      value: table.tableName,
    })

    // Store for env var injection (used in createAgentCoreRuntime)
    this.optimizationStateTableName = table.tableName
    this.optimizationStateTableArn = table.tableArn
  }

  // Creates a DynamoDB table for storing user feedback.
  /**
   * Creates an API Gateway with Lambda integration for optimization state.
   *
   * Endpoints:
   *   POST /cancel — Cancel a running optimization (body: { sessionId: string })
   *   GET  /state  — Get optimization state (query: ?sessionId=xxx)
   *
   * The DynamoDB item schema may evolve as development progresses.
   * GET /state returns the raw item — frontend should handle unknown/missing fields.
   */
  private createOptimizationStateApi(config: AppConfig, frontendUrl: string): void {
    const stateLambda = new PythonFunction(this, "OptimizationStateLambda", {
      functionName: `${config.stack_name_base}-optimization-state`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      entry: path.join(__dirname, "..", "lambdas", "feedback"), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      handler: "handler",
      environment: {
        TABLE_NAME: this.optimizationStateTableName,
        CORS_ALLOWED_ORIGINS: `${frontendUrl},http://localhost:3000`,
      },
      timeout: cdk.Duration.seconds(10),
      layers: [
        lambda.LayerVersion.fromLayerVersionArn(
          this,
          "PowertoolsLayer",
          `arn:aws:lambda:${
            cdk.Stack.of(this).region
          }:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-arm64:18`
        ),
      ],
      logGroup: new logs.LogGroup(this, "OptimizationStateLambdaLogGroup", {
        logGroupName: `/aws/lambda/${config.stack_name_base}-optimization-state`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Cancel needs write, state needs read
    stateLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["dynamodb:GetItem", "dynamodb:UpdateItem"],
        resources: [this.optimizationStateTableArn],
      })
    )

    const api = new apigateway.RestApi(this, "OptimizationStateApi", {
      restApiName: `${config.stack_name_base}-api`,
      description: "AutoTune optimization state and control API",
      defaultCorsPreflightOptions: {
        allowOrigins: [frontendUrl, "http://localhost:3000"],
        allowMethods: ["GET", "POST", "OPTIONS"],
        allowHeaders: ["Content-Type", "Authorization"],
      },
      deployOptions: {
        stageName: "prod",
        throttlingRateLimit: 100,
        throttlingBurstLimit: 200,
      },
    })

    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, "ApiAuthorizer", {
      cognitoUserPools: [this.userPool],
      identitySource: "method.request.header.Authorization",
    })

    const lambdaIntegration = new apigateway.LambdaIntegration(stateLambda)
    const authOptions = {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
    }

    api.root.addResource("cancel").addMethod("POST", lambdaIntegration, authOptions)
    api.root.addResource("state").addMethod("GET", lambdaIntegration, authOptions)

    this.optimizationStateApiUrl = api.url

    new ssm.StringParameter(this, "OptimizationStateApiUrlParam", {
      parameterName: `/${config.stack_name_base}/optimization-state-api-url`,
      stringValue: api.url,
      description: "AutoTune optimization state API URL",
    })
  }

  private createAgentCoreGateway(config: AppConfig): void {
    // Create sample tool Lambda
    const toolLambda = new lambda.Function(this, "SampleToolLambda", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "sample_tool_lambda.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../gateway/tools/sample_tool")), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      timeout: cdk.Duration.seconds(30),
      logGroup: new logs.LogGroup(this, "SampleToolLambdaLogGroup", {
        logGroupName: `/aws/lambda/${config.stack_name_base}-sample-tool`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Create comprehensive IAM role for gateway
    const gatewayRole = new iam.Role(this, "GatewayRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      description: "Role for AgentCore Gateway with comprehensive permissions",
    })

    // Lambda invoke permission
    toolLambda.grantInvoke(gatewayRole)

    // Bedrock permissions (region-agnostic)
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          "arn:aws:bedrock:*::foundation-model/*",
          `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
        ],
      })
    )

    // SSM parameter access
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/${config.stack_name_base}/*`,
        ],
      })
    )

    // Cognito permissions
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["cognito-idp:DescribeUserPoolClient", "cognito-idp:InitiateAuth"],
        resources: [this.userPool.userPoolArn],
      })
    )

    // CloudWatch Logs
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
        ],
      })
    )

    // Load tool specification from JSON file
    const toolSpecPath = path.join(__dirname, "../../gateway/tools/sample_tool/tool_spec.json") // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
    const apiSpec = JSON.parse(require("fs").readFileSync(toolSpecPath, "utf8"))

    // Cognito OAuth2 configuration for gateway
    const cognitoIssuer = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}`
    const cognitoDiscoveryUrl = `${cognitoIssuer}/.well-known/openid-configuration`

    // Create OAuth2 Credential Provider for AgentCore Runtime to authenticate with AgentCore Gateway
    // Uses cr.Provider pattern with explicit Lambda to avoid logging secrets in CloudWatch
    const providerName = `${config.stack_name_base}-runtime-gateway-auth`

    // Lambda to create/delete OAuth2 provider
    const oauth2ProviderLambda = new lambda.Function(this, "OAuth2ProviderLambda", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "oauth2-provider")), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      timeout: cdk.Duration.minutes(5),
      logGroup: new logs.LogGroup(this, "OAuth2ProviderLambdaLogGroup", {
        logGroupName: `/aws/lambda/${config.stack_name_base}-oauth2-provider`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Grant Lambda permissions to read machine client secret
    this.machineClientSecret.grantRead(oauth2ProviderLambda)

    // Grant Lambda permissions for Bedrock AgentCore operations
    // OAuth2 Credential Provider operations - scoped to all providers in default Token Vault
    // Note: Need both vault-level and nested resource permissions because:
    // - CreateOauth2CredentialProvider checks permission on vault itself (token-vault/default)
    // - Also checks permission on the nested resource path (token-vault/default/oauth2credentialprovider/*)
    oauth2ProviderLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateOauth2CredentialProvider",
          "bedrock-agentcore:DeleteOauth2CredentialProvider",
          "bedrock-agentcore:GetOauth2CredentialProvider",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:token-vault/default`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:token-vault/default/oauth2credentialprovider/*`,
        ],
      })
    )

    // Token Vault operations - scoped to default vault
    // Note: Need both exact match (default) and wildcard (default/*) because:
    // - AWS checks permission on the vault container itself (token-vault/default)
    // - AWS also checks permission on resources inside (token-vault/default/*)
    oauth2ProviderLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateTokenVault",
          "bedrock-agentcore:GetTokenVault",
          "bedrock-agentcore:DeleteTokenVault",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:token-vault/default`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:token-vault/default/*`,
        ],
      })
    )

    // Grant Lambda permissions for Token Vault secret management
    // Scoped to OAuth2 secrets in AgentCore Identity default namespace
    oauth2ProviderLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:PutSecretValue",
        ],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:bedrock-agentcore-identity!default/oauth2/*`,
        ],
      })
    )

    // Create Custom Resource Provider
    const oauth2Provider = new cr.Provider(this, "OAuth2ProviderProvider", {
      onEventHandler: oauth2ProviderLambda,
    })

    // Create Custom Resource
    const runtimeCredentialProvider = new cdk.CustomResource(this, "RuntimeCredentialProvider", {
      serviceToken: oauth2Provider.serviceToken,
      properties: {
        ProviderName: providerName,
        ClientSecretArn: this.machineClientSecret.secretArn,
        DiscoveryUrl: cognitoDiscoveryUrl,
        ClientId: this.machineClient.userPoolClientId,
      },
    })

    // Store for use in createAgentCoreRuntime()
    this.runtimeCredentialProvider = runtimeCredentialProvider

    // Create Gateway using L1 construct (CfnGateway)
    // This replaces the Custom Resource approach with native CloudFormation support
    const gateway = new bedrockagentcore.CfnGateway(this, "AgentCoreGateway", {
      name: `${config.stack_name_base}-gateway`,
      roleArn: gatewayRole.roleArn,
      protocolType: "MCP",
      protocolConfiguration: {
        mcp: {
          supportedVersions: ["2025-03-26"],
          // Optional: Enable semantic search for tools
          // searchType: "SEMANTIC",
        },
      },
      authorizerType: "CUSTOM_JWT",
      authorizerConfiguration: {
        customJwtAuthorizer: {
          allowedClients: [this.machineClient.userPoolClientId],
          discoveryUrl: cognitoDiscoveryUrl,
        },
      },
      description: "AgentCore Gateway with MCP protocol and JWT authentication",
    })

    // Create Gateway Target using L1 construct (CfnGatewayTarget)
    const gatewayTarget = new bedrockagentcore.CfnGatewayTarget(this, "GatewayTarget", {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: "sample-tool-target",
      description: "Sample tool Lambda target",
      targetConfiguration: {
        mcp: {
          lambda: {
            lambdaArn: toolLambda.functionArn,
            toolSchema: {
              inlinePayload: apiSpec,
            },
          },
        },
      },
      credentialProviderConfigurations: [
        {
          credentialProviderType: "GATEWAY_IAM_ROLE",
        },
      ],
    })

    // Ensure proper creation order
    gatewayTarget.addDependency(gateway)
    gateway.node.addDependency(toolLambda)
    gateway.node.addDependency(this.machineClient)
    gateway.node.addDependency(gatewayRole)

    // Store AgentCore Gateway URL in SSM for AgentCore Runtime access
    new ssm.StringParameter(this, "GatewayUrlParam", {
      parameterName: `/${config.stack_name_base}/gateway_url`,
      stringValue: gateway.attrGatewayUrl,
      description: "AgentCore Gateway URL",
    })

    // Output gateway information
    new cdk.CfnOutput(this, "GatewayId", {
      value: gateway.attrGatewayIdentifier,
      description: "AgentCore Gateway ID",
    })

    new cdk.CfnOutput(this, "GatewayUrl", {
      value: gateway.attrGatewayUrl,
      description: "AgentCore Gateway URL",
    })

    new cdk.CfnOutput(this, "GatewayArn", {
      value: gateway.attrGatewayArn,
      description: "AgentCore Gateway ARN",
    })

    new cdk.CfnOutput(this, "GatewayTargetId", {
      value: gatewayTarget.ref,
      description: "AgentCore Gateway Target ID",
    })

    new cdk.CfnOutput(this, "ToolLambdaArn", {
      description: "ARN of the sample tool Lambda",
      value: toolLambda.functionArn,
    })
  }

  private createMachineAuthentication(config: AppConfig): void {
    // Create Resource Server for Machine-to-Machine (M2M) authentication
    // This defines the API scopes that machine clients can request access to
    const resourceServer = new cognito.UserPoolResourceServer(this, "ResourceServer", {
      userPool: this.userPool,
      identifier: `${config.stack_name_base}-gateway`,
      userPoolResourceServerName: `${config.stack_name_base}-gateway-resource-server`,
      scopes: [
        new cognito.ResourceServerScope({
          scopeName: "read",
          scopeDescription: "Read access to gateway",
        }),
        new cognito.ResourceServerScope({
          scopeName: "write",
          scopeDescription: "Write access to gateway",
        }),
      ],
    })

    // Create Machine Client for AgentCore Gateway authentication
    //
    // WHAT IS A MACHINE CLIENT?
    // A machine client is a Cognito User Pool Client configured for server-to-server authentication
    // using the OAuth2 Client Credentials flow. Unlike user-facing clients, it doesn't require
    // human interaction or user credentials.
    //
    // HOW IS IT DIFFERENT FROM THE REGULAR USER POOL CLIENT?
    // - Regular client: Uses Authorization Code flow for human users (frontend login)
    // - Machine client: Uses Client Credentials flow for service-to-service authentication
    // - Regular client: No client secret (public client for frontend security)
    // - Machine client: Has client secret (confidential client for backend security)
    // - Regular client: Scopes are openid, email, profile (user identity)
    // - Machine client: Scopes are custom resource server scopes (API permissions)
    //
    // WHY IS IT NEEDED?
    // The AgentCore Gateway needs to authenticate with Cognito to validate tokens and make
    // API calls on behalf of the system. The machine client provides the credentials for
    // this service-to-service authentication without requiring user interaction.
    this.machineClient = new cognito.UserPoolClient(this, "MachineClient", {
      userPool: this.userPool,
      userPoolClientName: `${config.stack_name_base}-machine-client`,
      generateSecret: true, // Required for client credentials flow
      oAuth: {
        flows: {
          clientCredentials: true, // Enable OAuth2 Client Credentials flow
        },
        scopes: [
          // Grant access to the resource server scopes defined above
          cognito.OAuthScope.resourceServer(
            resourceServer,
            new cognito.ResourceServerScope({
              scopeName: "read",
              scopeDescription: "Read access to gateway",
            })
          ),
          cognito.OAuthScope.resourceServer(
            resourceServer,
            new cognito.ResourceServerScope({
              scopeName: "write",
              scopeDescription: "Write access to gateway",
            })
          ),
        ],
      },
    })

    // Machine client must be created after resource server
    this.machineClient.node.addDependency(resourceServer)

    // Store machine client secret in Secrets Manager for testing and external access.
    // This secret is used by test scripts and potentially other external tools.
    this.machineClientSecret = new secretsmanager.Secret(this, "MachineClientSecret", {
      secretName: `/${config.stack_name_base}/machine_client_secret`,
      secretStringValue: cdk.SecretValue.unsafePlainText(
        this.machineClient.userPoolClientSecret.unsafeUnwrap()
      ),
      description: "Machine Client Secret for M2M authentication",
    })
  }

  /**
   * Builds the RuntimeNetworkConfiguration based on the config.yaml settings.
   * When network_mode is "VPC", imports the user's existing VPC, subnets, and
   * optionally security groups, then returns a VPC-based network configuration.
   * When network_mode is "PUBLIC" (default), returns a public network configuration.
   *
   * @param config - The application configuration from config.yaml.
   * @returns A RuntimeNetworkConfiguration for the AgentCore Runtime.
   */
  private buildNetworkConfiguration(config: AppConfig): agentcore.RuntimeNetworkConfiguration {
    if (config.backend.network_mode === "VPC") {
      const vpcConfig = config.backend.vpc
      // vpc config is validated in ConfigManager, but guard here for type safety
      if (!vpcConfig) {
        throw new Error("backend.vpc configuration is required when network_mode is 'VPC'.")
      }

      // Import the user's existing VPC by ID.
      // This performs a context lookup at synth time to resolve VPC attributes.
      const vpc = ec2.Vpc.fromLookup(this, "ImportedVpc", {
        vpcId: vpcConfig.vpc_id,
      })

      // Import the user-specified subnets by their IDs.
      // These subnets must exist within the VPC specified above.
      const subnets: ec2.ISubnet[] = vpcConfig.subnet_ids.map((subnetId: string, index: number) =>
        ec2.Subnet.fromSubnetId(this, `ImportedSubnet${index}`, subnetId)
      )

      // Build the VPC config props for the AgentCore L2 construct.
      // Security groups are optional — if not provided, the construct creates a default one.
      const securityGroups =
        vpcConfig.security_group_ids && vpcConfig.security_group_ids.length > 0
          ? vpcConfig.security_group_ids.map((sgId: string, index: number) =>
              ec2.SecurityGroup.fromSecurityGroupId(this, `ImportedSG${index}`, sgId)
            )
          : undefined

      const vpcConfigProps: agentcore.VpcConfigProps = {
        vpc: vpc,
        vpcSubnets: {
          subnets: subnets,
        },
        securityGroups: securityGroups,
      }

      return agentcore.RuntimeNetworkConfiguration.usingVpc(this, vpcConfigProps)
    }

    // Default: public network mode
    return agentcore.RuntimeNetworkConfiguration.usingPublicNetwork()
  }

  /**
   * Recursively read directory contents and encode as base64.
   *
   * @param dirPath - Directory to read.
   * @param prefix - Prefix for file paths in output.
   * @param output - Output object to populate.
   */
  private readDirRecursive(dirPath: string, prefix: string, output: Record<string, string>): void {
    for (const entry of fs.readdirSync(dirPath, { withFileTypes: true })) {
      const fullPath = path.join(dirPath, entry.name) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      const relativePath = path.join(prefix, entry.name) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal

      if (entry.isDirectory()) {
        // Skip __pycache__ directories
        if (entry.name !== "__pycache__") {
          this.readDirRecursive(fullPath, relativePath, output)
        }
      } else if (entry.isFile()) {
        const content = fs.readFileSync(fullPath)
        output[relativePath] = content.toString("base64")
      }
    }
  }

  /**
   * Create a hash of content for change detection.
   *
   * @param content - Content to hash.
   * @returns Hash string.
   */
  private hashContent(content: string): string {
    const crypto = require("crypto")
    return crypto.createHash("sha256").update(content).digest("hex").slice(0, 16)
  }
}
