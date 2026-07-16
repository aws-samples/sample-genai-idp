# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Test config for the bda_ocr_project custom-resource Lambda.

Stubs ``cfnresponse`` (delivered via the ``cfnresponse`` pip dep at deploy
time) and sets fake AWS credentials so ``import index`` works locally.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")

# Stub cfnresponse with SUCCESS/FAILED sentinels and a recording send().
_cfnresponse = MagicMock()
_cfnresponse.SUCCESS = "SUCCESS"
_cfnresponse.FAILED = "FAILED"
sys.modules.setdefault("cfnresponse", _cfnresponse)
