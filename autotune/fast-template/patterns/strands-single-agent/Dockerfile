# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary
#
# Build context: IDP Accelerator repo root (set by CDK in backend-stack.ts)

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# BYPASS_TOOL_CONSENT: Strands community tools (shell, file_write, editor) prompt
# for user confirmation by default. In a headless container there is no terminal to
# respond, so the agent would hang. This env var skips those prompts.
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    DOCKER_CONTAINER=1 \
    OTEL_PYTHON_LOG_CORRELATION=true \
    PYTHONUNBUFFERED=1 \
    BYPASS_TOOL_CONSENT=true

# --- FAST framework ---
COPY autotune/fast-template/pyproject.toml .
COPY autotune/fast-template/gateway/ gateway/
COPY autotune/fast-template/tools/ agentcore_tools/

# --- Agent requirements (FAST + AutoTune deps) ---
COPY autotune/fast-template/patterns/strands-single-agent/requirements.txt requirements.txt
RUN uv pip install --no-cache -r requirements.txt && \
    uv pip install --no-cache aws-opentelemetry-distro==0.16.0

# Install FAST package
RUN uv pip install --no-cache -e . --no-deps && \
    uv pip install --no-cache requests>=2.31.0

# --- IDP CLI chain: idp_common -> idp_sdk -> idp-cli ---
COPY lib/idp_common_pkg/ /app/lib/idp_common_pkg/
COPY lib/idp_sdk/ /app/lib/idp_sdk/
COPY lib/idp_cli_pkg/ /app/lib/idp_cli_pkg/
RUN uv pip install --no-cache \
    -e /app/lib/idp_common_pkg/ \
    -e /app/lib/idp_sdk/ \
    -e /app/lib/idp_cli_pkg/

# --- idpac package ---
COPY autotune/agent/pyproject.toml /app/autotune/agent/pyproject.toml
COPY autotune/agent/idpac/ /app/autotune/agent/idpac/
RUN uv pip install --no-cache -e /app/autotune/agent/

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

EXPOSE 8080

# --- Agent code (no duplication — COPY from source locations) ---
COPY autotune/fast-template/patterns/strands-single-agent/basic_agent.py .
COPY autotune/fast-template/patterns/strands-single-agent/tools/ tools/
COPY autotune/fast-template/patterns/utils/ utils/
COPY autotune/agent/tools.py idpac_tools.py
COPY autotune/agent/code_interpreter_tools.py code_interpreter_tools.py
COPY autotune/agent/state.py optimization_state.py
COPY autotune/agent/hooks.py optimization_hooks.py
COPY autotune/agent/prompt.md .
COPY autotune/agent/skills/ skills/

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

CMD ["opentelemetry-instrument", "python", "-m", "basic_agent"]
