# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Test bootstrap for the ConfBench Test Set extension.

Puts the source roots on sys.path the way Lambda does at runtime:
  * shared/python  -> the layer's importable content (`import variants`)
  * ingest/        -> the planner and worker
  * feature-api/   -> the API handler (`import handler`)

NOTE: `ui-deployer/` is deliberately NOT on the path. Both it and feature-api/
define a top-level `handler` module, so including both makes `import handler`
resolve by sys.path order rather than intent — and the ui-deployer's module
raises KeyError on import unless a dozen install-time env vars are set. Tests
that need it should import it explicitly via importlib with a distinct name.

Also sets the environment variables every module reads at import time, so tests
can import them without a live stack. Individual tests override these via
monkeypatch where the value matters.
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

for _sub in ("shared/python", "ingest", "feature-api"):
    _path = str(_ROOT / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

os.environ.setdefault("TESTSET_BUCKET", "test-testset-bucket")
os.environ.setdefault("JOB_TABLE", "test-job-table")
os.environ.setdefault("HOST_TRACKING_TABLE", "test-tracking-table")
os.environ.setdefault(
    "INGEST_STATE_MACHINE_ARN",
    "arn:aws:states:us-east-1:123456789012:stateMachine:test-ingest",
)
# Keep boto3 from discovering real credentials or a real region during tests.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")  # nosec B105 - dummy
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")  # nosec B105 - dummy
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")  # nosec B105 - dummy
