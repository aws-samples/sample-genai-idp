#!/usr/bin/env python3
"""SRT run script to execute security assessment."""

import sys
import subprocess
import json
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


def print_high_priority_issues_table(issues_file):
    """Print high priority issues in a table format."""
    if not issues_file.exists():
        return

    try:
        with open(issues_file, 'r') as f:
            issues = json.load(f)
    except Exception as e:
        print(f"Warning: Could not read issues file: {e}")
        return

    # Filter for high priority issues that are not suppressed or resolved
    high_priority_issues = [
        i for i in issues
        if i.get('priority', '').upper() == 'HIGH'
        and i.get('status') not in ['suppressed', 'resolved']
    ]

    if not high_priority_issues:
        return

    print("\n" + "="*120)
    print("HIGH PRIORITY ISSUES FOUND")
    print("="*120)
    print(f"{'Source':<15} {'Priority':<10} {'Path':<50} {'Issue':<45}")
    print("-"*120)

    for issue in high_priority_issues:
        source = issue.get('source', 'Unknown')[:14]
        priority = issue.get('priority', 'Unknown')[:9]
        path = issue.get('path', 'Unknown')[:49]
        issue_text = issue.get('issue', 'No description')[:44]
        line = issue.get('line', '')

        if line:
            path_with_line = f"{path}:{line}"[:49]
        else:
            path_with_line = path

        print(f"{source:<15} {priority:<10} {path_with_line:<50} {issue_text:<45}")

    print("-"*120)
    print(f"Total HIGH priority issues: {len(high_priority_issues)}")
    print("="*120 + "\n")


def main():
    """Run SRT security assessment."""
    import os

    project_root = Path(__file__).parent.parent.parent
    srt_dir = project_root / ".srt"
    srt_executable = srt_dir / "srt"
    issues_file = srt_dir / "issues.json"

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

    # Print high priority issues table
    print_high_priority_issues_table(issues_file)

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
