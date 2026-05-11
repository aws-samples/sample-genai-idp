# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BYPASS_TOOL_CONSENT=true

# Install agent requirements
COPY products/autotune/agent/requirements.txt .
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
COPY products/autotune/agent/pyproject.toml /app/products/autotune/agent/pyproject.toml
COPY products/autotune/agent/idpac/ /app/products/autotune/agent/idpac/
RUN uv pip install --no-cache -e /app/products/autotune/agent/

# Copy agent code, prompt, and skills
COPY products/autotune/agent/agent.py /app/products/autotune/agent/
COPY products/autotune/agent/tools.py /app/products/autotune/agent/
COPY products/autotune/agent/prompt.md /app/products/autotune/agent/
COPY products/autotune/agent/skills/ /app/products/autotune/agent/skills/

WORKDIR /app/products/autotune/agent

# Create workspace dir for agent file operations
RUN mkdir -p /app/workspace

# Create non-root user
RUN useradd -m -u 1000 autotune && chown -R autotune:autotune /app
USER autotune

CMD ["python", "agent.py"]
