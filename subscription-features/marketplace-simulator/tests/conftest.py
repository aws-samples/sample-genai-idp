"""pytest fixtures — start the simulator on an ephemeral port with a temp DB,
set the AWS_ENDPOINT_URL_* env vars so boto3 clients find it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

# Ensure local package is importable without `pip install -e .`
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from client.mp_simulator_client import MpSimulatorClient  # noqa: E402
from mp_simulator import clock, server  # noqa: E402


@pytest.fixture()
def simulator():
    """Start a fresh simulator on a free port, yield (base_url, client)."""
    db_file = tempfile.NamedTemporaryFile(prefix="mp-sim-test-", suffix=".sqlite", delete=False)
    db_file.close()

    # Reset the global clock offset across test boundaries
    clock.reset()

    srv, port = server.serve_in_thread(host="127.0.0.1", port=0, db_path=db_file.name)
    base_url = f"http://127.0.0.1:{port}"

    # Wait for socket to accept
    for _ in range(50):
        try:
            requests.get(f"{base_url}/healthz", timeout=1).raise_for_status()
            break
        except Exception:
            time.sleep(0.02)
    else:
        raise RuntimeError("simulator did not start")

    # Set env for boto3 endpoint override. Env var names follow the
    # service's serviceId, uppercased with spaces/dashes -> underscores.
    #   meteringmarketplace    -> "Marketplace Metering"             -> _MARKETPLACE_METERING
    #   marketplace-entitlement-> "Marketplace Entitlement Service"  -> _MARKETPLACE_ENTITLEMENT_SERVICE
    #   marketplace-agreement  -> "Marketplace Agreement"            -> _MARKETPLACE_AGREEMENT
    #   marketplace-catalog    -> "Marketplace Catalog"              -> _MARKETPLACE_CATALOG
    env_names = [
        "AWS_ENDPOINT_URL_MARKETPLACE_METERING",
        "AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE",
        "AWS_ENDPOINT_URL_MARKETPLACE_AGREEMENT",
        "AWS_ENDPOINT_URL_MARKETPLACE_CATALOG",
    ]
    old_env = {n: os.environ.get(n) for n in env_names}
    for n in env_names:
        os.environ[n] = base_url
    # Dummy credentials so boto3 doesn't look for real ones
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    client = MpSimulatorClient(base_url)
    try:
        yield base_url, client
    finally:
        srv.shutdown()
        for n, v in old_env.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v

        try:
            os.unlink(db_file.name)
        except OSError:
            pass
