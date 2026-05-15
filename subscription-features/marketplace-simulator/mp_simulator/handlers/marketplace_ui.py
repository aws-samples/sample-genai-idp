"""HTML "Marketplace Simulation" buyer console.

A small set of browser-facing HTML pages that stand in for the pages a real
AWS Marketplace buyer clicks through (the `aws.amazon.com/marketplace/pp/...`
product listing, the purchase-options page, the EULA / terms acceptance
form, and the post-subscribe "Set up your account" page).

The IDP UI redirects the admin here instead of silently activating an
entitlement via `/admin/entitlements`, so the dev/demo experience matches
the real Marketplace flow: redirect → accept terms → return to app.

Branded prominently as **Marketplace Simulation** throughout to make it
obvious this is not real AWS Marketplace. Pages are plain HTML with a
small inline stylesheet — zero template-engine dependency, matching the
rest of the simulator's stdlib-only posture.

Endpoints (all under `/marketplace/*`):

    GET  /marketplace/pp/{productCode}
         Product listing page. Shows product name, description, pricing,
         and a "View purchase options" link to the offer page.

    GET  /marketplace/pp/{productCode}/offer/{offerId}
         Purchase-options / terms-acceptance page. Three required
         checkboxes (pricing, EULA, AWS Customer Agreement); form POSTs
         to /marketplace/subscribe.

    POST /marketplace/subscribe
         Form target. Validates the three checkboxes and, on success,
         calls the existing JSON `buyer.subscribe()` handler to create
         the subscription + seed entitlements + POST the registration
         token to the product's fulfillment URL. Redirects to the
         success page.

    GET  /marketplace/subscribe/success?customerIdentifier=...&returnUrl=...
         "Your subscription is active" page with a Return to Application
         button.

    GET  /marketplace/subscribe/cancel?returnUrl=...
         Bounce page when the admin clicks Cancel on the offer page.

Query-string parameters threaded through every page:

    returnUrl       Full URL to send the browser back to when the flow
                    completes or cancels (usually the IDP FeaturePage URL).
    buyerAccountId  12-digit simulator account identifier the admin is
                    subscribing on behalf of. Default DEFAULT_BUYER_ACCOUNT_ID
                    when not supplied.
    offerId         Which offer to subscribe to. Defaults to the product's
                    first public offer.

Design note: the richer marketplace-catalog / product-listing surfacing
(contract tiers, metering dimensions, fulfillment URL preview, trial
terms) is intentionally minimal. The goal is to convey the *flow* — not
to re-implement aws.amazon.com/marketplace/pp/… pixel-perfect.
"""

from __future__ import annotations

import html
import json
from typing import Any, Optional
from urllib.parse import quote_plus, urlencode

from .. import db
from ..protocol import InvalidParameterException
from . import admin as admin_handler
from . import buyer as buyer_handler

# ---------------------------------------------------------------------------
# shared markup fragments

_BRAND = "Marketplace Simulation"

