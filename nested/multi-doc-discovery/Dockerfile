# Multi-Document Discovery Lambda Container Image
# Contains: scikit-learn, scipy, numpy, strands-agents, jinja2, Pillow, pypdfium2
# These dependencies exceed Lambda's 250MB unzipped layer limit, so we use container packaging.
#
# This file is the ONE source of truth for the image: the CodeBuild project in
# nested/multi-doc-discovery/template.yaml builds it with `docker build -f` from
# the source zip. Build context is the REPO ROOT (the zip root), so all COPY
# paths below are repo-relative.

FROM public.ecr.aws/lambda/python:3.12 AS builder

# Install build dependencies
RUN dnf install -y gcc gcc-c++ make && dnf clean all

# Install Python dependencies into /opt/python so we can copy them cleanly.
#
# The pip invocations are wrapped in a retry loop: a mid-stream connection drop
# while pulling a large wheel (numpy is ~18MB) raises BrokenPipeError, which
# pip surfaces as a hard `exit 2` and which then fails the CodeBuild run, the
# DockerBuildRun custom resource, and ultimately the whole stack deploy.
# --retries/--timeout harden individual HTTP requests; the outer loop covers the
# unrecoverable stream-level faults that pip's own retries do not.
COPY nested/multi-doc-discovery/requirements.txt /tmp/requirements.txt
RUN for attempt in 1 2 3; do \
      pip install --no-cache-dir --retries 10 --timeout 60 \
        --target /opt/python -r /tmp/requirements.txt && break; \
      if [ "$attempt" = "3" ]; then \
        echo "ERROR: pip install of requirements.txt failed after 3 attempts"; \
        exit 1; \
      fi; \
      echo "pip install failed (attempt $attempt); retrying in $((attempt * 10))s..."; \
      sleep $((attempt * 10)); \
    done

# Install idp_common package
COPY lib/idp_common_pkg /tmp/idp_common_pkg
RUN for attempt in 1 2 3; do \
      pip install --no-cache-dir --retries 10 --timeout 60 --no-deps \
        --target /opt/python /tmp/idp_common_pkg && break; \
      if [ "$attempt" = "3" ]; then \
        echo "ERROR: pip install of idp_common_pkg failed after 3 attempts"; \
        exit 1; \
      fi; \
      echo "pip install failed (attempt $attempt); retrying in $((attempt * 10))s..."; \
      sleep $((attempt * 10)); \
    done

# --- Final stage ---
FROM public.ecr.aws/lambda/python:3.12

# Copy installed packages from builder
COPY --from=builder /opt/python ${LAMBDA_TASK_ROOT}/../opt/python

# Add /var/task/../opt/python to PYTHONPATH so Lambda can find the packages
ENV PYTHONPATH="${LAMBDA_TASK_ROOT}/../opt/python:${LAMBDA_TASK_ROOT}"

# Copy Lambda handler code
COPY src/lambda/multi_doc_discovery/*.py ${LAMBDA_TASK_ROOT}/

# Default handler - overridden per function via ImageConfig.Command
CMD ["embed_handler.handler"]
