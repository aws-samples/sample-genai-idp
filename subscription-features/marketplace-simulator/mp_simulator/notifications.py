"""Lifecycle notification dispatch.

For every subscription lifecycle event (subscribe-success, unsubscribe-pending,
unsubscribe-success, entitlement-updated) we walk the registered
``lifecycle_sinks`` for the product and deliver the event.

Transports supported:

- ``webhook``  — HTTP POST JSON payload to the target URL. Default. No AWS creds
  required. Body matches real SNS "Message" inner JSON, wrapped by a minimal
  SNS-like envelope so downstream handlers can parse the same way they would
  in prod.
- ``sns``      — Real ``boto3.client('sns').publish()`` to the target ARN.
  Useful when you want to exercise an actual SQS-fed Lambda locally.
- ``inproc``   — Calls a Python callable registered via ``register_inproc``.
  Synchronous. For unit tests.

All events are persisted to the ``notifications`` table for later inspection.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Callable

import requests

from . import clock, db

LOG = logging.getLogger("mp-sim.notify")

_INPROC: dict[str, Callable[[dict[str, Any]], None]] = {}
_lock = threading.Lock()


def register_inproc(name: str, fn: Callable[[dict[str, Any]], None]) -> None:
    """Register an in-process callback reachable via ``transport=inproc, target=<name>``."""
    with _lock:
        _INPROC[name] = fn


def clear_inproc() -> None:
    with _lock:
        _INPROC.clear()


def _sns_envelope(topic: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a payload in an SNS-shaped envelope. Real Marketplace delivers the
    inner ``Message`` as a JSON string inside an SNS envelope; our webhooks
    emit the same shape so handlers can reuse ``json.loads(envelope["Message"])``.
    """
    return {
        "Type": "Notification",
        "MessageId": str(uuid.uuid4()),
        "TopicArn": f"arn:aws:sns:us-east-1:000000000000:aws-mp-{topic}-notification",
        "Subject": f"aws-marketplace-{action}",
        "Message": json.dumps(payload),
        "Timestamp": clock.now_ms(),
    }


def _deliver(sink: dict[str, Any], envelope: dict[str, Any]) -> tuple[str, int]:
    """Returns ``(delivery_status, attempts)``."""
    transport = sink["transport"]
    target = sink["target"]
    if transport == "webhook":
        try:
            requests.post(target, json=envelope, timeout=5).raise_for_status()
            return "delivered", 1
        except Exception as exc:
            LOG.warning("webhook delivery to %s failed: %s", target, exc)
            return "failed", 1
    if transport == "sns":
        try:
            import boto3  # lazy to avoid import cost in tests that don't use SNS

            region = target.split(":")[3] if target.startswith("arn:aws:sns:") else "us-east-1"
            sns = boto3.client("sns", region_name=region)
            sns.publish(
                TopicArn=target,
                Subject=envelope.get("Subject", ""),
                Message=envelope["Message"],
            )
            return "delivered", 1
        except Exception as exc:
            LOG.warning("sns publish to %s failed: %s", target, exc)
            return "failed", 1
    if transport == "inproc":
        fn = _INPROC.get(target)
        if fn is None:
            LOG.warning("no inproc callback registered for %s", target)
            return "failed", 1
        try:
            fn(envelope)
            return "delivered", 1
        except Exception as exc:
            LOG.warning("inproc callback %s raised: %s", target, exc)
            return "failed", 1
    LOG.warning("unknown transport %s", transport)
    return "failed", 1


def emit(
    *,
    product_code: str,
    topic: str,
    action: str,
    customer_identifier: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical AWS Marketplace lifecycle payload, persist it,
    and deliver to every registered sink for the product+topic. Returns the
    inner payload.
    """
    payload = {
        "action": action,
        "customer-identifier": customer_identifier,
        "product-code": product_code,
        "offer-identifier": (extra or {}).get("offer-identifier", ""),
        "isFreeTrialTermPresent": "true"
        if (extra or {}).get("isFreeTrialTermPresent")
        else "false",
        "message-time": clock.now(),
    }
    if extra:
        for k, v in extra.items():
            payload.setdefault(k, v)

    envelope = _sns_envelope(topic, action, payload)

    # find sinks
    with db.read() as c:
        rows = c.execute(
            "SELECT * FROM lifecycle_sinks WHERE product_code = ? AND topic = ?",
            (product_code, topic),
        ).fetchall()
        sinks = [dict(r) for r in rows]

    now_t = clock.now()
    for sink in sinks:
        status, attempts = _deliver(sink, envelope)
        with db.write() as c:
            c.execute(
                """INSERT INTO notifications
                   (product_code, topic, action, customer_identifier,
                    payload_json, delivery_status, delivery_attempts, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product_code,
                    topic,
                    action,
                    customer_identifier,
                    json.dumps(envelope),
                    status,
                    attempts,
                    now_t,
                ),
            )

    if not sinks:
        # still log the event even if no sinks are registered, so tests can assert
        with db.write() as c:
            c.execute(
                """INSERT INTO notifications
                   (product_code, topic, action, customer_identifier,
                    payload_json, delivery_status, delivery_attempts, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product_code,
                    topic,
                    action,
                    customer_identifier,
                    json.dumps(envelope),
                    "no-sink",
                    0,
                    now_t,
                ),
            )

    return payload
