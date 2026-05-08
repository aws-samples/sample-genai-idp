#!/usr/bin/env python3
"""SRT run script to execute security assessment."""

import sys
import subprocess
from pathlib import Path


def run_command(cmd, cwd=None, capture_output=False):
    """Run shell command and return result."""
    try:
        # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - Reviewed: command input is controlled and sanitized
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            text=True,
            capture_output=capture_output
        )  # nosec B602 - hardcoded commands, no user input
        if capture_output:
            return result
        return result.returncode == 0
    except Exception as e:
        print(f"Exception running command {cmd}: {e}")
        return None if capture_output else False


def main():
    """Run SRT security assessment."""
    import os

    project_root = Path(__file__).parent.parent.parent
    srt_dir = project_root / ".srt"
    srt_executable = srt_dir / "srt"

    # Check if running in CI/CD environment
    is_ci = bool(os.getenv("CI") or os.getenv("GITLAB_CI") or os.getenv("GITHUB_ACTIONS"))

    if not srt_executable.exists():
        print(f"❌ SRT not found at: {srt_executable}")
        print(f"   Expected .srt directory at: {srt_dir}")
        print("   Run 'make srt-setup' first.")
        sys.exit(1)

    print("Running SRT security assessment...")
    print(f"✓ SRT binary found at: {srt_executable}")

    # Run SRT assessment on the project
    # Use -y flag to skip interactive prompts (e.g., "Open dashboard in browser?")
    # Use -p flag to specify project path
    # Use --no-diagrams and --no-threat-models to reduce memory usage in CI/CD
    # Use --no-license-update to prevent automatic license header updates
    project_path = str(project_root)
    print(f"Scanning project: {project_path}")

    result = run_command(
        f"./srt assess -y -p {project_path} --no-diagrams --no-threat-models --no-license-update",
        cwd=srt_dir,
        capture_output=True
    )

    if result is None or result.returncode != 0:
        print("❌ SRT scan failed to run")
        if result:
            print(f"Exit code: {result.returncode}")
            if result.stdout:
                print(f"Output:\n{result.stdout}")
            if result.stderr:
                print(f"Error:\n{result.stderr}")
        sys.exit(1)

    # Print the output
    print(result.stdout)

    # Check if there are any open security issues
    # SRT output includes "Open: N" where N is the number of open issues
    if "Open: 0" not in result.stdout:
        print("\n❌ Security issues found! Review the SRT report above.")
        if is_ci:
            # In CI/CD: fail the build
            sys.exit(1)
        else:
            # In local dev: continue to fix prompt (exit 0)
            print("💡 Run 'make srt-fix' to interactively review and suppress issues.")
            sys.exit(0)

    print("\n✅ SRT scan complete - no security issues found!")


if __name__ == "__main__":
    main()
