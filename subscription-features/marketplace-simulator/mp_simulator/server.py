"""HTTP server / router.

Three surfaces on one port:

1. Data-plane (AWS JSON-RPC 1.1): POST ``/`` with ``X-Amz-Target`` header. boto3
   clients using ``endpoint_url=http://host:port`` hit this surface unchanged.
2. Admin REST: ``/admin/*`` — plain JSON.
3. Buyer REST: ``/buyer/*`` — plain JSON.

A ``GET /`` returns a small HTML help page and a machine-readable ``/healthz``.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import clock, db, protocol
from .handlers import admin, agreement, buyer, catalog, entitlement, marketplace_ui, metering
from .protocol import (
    CONTENT_TYPE,
    InvalidParameterException,
    SimulatorError,
)

LOG = logging.getLogger("mp-sim.server")

# ─────────────────────────────── routing tables ──────────────────────────────
_METERING_OPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ResolveCustomer": metering.resolve_customer,
    "BatchMeterUsage": metering.batch_meter_usage,
    "MeterUsage": metering.meter_usage,
    "RegisterUsage": metering.register_usage,
}

_ENTITLEMENT_OPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "GetEntitlements": entitlement.get_entitlements,
}

_AGREEMENT_OPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "DescribeAgreement": agreement.describe_agreement,
    "SearchAgreements": agreement.search_agreements,
    "GetAgreementTerms": agreement.get_agreement_terms,
}

# marketplace-catalog is rest-json (real URL paths) rather than JSON-RPC.
# Map HTTP method + path to a handler. Handlers receive:
#   - POST/PATCH: (body_dict,)  combining JSON body + querystring params
#   - GET:        (querystring_dict,)
_CATALOG_ROUTES: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("POST", "/ListEntities"): catalog.list_entities,
    ("GET", "/DescribeEntity"): catalog.describe_entity,
    ("POST", "/StartChangeSet"): catalog.start_change_set,
    ("GET", "/DescribeChangeSet"): catalog.describe_change_set,
    ("POST", "/ListChangeSets"): catalog.list_change_sets,
    ("PATCH", "/CancelChangeSet"): catalog.cancel_change_set,
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "mp-sim/0.1"

    # ─────────────── low-level helpers ───────────────
    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _json(self) -> dict[str, Any]:
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidParameterException(f"invalid JSON: {exc}") from exc

    def _send_json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_aws_json(self, status: int, payload: dict[str, Any]) -> None:
        body = protocol.serialize(payload)
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_aws_error(self, exc: SimulatorError) -> None:
        body = protocol.error_body(exc)
        self.send_response(exc.http_status)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("X-Amzn-Errortype", exc.error_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ─────────────── routing ───────────────
    def _dispatch_catalog(self, parsed) -> bool:
        """Try to dispatch a marketplace-catalog rest-json request.
        Returns True if handled."""
        catalog_fn = _CATALOG_ROUTES.get((self.command, parsed.path))
        if catalog_fn is None:
            return False
        q = {k: v[0] if isinstance(v, list) and v else v for k, v in parse_qs(parsed.query).items()}
        if self.command in ("POST", "PATCH"):
            body = protocol.parse_request_body(self._body())
            body.update(q)
            params = body
        else:  # GET
            params = q
        result = catalog_fn(params)
        self._send_aws_json(200, result)
        return True

    def _q(self, parsed) -> dict[str, Any]:
        """Helper: flatten parse_qs results into a single-value dict."""
        return {
            k: v[0] if isinstance(v, list) and v else v for k, v in parse_qs(parsed.query).items()
        }

    def _send_html(
        self, status: int, body: bytes, extra_headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _dispatch_marketplace_ui_get(self, parsed) -> bool:
        """Route /marketplace/* GET requests. Returns True if handled."""
        path = parsed.path
        if not path.startswith("/marketplace/"):
            return False
        q = self._q(parsed)
        # /marketplace/subscribe/success
        if path == "/marketplace/subscribe/success":
            self._send_html(200, marketplace_ui.success_page(q))
            return True
        # /marketplace/subscribe/cancel
        if path == "/marketplace/subscribe/cancel":
            self._send_html(200, marketplace_ui.cancel_page(q))
            return True
        # /marketplace/pp/{productCode}/offer/{offerId}
        parts = path.split("/")
        # ['', 'marketplace', 'pp', '{pc}', 'offer', '{oid}']
        if len(parts) == 6 and parts[2] == "pp" and parts[4] == "offer":
            self._send_html(200, marketplace_ui.offer_page(parts[3], parts[5], q))
            return True
        # /marketplace/pp/{productCode}
        if len(parts) == 4 and parts[2] == "pp":
            self._send_html(200, marketplace_ui.product_listing(parts[3], q))
            return True
        self._send_html(
            404, marketplace_ui._error_page("Not found", f"Unknown marketplace path: {path}")
        )
        return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/healthz":
                self._send_json(200, {"ok": True, "now": clock.now()})
                return
            if path == "/":
                self._send_help()
                return
            # ─── marketplace-catalog (rest-json GET) ───
            if self._dispatch_catalog(parsed):
                return
            # ─── marketplace-ui (HTML buyer console) ───
            if self._dispatch_marketplace_ui_get(parsed):
                return
            if path == "/admin/state":
                self._send_json(200, db.dump_all())
                return
            if path == "/admin/products":
                self._send_json(200, admin.list_products())
                return
            if path == "/admin/offers":
                q = parse_qs(parsed.query)
                pc = (q.get("productCode") or [None])[0]
                self._send_json(200, admin.list_offers(pc))
                return
            if path == "/admin/subscriptions":
                self._send_json(200, admin.list_subscriptions())
                return
            if path == "/admin/lifecycle-sinks":
                q = parse_qs(parsed.query)
                pc = (q.get("productCode") or [None])[0]
                self._send_json(200, admin.list_lifecycle_sinks(pc))
                return
            if path == "/admin/usage":
                q = parse_qs(parsed.query)
                pc = (q.get("productCode") or [None])[0]
                self._send_json(200, admin.list_usage(pc))
                return
            if path == "/admin/notifications":
                q = parse_qs(parsed.query)
                pc = (q.get("productCode") or [None])[0]
                self._send_json(200, admin.list_notifications(pc))
                return
            if path.startswith("/admin/products/"):
                self._send_json(200, admin.get_product(path.split("/")[-1]))
                return
            if path.startswith("/admin/offers/"):
                self._send_json(200, admin.get_offer(path.split("/")[-1]))
                return
            if path.startswith("/buyer/entitlements/"):
                account = path.split("/")[-1]
                self._send_json(200, buyer.entitlements(account))
                return
        except SimulatorError as exc:
            self._send_json(exc.http_status, {"__type": exc.error_type, "message": exc.message})
            return
        self._send_json(404, {"error": f"no route for GET {path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            # ─── AWS data-plane (root POST with X-Amz-Target) ───
            if path == "/":
                target = self.headers.get("X-Amz-Target", "")
                parsed_target = protocol.parse_target(target)
                body = protocol.parse_request_body(self._body())
                if parsed_target.service == "metering":
                    ops = _METERING_OPS
                elif parsed_target.service == "entitlement":
                    ops = _ENTITLEMENT_OPS
                else:
                    ops = _AGREEMENT_OPS
                op_fn = ops.get(parsed_target.operation)
                if op_fn is None:
                    raise InvalidParameterException(f"unknown op: {parsed_target.operation}")
                result = op_fn(body)
                self._send_aws_json(200, result)
                return

            # ─── marketplace-catalog (rest-json POST) ───
            if self._dispatch_catalog(parsed):
                return

            # ─── marketplace-ui form POST ───
            if path == "/marketplace/subscribe":
                # Form-encoded body, not JSON.
                raw = self._body().decode("utf-8")
                form = {
                    k: v[0] if isinstance(v, list) and v else v
                    for k, v in parse_qs(raw, keep_blank_values=True).items()
                }
                status, headers, body_bytes = marketplace_ui.handle_subscribe_post(form)
                if status == 302:
                    self._send_html(302, body_bytes, extra_headers=headers)
                else:
                    self._send_html(status, body_bytes)
                return

            body = self._json()

            # ─── admin ───
            if path == "/admin/products":
                self._send_json(200, admin.create_product(body))
                return
            if path.startswith("/admin/products/") and path.endswith("/publish"):
                pc = path.split("/")[-2]
                self._send_json(200, admin.update_product(pc, {"published": True}))
                return
            if path.startswith("/admin/products/"):
                pc = path.split("/")[-1]
                self._send_json(200, admin.update_product(pc, body))
                return
            if path == "/admin/offers":
                self._send_json(200, admin.create_offer(body))
                return
            if path == "/admin/lifecycle-sinks":
                self._send_json(200, admin.create_lifecycle_sink(body))
                return
            if path == "/admin/time/advance":
                self._send_json(200, admin.advance_time(body))
                return
            # ─── direct entitlement management (simulator-only shortcut) ───
            # Used by feature-platform's subscribe_feature / unsubscribe_feature
            # Lambdas to flip a customer's entitlement without going through
            # the full product/offer/subscribe ceremony.
            if path == "/admin/entitlements":
                self._send_json(200, admin.grant_entitlement(body))
                return
            if path == "/admin/entitlements/expire":
                self._send_json(200, admin.expire_entitlement(body))
                return

            # ─── buyer ───
            if path == "/buyer/subscribe":
                self._send_json(200, buyer.subscribe(body))
                return
            if path == "/buyer/unsubscribe":
                self._send_json(200, buyer.unsubscribe(body))
                return
            if path == "/buyer/quick-launch":
                self._send_json(200, buyer.quick_launch(body))
                return

            self._send_json(404, {"error": f"no route for POST {path}"})
        except SimulatorError as exc:
            if path == "/":
                self._send_aws_error(exc)
            else:
                self._send_json(exc.http_status, {"__type": exc.error_type, "message": exc.message})
        except Exception:
            LOG.exception("unhandled exception on %s %s", self.command, path)
            self._send_json(500, {"error": "internal-server-error"})

    def do_PATCH(self) -> None:  # noqa: N802
        """marketplace-catalog CancelChangeSet uses PATCH."""
        parsed = urlparse(self.path)
        try:
            if self._dispatch_catalog(parsed):
                return
        except SimulatorError as exc:
            self._send_json(exc.http_status, {"__type": exc.error_type, "message": exc.message})
            return
        except Exception:
            LOG.exception("unhandled exception on PATCH %s", parsed.path)
            self._send_json(500, {"error": "internal-server-error"})
            return
        self._send_json(404, {"error": f"no route for PATCH {parsed.path}"})

    def _send_help(self) -> None:
        body = b"""<html><body>
<h1>AWS Marketplace Simulator</h1>
<p>Data-plane (boto3-compatible): POST <code>/</code> with <code>X-Amz-Target</code> header</p>
<ul>
  <li>AWSMPMeteringService.ResolveCustomer / BatchMeterUsage / MeterUsage / RegisterUsage</li>
  <li>AWSMPEntitlementService.GetEntitlements</li>
</ul>
<p>Admin REST: <code>/admin/products</code>, <code>/admin/offers</code>,
   <code>/admin/lifecycle-sinks</code>, <code>/admin/time/advance</code>,
   <code>/admin/subscriptions</code>, <code>/admin/usage</code>,
   <code>/admin/notifications</code>, <code>/admin/state</code></p>
<p>Buyer REST: <code>/buyer/subscribe</code>, <code>/buyer/unsubscribe</code>,
   <code>/buyer/quick-launch</code>, <code>/buyer/entitlements/{accountId}</code></p>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        LOG.info("%s - - %s", self.address_string(), fmt % args)


def serve(
    host: str = "127.0.0.1", port: int = 9999, db_path: str = "mp-sim.sqlite"
) -> ThreadingHTTPServer:
    """Start the simulator. Returns the server instance — caller owns shutdown.

    If you want a server in a background thread for tests, wrap this:

        srv = serve(port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
    """
    db.init(db_path)
    server = ThreadingHTTPServer((host, port), _Handler)
    LOG.info(
        "AWS Marketplace simulator listening on http://%s:%d  (db=%s)",
        host,
        server.server_address[1],
        db_path,
    )
    return server


def serve_in_thread(
    host: str = "127.0.0.1", port: int = 0, db_path: str = ":memory-like:"
) -> tuple[ThreadingHTTPServer, int]:
    """Convenience for tests — starts serving in a daemon thread. Uses a temp
    SQLite file unless ``db_path`` is supplied.
    """
    import tempfile

    if db_path == ":memory-like:":
        # SQLite :memory: doesn't share between threads even with the same
        # connection; use a temp file instead so background worker threads can
        # attach. Caller can delete afterwards.
        db_path = tempfile.NamedTemporaryFile(prefix="mp-sim-", suffix=".sqlite", delete=False).name

    server = serve(host=host, port=port, db_path=db_path)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="mp-sim")
    t.start()
    return server, server.server_address[1]
