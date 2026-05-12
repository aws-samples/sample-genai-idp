# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Test configuration for chat_with_document_processor.

Sets fake AWS credentials + mocks ``idp_common`` imports that would otherwise
require the Lambda layer. Tests patch the public AppSync / Bedrock surface
instead of relying on those packages being installed locally.
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

# Required env vars read at module import / handler entry.
os.environ.setdefault("TRACKING_TABLE_NAME", "tracking-table")
os.environ.setdefault("CONFIGURATION_TABLE_NAME", "config-table")
os.environ.setdefault("OUTPUT_BUCKET", "output-bucket")
os.environ.setdefault("USERS_TABLE_NAME", "")  # RBAC defaults to unrestricted

# Stub `idp_common.*` symbols that the processor imports. The real package is
# delivered via a Lambda layer at deploy time; for unit tests we only need to
# mock the two symbols the module references at import time.
_appsync_mod = MagicMock()


class _FakeAppSyncError(Exception):
    pass


_appsync_mod.AppSyncError = _FakeAppSyncError
_appsync_mod.AppSyncClient = MagicMock

sys.modules.setdefault("idp_common", MagicMock())
sys.modules.setdefault("idp_common.appsync", MagicMock())
sys.modules["idp_common.appsync.client"] = _appsync_mod
_cfg_mod = MagicMock()
_cfg_mod.get_config = MagicMock(return_value={})
sys.modules["idp_common.config"] = _cfg_mod

# Stub idp_common.bedrock.client.is_claude_4_7_model — used by the processor
# to decide whether to skip temperature/top_p for Claude 4.7+.
_bedrock_mod = MagicMock()
_bedrock_mod.is_claude_4_7_model = lambda model_id: "claude-opus-4-7" in model_id or "claude-4-7" in model_id
sys.modules.setdefault("idp_common.bedrock", MagicMock())
sys.modules["idp_common.bedrock.client"] = _bedrock_mod


# Stub idp_common.bedrock.model_utils.parse_model_id — used by the processor
# to split tier suffixes (:priority / :flex) off the model ID and pass the
# tier via performanceConfig.
def _fake_parse_model_id(model_id):
    if not model_id:
        return model_id, None
    parts = model_id.split(":")
    if len(parts) <= 2:
        return model_id, None
    potential_tier = parts[-1].lower().strip()
    if potential_tier in ("flex", "priority"):
        return ":".join(parts[:-1]), potential_tier
    return model_id, None


_model_utils_mod = MagicMock()
_model_utils_mod.parse_model_id = _fake_parse_model_id
sys.modules["idp_common.bedrock.model_utils"] = _model_utils_mod
