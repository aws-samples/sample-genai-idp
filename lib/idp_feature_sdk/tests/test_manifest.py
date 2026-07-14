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
    # docsUrl is optional — None when the manifest omits it.
    assert m.docsUrl is None


def test_docs_url_is_parsed(demo_feature_project: Path) -> None:
    manifest_path = demo_feature_project / "feature.yaml"
    manifest_path.write_text(
        manifest_path.read_text() + "\ndocsUrl: extensions/demo-feature\n"
    )
    m = load_manifest(demo_feature_project)
    assert m.docsUrl == "extensions/demo-feature"


def test_pipeline_hooks_and_config_preset_are_parsed(
    demo_feature_project: Path,
) -> None:
    """First real exercise of the configPreset + pipelineHooks manifest paths
    (used by the sample-health-insurance-review sample). Adds a preset file and the two
    manifest sections, then asserts they round-trip into the dataclass."""
    preset_dir = demo_feature_project / "config-preset"
    preset_dir.mkdir()
    (preset_dir / "claims-config.yaml").write_text("use_bda: false\n", encoding="utf-8")
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text()
        + (
            "\nconfigPreset:\n"
            "  path: config-preset/claims-config.yaml\n"
            "pipelineHooks:\n"
            "  postRuleValidation: ClaimStatusHookFunction\n"
        ),
        encoding="utf-8",
    )
    m = load_manifest(demo_feature_project)
    assert m.configPreset is not None
    assert m.configPreset.path == "config-preset/claims-config.yaml"
    assert m.pipelineHooks == {"postRuleValidation": "ClaimStatusHookFunction"}


def test_config_preset_missing_file_is_rejected(demo_feature_project: Path) -> None:
    """A configPreset.path that doesn't exist on disk should fail validation."""
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text() + "\nconfigPreset:\n  path: config-preset/missing.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError):
        load_manifest(demo_feature_project)


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


def test_structured_build_steps_are_parsed(demo_feature_project: Path) -> None:
    """The shell-free `ui.build` step-list form parses into CommandStep objects
    and, like buildCommand, allows a missing bundle at load time."""
    (demo_feature_project / "feature-ui" / "dist" / "ui-bundle.js").unlink()
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  build:\n"
            "    - cwd: feature-ui\n"
            "      argv: ['npm', 'ci']\n"
            "    - argv: ['npm', 'run', 'build']\n",
        ),
        encoding="utf-8",
    )
    m = load_manifest(demo_feature_project)
    assert [s.argv for s in m.ui.build] == [["npm", "ci"], ["npm", "run", "build"]]
    assert [s.cwd for s in m.ui.build] == ["feature-ui", None]
    assert m.ui.has_build


def test_build_and_build_command_are_mutually_exclusive(
    demo_feature_project: Path,
) -> None:
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  buildCommand: 'echo build'\n"
            "  build:\n"
            "    - argv: ['echo', 'build']\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="is invalid"):
        load_manifest(demo_feature_project)


def test_build_step_missing_cwd_dir_is_rejected(demo_feature_project: Path) -> None:
    """A typo'd step cwd should fail at load time, not mid-publish."""
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  build:\n"
            "    - cwd: no-such-dir\n"
            "      argv: ['npm', 'ci']\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="cwd directory not found"):
        load_manifest(demo_feature_project)


def test_agent_source_structured_package_is_parsed(
    demo_feature_project: Path,
) -> None:
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text()
        + (
            "\nagentSource:\n"
            "  artifactPath: dist/agent-source.zip\n"
            "  package:\n"
            "    - argv: ['python3', 'scripts/package_agent.py']\n"
        ),
        encoding="utf-8",
    )
    m = load_manifest(demo_feature_project)
    assert m.agentSource is not None
    assert m.agentSource.packageCommand is None
    assert [s.argv for s in m.agentSource.package] == [
        ["python3", "scripts/package_agent.py"]
    ]


def test_agent_source_requires_some_package_form(demo_feature_project: Path) -> None:
    """agentSource must declare exactly one of packageCommand / package."""
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text() + "\nagentSource:\n  artifactPath: dist/agent-source.zip\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="is invalid"):
        load_manifest(demo_feature_project)
