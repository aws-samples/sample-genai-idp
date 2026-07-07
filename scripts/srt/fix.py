#!/usr/bin/env python3
"""SRT fix script to run interactive issue fixing."""

import shlex
import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run shell command and return result."""
    try:
        # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - Reviewed: command input is controlled and sanitized
        result = subprocess.run(cmd, shell=True, cwd=cwd, text=True)  # nosec B602 - hardcoded commands, no user input
        return result.returncode == 0
    except Exception as e:
        print(f"Exception running command {cmd}: {e}")
        return False


def main():
    """Run SRT fix."""
    project_root = Path(__file__).parent.parent.parent
    srt_dir = project_root / ".srt"
    srt_executable = srt_dir / "srt"

    if not srt_executable.exists():
        print("SRT not found. Run 'make srt-setup' first.")
        sys.exit(1)

    print("Running SRT interactive fix...")

    # Use -p flag to specify project path
    project_path = str(project_root)
    print(f"Fixing issues in project: {project_path}")

    # Properly quote the project path to prevent command injection
    quoted_path = shlex.quote(project_path)
    if not run_command(f"./srt fix -p {quoted_path}", cwd=srt_dir):
        print("SRT fix completed with some issues remaining")
        sys.exit(0)

    # Copy updated issues.json back to scripts/srt (save suppressions)
    # Filter to keep only high-priority non-Open issues to minimize file size
    issues_source = srt_dir / "issues.json"
    issues_target = Path(__file__).parent / "issues.json"

    if issues_source.exists():
        import json

        # Load full scan results
        with open(issues_source, encoding="utf-8") as f:
            all_issues = json.load(f)

        # Filter: keep only HIGH priority issues that are NOT Open
        # This preserves suppressions, resolutions, and reopened HIGH issues
        # Rationale: Only HIGH priority issues gate CI/CD, so we only persist those
        # suppressions to minimize the committed file size. Medium/Low findings are
        # informational only and don't need to be tracked across runs.
        filtered_issues = [
            issue
            for issue in all_issues
            if issue.get("priority") in ["High", "HIGH"]
            and issue.get("status") != "Open"
        ]

        # Save filtered version
        with open(issues_target, "w", encoding="utf-8") as f:
            json.dump(filtered_issues, f, indent=2)

        print(
            f"✅ Updated issues.json in scripts/srt/ (saved {len(filtered_issues)} high-priority suppressions)"
        )
        print(
            f"   Filtered from {len(all_issues)} total issues to {len(filtered_issues)} (removed all Open and Low/Medium priority)"
        )
    else:
        print("⚠️  Warning: issues.json not found in .srt/ directory")

    print("✅ SRT fix complete!")


if __name__ == "__main__":
    main()
