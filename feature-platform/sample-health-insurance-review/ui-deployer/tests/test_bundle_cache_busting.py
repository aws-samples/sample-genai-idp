"""Unit tests for the ui-deployer's content-hashed bundle key (cache busting).

The bundle is copied into the WebUIBucket with `Cache-Control: immutable`,
which is only safe if the URL changes whenever the content changes. The dst
key therefore embeds the first 8 hex chars of the sha256 of the bundle bytes:
`features/<id>/v<version>-<sha8>/ui-bundle.js`. Republishing the same feature
version with different bytes must yield a different key (and uiBundlePath), so
browsers holding the old immutable copy fetch the new one.

On Delete, cleanup lists the feature's whole `features/<id>/` prefix so every
published copy is removed — current + superseded hashed dirs + keys from the
older non-hashed layout.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]

_BUNDLE_BYTES = b"console.log('bundle v1');"
_SHA8 = hashlib.sha256(_BUNDLE_BYTES).hexdigest()[:8]


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]):
        self._pages = pages

    def paginate(self, **kwargs: Any):
        self.paginate_kwargs = kwargs
        return iter(self._pages)


class _FakeS3:
    """Just enough of the S3 client for _bundle_ui / _delete_bundle_objects."""

    def __init__(self, bundle_bytes: bytes = _BUNDLE_BYTES, listed_keys=()):
        self.bundle_bytes = bundle_bytes
        self.listed_keys = list(listed_keys)
        self.copy_calls: list[dict[str, Any]] = []
        self.delete_batches: list[list[str]] = []

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": _FakeBody(self.bundle_bytes)}

    def copy_object(self, **kwargs: Any) -> None:
        self.copy_calls.append(kwargs)

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        contents = [{"Key": k} for k in self.listed_keys]
        self.paginator = _FakePaginator([{"Contents": contents}] if contents else [{}])
        return self.paginator

    def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> None:
        self.delete_batches.append([o["Key"] for o in Delete["Objects"]])


@pytest.fixture
def mod(monkeypatch):
    """Import the ui-deployer handler with the env it reads at module load."""
    monkeypatch.setenv("FEATURE_ID", "sample-health-insurance-review")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "Sample: Health Insurance Review")
    monkeypatch.setenv("FEATURE_VERSION", "0.1.0")
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("WEBUI_BUCKET", "webui")
    monkeypatch.setenv("FEATURE_BUCKET", "artifacts")
    monkeypatch.setenv("FEATURE_ARTIFACT_PREFIX", "idp-cli/extensions/f")
    monkeypatch.setenv(
        "REGISTER_FEATURE_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-RegisterFeature",
    )
    monkeypatch.setenv(
        "REGISTER_FEATURE_HOOKS_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-RegisterFeatureHooks",
    )
    monkeypatch.setenv(
        "APPLY_FEATURE_CONFIG_PRESET_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-ApplyFeatureConfigPreset",
    )
    monkeypatch.setenv("HOOK_FUNCTION_ARN", "arn:aws:lambda:us-west-2:1:function:H")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def test_create_copies_to_content_hashed_key(mod, monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(mod, "_s3", fake)
    path = mod._bundle_ui("Create")
    assert path == f"features/sample-health-insurance-review/v0.1.0-{_SHA8}/"
    (call,) = fake.copy_calls
    assert (
        call["Key"]
        == f"features/sample-health-insurance-review/v0.1.0-{_SHA8}/ui-bundle.js"
    )
    assert call["CacheControl"] == "public,max-age=31536000,immutable"
    assert call["CopySource"]["Key"].endswith("/0.1.0/ui-bundle.js")


def test_same_version_different_bytes_changes_path(mod, monkeypatch):
    fake = _FakeS3(bundle_bytes=b"console.log('bundle v2');")
    monkeypatch.setattr(mod, "_s3", fake)
    path = mod._bundle_ui("Update")
    assert path != f"features/sample-health-insurance-review/v0.1.0-{_SHA8}/"
    assert path.startswith("features/sample-health-insurance-review/v0.1.0-")


def test_delete_removes_all_copies_under_feature_prefix(mod, monkeypatch):
    stale = [
        # older non-hashed layout
        "features/sample-health-insurance-review/v0.1.0/ui-bundle.js",
        # superseded hashed copies
        "features/sample-health-insurance-review/v0.1.0-deadbeef/ui-bundle.js",
        f"features/sample-health-insurance-review/v0.1.0-{_SHA8}/ui-bundle.js",
    ]
    fake = _FakeS3(listed_keys=stale)
    monkeypatch.setattr(mod, "_s3", fake)
    mod._bundle_ui("Delete")
    assert (
        fake.paginator.paginate_kwargs["Prefix"]
        == "features/sample-health-insurance-review/"
    )
    (batch,) = fake.delete_batches
    assert sorted(batch) == sorted(stale)


def test_delete_cleanup_failure_is_swallowed(mod, monkeypatch):
    """Teardown must never block stack delete."""

    class _Boom:
        def get_paginator(self, name):
            raise RuntimeError("no ListBucket for you")

    monkeypatch.setattr(mod, "_s3", _Boom())
    mod._bundle_ui("Delete")  # must not raise
