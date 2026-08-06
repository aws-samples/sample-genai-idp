"""Unit tests for bundle static validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from idp_feature_sdk.bundle import BundleValidationError, validate_bundle


def _make_bundle(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


VALID = (
    "window.IdpFeatures.register('foo-bar', {"
    "Component: function(){return null}, version: '1.0.0', displayName: 'X'"
    "});"
)


def test_valid_bundle_passes(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    _make_bundle(p, VALID)
    info = validate_bundle(p, "foo-bar", "1.0.0")
    assert info.size_bytes > 0
    assert len(info.sha256) == 64


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(BundleValidationError, match="not found"):
        validate_bundle(tmp_path / "missing.js", "foo-bar", "1.0.0")


def test_empty_file_fails(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    p.write_text("", encoding="utf-8")
    with pytest.raises(BundleValidationError, match="empty"):
        validate_bundle(p, "foo-bar", "1.0.0")


def test_missing_IdpFeatures_token_fails(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    _make_bundle(p, "console.log('hello');")
    with pytest.raises(BundleValidationError, match="IdpFeatures"):
        validate_bundle(p, "foo-bar", "1.0.0")


def test_missing_feature_id_literal_fails(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    _make_bundle(p, VALID)
    with pytest.raises(BundleValidationError, match="featureId literal"):
        validate_bundle(p, "other-feature", "1.0.0")


def test_missing_version_literal_fails(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    _make_bundle(p, VALID)
    with pytest.raises(BundleValidationError, match="version literal"):
        validate_bundle(p, "foo-bar", "2.0.0")


def test_bundled_react_detected(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    _make_bundle(p, VALID + "\n/* Minified React error #x */")
    with pytest.raises(BundleValidationError, match="bundle React"):
        validate_bundle(p, "foo-bar", "1.0.0")


def test_oversized_bundle_fails(tmp_path: Path) -> None:
    p = tmp_path / "ui-bundle.js"
    # Put the required markers at the start, then pad with filler.
    _make_bundle(p, VALID + "\n" + ("x" * (600 * 1024)))
    with pytest.raises(BundleValidationError, match="suspiciously large"):
        validate_bundle(p, "foo-bar", "1.0.0")
