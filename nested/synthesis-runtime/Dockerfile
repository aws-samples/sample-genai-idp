# AgentCore Runtime container for the SEED document generator.
#
# AgentCore Runtime requires a linux/arm64 image serving the HTTP service
# contract on port 8080. A Debian base is used (not the AL2023 Lambda base)
# because WeasyPrint's native stack — Pango, cairo, GDK-Pixbuf, HarfBuzz,
# fontconfig and fonts — installs cleanly and completely there, which the
# Lambda base could not provide.
# Pull the Python base from the ECR Public mirror rather than Docker Hub:
# CodeBuild's anonymous Docker Hub pulls hit the registry rate limit, which
# fails the build intermittently ("failed to resolve source metadata for
# docker.io/library/python"). ECR Public is not rate-limited from within AWS.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint runtime libraries + fonts. build-essential/libffi-dev are needed
# to compile any wheels without prebuilt arm64 artifacts.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        libharfbuzz0b \
        libfribidi0 \
        libfontconfig1 \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY nested/synthesis-runtime/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY lib/idp_common_pkg /tmp/idp_common_pkg
RUN pip install --no-deps /tmp/idp_common_pkg

COPY lib/doc-gen-agent /tmp/doc-gen-agent
RUN pip install --no-deps /tmp/doc-gen-agent

COPY src/lambda/synthesis_runtime/*.py /app/

EXPOSE 8080

CMD ["python", "handler.py"]