_CSS = """
  :root {
    --mp-bg: #ffffff;
    --mp-text: #16191f;
    --mp-muted: #5f6b7a;
    --mp-border: #d5dbdb;
    --mp-accent: #0972d3;
    --mp-accent-dark: #033160;
    --mp-warn-bg: #fff4e1;
    --mp-warn-border: #e58c00;
    --mp-success-bg: #e8f5ea;
    --mp-success-border: #2e7d32;
    --mp-error-bg: #fdeeee;
    --mp-error-border: #d13212;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    color: var(--mp-text);
    background: var(--mp-bg);
    margin: 0;
    padding: 0;
    line-height: 1.45;
  }
  header.sim-banner {
    background: var(--mp-warn-bg);
    border-bottom: 2px solid var(--mp-warn-border);
    color: #663c00;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: 600;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  header.sim-banner .pill {
    display: inline-block;
    background: var(--mp-warn-border);
    color: #fff;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  nav.sim-nav {
    background: #232f3e;
    color: #fff;
    padding: 14px 24px;
    font-size: 18px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  nav.sim-nav .logo {
    background: #ff9900;
    color: #000;
    font-weight: 800;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 14px;
  }
  main {
    max-width: 900px;
    margin: 28px auto;
    padding: 0 24px 64px 24px;
  }
  main h1 {
    font-size: 24px;
    margin: 0 0 4px 0;
  }
  main .subtitle {
    color: var(--mp-muted);
    font-size: 14px;
    margin-bottom: 18px;
  }
  section.card {
    border: 1px solid var(--mp-border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 20px;
    background: #fff;
  }
  section.card h2 {
    font-size: 16px;
    margin: 0 0 10px 0;
  }
  dl.facts {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 8px 16px;
    margin: 0;
    font-size: 14px;
  }
  dl.facts dt { color: var(--mp-muted); }
  dl.facts dd { margin: 0; }
  label.terms {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 10px 0;
    border-bottom: 1px solid var(--mp-border);
    font-size: 14px;
  }
  label.terms:last-of-type { border-bottom: none; }
  label.terms input { margin-top: 3px; flex-shrink: 0; }
  .actions {
    display: flex;
    gap: 10px;
    margin-top: 20px;
  }
  button, a.btn {
    font: inherit;
    cursor: pointer;
    padding: 8px 18px;
    border-radius: 4px;
    border: 1px solid var(--mp-accent);
    background: var(--mp-accent);
    color: #fff;
    text-decoration: none;
    display: inline-block;
  }
  button.secondary, a.btn.secondary {
    background: #fff;
    color: var(--mp-accent);
  }
  button:hover, a.btn:hover { background: var(--mp-accent-dark); color: #fff; }
  button.secondary:hover, a.btn.secondary:hover {
    background: #f5f9ff;
    color: var(--mp-accent-dark);
  }
  .alert {
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 16px;
    font-size: 14px;
  }
  .alert.success { background: var(--mp-success-bg); border: 1px solid var(--mp-success-border); color: #1b5e20; }
  .alert.error { background: var(--mp-error-bg); border: 1px solid var(--mp-error-border); color: #7f1d1d; }
  footer.sim-footer {
    color: var(--mp-muted);
    font-size: 12px;
    text-align: center;
    padding: 24px 16px;
    border-top: 1px solid var(--mp-border);
    margin-top: 24px;
  }
  code { background: #f2f3f3; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
"""


def _page(title: str, body: str) -> bytes:
    """Assemble a full HTML document with the simulator chrome."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} | {_BRAND}</title>
  <style>{_CSS}</style>
</head>
<body>
  <header class="sim-banner">
    <span>⚠️ This is a <b>Marketplace Simulation</b> — not aws.amazon.com. No real charges will be made.</span>
    <span class="pill">Simulator</span>
  </header>
  <nav class="sim-nav">
    <span class="logo">aws</span>
    <span>{_BRAND}</span>
  </nav>
  <main>
    {body}
  </main>
  <footer class="sim-footer">
    Marketplace Simulation — a local stand-in for AWS Marketplace used by the IDP Accelerator feature platform.
  </footer>
</body>
</html>""".encode("utf-8")


def _error_page(title: str, message: str) -> bytes:
    body = f"""
      <h1>{html.escape(title)}</h1>
      <section class="card">
        <div class="alert error">{html.escape(message)}</div>
      </section>
    """
    return _page(title, body)


# ---------------------------------------------------------------------------
# subscription lookup helpers


