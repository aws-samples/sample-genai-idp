# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Containerises the AWS Marketplace simulator for dev deployments.
#   - Local:  docker compose up
#   - ECS/EC2: push to ECR and run as a single-replica service
#   - Lambda (future): needs db.py swap for DDB — not yet supported

FROM python:3.12-slim

WORKDIR /app

# Copy the simulator package and install it + client helper.
COPY pyproject.toml README.md ./
COPY mp_simulator ./mp_simulator
COPY client ./client

RUN pip install --no-cache-dir -e .

# SQLite state persists here; mount a volume for persistence across restarts.
RUN mkdir -p /data
ENV MP_SIM_DB=/data/mp-sim.sqlite

EXPOSE 9999

# Default: bind to 0.0.0.0 so container networking can reach it.
ENTRYPOINT ["python", "-m", "mp_simulator", "serve", "--host", "0.0.0.0", "--port", "9999"]
CMD ["--db", "/data/mp-sim.sqlite"]

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9999/healthz', timeout=2).read()"
