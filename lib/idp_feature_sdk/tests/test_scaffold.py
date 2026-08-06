# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for ``idp_feature_sdk.scaffold``.

The scaffold copies the live ``feature-template/`` directory from the repo
checkout, which we locate by walking up from cwd. The tests stage a fake
template in a temp directory and chdir into a sibling so the same lookup
finds it without depending on the real on-disk template (keeps tests fast
and self-contained).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from idp_feature_sdk.scaffold import (
    ScaffoldError,
    ScaffoldOptions,
    _substitute_in_file,
    find_feature_template,
    scaffold_feature,
)


def _stage_fake_template(repo_root: Path) -> Path:
    """Create a minimal ``subscription-features/feature-platform/feature-template/`` layout.

    Mirrors the placeholder shape of the real scaffold (``my-feature``,
    ``My Feature``, ``0.1.0``) across the files :mod:`scaffold` substitutes
    into. Returns the template directory.
    """
    template = (
        repo_root / "subscription-features" / "feature-platform" / "feature-template"
    )
    template.mkdir(parents=True)

    (template / "feature.yaml").write_text(
        dedent("""
            featureId: my-feature
            displayName: My Feature
            version: 0.1.0
            template:
              path: template.yaml
            ui:
              bundlePath: feature-ui/dist/ui-bundle.js
        """).strip(),
        encoding="utf-8",
    )
    (template / "template.yaml").write_text(
        "Default: my-feature\nDisplayName: My Feature\n", encoding="utf-8"
    )
    (template / "README.md").write_text(
        "# My Feature\nfeatureId: my-feature, version 0.1.0.\n", encoding="utf-8"
    )

    api = template / "feature-api"
    api.mkdir()
    (api / "handler.py").write_text(
        '"""Hello from my-feature API."""\n', encoding="utf-8"
    )

    ui_src = template / "feature-ui" / "src"
    ui_src.mkdir(parents=True)
    (template / "feature-ui" / "package.json").write_text(
        '{"name": "my-feature-ui", "version": "0.1.0"}\n', encoding="utf-8"
    )
    (ui_src / "App.tsx").write_text("// My Feature root component\n", encoding="utf-8")
    (ui_src / "entry.tsx").write_text(
        dedent("""
            window.IdpFeatures.register('my-feature', {
              Component: App,
              version: '0.1.0',
              displayName: 'My Feature',
            });
        """).strip(),
        encoding="utf-8",
    )

    # Things scaffold_feature must NOT copy (to avoid leaking dev artifacts).
    (template / "feature-ui" / "node_modules").mkdir()
    (template / "feature-ui" / "node_modules" / ".bin").mkdir()
    (template / "feature-ui" / "dist").mkdir()
    (template / "feature-ui" / "dist" / "ui-bundle.js").write_text(
        "ignored\n", encoding="utf-8"
    )
    (api / "__pycache__").mkdir()
    (api / "__pycache__" / "handler.cpython-311.pyc").write_text(
        "junk\n", encoding="utf-8"
    )

    return template


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch) -> Path:
    """Stage a fake repo with feature-template/ and chdir into it.

    Returns the repo root so tests can assert on absolute paths created
    underneath.
    """
    repo = tmp_path / "fake-idp-repo"
    repo.mkdir()
    _stage_fake_template(repo)
    monkeypatch.chdir(repo)
    return repo


def test_substitute_in_file_replaces_all_three_placeholders(tmp_path: Path) -> None:
    """The internal substitution helper handles all 3 placeholders together."""
    target = tmp_path / "f.txt"
    target.write_text(
        "id=my-feature name='My Feature' v=0.1.0 (my-feature again)\n",
        encoding="utf-8",
    )
    _substitute_in_file(
        target,
        feature_id="docs-by-status",
        display_name="Docs By Status",
        version="2.0.0",
    )
    assert target.read_text(encoding="utf-8") == (
        "id=docs-by-status name='Docs By Status' v=2.0.0 (docs-by-status again)\n"
    )


def test_find_feature_template_walks_up_from_cwd(fake_repo: Path) -> None:
    """``find_feature_template`` discovers the scaffold from a sibling cwd."""
    nested = fake_repo / "some" / "subdir"
    nested.mkdir(parents=True)
    import os

    os.chdir(nested)
    expected = (
        fake_repo / "subscription-features" / "feature-platform" / "feature-template"
    ).resolve()
    assert find_feature_template() == expected


def test_find_feature_template_returns_none_when_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Returns None outside any IDP checkout so the CLI can show a friendly error."""
    monkeypatch.chdir(tmp_path)
    assert find_feature_template() is None


def test_scaffold_creates_project_with_substituted_placeholders(
    fake_repo: Path,
) -> None:
    """End-to-end: scaffold copies + substitutes + skips dev artifacts."""
    target = fake_repo / "my-new-feature"
    result = scaffold_feature(
        ScaffoldOptions(
            project_dir=target,
            feature_id="docs-by-status",
            display_name="Docs By Status",
            version="2.0.0",
        )
    )

    assert result == target.resolve()
    assert target.is_dir()

    # All known placeholders gone from substituted files.
    manifest = (target / "feature.yaml").read_text(encoding="utf-8")
    assert "my-feature" not in manifest
    assert "My Feature" not in manifest
    assert "0.1.0" not in manifest
    assert "featureId: docs-by-status" in manifest
    assert "displayName: Docs By Status" in manifest
    assert "version: 2.0.0" in manifest

    entry = (target / "feature-ui" / "src" / "entry.tsx").read_text(encoding="utf-8")
    assert "register('docs-by-status'" in entry
    assert "version: '2.0.0'" in entry
    assert "displayName: 'Docs By Status'" in entry

    pkg = (target / "feature-ui" / "package.json").read_text(encoding="utf-8")
    assert '"version": "2.0.0"' in pkg
    assert '"name": "docs-by-status-ui"' in pkg

    # Dev artifacts must NOT have been copied.
    assert not (target / "feature-ui" / "node_modules").exists()
    assert not (target / "feature-ui" / "dist").exists()
    assert not (target / "feature-api" / "__pycache__").exists()


def test_scaffold_default_version_is_010(fake_repo: Path) -> None:
    """Omitting --version keeps the template's 0.1.0 default."""
    target = fake_repo / "default-version-feature"
    scaffold_feature(
        ScaffoldOptions(
            project_dir=target,
            feature_id="my-feature-2",
            display_name="My Feature 2",
        )
    )
    manifest = (target / "feature.yaml").read_text(encoding="utf-8")
    assert "version: 0.1.0" in manifest


def test_scaffold_refuses_to_overwrite_existing_directory(fake_repo: Path) -> None:
    """Scaffolding into an existing directory raises ScaffoldError."""
    target = fake_repo / "existing"
    target.mkdir()
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold_feature(
            ScaffoldOptions(
                project_dir=target,
                feature_id="x",
                display_name="X",
            )
        )


def test_scaffold_raises_when_template_missing(tmp_path: Path, monkeypatch) -> None:
    """Scaffolding without a checkout (no feature-template/ found) is rejected."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ScaffoldError, match="feature-template/ not found"):
        scaffold_feature(
            ScaffoldOptions(
                project_dir=tmp_path / "nope",
                feature_id="x",
                display_name="X",
            )
        )
