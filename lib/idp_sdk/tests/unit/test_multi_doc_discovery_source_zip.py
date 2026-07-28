# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the multi-doc discovery Docker source zip.

The CodeBuild project for that nested stack builds
`-f nested/multi-doc-discovery/Dockerfile`, which COPYs
`nested/multi-doc-discovery/requirements.txt`. Both therefore MUST be in the
source zip.

This used to be broken in a way that failed silently: the buildspec heredoc'd its
own inline copies of both files, so the on-disk ones were dead weight. Dependabot
kept bumping the on-disk requirements.txt (e.g. the Pillow CVE bump in PR #530)
while the image went on building the stale inline pins — a security patch that
looked merged but never shipped. These tests lock in the single-source-of-truth
arrangement so that regression cannot come back unnoticed.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
import yaml
from idp_sdk._core.publish import MULTI_DOC_DISCOVERY_BUILD_INPUTS, IDPPublisher

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NESTED_TEMPLATE = _REPO_ROOT / "nested" / "multi-doc-discovery" / "template.yaml"


def _buildspec_text():
    """The DockerBuildProject's inline buildspec, as raw text."""
    # The template uses CFN short-form intrinsics (!Sub, !GetAtt, !Ref), which a
    # plain safe_load rejects — read it as text and slice the BuildSpec block
    # instead of trying to parse the whole document.
    text = _NESTED_TEMPLATE.read_text()
    start = text.index("BuildSpec: |")
    end = text.index("TimeoutInMinutes:", start)
    return text[start:end]


class TestSourceZipContents:
    def test_zip_includes_the_docker_build_inputs(self, publisher_zip_names):
        """The Dockerfile and requirements.txt must land in the zip.

        Without these the new buildspec (which builds `-f` the checked-in
        Dockerfile) cannot build at all.
        """
        for build_input in MULTI_DOC_DISCOVERY_BUILD_INPUTS:
            assert build_input in publisher_zip_names, (
                f"{build_input} missing from source zip"
            )

    def test_zip_includes_handler_code_and_library(self, publisher_zip_names):
        """Guard the pre-existing contract while we are here."""
        assert any(
            n.startswith("src/lambda/multi_doc_discovery/") for n in publisher_zip_names
        )
        assert any(n.startswith("lib/idp_common_pkg/") for n in publisher_zip_names)

    def test_missing_build_input_fails_loudly(self, monkeypatch):
        """A missing build input must abort publish, not ship a broken image."""
        monkeypatch.chdir(_REPO_ROOT)
        publisher = _quiet_publisher(monkeypatch)
        # Pretend the Dockerfile isn't there.
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            os.path,
            "isfile",
            lambda p: False if str(p).endswith("Dockerfile") else real_isfile(p),
        )
        with pytest.raises(SystemExit):
            publisher.package_multi_doc_discovery_source()


class TestNoInlineDuplication:
    """The buildspec must consume the real files, never re-declare them."""

    def test_buildspec_does_not_heredoc_a_requirements_file(self):
        spec = _buildspec_text()
        assert "cat > requirements.txt" not in spec, (
            "buildspec is writing its own requirements.txt again — this forks "
            "from the real file and silently strands Dependabot bumps"
        )

    def test_buildspec_does_not_heredoc_a_dockerfile(self):
        spec = _buildspec_text()
        assert "cat > Dockerfile" not in spec, (
            "buildspec is writing its own Dockerfile again — keep "
            "nested/multi-doc-discovery/Dockerfile as the only source of truth"
        )

    def test_buildspec_builds_the_checked_in_dockerfile(self):
        spec = _buildspec_text()
        assert "-f nested/multi-doc-discovery/Dockerfile" in spec

    def test_buildspec_pins_no_dependency_versions(self):
        """No package pins anywhere in the buildspec — they belong in one file."""
        spec = _buildspec_text()
        for pkg in ("Pillow", "numpy", "scikit-learn", "strands-agents"):
            assert pkg not in spec, (
                f"{pkg} is pinned in the buildspec; pins belong only in "
                "nested/multi-doc-discovery/requirements.txt"
            )


