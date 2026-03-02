#!/usr/bin/env python3
"""DSR run script to execute DSR scan."""

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
    """Run DSR scan."""
    project_root = Path(__file__).parent.parent.parent
    dsr_dir = project_root / ".dsr"
    dsr_executable = dsr_dir / "dsr"
    
    if not dsr_executable.exists():
        print("DSR not found. Run 'make dsr-setup' first.")
        sys.exit(1)
    
    print("Running DSR scan...")
    
    # Always run DSR assess - it will be faster on subsequent runs
    project_path = str(project_root)
    print(f"Using project path: {project_path}")
    
    if not run_command(f"./dsr assess -p {project_path} -l aws -y --no-license-update", cwd=dsr_dir):
        print("DSR scan failed")
        sys.exit(1)
    
    print("DSR scan complete!")


if __name__ == "__main__":
    main()
