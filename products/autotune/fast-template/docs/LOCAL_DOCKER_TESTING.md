# Local Docker Testing Guide

Build and test your AgentCore agent Docker image locally to validate Dockerfile configuration and dependencies.

## LIMITATIONS

**Gateway tools will NOT work in standalone Docker testing** because:
- The `@requires_access_token` decorator requires AgentCore Identity service
- AgentCore Identity only operates within AgentCore Runtime context
- OAuth2 M2M authentication cannot be mocked outside Runtime

**What works:** Dockerfile builds, dependency installation, Code Interpreter, non-Gateway tools  
**What doesn't work:** AgentCore Gateway tools (MCP-based Lambda tools)

**For full local testing with Gateway support**, use `docker-compose` (see [Local Development Guide](LOCAL_DEVELOPMENT.md)).

## Why Docker Testing?

| Testing Mode | Gateway Tools | Code Interpreter | Use Case |
|--------------|---------------|------------------|----------|
| `test-agent.py --local` | Yes | Yes | Quick Python iteration |
| **Manual Docker** | No | Yes | Validate Dockerfile/dependencies |
| **`docker-compose`** | Yes | Yes | Full local development |
| `test-agent.py` (remote) | Yes | Yes | Test deployed agent |

Docker testing validates:
- Dockerfile builds correctly
- Dependencies install properly in container
- Container starts and responds to health checks
- Agent code runs in containerized environment (without Gateway tools)

## Prerequisites

1. **Docker** installed and running (`docker ps` should work)
2. **Deployed stack** - Required for Memory ID and SSM parameters
3. **AWS credentials** configured in your environment

## Building the Docker Image

```bash
# Build image for your agent pattern
docker build -f patterns/strands-single-agent/Dockerfile \
  -t fast-agent-local \
  --platform linux/arm64 .

# Or for LangGraph pattern
docker build -f patterns/langgraph-single-agent/Dockerfile \
  -t fast-agent-local \
  --platform linux/arm64 .
```

### Platform Requirements

AgentCore Runtime requires ARM64 architecture. On x86/amd64 machines, enable emulation:

```bash
# One-time setup for ARM64 emulation
docker run --privileged --rm tonistiigi/binfmt --install all
```

## Running the Container

```bash
# Get Memory ID from CloudFormation outputs
MEMORY_ID=$(aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`MemoryArn`].OutputValue' \
  --output text | awk -F'/' '{print $NF}')

# Export AWS credentials (required for container)
export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
export AWS_SESSION_TOKEN=$(aws configure get aws_session_token)  # if using temporary credentials

# Run container
docker run --rm -it -p 8080:8080 \
  --platform linux/arm64 \
  -e MEMORY_ID=$MEMORY_ID \
  -e STACK_NAME=<your-stack-name> \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  -e AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN \
  fast-agent-local
```

**Important:** AWS credentials must be exported as environment variables. The Docker container cannot read credentials from `~/.aws/credentials` or `~/.aws/config`.

## Testing the Agent

### Health Check

```bash
curl http://localhost:8080/ping
# Returns: {"status":"Healthy","time_of_last_update":...}
```

### Mock JWT for Testing

Since there's no AgentCore Runtime to provide a validated JWT, create a mock unsigned JWT:

```bash
# Generate mock JWT with sub=test-user
MOCK_JWT=$(python3 -c "import base64,json; h=base64.urlsafe_b64encode(json.dumps({'alg':'none','typ':'JWT'}).encode()).rstrip(b'=').decode(); p=base64.urlsafe_b64encode(json.dumps({'sub':'test-user'}).encode()).rstrip(b'=').decode(); print(f'{h}.{p}.')")

# Test agent (will fail on Gateway tools but Code Interpreter should work)
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MOCK_JWT" \
  -d '{"prompt": "Execute Python: print(2+2)", "runtimeSessionId": "test-123"}'
```

**Expected behavior:**
- Code Interpreter requests will work
- Gateway tool requests will fail with authentication errors

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Local Machine                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Docker Container (ARM64)                           │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │  Agent (basic_agent.py / langgraph_agent.py)│   │   │
│  │  │  - Listens on :8080                         │   │   │
│  │  │  - Uses passed AWS credentials              │   │   │
│  │  │  - Gateway auth will FAIL                   │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│              http://localhost:8080/invocations              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────────┐
              │  AWS (Deployed Resources)       │
              │  - AgentCore Memory      (Yes)  │
              │  - Code Interpreter      (Yes)  │
              │  - AgentCore Gateway     (No)   │
              │  - SSM Parameters        (Yes)  │
              └─────────────────────────────────┘
```

## Troubleshooting

### Container starts but Gateway authentication fails

This is **expected behavior**. The `@requires_access_token` decorator requires AgentCore Identity service, which only works within AgentCore Runtime.

**Solution:** Use `docker-compose` for full local testing (see [Local Development Guide](LOCAL_DEVELOPMENT.md)).

### Container starts but agent fails immediately

Check container logs:

```bash
# Find container ID
docker ps

# View logs
docker logs <container-id>
```

Common issues:
- **Missing AWS credentials**: Ensure `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` are set
- **Expired session token**: Refresh your AWS credentials
- **Stack not deployed**: The script needs a deployed stack to fetch Memory ID

### Build fails with "platform mismatch"

Enable ARM64 emulation (see Platform Requirements above).

### "Connection refused" on localhost:8080

The agent may still be starting. Wait 10-30 seconds and try again. Check logs if it persists.

### ECS/EKS warnings in logs

These warnings are expected when running locally:

```
AwsEcsResourceDetector failed: Missing ECS_CONTAINER_METADATA_URI...
AwsEksResourceDetector failed: No such file or directory...
```

The OpenTelemetry instrumentation looks for ECS/EKS metadata which doesn't exist locally. These can be safely ignored.

## Advanced Usage

### Viewing Container Logs in Real-Time

```bash
# Start container in foreground (not detached)
docker run --rm -p 8080:8080 \
  --platform linux/arm64 \
  -e MEMORY_ID=<memory-id> \
  -e STACK_NAME=<stack-name> \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  -e AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN \
  fast-agent-local
```

### Build-Only Validation

To validate Dockerfile without running:

```bash
docker build -f patterns/strands-single-agent/Dockerfile \
  -t fast-agent-local \
  --platform linux/arm64 .

# Check if build succeeded
echo $?  # Should return 0
```

## When to Use Each Testing Mode

| Scenario | Recommended Mode |
|----------|------------------|
| Quick iteration on agent logic | `test-agent.py --local` |
| Verify Dockerfile builds correctly | Manual Docker build |
| Test with Gateway tools locally | `docker-compose` (LOCAL_DEVELOPMENT.md) |
| Test deployed production agent | `test-agent.py` (remote) |
| CI/CD pipeline validation | Manual Docker build |

## Related Documentation

- [Local Development Guide](LOCAL_DEVELOPMENT.md) - Full local development with `docker-compose` and Gateway support
- [Deployment Guide](DEPLOYMENT.md) - Full stack deployment instructions
- [Agent Configuration](AGENT_CONFIGURATION.md) - Configuring agent patterns
- [Streaming Guide](STREAMING.md) - Understanding streaming events
