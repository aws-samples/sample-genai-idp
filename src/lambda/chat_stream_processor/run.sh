#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Entry point used by the AWS Lambda Web Adapter (LWA). The Lambda Handler is
# set to "run.sh" and AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap so LWA boots this
# script, which launches the FastAPI app under uvicorn on the port LWA probes
# (default 8080, overridable via AWS_LWA_PORT/PORT). LWA bridges the Lambda
# Function URL RESPONSE_STREAM invocation to the app's streamed HTTP response.
set -euo pipefail
PORT="${PORT:-8080}"
# LWA execs this script as a child process; unlike the managed Python runtime's
# handler process, it does NOT automatically get the Lambda layers' /opt/python
# on sys.path. Without this, `import idp_common` (provided by the base/agents
# layers, which extract to /opt/python) fails with ModuleNotFoundError and
# uvicorn exits 1. Prepend the layer path and the task root (for the vendored
# processor modules copied in at build time) to PYTHONPATH.
export PYTHONPATH="/opt/python:${LAMBDA_TASK_ROOT:-/var/task}${PYTHONPATH:+:${PYTHONPATH}}"
exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT}" --no-access-log
