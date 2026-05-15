"""Phase F — live simulator integration.

Spins up the real marketplace-simulator HTTP server on an ephemeral port,
points the check_feature_entitlement Lambda at it via the boto3 endpoint-URL
env var, and verifies the full wire path:

    Lambda → boto3 → marketplace-entitlement protocol → simulator → SQLite → response

Skipped if the simulator package isn't importable (i.e. not in a dev checkout).
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

_SIM_ROOT = Path(__file__).resolve().parents[1].parent / "marketplace-simulator"

try:
    sys.path.insert(0, str(_SIM_ROOT))
    from client.mp_simulator_client import MpSimulatorClient  # noqa: E402
    from mp_simulator import clock, server  # noqa: E402

    _SIM_AVAILABLE = True
finally:
    if str(_SIM_ROOT) in sys.path:
        sys.path.remove(str(_SIM_ROOT))

pytestmark = pytest.mark.skipif(
    not _SIM_AVAILABLE, reason="marketplace-simulator not available in this checkout"
)


_DIMS = [
    {
        "apiName": "users",
        "displayName": "Users",
        "category": "Units",
        "unitPrice": 1.0,
        "kind": "contract",
    }
]


@pytest.fixture
def simulator():
    """Start a fresh simulator on a free port; yield (base_url, client)."""
    db = tempfile.NamedTemporaryFile(
        prefix="mp-sim-fp-", suffix=".sqlite", delete=False
    )
    db.close()
    clock.reset()
    srv, port = server.serve_in_thread(host="127.0.0.1", port=0, db_path=db.name)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            requests.get(f"{base}/healthz", timeout=1).raise_for_status()
            break
        except Exception:
            time.sleep(0.02)
    client = MpSimulatorClient(base)
    try:
        yield base, client
    finally:
        srv.shutdown()
        Path(db.name).unlink(missing_ok=True)


def _load_entitlement_lambda(
    simulator_url: str, monkeypatch, product_code: str, customer: str
):
    """Import the Phase A check_feature_entitlement Lambda with simulator endpoint set."""
    module_dir = (
        Path(__file__).resolve().parents[1]
        / "main-stack-extensions"
        / "lambdas"
        / "check_feature_entitlement"
    )
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv(
        "AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE", simulator_url
    )
    monkeypatch.setenv(
        "FEATURE_PRODUCT_CODE_MAP", f'{{"docs-by-status":"{product_code}"}}'
    )
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", customer)
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", "simulator")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    sys.path.insert(0, str(module_dir))
    try:
        sys.modules.pop("index", None)
        return importlib.import_module("index")
    finally:
        if str(module_dir) in sys.path:
            sys.path.remove(str(module_dir))


def _appsync_event(field: str, feature_id: str) -> dict:
    return {
        "info": {"fieldName": field},
        "arguments": {"featureId": feature_id},
        "identity": {"claims": {"cognito:groups": []}},
        "request": {"headers": {}},
    }


def test_active_subscription_flows_through_simulator(simulator, monkeypatch):
    """Create product + public offer + subscribe, then confirm the Lambda
    sees state=ACTIVE via the real GetEntitlements wire path."""
    _, client = simulator[0], simulator[1]
    base_url = simulator[0]

    product = client.create_product(
        name="DemoFeature - Docs By Status", pricingModel="contract", dimensions=_DIMS
    )
    pc = product["product_code"]
    offer = client.create_offer(
        productCode=pc,
        kind="public",
        contractTier={"dimension": "users", "quantity": 10},
        durationMonths=12,
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="111111111111")
    cid = sub["customerIdentifier"]

    mod = _load_entitlement_lambda(base_url, monkeypatch, pc, cid)
    # The mockable clock starts at "now" for this fixture; new subscriptions are
    # immediately active until their expiry.
    resp = mod.handler(
        _appsync_event("checkFeatureEntitlement", "docs-by-status"), None
    )

    assert resp["state"] == "ACTIVE"
    assert resp["customerIdentifier"] == cid
    assert resp["productCode"] == pc
    assert resp["source"] == "simulator"


def test_unsubscribed_customer_sees_none(simulator, monkeypatch):
    """Product exists, but caller isn't subscribed → NONE."""
    base_url, client = simulator
    product = client.create_product(
        name="DemoFeature - Docs By Status", pricingModel="contract", dimensions=_DIMS
    )
    pc = product["product_code"]

    mod = _load_entitlement_lambda(base_url, monkeypatch, pc, "CUST-nobody")
    resp = mod.handler(
        _appsync_event("checkFeatureEntitlement", "docs-by-status"), None
    )
    assert resp["state"] == "NONE"
    assert resp["customerIdentifier"] == "CUST-nobody"


def test_expired_subscription_flows_through(simulator, monkeypatch):
    """Advance the simulator's clock past the subscription's expiry → Lambda returns NONE
    (the simulator's GetEntitlements filters past-dated entitlements out of its response,
    so from the Lambda's perspective there's no active entitlement)."""
    base_url, client = simulator
    product = client.create_product(
        name="DemoFeature - Docs By Status", pricingModel="contract", dimensions=_DIMS
    )
    pc = product["product_code"]
    offer = client.create_offer(
        productCode=pc,
        kind="public",
        contractTier={"dimension": "users", "quantity": 10},
        durationMonths=1,
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="222222222222")
    cid = sub["customerIdentifier"]

    # Advance 31 days so the 1-month entitlement is expired.
    client.advance_time(31 * 86400)

    mod = _load_entitlement_lambda(base_url, monkeypatch, pc, cid)
    resp = mod.handler(
        _appsync_event("checkFeatureEntitlement", "docs-by-status"), None
    )
    # The simulator drops expired entitlements from its response, matching the
    # real AWS Marketplace contract, so the Lambda sees no entitlements → NONE.
    assert resp["state"] == "NONE"
