#!/usr/bin/env python3
"""DSR fix script to run interactive issue fixing."""

import sys
import subprocess
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run shell command and return result."""
    try:
        # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - Reviewed: command input is controlled and sanitized
        result = subprocess.run(cmd, shell=True, cwd=cwd, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"Exception running command {cmd}: {e}")
        return False


def main():
    """Run DSR fix."""
    project_root = Path(__file__).parent.parent.parent
    dsr_dir = project_root / ".dsr"
    dsr_executable = dsr_dir / "dsr"
    
    if not dsr_executable.exists():
        print("DSR not found. Run 'make dsr' first.")
        sys.exit(1)
    
    print("Running DSR fix...")
    
    if not run_command(".dsr/dsr fix -e", cwd=project_root):
        print("DSR fix failed")
        sys.exit(1)
    
    # Copy updated results back to scripts/dsr
    issues_source = dsr_dir / "issues.json"
    issues_target = Path(__file__).parent / "issues.json"
    
    if issues_source.exists():
        import shutil
        shutil.copy2(issues_source, issues_target)
        print(f"Updated issues.json in scripts/dsr/")
    
    print("DSR fix complete!")


if __name__ == "__main__":
    main()
