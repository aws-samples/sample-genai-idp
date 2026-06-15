"""Unit tests for the subscribe_feature Lambda.

The Lambda returns a Marketplace (or simulator) URL the UI should redirect the
admin to. The product code + marketplace listing URL now come from the feature's
InstalledFeatures row (baked from the manifest at install) — not a host env map.
These tests seed that row via the `installed_features_table` fixture.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from _helpers import make_appsync_event


def _seed_row(table_name, feature_id, *, product_code=None, listing_url=None):
    """Put an InstalledFeatures row carrying the marketplace identity."""
    item = {"featureId": feature_id}
    if product_code is not None:
        item["productCode"] = product_code
    if listing_url is not None:
        item["marketplaceListingUrl"] = listing_url
    boto3.resource("dynamodb", region_name="us-east-1").Table(table_name).put_item(
        Item=item
    )


def _preload(
    monkeypatch,
    load_lambda,
    *,
    table_name="",
    simulator_endpoint="http://sim.example.com",
    offer_map="{}",
    default_customer="CUST-default",
    default_buyer_account="111122223333",
    source_tag="simulator",
):
    monkeypatch.setenv("SIMULATOR_ADMIN_ENDPOINT", simulator_endpoint)
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", table_name)
    monkeypatch.setenv("FEATURE_OFFER_ID_MAP", offer_map)
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", default_customer)
    monkeypatch.setenv("DEFAULT_BUYER_ACCOUNT_ID", default_buyer_account)
    monkeypatch.setenv("ADMIN_GROUP", "Admin")
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", source_tag)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("subscribe_feature")


def test_happy_path_simulator_mode(monkeypatch, load_lambda, installed_features_table):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
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


def test_simulator_mode_synthesizes_product_code(
    monkeypatch, load_lambda, installed_features_table
):
    """In simulator mode, a row without a productCode falls back to prod-<id>-sim."""
    _seed_row(installed_features_table, "docs-by-status")  # no productCode
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    assert result["productCode"] == "prod-docs-by-status-sim"
    assert "prod-docs-by-status-sim" in result["marketplaceUrl"]


def test_marketplace_mode_requires_product_code(
    monkeypatch, load_lambda, installed_features_table
):
    """In marketplace mode, a feature whose install row has no productCode raises."""
    _seed_row(installed_features_table, "docs-by-status")  # no productCode
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        source_tag="marketplace",
        simulator_endpoint="",
    )
    with pytest.raises(mod.SubscribeError, match="productCode"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_marketplace_mode_uses_install_row_listing_url(
    monkeypatch, load_lambda, installed_features_table
):
    """In marketplace mode, returns the listing URL from the install row."""
    _seed_row(
        installed_features_table,
        "docs-by-status",
        product_code="prod123",
        listing_url="https://aws.amazon.com/marketplace/pp/prodview-abc",
    )
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        source_tag="marketplace",
        simulator_endpoint="",
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


def test_marketplace_mode_requires_listing_url(
    monkeypatch, load_lambda, installed_features_table
):
    """Marketplace mode, row has productCode but no listing URL AND no simulator
    fallback → raises."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        source_tag="marketplace",
        simulator_endpoint="",  # no simulator fallback
    )
    with pytest.raises(mod.SubscribeError, match="listing URL"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_offer_id_is_threaded_through(
    monkeypatch, load_lambda, installed_features_table
):
    """When FEATURE_OFFER_ID_MAP has an entry, offerId appears in the URL."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
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


def test_rejects_non_admin(monkeypatch, load_lambda, installed_features_table):
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    with pytest.raises(Exception, match="Admin"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Viewer"]
            ),
            None,
        )


def test_missing_feature_id(monkeypatch, load_lambda, installed_features_table):
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    with pytest.raises(ValueError, match="featureId"):
        mod.handler(
            make_appsync_event("subscribeFeature", {}, groups=["Admin"]),
            None,
        )


def test_missing_simulator_endpoint_in_simulator_mode(
    monkeypatch, load_lambda, installed_features_table
):
    """Simulator mode + no endpoint → SubscribeError (can't build URL)."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        simulator_endpoint="",
    )
    with pytest.raises(mod.SubscribeError, match="SIMULATOR_ADMIN_ENDPOINT"):
        mod.handler(
            make_appsync_event(
                "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
            ),
            None,
        )


def test_header_customer_identifier_takes_precedence(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
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
    monkeypatch, load_lambda, installed_features_table
):
    """Simulator mode with no default customer → falls back to cust-idp-default."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        default_customer="",
    )
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    assert result["customerIdentifier"] == "cust-idp-default"


def test_return_url_defaults_when_not_supplied(
    monkeypatch, load_lambda, installed_features_table
):
    """If the caller didn't supply returnUrl, a default /features/<id> is used."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    result = mod.handler(
        make_appsync_event(
            "subscribeFeature", {"featureId": "docs-by-status"}, groups=["Admin"]
        ),
        None,
    )
    q = parse_qs(urlparse(result["marketplaceUrl"]).query)
    assert q["returnUrl"] == ["/features/docs-by-status"]
