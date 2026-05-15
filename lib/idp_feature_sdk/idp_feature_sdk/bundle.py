# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""UMD bundle validation.

The feature UI bundle is a single UMD `.js` file that — when loaded in the
host — calls `window.IdpFeatures.register(featureId, { Component, version, displayName })`.

We can't actually execute the bundle here (that would need a DOM/jsdom/Node
runtime with React externals), but we can statically check that the bundle:

1. Is non-empty and reasonably sized.
2. Contains a `window.IdpFeatures.register(` call with the expected featureId
   and version literals somewhere in its source.
3. Does NOT bundle its own copy of React (a bundled React would bloat the
   output and conflict with the host's React at runtime).

The static check is deliberately loose — bundlers minify identifiers, so we
use forgiving regex patterns keyed on the string literals we know must appear.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


class BundleValidationError(ValueError):
    """Raised when the built UI bundle fails static validation."""


@dataclass(frozen=True)
class BundleInfo:
    path: Path
    size_bytes: int
    sha256: str


# Hand-rolled React-bundled detector: these string tokens appear in React's
# UMD/min builds; their presence in a feature bundle means React wasn't
# externalised. These are deliberately permissive — any one match is a signal.
_REACT_BUNDLED_MARKERS = (
    "Minified React error",
    "react.development.js",
    "react.production.min.js",
    "ReactCurrentDispatcher",  # React 18+ internals token
)

# Empirically-derived size threshold. A bundle that correctly externalises
# React + Cloudscape + aws-amplify is usually 5–80 KiB. Anything > 500 KiB is
# suspicious.
_SUSPICIOUS_SIZE_BYTES = 500 * 1024


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_bundle(
    bundle_path: Path,
    feature_id: str,
    expected_version: str,
) -> BundleInfo:
    """Static sanity-check of the UMD bundle. Returns size + sha256 if OK."""
    if not bundle_path.is_file():
        raise BundleValidationError(f"UI bundle not found at {bundle_path}")
    size = bundle_path.stat().st_size
    if size == 0:
        raise BundleValidationError(f"UI bundle {bundle_path} is empty")

    try:
        content = bundle_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BundleValidationError(
            f"UI bundle {bundle_path} is not UTF-8 (bundled binary? raw WASM?)"
        ) from exc

    # 1. Must reference the host registration entrypoint.
    if "IdpFeatures" not in content:
        raise BundleValidationError(
            f"UI bundle {bundle_path} does not reference `window.IdpFeatures` — "
            f"did you forget to call `window.IdpFeatures.register(...)` at the top level?"
        )

    # 2. Must reference the registered feature id (as a quoted literal).
    quoted_id = re.compile(r"""(['"])""" + re.escape(feature_id) + r"""\1""")
    if not quoted_id.search(content):
        raise BundleValidationError(
            f"UI bundle {bundle_path} does not contain the featureId literal "
            f"{feature_id!r}. The bundle must register with that exact id."
        )

    # 3. Must reference the declared version.
    quoted_version = re.compile(r"""(['"])""" + re.escape(expected_version) + r"""\1""")
    if not quoted_version.search(content):
        raise BundleValidationError(
            f"UI bundle {bundle_path} does not contain the version literal "
            f"{expected_version!r}. Ensure your bundle registers with version={expected_version!r}."
        )

    # 4. React must not be bundled.
    bundled_react = next((m for m in _REACT_BUNDLED_MARKERS if m in content), None)
    if bundled_react:
        raise BundleValidationError(
            f"UI bundle {bundle_path} appears to bundle React "
            f"(found marker {bundled_react!r}). React must be externalised — "
            f"see the feature-template's vite.config.ts for the correct externals config."
        )

    # 5. Size gate.
    if size > _SUSPICIOUS_SIZE_BYTES:
        raise BundleValidationError(
            f"UI bundle {bundle_path} is suspiciously large ({size:,} bytes). "
            f"Check your externals config: React/ReactDOM/Cloudscape/aws-amplify "
            f"should all be external."
        )

    return BundleInfo(path=bundle_path, size_bytes=size, sha256=_hash(bundle_path))
