# AgentCore Code Interpreter Integration

This document explains the architectural decisions for integrating Amazon Bedrock AgentCore Code Interpreter into FAST.

## What is AgentCore Code Interpreter?

Amazon Bedrock AgentCore Code Interpreter is a fully managed capability that enables AI agents to execute code securely in isolated sandbox environments. Key features:

- Secure code execution in containerized environments
- Multiple language support (Python, JavaScript, TypeScript)
- Pre-built runtimes with common libraries
- Session management with state persistence
- Long execution duration (default 15 minutes, up to 8 hours)

**Documentation**: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html

## Why Direct Integration (Not Gateway)?

FAST integrates Code Interpreter **directly into agents** rather than through the Gateway. Here's why:

### Approach 1: Direct Integration ✅ (Chosen)

**Architecture**: `Agent → Code Interpreter SDK → Code Interpreter Service`

**Pros**:
- **Simpler implementation** - Minimal code, no additional infrastructure
- **Lower latency** - No Gateway/Lambda hops
- **Lower cost** - No Lambda invocations
- **Session management** - Code Interpreter maintains state across calls
- **Follows AWS patterns** - Matches official documentation examples
- **Better error handling** - Direct access to Code Interpreter errors

**Cons**:
- Not discoverable through Gateway
- Requires agent redeployment for updates
- Tool logic lives in agent code

### Approach 2: Gateway Integration ❌ (Not Chosen)

**Architecture**: `Agent → Gateway → Lambda → Code Interpreter SDK → Code Interpreter Service`

**Pros**:
- Consistent with Gateway pattern
- Discoverable through MCP
- Independent deployment

**Cons**:
- **More complex** - Lambda wrapper + Gateway target + IAM roles
- **Higher latency** - Additional hops in request path
- **Higher cost** - Lambda invocations + Code Interpreter usage
- **Session complexity** - Lambda must manage sessions across cold starts
- **No AWS references** - No official examples of this pattern
- **Not intended use case** - Code Interpreter is a built-in service, not a custom tool

### Decision Rationale

Code Interpreter is a **built-in AgentCore service**, similar to Bedrock models or AgentCore Memory. AWS designed it for direct integration, not to be proxied through Gateway. Gateway is meant for **custom Lambda-based tools**, not built-in services.

**Comparison**:
| Aspect | Direct | Gateway |
|--------|--------|---------|
| Complexity | Low | High |
| Latency | ~100ms | ~300-500ms |
| Cost | CI only | Lambda + CI |
| AWS Pattern | ✅ Documented | ❌ No examples |
| Use Case | Built-in service | Custom tools |

## Implementation Architecture

FAST uses a **layered architecture** for reusability across agent patterns:

```
tools/code_interpreter/
└── code_interpreter_tools.py          # Core logic (framework-agnostic)

patterns/strands-single-agent/
├── strands_code_interpreter.py        # Strands wrapper (@tool decorator)
└── basic_agent.py                     # Agent implementation

patterns/langgraph-single-agent/
└── tools/
    └── langgraph_execute_python.py    # LangGraph wrapper (ready for future)
```

### Design Principles

1. **Core logic is framework-agnostic** - No Strands/LangGraph dependencies in `tools/code_interpreter/`
2. **Pattern-specific wrappers** - Each framework has its own wrapper with appropriate decorators
3. **Reusability** - Core tool can be used by any agent pattern
4. **Maintainability** - Bug fixes in core benefit all patterns

### Key Components

**Core Tool** (`tools/code_interpreter/code_interpreter_tools.py`):
- Framework-agnostic Code Interpreter client
- Lazy initialization for performance
- Session management with cleanup support

**Strands Wrapper** (`patterns/strands-single-agent/strands_code_interpreter.py`):
- Adds Strands `@tool` decorator
- Delegates to core tool
- Located at pattern root for easy imports

**Agent Integration** (`patterns/strands-single-agent/basic_agent.py`):
- Imports wrapper: `from strands_code_interpreter import StrandsCodeInterpreterTools`
- Registers tool: `tools=[gateway_client, code_tools.execute_python_securely]`

### Dockerfile Changes

The Dockerfile copies both core tools and pattern-specific wrappers:

```dockerfile
# Copy core tools (reusable)
COPY tools/ tools/

# Copy pattern-specific wrapper
COPY patterns/strands-single-agent/strands_code_interpreter.py .
```

Working directory is `/app/`, so imports work naturally:
- `from tools.code_interpreter.code_interpreter_tools import CodeInterpreterTools`
- `from strands_code_interpreter import StrandsCodeInterpreterTools`

## Benefits of This Architecture

1. **Reusability**: Core logic shared across Strands, LangGraph, and future patterns
2. **Maintainability**: Bug fixes in core benefit all patterns
3. **Testability**: Core logic can be unit tested independently
4. **Extensibility**: Easy to add new agent patterns - just create a wrapper
5. **Performance**: Direct integration = lower latency
6. **Cost**: No Lambda overhead
7. **Simplicity**: Follows AWS documented patterns

## Usage

The agent automatically uses Code Interpreter when users request code execution:

**Example prompts**:
- "Calculate the factorial of 20"
- "Create a list of the first 50 Fibonacci numbers"
- "Generate 100 random numbers and calculate statistics"

The tool is registered as `execute_python_securely` to emphasize security vs built-in Python execution.

## Session Management

- **Automatic**: Code Interpreter creates sessions on first use
- **Persistence**: Sessions maintain state across multiple calls (`clearContext=False`)
- **Cleanup**: AgentCore automatically cleans up inactive sessions after timeout
- **Manual cleanup**: Optional via `cleanup()` method for immediate resource release

## Testing

**Local Docker Build**:
```bash
docker build -f patterns/strands-single-agent/Dockerfile -t test-agent .
docker run --rm test-agent python -c "from strands_code_interpreter import StrandsCodeInterpreterTools; print('✓ Import successful')"
```

**Deployment**:
```bash
cd infra-cdk
cdk deploy
```

**Frontend Testing**: Use prompts that require code execution to verify functionality.

## Future Enhancements

Potential improvements:
- Add `write_files` tool for file operations
- Add `list_files` tool to see sandbox contents
- Support JavaScript/TypeScript execution
- Add file upload from S3
- Implement custom timeout configuration

## References

- [AgentCore Code Interpreter Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html)
- [AWS IDP Reference Implementation](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws)
- [FAST Gateway Documentation](./GATEWAY.md)