def _find_existing_subscription(
    product_code: str, buyer_account_id: str
) -> Optional[dict[str, Any]]:
    """Return the ACTIVE subscription row + customerIdentifier shape that
    ``buyer_handler.subscribe`` would normally return, or None if no active
    subscription exists for this (product, buyer-account) pair.

    Used by ``handle_subscribe_post`` to make re-subscribe idempotent (match
    real AWS Marketplace behaviour) instead of erroring out when the admin
    clicks Subscribe a second time after an earlier successful flow.
    """
    with db.read() as conn:
        row = conn.execute(
            """SELECT customer_identifier, product_code
               FROM subscriptions
               WHERE customer_aws_account_id = ?
                 AND product_code = ?
                 AND status IN ('trial', 'active')
               ORDER BY subscribed_at DESC
               LIMIT 1""",
            (buyer_account_id, product_code),
        ).fetchone()
    if not row:
        return None
    # Shape matches buyer_handler.subscribe's return so the caller can
    # reuse the same downstream code path.
    return {
        "customerIdentifier": row["customer_identifier"],
        "productCode": row["product_code"],
    }


# ---------------------------------------------------------------------------
# offer lookup helpers


def _default_offer_for_product(product_code: str) -> Optional[dict[str, Any]]:
    offers = admin_handler.list_offers(product_code)
    # Prefer first public offer; else the first offer at all.
    for o in offers:
        if o.get("kind") == "public":
            return o
    return offers[0] if offers else None


