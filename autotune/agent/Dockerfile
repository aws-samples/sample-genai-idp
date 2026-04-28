# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BYPASS_TOOL_CONSENT=true

# Install agent requirements
COPY autotune/agent/requirements.txt .
RUN uv pip install --no-cache -r requirements.txt

# Install idp-cli chain: idp_common -> idp_sdk -> idp-cli
COPY lib/idp_common_pkg/ /app/lib/idp_common_pkg/
COPY lib/idp_sdk/ /app/lib/idp_sdk/
COPY lib/idp_cli_pkg/ /app/lib/idp_cli_pkg/
RUN uv pip install --no-cache \
    -e /app/lib/idp_common_pkg/ \
    -e /app/lib/idp_sdk/ \
    -e /app/lib/idp_cli_pkg/

# Install idpac package
COPY autotune/agent/pyproject.toml /app/autotune/agent/pyproject.toml
COPY autotune/agent/idpac/ /app/autotune/agent/idpac/
RUN uv pip install --no-cache -e /app/autotune/agent/

# Copy agent code, prompt, and skills
COPY autotune/agent/agent.py /app/autotune/agent/
COPY autotune/agent/tools.py /app/autotune/agent/
COPY autotune/agent/prompt.md /app/autotune/agent/
COPY autotune/agent/skills/ /app/autotune/agent/skills/

WORKDIR /app/autotune/agent

# Create workspace dir for agent file operations
RUN mkdir -p /app/workspace

# Create non-root user
RUN useradd -m -u 1000 autotune && chown -R autotune:autotune /app
USER autotune

CMD ["python", "agent.py"]
