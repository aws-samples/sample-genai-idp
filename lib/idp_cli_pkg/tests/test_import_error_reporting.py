# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests that a broken idp_sdk install is reported clearly instead of crashing.

Regression coverage for the dependency-confusion failure mode: the squatted
`idp_sdk` on public PyPI imports fine but exports nothing, so
`from idp_sdk import IDPClient` raises ImportError. That must not take out
`click` — importing cli.py used to die at the module-level `@click.group()`
decorator with `AttributeError: 'NoneType' object has no attribute 'group'`,
which hides the real cause.

These run in a subprocess: the checks are about module-import behavior, and a
fake `idp_sdk` injected into an already-imported process would not be picked up.
"""

import subprocess
import sys
import textwrap

import pytest

# Stand in for the squatted package: imports cleanly, exports no IDPClient.
_FAKE_SQUATTED_SDK = """
import sys
import types

fake = types.ModuleType("idp_sdk")
fake.__version__ = "0.1.0"
sys.modules["idp_sdk"] = fake
"""


def _run(*parts: str) -> subprocess.CompletedProcess:
    """Run the dedented concatenation of `parts` as a fresh Python process."""
    script = "\n".join(textwrap.dedent(part) for part in parts)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.unit
def test_import_survives_sdk_without_idpclient():
    """cli.py must import even when idp_sdk lacks IDPClient (click stays usable)."""
    result = _run(
        _FAKE_SQUATTED_SDK,
        """
        import idp_cli.cli as cli

        # The module imported at all — this is what used to fail.
        assert cli.click is not None, "click must not be stubbed to None"
        assert cli.console is not None, "console must be constructed"

        # The real cause is retained for main() to report.
        assert cli._IMPORT_ERROR is not None, "ImportError must be recorded"
        assert "IDPClient" in str(cli._IMPORT_ERROR)

        # Only the sdk-dependent names are stubbed.
        assert cli.IDPClient is None
        print("IMPORT_OK")
        """,
    )
    assert "IMPORT_OK" in result.stdout, (
        f"import failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "AttributeError" not in result.stderr
    assert result.returncode == 0


@pytest.mark.unit
def test_main_reports_root_cause_and_exits_nonzero():
    """main() must explain the problem and surface the underlying ImportError."""
    result = _run(
        _FAKE_SQUATTED_SDK,
        """
        from idp_cli.cli import main

        main()
        """,
    )
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
    # The actionable guidance, and the specific root cause.
    assert "Underlying import error:" in result.stderr
    assert "IDPClient" in result.stderr
    assert "check_first_party_deps.py" in result.stderr
    # The misleading symptom must be gone.
    assert "AttributeError" not in result.stderr


@pytest.mark.unit
def test_healthy_install_records_no_import_error():
    """With a real idp_sdk present, nothing is stubbed and no error is recorded."""
    result = _run(
        """
        import idp_cli.cli as cli

        assert cli._IMPORT_ERROR is None, f"unexpected: {cli._IMPORT_ERROR}"
        assert cli.IDPClient is not None
        assert cli.display is not None
        print("HEALTHY_OK")
        """
    )
    assert "HEALTHY_OK" in result.stdout, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
