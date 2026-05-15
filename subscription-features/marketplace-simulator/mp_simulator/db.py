"""SQLite persistence for the simulator.

One file, single-process server. Thread-safe via a per-thread connection
cached on ``threading.local()`` and ``check_same_thread=False`` enabled with
a module-level write lock to serialise writes.

Schema is created on first open and is idempotent.

Tables:

- ``products``        catalog entry with pricing model, dimensions, trial cfg
- ``offers``          public or private offer referencing a product
- ``subscriptions``   buyer's acceptance of an offer (one per customer per product)
- ``entitlements``    per-customer current dimension values (denormalized cache)
- ``usage_records``   every UsageRecord seen by BatchMeterUsage / MeterUsage
- ``lifecycle_sinks`` webhook URL / SNS ARN / in-proc callback per product
- ``notifications``   outbound lifecycle event log (for inspection + retry)
- ``tokens``          x-amzn-marketplace-token ↔ customer mapping
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_LOCAL = threading.local()
_WRITE_LOCK = threading.Lock()
_DB_PATH: Path | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_code   TEXT PRIMARY KEY,
    license_arn    TEXT NOT NULL,
    name           TEXT NOT NULL,
    pricing_model  TEXT NOT NULL,                -- 'contract' | 'contract-with-payg' | 'subscription' | 'free'
    published      INTEGER NOT NULL DEFAULT 0,
    trial_days     INTEGER NOT NULL DEFAULT 0,
    fulfillment_url TEXT,
    quick_launch_template_url TEXT,
    dimensions_json TEXT NOT NULL,                -- list of {apiName, displayName, category, unitPrice, kind: 'contract'|'usage'|'overage'}
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    offer_id       TEXT PRIMARY KEY,
    product_code   TEXT NOT NULL REFERENCES products(product_code),
    kind           TEXT NOT NULL,                 -- 'public' | 'private'
    buyer_account_allowlist_json TEXT,            -- JSON array of AWS account ids for private offers
    contract_tier_json  TEXT,                     -- e.g. {"dimension": "capacity_docs", "quantity": 100}
    duration_months INTEGER NOT NULL DEFAULT 1,
    free_trial_enabled INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    customer_identifier TEXT PRIMARY KEY,
    customer_aws_account_id TEXT NOT NULL,
    product_code   TEXT NOT NULL REFERENCES products(product_code),
    offer_id       TEXT NOT NULL REFERENCES offers(offer_id),
    status         TEXT NOT NULL,                 -- 'trial' | 'active' | 'unsubscribe-pending' | 'cancelled'
    trial_ends_at  REAL,
    subscribed_at  REAL NOT NULL,
    cancelled_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_sub_account_product
    ON subscriptions(customer_aws_account_id, product_code);

CREATE TABLE IF NOT EXISTS entitlements (
    customer_identifier TEXT NOT NULL,
    product_code   TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    value_type     TEXT NOT NULL,                 -- 'Integer' | 'Double' | 'Boolean' | 'String'
    value_json     TEXT NOT NULL,
    expiration_date REAL NOT NULL,
    PRIMARY KEY (customer_identifier, product_code, dimension)
);

CREATE TABLE IF NOT EXISTS usage_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code   TEXT NOT NULL,
    customer_identifier TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    quantity       INTEGER NOT NULL,
    timestamp      REAL NOT NULL,
    status         TEXT NOT NULL,                 -- 'Success' | 'CustomerNotSubscribed' | ...
    client_token   TEXT,                          -- MeterUsage idempotency key
    recorded_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_customer
    ON usage_records(customer_identifier, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_client_token
    ON usage_records(product_code, client_token)
    WHERE client_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS tokens (
    token          TEXT PRIMARY KEY,
    customer_identifier TEXT NOT NULL,
    customer_aws_account_id TEXT NOT NULL,
    product_code   TEXT NOT NULL,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_sinks (
    sink_id        TEXT PRIMARY KEY,
    product_code   TEXT NOT NULL REFERENCES products(product_code),
    transport      TEXT NOT NULL,                 -- 'webhook' | 'sns' | 'inproc'
    target         TEXT NOT NULL,                 -- URL / ARN / callback name
    topic          TEXT NOT NULL,                 -- 'subscription' | 'entitlement'
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code   TEXT NOT NULL,
    topic          TEXT NOT NULL,                 -- 'subscription' | 'entitlement'
    action         TEXT NOT NULL,                 -- 'subscribe-success', 'unsubscribe-pending', ...
    customer_identifier TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    delivery_status TEXT NOT NULL,                -- 'delivered' | 'failed' | 'pending'
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL
);

-- Agreements = the buyer-side view of a subscription. Real AWS exposes these
-- through the marketplace-agreement SDK (DescribeAgreement, SearchAgreements,
-- GetAgreementTerms). We create one row per /buyer/subscribe.
CREATE TABLE IF NOT EXISTS agreements (
    agreement_id         TEXT PRIMARY KEY,
    customer_identifier  TEXT NOT NULL UNIQUE,
    proposer_account_id  TEXT NOT NULL,           -- seller
    acceptor_account_id  TEXT NOT NULL,           -- buyer
    product_code         TEXT NOT NULL,
    offer_id             TEXT NOT NULL,
    agreement_type       TEXT NOT NULL DEFAULT 'PurchaseAgreement',
    start_time           REAL NOT NULL,
    end_time             REAL,
    acceptance_time      REAL NOT NULL,
    status               TEXT NOT NULL,           -- ACTIVE | CANCELLED | EXPIRED
    cancelled_at         REAL
);

CREATE INDEX IF NOT EXISTS idx_agreement_acceptor ON agreements(acceptor_account_id);
CREATE INDEX IF NOT EXISTS idx_agreement_proposer ON agreements(proposer_account_id);

-- ChangeSets = the seller-side SDK-driven way to mutate the catalog.
-- Real AWS exposes this through marketplace-catalog (StartChangeSet applied
-- asynchronously; status transitions PREPARING -> APPLYING_CHANGES -> SUCCEEDED).
-- We apply synchronously for simplicity but still record the states.
CREATE TABLE IF NOT EXISTS change_sets (
    change_set_id      TEXT PRIMARY KEY,
    change_set_name    TEXT,
    catalog            TEXT NOT NULL DEFAULT 'AWSMarketplace',
    intent             TEXT NOT NULL DEFAULT 'APPLY',   -- APPLY | VALIDATE
    status             TEXT NOT NULL,                    -- PREPARING | APPLYING_CHANGES | SUCCEEDED | FAILED | CANCELLED
    failure_code       TEXT,
    failure_description TEXT,
    changes_json       TEXT NOT NULL,                    -- list of {ChangeType, Entity, Details, ChangeName}
    client_request_token TEXT,
    start_time         REAL NOT NULL,
    end_time           REAL,
    created_at         REAL NOT NULL
);

-- Convenient seller identity per product (who's the Proposer AWS account on agreements).
-- Real Marketplace tracks this in the Catalog; we add a simple column to products.
"""


def init(db_path: str | Path) -> None:
    """Point the simulator at a SQLite file. Creates schema if missing."""
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _conn() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("db.init() not called")
    c = getattr(_LOCAL, "conn", None)
    if c is None:
        c = sqlite3.connect(str(_DB_PATH), check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _LOCAL.conn = c
    return c


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    yield _conn()


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    with _WRITE_LOCK:
        c = _conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def dump_all() -> dict[str, list[dict[str, Any]]]:
    """Debug / snapshot helper. Dumps every table as a dict of rows."""
    out: dict[str, list[dict[str, Any]]] = {}
    with read() as c:
        for (table,) in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall():
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = [dict(r) for r in rows]
    return out


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # decode *_json columns transparently
    for k in list(d.keys()):
        if k.endswith("_json") and d[k] is not None:
            try:
                d[k[:-5]] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d
