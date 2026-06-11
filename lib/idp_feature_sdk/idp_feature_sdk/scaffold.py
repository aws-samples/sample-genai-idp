# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Scaffold a new feature project from the bundled feature-template/.

`idp-feature-cli init <project_dir> --feature-id <id> --display-name <name>`
copies `subscription-features/feature-platform/feature-template/` into <project_dir> and
substitutes the placeholder featureId / displayName / version literals so the
result is a valid feature ready for `idp-feature-cli build` and `publish`.

Substitutions performed (case-sensitive, exact-match only — comments
mentioning "my-feature" in source code are intentionally left alone since
they document the substitution itself):

| Placeholder      | Replaced with        | Files |
|------------------|----------------------|-------|
| `my-feature`     | <feature_id>         | feature.yaml, template.yaml, package.json (`name`), handler.py, README.md |
| `My Feature`     | <display_name>       | feature.yaml, template.yaml, App.tsx, README.md |
| `0.1.0`          | <version> (def 0.1.0)| feature.yaml, package.json (`version`), README.md |

`entry.tsx` is NOT in this table: featureId / displayName / version are
read from `feature.yaml` at build time by `vite.config.ts` and injected
into the bundle as compile-time constants (see __FEATURE_*__ in
feature-template/feature-ui/vite.config.ts). The single source of truth
for those three values is therefore `feature.yaml`.

The substitutions are done by literal string replacement rather than
templating so that the source `feature-template/` remains a syntactically
valid project (importable, lint-clean, type-checked) at all times — copying
it without running this scaffold yields a working "my-feature" project that
just needs renaming.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Files in feature-template/ that contain placeholders worth substituting.
# Other files (vite.config.ts, tsconfig.json, etc.) don't reference the
# placeholders. package-lock.json contains the package name `my-feature` but
# we regenerate it on first `npm install` so substitution there is unhelpful.
_TEXT_FILES_RELATIVE = (
    "feature.yaml",
    "template.yaml",
    "feature-ui/package.json",
    "feature-ui/src/App.tsx",
    "feature-ui/src/entry.tsx",
    "feature-api/handler.py",
    "README.md",
)


class ScaffoldError(RuntimeError):
    """Raised when scaffolding cannot proceed (missing template, target exists)."""


@dataclass(frozen=True)
class ScaffoldOptions:
    """Inputs to :func:`scaffold_feature`."""

    project_dir: Path
    feature_id: str
    display_name: str
    version: str = "0.1.0"


def find_feature_template() -> Path | None:
    """Return the absolute path to the bundled `feature-template/` directory.

    The SDK is intended to run from a developer checkout of the IDP
    repository where the template lives at ``feature-platform/feature-template/``
    relative to the repo root (the open-source layout). For backward
    compatibility we also accept the legacy private-repo layout
    ``subscription-features/feature-platform/feature-template/``. We walk up
    from the current working directory looking for either path; this lets the
    CLI be invoked from any subdirectory (including the repo root itself).

    Returns ``None`` if the template can't be found — the caller is expected
    to surface a friendly error rather than fall over.
    """
    relative_candidates = (
        # Open-source layout (feature-platform/ at the repo root).
        Path("feature-platform") / "feature-template",
        # Legacy private-repo layout.
        Path("subscription-features") / "feature-platform" / "feature-template",
    )
    cwd = Path.cwd().resolve()
    for candidate_root in (cwd, *cwd.parents):
        for relative in relative_candidates:
            candidate = candidate_root / relative
            if candidate.is_dir():
                return candidate
    return None


def _substitute_in_file(
    path: Path,
    *,
    feature_id: str,
    display_name: str,
    version: str,
) -> None:
    """Apply the three placeholder substitutions to a single text file.

    Order matters: we replace the longer/more-specific placeholders first
    (`My Feature` before `Feature` would only matter if we substituted
    `Feature`, but we keep the explicit ordering for safety) so partial
    matches don't corrupt unrelated tokens.
    """
    text = path.read_text(encoding="utf-8")
    text = text.replace("my-feature", feature_id)
    text = text.replace("My Feature", display_name)
    text = text.replace("0.1.0", version)
    path.write_text(text, encoding="utf-8")


def _iter_text_files(project_dir: Path) -> Iterable[Path]:
    for relative in _TEXT_FILES_RELATIVE:
        path = project_dir / relative
        if path.is_file():
            yield path


def scaffold_feature(options: ScaffoldOptions) -> Path:
    """Copy the bundled feature-template into <project_dir> and substitute placeholders.

    Returns the absolute path to the created project directory. Raises
    :class:`ScaffoldError` if the template can't be found or the target
    directory already exists.
    """
    template_dir = find_feature_template()
    if template_dir is None:
        raise ScaffoldError(
            "feature-template/ not found. Run `idp-feature-cli init` from a "
            "checkout of the IDP repository — the scaffold lives at "
            "subscription-features/feature-platform/feature-template/."
        )

    project_dir = options.project_dir.resolve()
    if project_dir.exists():
        raise ScaffoldError(
            f"{project_dir} already exists; refusing to overwrite. "
            f"Choose a different path or remove the existing directory."
        )

    # Copy everything except node_modules / dist / __pycache__ which would
    # leak from a previous local build.
    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in ("node_modules", "dist", "__pycache__")}

    shutil.copytree(template_dir, project_dir, ignore=_ignore)

    for path in _iter_text_files(project_dir):
        _substitute_in_file(
            path,
            feature_id=options.feature_id,
            display_name=options.display_name,
            version=options.version,
        )

    return project_dir
