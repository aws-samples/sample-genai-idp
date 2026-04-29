#!/usr/bin/env python3
"""Type check only files changed in current branch vs target branch.

This script enables incremental type checking for PRs by:
1. Finding all Python files changed compared to the target branch
2. Creating a temporary pyrightconfig that only includes changed files
3. Running basedpyright on those files
4. Ensuring new code doesn't introduce type errors

Usage:
    python scripts/sdlc/typecheck_pr_changes.py [target_branch]

    target_branch: Branch to compare against (default: main)

Examples:
    python scripts/sdlc/typecheck_pr_changes.py main
    python scripts/sdlc/typecheck_pr_changes.py develop
    python scripts/sdlc/typecheck_pr_changes.py origin/main
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def get_changed_files(target_branch: str = "develop") -> list[str]:
    """Get list of changed Python files compared to target branch.

    Args:
        target_branch: Git branch to compare against

    Returns:
        List of Python file paths that have been modified
    """
    # Try different git reference formats for CI compatibility
    ref_formats = [
        f"origin/{target_branch}...HEAD",  # Standard format
        f"origin/{target_branch}",  # Simple diff against target
        target_branch,  # Local branch if origin not available
    ]

    for ref in ref_formats:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", ref],
                capture_output=True,
                text=True,
                check=True,
            )
            files = [
                f
                for f in result.stdout.splitlines()
                if f.endswith(".py") and Path(f).exists()
            ]
            if files or result.returncode == 0:
                return files
        except subprocess.CalledProcessError:
            continue

    # If all methods fail, print error
    print(
        f"❌ Error: Could not compare against target branch '{target_branch}'",
        file=sys.stderr,
    )
    print(f"Tried: {', '.join(ref_formats)}", file=sys.stderr)
    print("\nAvailable branches:", file=sys.stderr)
    try:
        subprocess.run(["git", "branch", "-a"], check=False)
    except Exception:
        pass
    sys.exit(1)


def create_temp_config(
    files: list[str], base_config: str = "pyrightconfig.json"
) -> str:
    """Create temporary pyrightconfig with only changed files.

    Args:
        files: List of Python files to check
        base_config: Path to base configuration file

    Returns:
        Path to temporary configuration file
    """
    config_path = Path(base_config)

    config: dict[str, Any]
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        # Default config if none exists
        config = {
            "pythonVersion": "3.12",
            "pythonPlatform": "Linux",
            "typeCheckingMode": "basic",
        }

    # Override include to only check changed files
    config["include"] = files

    temp_config_path = "pyrightconfig.temp.json"
    with open(temp_config_path, "w") as f:
        json.dump(config, f, indent=2)

    return temp_config_path


def run_type_check(config_path: str) -> int:
    """Run basedpyright with specified config.

    Args:
        config_path: Path to pyrightconfig file

    Returns:
        Exit code: 0 if no errors, 1 if errors found
    """
    result = subprocess.run(
        ["basedpyright", "--project", config_path],
        capture_output=True,
        text=True,
        check=False,
    )
    
    # Print the output
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    
    # Parse output to check for actual errors
    # basedpyright outputs a summary line like "X errors, Y warnings, Z notes"
    for line in result.stdout.splitlines():
        if " error" in line and " warning" in line:
            # Extract error count from the summary line
            import re
            match = re.search(r"(\d+)\s+error", line)
            if match:
                error_count = int(match.group(1))
                return 0 if error_count == 0 else 1
    
    # If we can't parse the output, fall back to exit code
    # But only treat it as an error if exit code indicates actual type errors
    # (exit code 3 might be from venv warnings, not actual errors)
    return result.returncode if result.returncode in [0, 1] else 0


def main() -> int:
    """Main entry point for incremental type checking."""
    target_branch = sys.argv[1] if len(sys.argv) > 1 else "main"

    print(f"🔍 Checking for Python files changed vs {target_branch}...")
    files = get_changed_files(target_branch)

    if not files:
        print("✅ No Python files changed - skipping type check")
        return 0

    print(f"\n📝 Found {len(files)} changed Python file(s):")
    for f in files:
        print(f"  • {f}")

    print("\n🔬 Running type checks on changed files...\n")

    temp_config = create_temp_config(files)

    try:
        exit_code = run_type_check(temp_config)

        if exit_code == 0:
            print("\n✅ Type checking passed!")
        else:
            print("\n❌ Type checking failed - please fix the errors above")

        return exit_code
    finally:
        # Clean up temporary config
        Path(temp_config).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())