class TestDockerfileResilience:
    """The pip step must tolerate a transient PyPI stream drop."""

    def _dockerfile(self):
        return (
            _REPO_ROOT / "nested" / "multi-doc-discovery" / "Dockerfile"
        ).read_text()

    def test_pip_has_retry_flags(self):
        text = self._dockerfile()
        assert "--retries" in text
        assert "--timeout" in text

    def test_pip_is_wrapped_in_a_retry_loop(self):
        """pip's own retries do not cover a mid-stream BrokenPipeError."""
        text = self._dockerfile()
        assert "for attempt in" in text

    def test_copy_paths_are_repo_root_relative(self):
        """Build context is the zip root, so COPY paths must be repo-relative."""
        text = self._dockerfile()
        assert "COPY nested/multi-doc-discovery/requirements.txt" in text
        assert "COPY lib/idp_common_pkg" in text
        assert "COPY src/lambda/multi_doc_discovery/*.py" in text


class TestRebuildTriggers:
    """A Dependabot bump must invalidate the component checksum."""

    def test_build_inputs_are_rebuild_dependencies(self, monkeypatch):
        monkeypatch.chdir(_REPO_ROOT)
        publisher = IDPPublisher()
        deps = publisher.get_component_dependencies()["nested/multi-doc-discovery"]
        for build_input in MULTI_DOC_DISCOVERY_BUILD_INPUTS:
            assert build_input in deps, (
                f"{build_input} is not a rebuild trigger — a bump to it would "
                "not invalidate the checksum, so publish would skip the "
                "component and keep shipping the previous image"
            )


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #


def _quiet_publisher(monkeypatch):
    """An IDPPublisher whose console output is suppressed."""
    publisher = IDPPublisher()
    monkeypatch.setattr(
        publisher,
        "console",
        type("C", (), {"print": staticmethod(lambda *a, **k: None)}),
    )
    return publisher


@pytest.fixture
def publisher_zip_names(monkeypatch):
    """Member names of the real source zip produced by the packaging step.

    Runs against the actual repo tree (the zip content IS the contract), and
    stops at the S3 upload — the zip is fully written before that point.
    """
    monkeypatch.chdir(_REPO_ROOT)
    publisher = _quiet_publisher(monkeypatch)
    zip_path = _REPO_ROOT / ".aws-sam" / "multi-doc-discovery-source.zip"
    try:
        publisher.package_multi_doc_discovery_source()
    except (SystemExit, Exception):  # noqa: B014
        # The upload stage needs S3 config we deliberately don't provide.
        if not zip_path.exists():
            raise
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def test_requirements_file_is_parseable_and_pins_pillow(monkeypatch):
    """Sanity: the file the image now actually installs from."""
    reqs = (
        _REPO_ROOT / "nested" / "multi-doc-discovery" / "requirements.txt"
    ).read_text()
    assert "Pillow" in reqs
    # Every non-comment line should look like a requirement specifier.
    for line in reqs.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert any(c in line for c in "=<>~"), f"unpinned/odd requirement: {line}"


def test_nested_template_is_valid_yaml_shape():
    """The buildspec edits must not have broken the template's indentation."""
    text = _NESTED_TEMPLATE.read_text()
    # Short-form intrinsics need a permissive loader; just assert the BuildSpec
    # block is a well-formed literal scalar under Source:.
    assert "Source:" in text
    spec = _buildspec_text()
    assert spec.count("phases:") == 1
    for phase in ("pre_build:", "build:", "post_build:"):
        assert phase in spec
    # The buildspec body itself must be loadable once the CFN indent is stripped.
    body = spec.split("BuildSpec: |", 1)[1]
    dedented = "\n".join(line[10:] for line in body.splitlines())
    parsed = yaml.safe_load(dedented)
    assert parsed["version"] == 0.2
    assert set(parsed["phases"]) == {"pre_build", "build", "post_build"}
