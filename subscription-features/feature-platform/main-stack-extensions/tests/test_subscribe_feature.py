"""Unit tests for the subscribe_feature Lambda.

The Lambda no longer POSTs to the simulator — it returns a Marketplace (or
simulator) URL the UI should redirect the admin to. These tests verify the
URL composition, env-var-driven behaviour, and admin / argument validation.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from _helpers import make_appsync_event


def _preload(
    monkeypatch,
    load_lambda,
    *,
    simulator_endpoint="http://sim.example.com",
    product_map='{"docs-by-status":"prod123"}',
    offer_map="{}",
    marketplace_url_map="{}",
    default_customer="CUST-default",
    default_buyer_account="111122223333",
    source_tag="simulator",
):
    monkeypatch.setenv("SIMULATOR_ADMIN_ENDPOINT", simulator_endpoint)
    monkeypatch.setenv("FEATURE_PRODUCT_CODE_MAP", product_map)
    monkeypatch.setenv("FEATURE_OFFER_ID_MAP", offer_map)
    monkeypatch.setenv("FEATURE_MARKETPLACE_URL_MAP", marketplace_url_map)
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", default_customer)
    monkeypatch.setenv("DEFAULT_BUYER_ACCOUNT_ID", default_buyer_account)
    monkeypatch.setenv("ADMIN_GROUP", "Admin")
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", source_tag)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("subscribe_feature")


def test_happy_path_simulator_mode(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature",
            {
                "featureId": "docs-by-status",
                "returnUrl": "http://app/features/docs-by-status",
            },
            groups=["Admin"],
        ),
        None,
    )

    # Entitlement state stays NONE — the admin still has to accept terms.
    assert result["featureId"] == "docs-by-status"
    assert result["state"] == "NONE"
    assert result["expiresAt"] is None
    assert result["customerIdentifier"] == "CUST-default"
    assert result["productCode"] == "prod123"
    assert result["source"] == "simulator"
    # Constructed marketplaceUrl
    assert result["marketplaceUrl"].startswith(
        "http://sim.example.com/marketplace/pp/prod123"
    )
    parsed = urlparse(result["marketplaceUrl"])
    q = parse_qs(parsed.query)
    assert q["featureId"] == ["docs-by-status"]
    assert q["buyerAccountId"] == ["111122223333"]
    assert q["returnUrl"] == ["http://app/features/docs-by-status"]


def test_simulator_mode_synthesizes_product_code(monkeypatch, load_lambda):
    """In simulator mode, unmapped featureIds fall back to prod-<id>-sim."""
    mod = _preload(monkeypatch, load_lambda, product_map="{}")
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    assert result["productCode"] == "prod-docs-by-status-sim"
    assert "prod-docs-by-status-sim" in result["marketplaceUrl"]


def test_marketplace_mode_requires_product_code(monkeypatch, load_lambda):
    """In marketplace mode, unmapped featureId raises SubscribeError."""
    mod = _preload(
        monkeypatch,
        load_lambda,
        source_tag="marketplace",
        simulator_endpoint="",
        product_map='{"other":"x"}',
    )
    with pytest.raises(mod.SubscribeError, match="productCode"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_marketplace_mode_uses_marketplace_url_map(monkeypatch, load_lambda):
    """In marketplace mode, returns the URL from FEATURE_MARKETPLACE_URL_MAP."""
    mod = _preload(
        monkeypatch,
        load_lambda,
        source_tag="marketplace",
        simulator_endpoint="",
        product_map='{"docs-by-status":"prod123"}',
        marketplace_url_map='{"docs-by-status":"https://aws.amazon.com/marketplace/pp/prodview-abc"}',
    )
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    assert (
        result["marketplaceUrl"] == "https://aws.amazon.com/marketplace/pp/prodview-abc"
    )
    assert result["source"] == "marketplace"


def test_marketplace_mode_requires_marketplace_url(monkeypatch, load_lambda):
    """In marketplace mode without a URL map AND no simulator fallback, raises."""
    mod = _preload(
        monkeypatch,
        load_lambda,
        source_tag="marketplace",
        simulator_endpoint="",  # no simulator fallback
        product_map='{"docs-by-status":"prod123"}',
        marketplace_url_map="{}",
    )
    with pytest.raises(mod.SubscribeError, match="marketplace URL"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_offer_id_is_threaded_through(monkeypatch, load_lambda):
    """When FEATURE_OFFER_ID_MAP has an entry, offerId appears in the URL."""
    mod = _preload(
        monkeypatch,
        load_lambda,
        offer_map='{"docs-by-status":"offer-abc123"}',
    )
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    q = parse_qs(urlparse(result["marketplaceUrl"]).query)
    assert q["offerId"] == ["offer-abc123"]


def test_rejects_non_admin(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    with pytest.raises(Exception, match="Admin"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Viewer"]
            ),
            None,
        )


def test_missing_feature_id(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    with pytest.raises(ValueError, match="featureId"):
        mod.handler(
            make_appsync_event("subscribeFeature", {}, groups=["Admin"]),
            None,
        )


def test_missing_simulator_endpoint_in_simulator_mode(monkeypatch, load_lambda):
    """Simulator mode + no endpoint → SubscribeError (can't build URL)."""
    mod = _preload(monkeypatch, load_lambda, simulator_endpoint="")
    with pytest.raises(mod.SubscribeError, match="SIMULATOR_ADMIN_ENDPOINT"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_header_customer_identifier_takes_precedence(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature",
            {"featureId": "docs-by-status"},
            groups=["Admin"],
            headers={"x-amzn-marketplace-customer-identifier": "CUST-override"},
        ),
        None,
    )
    assert result["customerIdentifier"] == "CUST-override"


def test_default_customer_identifier_for_simulator_when_missing(
    monkeypatch, load_lambda
):
    """Simulator mode with no default customer → falls back to cust-idp-default."""
    mod = _preload(monkeypatch, load_lambda, default_customer="")
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    assert result["customerIdentifier"] == "cust-idp-default"


def test_return_url_defaults_when_not_supplied(monkeypatch, load_lambda):
    """If the caller didn't supply returnUrl, a default /features/<id> is used."""
    mod = _preload(monkeypatch, load_lambda)
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    q = parse_qs(urlparse(result["marketplaceUrl"]).query)
    assert q["returnUrl"] == ["/features/docs-by-status"]
