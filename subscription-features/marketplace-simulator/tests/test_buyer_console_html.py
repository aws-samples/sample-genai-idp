"""Tests for the HTML "Marketplace Simulation" buyer console.

These exercise the browser-facing `/marketplace/*` surface added to the
simulator — the product listing page, the offer / terms-acceptance page,
and the form POST that completes a subscription.

The UI's `subscribeFeature` mutation redirects the admin here instead of
silently granting an entitlement, mirroring how real AWS Marketplace
requires pricing + EULA + AWS Customer Agreement acceptance before a
subscription becomes ACTIVE.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import requests


def test_product_listing_page_renders(simulator):
    base, _client = simulator
    r = requests.get(
        f"{base}/marketplace/pp/prod-docs-by-status-sim",
        params={"featureId": "docs-by-status", "returnUrl": "http://app/features/docs-by-status"},
    )
    r.raise_for_status()
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "Marketplace Simulation" in body
    assert "prod-docs-by-status-sim" in body
    # Simulator banner must be prominent
    assert "not aws.amazon.com" in body
    # View purchase options link should point to the offer page
    assert "/marketplace/pp/prod-docs-by-status-sim/offer/" in body


def test_offer_page_has_three_required_checkboxes(simulator):
    base, _client = simulator
    # First hit listing page so the simulator lazily creates product + default offer
    r0 = requests.get(f"{base}/marketplace/pp/prod-foo-sim", params={"featureId": "foo"})
    r0.raise_for_status()
    # Find the generated offerId from the HTML
    import re

    m = re.search(r"/marketplace/pp/prod-foo-sim/offer/([^\"?]+)", r0.text)
    assert m, "listing page should link to an offer page"
    offer_id = m.group(1)

    r = requests.get(
        f"{base}/marketplace/pp/prod-foo-sim/offer/{offer_id}",
        params={"featureId": "foo", "returnUrl": "http://app/x"},
    )
    r.raise_for_status()
    body = r.text
    # The three required acceptance checkboxes
    assert 'name="acceptPricing"' in body
    assert 'name="acceptEula"' in body
    assert 'name="acceptAwsCa"' in body
    # Hidden form fields for the POST target
    assert 'name="productCode"' in body
    assert 'name="offerId"' in body
    assert 'name="returnUrl"' in body
    # Form posts to /marketplace/subscribe
    assert 'action="/marketplace/subscribe"' in body


def test_subscribe_post_requires_all_three_terms(simulator):
    base, _client = simulator
    # Lazily create the product + default offer via a listing GET
    r0 = requests.get(f"{base}/marketplace/pp/prod-missing-terms-sim")
    r0.raise_for_status()
    import re

    m = re.search(r"/marketplace/pp/prod-missing-terms-sim/offer/([^\"?]+)", r0.text)
    offer_id = m.group(1)

    # POST with only pricing accepted — must 302 back to the offer page with an error.
    r = requests.post(
        f"{base}/marketplace/subscribe",
        data={
            "productCode": "prod-missing-terms-sim",
            "offerId": offer_id,
            "buyerAccountId": "111122223333",
            "returnUrl": "http://app/x",
            "acceptPricing": "1",
            # acceptEula missing
            # acceptAwsCa missing
        },
        allow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["Location"]
    parsed = urlparse(loc)
    assert f"/marketplace/pp/prod-missing-terms-sim/offer/{offer_id}" in parsed.path
    q = parse_qs(parsed.query)
    assert "error" in q
    assert "EULA" in q["error"][0]


def test_subscribe_post_happy_path_creates_subscription(simulator):
    base, client = simulator
    # Lazily create the product + default offer via a listing GET
    r0 = requests.get(
        f"{base}/marketplace/pp/prod-happy-sim",
        params={"featureId": "happy"},
    )
    r0.raise_for_status()
    import re

    m = re.search(r"/marketplace/pp/prod-happy-sim/offer/([^\"?]+)", r0.text)
    offer_id = m.group(1)

    r = requests.post(
        f"{base}/marketplace/subscribe",
        data={
            "productCode": "prod-happy-sim",
            "offerId": offer_id,
            "buyerAccountId": "111122223333",
            "returnUrl": "http://app/features/happy",
            "featureId": "happy",
            "acceptPricing": "1",
            "acceptEula": "1",
            "acceptAwsCa": "1",
        },
        allow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert loc.startswith("/marketplace/subscribe/success?")
    q = parse_qs(urlparse(loc).query)
    customer_id = q["customerIdentifier"][0]
    assert customer_id.startswith("cust-")

    # The subscription should be visible via the admin API.
    subs = client.list_subscriptions()
    match = [s for s in subs if s["product_code"] == "prod-happy-sim"]
    assert len(match) == 1
    assert match[0]["customer_identifier"] == customer_id

    # Fetching the success page should render cleanly with the return button.
    success = requests.get(
        f"{base}/marketplace/subscribe/success",
        params={
            "customerIdentifier": customer_id,
            "productCode": "prod-happy-sim",
            "returnUrl": "http://app/features/happy",
            "featureId": "happy",
        },
    )
    success.raise_for_status()
    body = success.text
    assert "Subscription active" in body
    assert "Return to application" in body
    assert "http://app/features/happy" in body
    assert "subscribe=success" in body


def test_subscribe_post_is_idempotent_for_existing_subscription(simulator):
    """Re-submitting the subscribe form when the buyer already has an ACTIVE
    subscription must redirect to the success page (mirrors real Marketplace's
    'this account is already subscribed — continue' UX) instead of returning
    a 500 or dead-ending the buyer on the offer page with an error.

    Regression guard for the case where the IDP UI's entitlement cache shows
    "not subscribed" but the simulator DB still has a prior subscription row
    — the buyer should still be able to complete the Marketplace flow and
    have the UI's focus-refresh pick up ACTIVE state.
    """
    base, _client = simulator
    # Lazily create product + offer via listing GET
    r0 = requests.get(
        f"{base}/marketplace/pp/prod-idempotent-sim",
        params={"featureId": "idempotent"},
    )
    r0.raise_for_status()
    import re

    m = re.search(r"/marketplace/pp/prod-idempotent-sim/offer/([^\"?]+)", r0.text)
    offer_id = m.group(1)
    payload = {
        "productCode": "prod-idempotent-sim",
        "offerId": offer_id,
        "buyerAccountId": "111122223333",
        "returnUrl": "http://app/features/idempotent",
        "featureId": "idempotent",
        "acceptPricing": "1",
        "acceptEula": "1",
        "acceptAwsCa": "1",
    }

    r1 = requests.post(f"{base}/marketplace/subscribe", data=payload, allow_redirects=False)
    assert r1.status_code == 302
    loc1 = r1.headers["Location"]
    assert loc1.startswith("/marketplace/subscribe/success?")
    customer_id_1 = parse_qs(urlparse(loc1).query)["customerIdentifier"][0]

    # Second submit (same buyer + same product): must NOT 500 and must NOT
    # bounce to the offer page with an "already subscribed" error. Should
    # redirect to the same success page with the same customerIdentifier.
    r2 = requests.post(f"{base}/marketplace/subscribe", data=payload, allow_redirects=False)
    assert r2.status_code == 302, (
        f"re-subscribe should be idempotent; got status {r2.status_code} body={r2.text[:300]}"
    )
    loc2 = r2.headers["Location"]
    assert loc2.startswith("/marketplace/subscribe/success?"), (
        f"re-subscribe should land on success page; got {loc2}"
    )
    customer_id_2 = parse_qs(urlparse(loc2).query)["customerIdentifier"][0]
    # Same customerIdentifier proves we returned the existing subscription,
    # not created a new one.
    assert customer_id_1 == customer_id_2


def test_cancel_page_renders(simulator):
    base, _client = simulator
    r = requests.get(
        f"{base}/marketplace/subscribe/cancel",
        params={"returnUrl": "http://app/features/foo"},
    )
    r.raise_for_status()
    body = r.text
    assert "Subscription cancelled" in body
    assert "subscribe=cancelled" in body
