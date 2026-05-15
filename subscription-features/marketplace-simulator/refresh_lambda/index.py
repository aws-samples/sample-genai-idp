"""CloudFormation Custom Resource: refresh the simulator EC2 in-place.

Invoked on every stack CREATE and UPDATE of the
``MarketplaceSimulatorRefreshResource`` custom resource in the simulator
nested stack. The custom resource's ``SourceHash`` property is bumped by
``publish.py`` on every deploy, which forces CloudFormation to call this
Lambda, which in turn uses SSM ``SendCommand`` to tell the simulator EC2
to:

    1. Download the current simulator source tarball from S3
    2. Extract over the existing /srv/idp/subscription-features/marketplace-simulator/
    3. Re-run ``docker compose up -d --build`` so the container picks up
       the new HTTP routes (e.g. the new /marketplace/* HTML pages).

This lets deployers iterate on simulator code with a simple
``idp-cli deploy`` — no SSH, no manual docker compose, no stack
re-creation required.

Inputs (from CFN event.ResourceProperties):
    InstanceId       EC2 instance to run the refresh command on.
    SourceS3Uri      s3://bucket/key to the tarball publish.py uploaded.
    SourceHash       Content hash — changing it forces CFN Update, which
                     is how "refresh on every deploy" is triggered.
    WaitSeconds      Optional int (default 120). How long to wait for the
                     SSM command to reach Success before returning.

Returns:
    On CREATE/UPDATE: {PhysicalResourceId: CommandId, CommandStatus, …}.
    On DELETE: no-op; the EC2 is tearing down with the stack anyway.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict
from urllib.parse import urlparse

import boto3
import urllib.request

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_ssm = boto3.client("ssm")


def _cfn_respond(
    event: Dict[str, Any], status: str, data: Dict[str, Any], physical_id: str, reason: str = ""
) -> None:
    """POST a CloudFormation custom-resource response."""
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason
            or f"See CloudWatch Logs: {os.environ.get('AWS_LAMBDA_LOG_STREAM_NAME', 'n/a')}",
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
            "NoEcho": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"Content-Type": "", "Content-Length": str(len(body))},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — CFN response URL
        resp.read()


def _build_refresh_script(source_s3_uri: str) -> str:
    """Shell commands SSM runs on the EC2 to pull new source + rebuild."""
    parsed = urlparse(source_s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return f"""#!/bin/bash
set -uxo pipefail
exec > >(tee -a /var/log/mp-simulator-refresh.log) 2>&1

echo "[$(date -Iseconds)] starting simulator refresh from s3://{bucket}/{key}"

# Download the new source tarball.
mkdir -p /srv/refresh-tmp
cd /srv/refresh-tmp
aws s3 cp s3://{bucket}/{key} source.tar.gz
rm -rf ./new && mkdir ./new
tar xzf source.tar.gz -C ./new

# Replace the marketplace-simulator directory in the existing checkout.
# /srv/idp was created by UserData; if we're running for the first time
# after migrating from git-clone to tarball deploy, /srv/idp may not
# exist yet — bootstrap it from the tarball in that case.
if [ ! -d /srv/idp/subscription-features/marketplace-simulator ]; then
  mkdir -p /srv/idp/prototype
fi
rm -rf /srv/idp/subscription-features/marketplace-simulator
mv ./new /srv/idp/subscription-features/marketplace-simulator

# The compose file at /srv/compose.yaml references the build context
# ${{PWD}}/idp/subscription-features/marketplace-simulator, so nothing else needs
# to be updated — just rebuild + recreate the container in place.
cd /srv
docker compose -f compose.yaml up -d --build --force-recreate mp-simulator

rm -rf /srv/refresh-tmp
echo "[$(date -Iseconds)] simulator refresh complete"
"""


def _wait_for_ssm_command(command_id: str, instance_id: str, timeout_s: int) -> Dict[str, Any]:
    """Poll SSM until the command reaches a terminal state or timeout."""
    deadline = time.time() + timeout_s
    last_status = "Pending"
    while time.time() < deadline:
        try:
            resp = _ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except _ssm.exceptions.InvocationDoesNotExist:
            # Command hasn't reached the instance yet.
            time.sleep(3)
            continue
        last_status = resp.get("Status", "Unknown")
        if last_status in ("Success", "Cancelled", "TimedOut", "Failed"):
            return resp
        time.sleep(5)
    return {"Status": f"TimedOut after {timeout_s}s (last={last_status})"}


def handler(event: Dict[str, Any], _context: Any) -> None:
    """Custom-resource entry point."""
    logger.info("Refresh event: %s", json.dumps(event, default=str)[:2000])

    request_type = event.get("RequestType", "")
    props = event.get("ResourceProperties", {}) or {}
    old_props = event.get("OldResourceProperties", {}) or {}

    instance_id = (props.get("InstanceId") or "").strip()
    source_s3_uri = (props.get("SourceS3Uri") or "").strip()
    source_hash = (props.get("SourceHash") or "").strip()
    wait_seconds = int(props.get("WaitSeconds") or 120)

    physical_id = event.get("PhysicalResourceId") or f"mp-sim-refresh-{source_hash[:12]}"

    if request_type == "Delete":
        # Nothing to do — the EC2 is being terminated with the stack.
        _cfn_respond(event, "SUCCESS", {"Action": "delete-noop"}, physical_id)
        return

    try:
        if not instance_id or not source_s3_uri or not source_hash:
            raise ValueError(
                "Missing required properties (need InstanceId, SourceS3Uri, SourceHash)"
            )

        # Skip refresh on UPDATE if the hash didn't actually change (this
        # custom resource gets re-invoked on many unrelated property
        # changes; avoid unnecessary container rebuilds).
        if request_type == "Update" and old_props.get("SourceHash") == source_hash:
            logger.info("SourceHash unchanged (%s) — skipping refresh.", source_hash[:12])
            _cfn_respond(
                event,
                "SUCCESS",
                {"Action": "skip-unchanged", "SourceHash": source_hash},
                physical_id,
            )
            return

        script = _build_refresh_script(source_s3_uri)
        logger.info(
            "Sending SSM RunShellScript to %s (hash=%s, s3=%s)",
            instance_id,
            source_hash[:12],
            source_s3_uri,
        )
        send = _ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [script], "executionTimeout": [str(wait_seconds)]},
            TimeoutSeconds=wait_seconds,
            Comment="marketplace-simulator refresh",
        )
        command_id = send["Command"]["CommandId"]
        physical_id = f"mp-sim-refresh-{command_id}"
        # Wait briefly so the stack surfaces a real success/failure, not
        # a fire-and-forget that might leave the simulator half-built.
        result = _wait_for_ssm_command(command_id, instance_id, wait_seconds)
        status = result.get("Status", "Unknown")
        logger.info("SSM command %s finished with status=%s", command_id, status)
        if status != "Success":
            raise RuntimeError(
                f"simulator refresh SSM command failed: {status}: "
                f"{result.get('StandardErrorContent') or result.get('StatusDetails')}"
            )
        _cfn_respond(
            event,
            "SUCCESS",
            {
                "CommandId": command_id,
                "CommandStatus": status,
                "SourceHash": source_hash,
            },
            physical_id,
        )
    except Exception as exc:  # noqa: BLE001 — final catch for CFN
        logger.exception("Refresh failed")
        _cfn_respond(
            event,
            "FAILED",
            {"Error": str(exc)[:1000]},
            physical_id,
            reason=str(exc)[:1000],
        )
