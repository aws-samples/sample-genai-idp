# Local Development with Docker Compose

This guide explains how to run the full FAST stack locally using Docker Compose for development purposes.

## Prerequisites

**Important**: Local development still requires a deployed FAST stack in AWS for backend dependencies (Memory, Gateway, SSM parameters). Docker Compose only containerizes the frontend and agent - it doesn't replace AWS services.

### Required

1. **Deployed FAST Stack**: You must have already deployed FAST to AWS using:
   ```bash
   cd infra-cdk
   cdk deploy
   ```

2. **AWS Credentials**: AWS credentials **must be exported as environment variables** — the Docker containers cannot read from `~/.aws/credentials` or `~/.aws/config`:
   ```bash
   # Option 1: Export from your existing aws configure profile
   export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
   export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
   export AWS_SESSION_TOKEN=$(aws configure get aws_session_token)  # if using temporary credentials

   # Option 2: Set directly
   export AWS_ACCESS_KEY_ID=your-key
   export AWS_SECRET_ACCESS_KEY=your-secret
   export AWS_SESSION_TOKEN=your-token  # if using temporary credentials
   ```

3. **Docker & Docker Compose**: Install Docker Desktop or Docker Engine with Compose support

4. **Environment Variables**: Set the following required variables:
   ```bash
   export MEMORY_ID=your-memory-id
   export STACK_NAME=your-stack-name
   export AWS_DEFAULT_REGION=us-east-1
   ```

### Finding Your Environment Variables

Get these values from your deployed stack:

```bash
# Get stack outputs
aws cloudformation describe-stacks --stack-name your-stack-name --query 'Stacks[0].Outputs'

# Extract Memory ID from MemoryArn (last part after the final /)
# Extract Stack Name (the name you used when deploying)
# Use the same region where you deployed
```

## Quick Start

1. **Set Environment Variables**:
   ```bash
   export MEMORY_ID=your-memory-id-from-stack-outputs
   export STACK_NAME=your-stack-name
   export AWS_DEFAULT_REGION=us-east-1
   ```

2. **Start the Stack**:
   ```bash
   cd docker && docker compose up --build
   ```

3. **Access the Application**:
   - Frontend: http://localhost:3000
   - Agent API: http://localhost:8080
   - Agent Health: http://localhost:8080/ping

## Authentication in Local Mode

In production, AgentCore Runtime validates the user's JWT and passes it to the agent. The agent extracts the user ID from the JWT's `sub` claim rather than trusting the request payload (preventing impersonation via prompt injection).

When running locally via Docker Compose, there is no AgentCore Runtime. The test scripts generate a mock unsigned JWT with a test user ID as the `sub` claim and send it in the `Authorization: Bearer` header. This exercises the same code path as production without requiring a real Cognito token.

## Environment Configuration

Create a `.env` file in the repository root for convenience:

```bash
# Required - from your deployed AWS stack
MEMORY_ID=your-memory-id
STACK_NAME=your-stack-name
AWS_DEFAULT_REGION=us-east-1

# AWS Credentials (required - Docker containers cannot read ~/.aws/credentials)
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_SESSION_TOKEN=your-token
```

Then run: `cd docker && docker compose up --build`

## Development Workflow

### Making Changes

- **Frontend Changes**: Files are mounted as volumes, so changes appear immediately
- **Agent Changes**: Rebuild the agent container:
  ```bash
  cd docker && docker compose up --build agent
  ```

### Using Different Agent Patterns

To use a different agent pattern (e.g., LangGraph):

1. **Edit docker/docker-compose.yml**:
   ```yaml
   agent:
     build:
       dockerfile: patterns/langgraph-single-agent/Dockerfile
   ```

2. **Rebuild**:
   ```bash
   cd docker && docker compose up --build agent
   ```

### Logs and Debugging

```bash
# View all logs
docker compose logs -f

# View specific service logs
docker compose logs -f agent
docker compose logs -f frontend

# Access container shell
docker compose exec agent bash
docker compose exec frontend sh
```

## Troubleshooting

### Agent Won't Start

**Symptoms**: Agent container exits or health check fails

**Solutions**:
1. Verify AWS credentials: `aws sts get-caller-identity`
2. Check environment variables are set correctly
3. Ensure deployed stack exists and is healthy
4. Check agent logs: `docker compose logs agent`

### Frontend Can't Connect to Agent

**Symptoms**: Frontend loads but can't communicate with backend

**Solutions**:
1. Verify agent is healthy: `curl http://localhost:8080/ping`
2. Check network connectivity between containers
3. Ensure frontend is configured to use local agent endpoint

### AWS Permission Errors

**Symptoms**: Agent starts but fails on AWS API calls

**Solutions**:
1. Verify IAM permissions for your AWS credentials
2. Check that the deployed stack resources are accessible
3. Ensure correct AWS region is set

### Memory/Gateway Not Found

**Symptoms**: Agent reports missing Memory or Gateway resources

**Solutions**:
1. Verify `MEMORY_ID` matches the deployed stack's Memory resource
2. Check `STACK_NAME` matches your CloudFormation stack name
3. Ensure stack deployment completed successfully

## Stopping the Stack

```bash
# Stop all services
cd docker && docker compose down

# Stop and remove volumes
cd docker && docker compose down -v

# Stop and remove images
cd docker && docker compose down --rmi all
```

## Production Deployment

This Docker Compose setup is for development only. For production deployment, use:

```bash
cd infra-cdk
cdk deploy
cd ..
python scripts/deploy-frontend.py
```

## Next Steps

- Customize the agent code in `patterns/`
- Modify the frontend in `frontend/src/`
- Add new tools in `tools/` or `gateway/tools/`
- Update infrastructure in `infra-cdk/`

Remember: Changes to infrastructure require redeployment via CDK, not just Docker Compose restart.