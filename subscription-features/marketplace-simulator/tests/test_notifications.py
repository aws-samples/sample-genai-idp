"""Lifecycle notification delivery tests.

Uses the in-process transport (synchronous, no HTTP) to assert payload shape
and event ordering, then uses the webhook transport against a local HTTP
server to assert real HTTP delivery works end-to-end.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from mp_simulator import notifications

DIMS = [
    {
        "apiName": "cap_docs",
        "displayName": "Capacity",
        "category": "Units",
        "unitPrice": 0.01,
        "kind": "contract",
    },
    {
        "apiName": "docs_used",
        "displayName": "Used",
        "category": "Units",
        "unitPrice": 0.001,
        "kind": "usage",
    },
]


def _create_product_with_sink(client, *, transport: str, target: str) -> dict:
    p = client.create_product(name="Notif", pricingModel="contract", dimensions=DIMS)
    client.create_lifecycle_sink(
        productCode=p["product_code"], transport=transport, target=target, topic="subscription"
    )
    client.create_lifecycle_sink(
        productCode=p["product_code"], transport=transport, target=target, topic="entitlement"
    )
    offer = client.create_offer(
        productCode=p["product_code"],
        kind="public",
        contractTier={"dimension": "cap_docs", "quantity": 10},
    )
    return p, offer


# ─────────────────────────── in-process transport ────────────────────────────
def test_inproc_notifications_shape_and_order(simulator):
    _, client = simulator
    received: list[dict] = []

    def capture(envelope: dict) -> None:
        received.append(envelope)

    notifications.register_inproc("test-sink", capture)

    p, offer = _create_product_with_sink(client, transport="inproc", target="test-sink")
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="321321321321")
    client.unsubscribe(customerIdentifier=sub["customerIdentifier"])

    # Expect: subscribe-success, unsubscribe-pending, unsubscribe-success, entitlement-updated
    assert len(received) == 4
    actions = [json.loads(env["Message"])["action"] for env in received]
    assert actions == [
        "subscribe-success",
        "unsubscribe-pending",
        "unsubscribe-success",
        "entitlement-updated",
    ]

    # Envelope shape matches SNS
    first = received[0]
    assert first["Type"] == "Notification"
    assert "TopicArn" in first
    assert "MessageId" in first

    inner = json.loads(first["Message"])
    assert inner["action"] == "subscribe-success"
    assert inner["customer-identifier"] == sub["customerIdentifier"]
    assert inner["product-code"] == p["product_code"]
    assert inner["offer-identifier"] == offer["offer_id"]


# ─────────────────────────── webhook transport ───────────────────────────────
class _WebhookReceiver(BaseHTTPRequestHandler):
    captured: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.captured.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args, **kwargs) -> None:  # noqa: D401 - silence
        pass


def test_webhook_notifications_deliver(simulator):
    _, client = simulator
    _WebhookReceiver.captured = []
    httpd = HTTPServer(("127.0.0.1", 0), _WebhookReceiver)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        p, offer = _create_product_with_sink(
            client, transport="webhook", target=f"http://127.0.0.1:{port}/hook"
        )
        sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="987987987987")
        # Give the server a moment to drain
        for _ in range(20):
            if len(_WebhookReceiver.captured) >= 1:
                break
            time.sleep(0.05)
        assert len(_WebhookReceiver.captured) >= 1
        first = _WebhookReceiver.captured[0]
        inner = json.loads(first["Message"])
        assert inner["action"] == "subscribe-success"
        assert inner["customer-identifier"] == sub["customerIdentifier"]

        # Check delivery log in admin
        admin_notes = client.list_notifications(product_code=p["product_code"])
        assert all(n["delivery_status"] == "delivered" for n in admin_notes)
    finally:
        httpd.shutdown()
