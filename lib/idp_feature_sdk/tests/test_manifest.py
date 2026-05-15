"""Unit tests for feature-manifest loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from idp_feature_sdk.manifest import ManifestError, load_manifest


def test_load_valid_manifest(demo_feature_project: Path) -> None:
    m = load_manifest(demo_feature_project)
    assert m.featureId == "demo-feature"
    assert m.version == "1.2.3"
    assert m.template.path == "template.yaml"
    assert m.ui.bundlePath == "feature-ui/dist/ui-bundle.js"
    assert m.marketplace.productCode == "prod-demo"
    assert m.defaultParameters == {"LogLevel": "INFO"}
    assert m.capabilities == ["custom-api"]


def test_missing_manifest_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path)


def test_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "feature.yaml").write_text("this: : : not yaml", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(tmp_path)


def test_missing_required_fields(tmp_path: Path) -> None:
    (tmp_path / "feature.yaml").write_text(
        "featureId: x\ndisplayName: X\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError, match="is invalid"):
        load_manifest(tmp_path)


def test_invalid_feature_id_pattern(demo_feature_project: Path) -> None:
    (demo_feature_project / "feature.yaml").write_text(
        (demo_feature_project / "feature.yaml")
        .read_text()
        .replace("featureId: demo-feature", "featureId: Bad_Name"),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="is invalid"):
        load_manifest(demo_feature_project)


def test_missing_template_file(demo_feature_project: Path) -> None:
    (demo_feature_project / "template.yaml").unlink()
    with pytest.raises(ManifestError, match="template file not found"):
        load_manifest(demo_feature_project)


def test_missing_bundle_without_build_cmd(demo_feature_project: Path) -> None:
    (demo_feature_project / "feature-ui" / "dist" / "ui-bundle.js").unlink()
    with pytest.raises(ManifestError, match="ui bundle not found"):
        load_manifest(demo_feature_project)


def test_missing_bundle_with_build_cmd_is_allowed(demo_feature_project: Path) -> None:
    (demo_feature_project / "feature-ui" / "dist" / "ui-bundle.js").unlink()
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js\n  buildCommand: 'echo build'",
        ),
        encoding="utf-8",
    )
    # Should load now (buildCommand present, bundle missing is OK).
    m = load_manifest(demo_feature_project)
    assert m.ui.buildCommand == "echo build"
