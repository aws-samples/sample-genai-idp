"""Thin Python helper for the simulator's /admin and /buyer surfaces.

Uses ``requests``. Raises ``MpSimulatorError`` with the parsed ``__type`` and
``message`` fields on any non-2xx.

Example::

    from client.mp_simulator_client import MpSimulatorClient
    c = MpSimulatorClient("http://localhost:9999")
    product = c.create_product(
        name="IDP Test Feature",
        pricingModel="contract-with-payg",
        dimensions=[
            {"apiName": "cap_docs", "displayName": "Capacity (docs/mo)", "category": "Units",
             "unitPrice": 0.01, "kind": "contract"},
            {"apiName": "docs_over", "displayName": "Overage docs", "category": "Units",
             "unitPrice": 0.001, "kind": "overage"},
        ],
        trialDays=30,
        fulfillmentUrl="http://localhost:8080/register",
    )
    offer = c.create_offer(
        productCode=product["product_code"], kind="private",
        buyerAccountAllowlist=["123456789012"],
        contractTier={"dimension": "cap_docs", "quantity": 100},
        freeTrialEnabled=True,
    )
    result = c.subscribe(offerId=offer["offer_id"], buyerAccountId="123456789012")
"""

from __future__ import annotations

from typing import Any

import requests


class MpSimulatorError(RuntimeError):
    def __init__(self, status: int, error_type: str, message: str):
        super().__init__(f"[{status} {error_type}] {message}")
        self.status = status
        self.error_type = error_type
        self.message = message


class MpSimulatorClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ─────────────── internal ───────────────
    def _req(self, method: str, path: str, *, json_body: Any = None, params: Any = None) -> Any:
        resp = requests.request(
            method,
            f"{self.base_url}{path}",
            json=json_body,
            params=params,
            timeout=self.timeout,
        )
        if 200 <= resp.status_code < 300:
            if not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return resp.content
        try:
            j = resp.json()
            raise MpSimulatorError(
                resp.status_code,
                j.get("__type", "Unknown"),
                j.get("message", resp.text or ""),
            )
        except ValueError:
            raise MpSimulatorError(resp.status_code, "Unknown", resp.text or "no body") from None

    # ─────────────── admin: products ───────────────
    def create_product(self, **body: Any) -> dict[str, Any]:
        return self._req("POST", "/admin/products", json_body=body)

    def get_product(self, product_code: str) -> dict[str, Any]:
        return self._req("GET", f"/admin/products/{product_code}")

    def list_products(self) -> list[dict[str, Any]]:
        return self._req("GET", "/admin/products")

    def update_product(self, product_code: str, **body: Any) -> dict[str, Any]:
        return self._req("POST", f"/admin/products/{product_code}", json_body=body)

    def publish_product(self, product_code: str) -> dict[str, Any]:
        return self._req("POST", f"/admin/products/{product_code}/publish")

    # ─────────────── admin: offers ───────────────
    def create_offer(self, **body: Any) -> dict[str, Any]:
        return self._req("POST", "/admin/offers", json_body=body)

    def list_offers(self, product_code: str | None = None) -> list[dict[str, Any]]:
        return self._req(
            "GET", "/admin/offers", params={"productCode": product_code} if product_code else None
        )

    def get_offer(self, offer_id: str) -> dict[str, Any]:
        return self._req("GET", f"/admin/offers/{offer_id}")

    # ─────────────── admin: lifecycle sinks ───────────────
    def create_lifecycle_sink(
        self, *, productCode: str, transport: str, target: str, topic: str
    ) -> dict[str, Any]:
        return self._req(
            "POST",
            "/admin/lifecycle-sinks",
            json_body={
                "productCode": productCode,
                "transport": transport,
                "target": target,
                "topic": topic,
            },
        )

    def list_lifecycle_sinks(self, product_code: str | None = None) -> list[dict[str, Any]]:
        return self._req(
            "GET",
            "/admin/lifecycle-sinks",
            params={"productCode": product_code} if product_code else None,
        )

    # ─────────────── admin: direct entitlement management ───────────────
    # Simulator-only shortcuts (no real-AWS equivalent): flip an entitlement
    # on/off without going through product+offer+subscribe. Used by the
    # feature-platform subscribeFeature / unsubscribeFeature Lambdas.
    def grant_entitlement(
        self,
        *,
        customerIdentifier: str,
        productCode: str,
        featureId: str | None = None,
        expiresInSeconds: int | None = None,
        dimension: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "customerIdentifier": customerIdentifier,
            "productCode": productCode,
        }
        if featureId is not None:
            body["featureId"] = featureId
        if expiresInSeconds is not None:
            body["expiresInSeconds"] = expiresInSeconds
        if dimension is not None:
            body["dimension"] = dimension
        return self._req("POST", "/admin/entitlements", json_body=body)

    def expire_entitlement(
        self,
        *,
        customerIdentifier: str,
        productCode: str,
        featureId: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "customerIdentifier": customerIdentifier,
            "productCode": productCode,
        }
        if featureId is not None:
            body["featureId"] = featureId
        return self._req("POST", "/admin/entitlements/expire", json_body=body)

    # ─────────────── admin: misc ───────────────
    def advance_time(self, seconds: float) -> dict[str, Any]:
        return self._req("POST", "/admin/time/advance", json_body={"seconds": seconds})

    def list_subscriptions(self) -> list[dict[str, Any]]:
        return self._req("GET", "/admin/subscriptions")

    def list_usage(self, product_code: str | None = None) -> list[dict[str, Any]]:
        return self._req(
            "GET", "/admin/usage", params={"productCode": product_code} if product_code else None
        )

    def list_notifications(self, product_code: str | None = None) -> list[dict[str, Any]]:
        return self._req(
            "GET",
            "/admin/notifications",
            params={"productCode": product_code} if product_code else None,
        )

    def dump_state(self) -> dict[str, Any]:
        return self._req("GET", "/admin/state")

    # ─────────────── buyer ───────────────
    def subscribe(self, *, offerId: str, buyerAccountId: str) -> dict[str, Any]:
        return self._req(
            "POST",
            "/buyer/subscribe",
            json_body={"offerId": offerId, "buyerAccountId": buyerAccountId},
        )

    def unsubscribe(self, *, customerIdentifier: str) -> dict[str, Any]:
        return self._req(
            "POST", "/buyer/unsubscribe", json_body={"customerIdentifier": customerIdentifier}
        )

    def quick_launch(self, *, customerIdentifier: str) -> dict[str, Any]:
        return self._req(
            "POST", "/buyer/quick-launch", json_body={"customerIdentifier": customerIdentifier}
        )

    def buyer_entitlements(self, buyer_account_id: str) -> dict[str, Any]:
        return self._req("GET", f"/buyer/entitlements/{buyer_account_id}")
