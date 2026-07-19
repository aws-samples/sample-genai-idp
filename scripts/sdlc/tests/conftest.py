"""Test bootstrap for the SDLC CodeBuild harness tests.

`scripts/sdlc/codebuild_deployment.py` is a standalone script (not an installed
package), so put its directory on sys.path and import it once as a module the
tests can monkeypatch. Importing it has no side effects — all AWS/subprocess
work lives inside functions guarded by `if __name__ == "__main__"`.
"""

import sys
from pathlib import Path

import pytest

_SDLC_DIR = Path(__file__).resolve().parent.parent
if str(_SDLC_DIR) not in sys.path:
    sys.path.insert(0, str(_SDLC_DIR))


@pytest.fixture
def cbd():
    """Import (and reset per-test global state on) the harness module."""
    import codebuild_deployment as module

    # These module-level primitives are process-global; clear them so a test
    # that sets ABORT_TESTS / never_abort can't leak into the next test.
    module.ABORT_TESTS.clear()
    if hasattr(module._thread_local, "never_abort"):
        del module._thread_local.never_abort
    yield module
    module.ABORT_TESTS.clear()
    if hasattr(module._thread_local, "never_abort"):
        del module._thread_local.never_abort