def _ensure_product_and_offer(
    product_code: str, feature_id: Optional[str] = None, offer_id: Optional[str] = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch product + offer, lazily creating both if needed. Used so the
    simulator buyer-console flow works end-to-end even when the admin has
    never called create_product / create_offer explicitly — the feature
    platform's subscribe_feature Lambda kicks off the flow with just a
    `productCode` derived from the featureId.
    """
    # Product: create if missing (same minimal row shape as admin.grant_entitlement).
    try:
        product = admin_handler.get_product(product_code)
    except InvalidParameterException:
        admin_handler._ensure_product(product_code, feature_id)  # type: ignore[attr-defined]
        product = admin_handler.get_product(product_code)

    # Offer: if specific offerId provided, fetch it; else use default; else create.
    offer = None
    if offer_id:
        try:
            offer = admin_handler.get_offer(offer_id)
        except InvalidParameterException:
            offer = None
    if offer is None:
        offer = _default_offer_for_product(product_code)
    if offer is None:
        # Auto-create a zero-price public offer so the flow can proceed.
        offer = admin_handler.create_offer(
            {
                "productCode": product_code,
                "kind": "public",
                "durationMonths": 12,
                "freeTrialEnabled": False,
            }
        )
    return product, offer


# ---------------------------------------------------------------------------
# GET /marketplace/pp/{productCode}


def product_listing(product_code: str, query: dict[str, Any]) -> bytes:
    return_url = query.get("returnUrl", "")
    buyer_account_id = query.get("buyerAccountId", "")
    feature_id = query.get("featureId")
    offer_id = query.get("offerId")

    try:
        product, offer = _ensure_product_and_offer(
            product_code, feature_id=feature_id, offer_id=offer_id
        )
    except InvalidParameterException as exc:
        return _error_page("Product not found", str(exc))

    dims = json.loads(product.get("dimensions_json") or "[]")
    dim_lines = (
        "<ul>"
        + "".join(
            f"<li><b>{html.escape(d.get('displayName', d.get('apiName', '')))}</b> "
            f"— {html.escape(d.get('category', ''))}</li>"
            for d in dims
        )
        + "</ul>"
        if dims
        else '<p class="muted">No dimensions declared.</p>'
    )

    offer_params = urlencode(
        {
            k: v
            for k, v in {
                "returnUrl": return_url,
                "buyerAccountId": buyer_account_id,
                "featureId": feature_id or "",
            }.items()
            if v
        }
    )
    view_offer_href = (
        f"/marketplace/pp/{quote_plus(product_code)}/offer/{quote_plus(offer['offer_id'])}"
        + (f"?{offer_params}" if offer_params else "")
    )
    cancel_href = (
        f"/marketplace/subscribe/cancel?{urlencode({'returnUrl': return_url})}"
        if return_url
        else "/marketplace/subscribe/cancel"
    )

    body = f"""
      <h1>{html.escape(product["name"])}</h1>
      <div class="subtitle">By <b>Amazon Web Services (Simulated Seller)</b> · Product code:
        <code>{html.escape(product["product_code"])}</code></div>

      <section class="card">
        <h2>Overview</h2>
        <p>This is a simulated AWS Marketplace product listing. In production, clicking
        <b>View purchase options</b> would take you to the offer acceptance page on
        <code>aws.amazon.com/marketplace</code>. Here, it takes you to the equivalent
        simulated page.</p>
      </section>

      <section class="card">
        <h2>Pricing &amp; terms</h2>
        <dl class="facts">
          <dt>Pricing model</dt><dd>{html.escape(product.get("pricing_model", "contract"))}</dd>
          <dt>Duration</dt><dd>{int(offer.get("duration_months") or 12)} months</dd>
          <dt>Free trial</dt><dd>{("Yes — " + str(product.get("trial_days")) + " days") if product.get("trial_days") else "No"}</dd>
          <dt>Offer kind</dt><dd>{html.escape(offer.get("kind", "public"))}</dd>
        </dl>
      </section>

      <section class="card">
        <h2>Included dimensions</h2>
        {dim_lines}
      </section>

      <div class="actions">
        <a class="btn" href="{html.escape(view_offer_href)}">View purchase options →</a>
        <a class="btn secondary" href="{html.escape(cancel_href)}">Cancel</a>
      </div>
    """
    return _page(product["name"], body)


# ---------------------------------------------------------------------------
# GET /marketplace/pp/{productCode}/offer/{offerId}


def offer_page(product_code: str, offer_id: str, query: dict[str, Any]) -> bytes:
    return_url = query.get("returnUrl", "")
    buyer_account_id = query.get("buyerAccountId", "")
    feature_id = query.get("featureId", "")

    try:
        product, offer = _ensure_product_and_offer(
            product_code, feature_id=feature_id, offer_id=offer_id
        )
    except InvalidParameterException as exc:
        return _error_page("Offer not found", str(exc))

    # Surface any error from a failed subscribe attempt (passed via ?error=)
    error_msg = query.get("error", "")
    error_html = f'<div class="alert error">{html.escape(error_msg)}</div>' if error_msg else ""

    body = f"""
      <h1>Subscribe — {html.escape(product["name"])}</h1>
      <div class="subtitle">Review the terms and complete your subscription.</div>

      {error_html}

      <section class="card">
        <h2>Order summary</h2>
        <dl class="facts">
          <dt>Product</dt><dd>{html.escape(product["name"])}</dd>
          <dt>Offer</dt><dd><code>{html.escape(offer["offer_id"])}</code> ({html.escape(offer.get("kind", "public"))})</dd>
          <dt>Duration</dt><dd>{int(offer.get("duration_months") or 12)} months</dd>
          <dt>Buyer account</dt><dd><code>{html.escape(buyer_account_id) or "(default)"}</code></dd>
        </dl>
      </section>

      <form method="POST" action="/marketplace/subscribe">
        <input type="hidden" name="productCode" value="{html.escape(product["product_code"])}">
        <input type="hidden" name="offerId" value="{html.escape(offer["offer_id"])}">
        <input type="hidden" name="buyerAccountId" value="{html.escape(buyer_account_id)}">
        <input type="hidden" name="returnUrl" value="{html.escape(return_url)}">
        <input type="hidden" name="featureId" value="{html.escape(feature_id)}">

        <section class="card">
          <h2>Terms of service</h2>
          <label class="terms">
            <input type="checkbox" name="acceptPricing" value="1" required>
            <span>I have reviewed and accept the <b>pricing</b> for this subscription. (Simulated — no real charge.)</span>
          </label>
          <label class="terms">
            <input type="checkbox" name="acceptEula" value="1" required>
            <span>I have reviewed and accept the <b>seller's End User License Agreement (EULA)</b>.</span>
          </label>
          <label class="terms">
            <input type="checkbox" name="acceptAwsCa" value="1" required>
            <span>I have reviewed and accept the <b>AWS Customer Agreement</b>.</span>
          </label>
        </section>

        <div class="actions">
          <button type="submit">Subscribe</button>
          <a class="btn secondary" href="/marketplace/subscribe/cancel?{urlencode({"returnUrl": return_url}) if return_url else ""}">Cancel</a>
        </div>
      </form>
    """
    return _page(f"Subscribe to {product['name']}", body)


# ---------------------------------------------------------------------------
# POST /marketplace/subscribe — returns a redirect Location OR an error page.


def handle_subscribe_post(form: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    """Return (status, headers, body) for the POST target.

    On success → 302 Location = /marketplace/subscribe/success?...
    On failure → re-render the offer page with an error alert.
    """
    product_code = form.get("productCode", "").strip()
    offer_id = form.get("offerId", "").strip()
    buyer_account_id = form.get("buyerAccountId", "").strip() or "111122223333"
    return_url = form.get("returnUrl", "")
    feature_id = form.get("featureId", "")

    missing_terms = []
    if not form.get("acceptPricing"):
        missing_terms.append("pricing")
    if not form.get("acceptEula"):
        missing_terms.append("EULA")
    if not form.get("acceptAwsCa"):
        missing_terms.append("AWS Customer Agreement")
    if missing_terms:
        err = f"You must accept: {', '.join(missing_terms)}."
        qs = urlencode(
            {
                "error": err,
                "returnUrl": return_url,
                "buyerAccountId": buyer_account_id,
                "featureId": feature_id,
            }
        )
        loc = f"/marketplace/pp/{quote_plus(product_code)}/offer/{quote_plus(offer_id)}?{qs}"
        return 302, {"Location": loc}, b""

    try:
        # Ensure product and offer exist — the admin may never have hit the admin API.
        _ensure_product_and_offer(product_code, feature_id=feature_id, offer_id=offer_id)
        sub = buyer_handler.subscribe({"offerId": offer_id, "buyerAccountId": buyer_account_id})
    except InvalidParameterException as exc:
        # Real AWS Marketplace treats "re-subscribe while already subscribed"
        # as an idempotent no-op (it shows "This account is already subscribed
        # — continue to manage"). The simulator's `buyer_handler.subscribe`
        # raises InvalidParameterException in that case, but we don't want to
        # dead-end the buyer: the IDP UI may be showing "not subscribed"
        # because its own entitlement cache hasn't caught up. Look up the
        # existing subscription, re-grant the entitlement (idempotent), and
        # redirect to the success page so the UI's return-to-app refresh
        # picks up the active state.
        msg = str(exc).lower()
        if "already has an active subscription" in msg:
            existing = _find_existing_subscription(product_code, buyer_account_id)
            if existing:
                sub = existing
            else:
                # Shouldn't happen, but fail gracefully with the raw error.
                qs = urlencode(
                    {
                        "error": str(exc),
                        "returnUrl": return_url,
                        "buyerAccountId": buyer_account_id,
                        "featureId": feature_id,
                    }
                )
                loc = (
                    f"/marketplace/pp/{quote_plus(product_code)}/offer/{quote_plus(offer_id)}?{qs}"
                )
                return 302, {"Location": loc}, b""
        else:
            qs = urlencode(
                {
                    "error": str(exc),
                    "returnUrl": return_url,
                    "buyerAccountId": buyer_account_id,
                    "featureId": feature_id,
                }
            )
            loc = f"/marketplace/pp/{quote_plus(product_code)}/offer/{quote_plus(offer_id)}?{qs}"
            return 302, {"Location": loc}, b""

    # Simulator shortcut: also grant a Boolean "feature" entitlement so the
    # existing check_feature_entitlement path (which queries by productCode
    # only, not offerId) sees ACTIVE for this buyer account. Real Marketplace
    # does this automatically for feature-flag products; the simulator's
    # buyer.subscribe does it for contract offers too, so this is only
    # needed for the zero-price fallback path where no contract tier exists.
    try:
        admin_handler.grant_entitlement(
            {
                "customerIdentifier": sub["customerIdentifier"],
                "productCode": product_code,
                "featureId": feature_id or None,
            }
        )
    except Exception:
        # Non-fatal: buyer.subscribe already seeded entitlements where appropriate.
        pass

    # Also pin the default customer identifier → productCode mapping so the
    # IDP's check_feature_entitlement Lambda (which resolves the caller to
    # DEFAULT_CUSTOMER_IDENTIFIER) can find this entitlement. We do this by
    # writing an additional entitlement row keyed by "cust-idp-default".
    try:
        admin_handler.grant_entitlement(
            {
                "customerIdentifier": "cust-idp-default",
                "productCode": product_code,
                "featureId": feature_id or None,
            }
        )
    except Exception:
        pass

    qs = urlencode(
        {
            "customerIdentifier": sub["customerIdentifier"],
            "productCode": product_code,
            "returnUrl": return_url,
            "featureId": feature_id,
        }
    )
    return 302, {"Location": f"/marketplace/subscribe/success?{qs}"}, b""


# ---------------------------------------------------------------------------
# GET /marketplace/subscribe/success


def success_page(query: dict[str, Any]) -> bytes:
    return_url = query.get("returnUrl", "")
    customer_identifier = query.get("customerIdentifier", "")
    product_code = query.get("productCode", "")
    feature_id = query.get("featureId", "")

    # Append a subscribe=success flag so the app can refresh entitlement state.
    if return_url:
        sep = "&" if "?" in return_url else "?"
        return_href = f"{return_url}{sep}subscribe=success"
    else:
        return_href = "/"

    body = f"""
      <h1>Subscription active ✓</h1>
      <div class="subtitle">Your simulated subscription has been recorded.</div>

      <section class="card">
        <div class="alert success">
          Subscription is now <b>ACTIVE</b>. You can close this tab or return to the application to continue.
        </div>
        <dl class="facts">
          <dt>Product code</dt><dd><code>{html.escape(product_code)}</code></dd>
          <dt>Customer identifier</dt><dd><code>{html.escape(customer_identifier)}</code></dd>
          {("<dt>Feature</dt><dd><code>" + html.escape(feature_id) + "</code></dd>") if feature_id else ""}
        </dl>
      </section>

      <section class="card">
        <h2>Next step: set up your account</h2>
        <p>In the real AWS Marketplace flow, the <b>Set up your account</b> button would POST
        a <code>x-amzn-marketplace-token</code> to the seller's fulfillment URL. The simulator
        has already done this on your behalf when the subscription was created.</p>
        <p>Returning to the application will refresh the feature's entitlement state to <b>ACTIVE</b>.</p>
      </section>

      <div class="actions">
        <a class="btn" href="{html.escape(return_href)}">Return to application →</a>
      </div>
    """
    return _page("Subscription active", body)


# ---------------------------------------------------------------------------
# GET /marketplace/subscribe/cancel


def cancel_page(query: dict[str, Any]) -> bytes:
    return_url = query.get("returnUrl", "")
    if return_url:
        sep = "&" if "?" in return_url else "?"
        return_href = f"{return_url}{sep}subscribe=cancelled"
    else:
        return_href = "/"
    body = f"""
      <h1>Subscription cancelled</h1>
      <section class="card">
        <div class="alert error">
          You cancelled before accepting the terms. No subscription was created.
        </div>
      </section>
      <div class="actions">
        <a class="btn" href="{html.escape(return_href)}">Return to application</a>
      </div>
    """
    return _page("Cancelled", body)


# ---------------------------------------------------------------------------
# db ref is imported just to keep flake quiet (used for type visibility)

_ = db  # noqa: F841
