#!/usr/bin/env python3
"""SRT setup script to download and configure the Sample Security Review Tool."""

import sys
import shutil
import subprocess
import platform
import urllib.request
import json
import os
from pathlib import Path


def run_command(cmd, cwd=None, interactive=False):
    """Run shell command and return result."""
    try:
        if interactive:
            result = subprocess.run(cmd, shell=True, cwd=cwd, text=True)  # nosec B602 nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - hardcoded commands, no user input
        else:
            result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)  # nosec B602 nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - hardcoded commands, no user input
        if result.returncode != 0:
            if not interactive:
                print(f"Error running command: {cmd}")
                print(f"Error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"Exception running command {cmd}: {e}")
        return False


def get_platform_suffix():
    """Get SRT platform suffix based on system."""
    system = platform.system().lower()
    arch = platform.machine().lower()

    if system == "linux":
        if "x86_64" in arch or "amd64" in arch:
            return "linux-x64"
        elif "arm" in arch or "aarch64" in arch:
            return "linux-arm64"
    elif system == "darwin":  # macOS
        if "arm" in arch or "aarch64" in arch:
            return "macos-arm64"
        else:
            return "macos-x64"
    elif system == "windows":
        return "windows-x64"

    raise ValueError(f"Unsupported platform: {system} {arch}")


def get_latest_release():
    """Fetch latest release information from GitHub."""
    url = "https://api.github.com/repos/aws-samples/sample-security-review-tool/releases/latest"
    try:
        with urllib.request.urlopen(url) as response:  # nosec B310 - GitHub API URL is trusted
            data = json.loads(response.read().decode())
            return data["tag_name"], data["assets"]
    except Exception as e:
        print(f"Failed to fetch latest release: {e}")
        return None, None


def download_srt(tag_name, assets, srt_dir):
    """Download SRT binary for current platform."""
    platform_suffix = get_platform_suffix()

    # Construct expected filename pattern: srt-cli-v{version}-{platform}.{ext}
    # e.g., srt-cli-v1.0.2-linux-x64.tar.gz
    extension = ".zip" if "windows" in platform_suffix else ".tar.gz"
    expected_pattern = f"srt-cli-{tag_name}-{platform_suffix}{extension}"

    # Find matching asset
    asset = None
    for a in assets:
        if a["name"] == expected_pattern:
            asset = a
            break

    if not asset:
        print(f"No release found for platform: {expected_pattern}")
        print(f"Available assets: {[a['name'] for a in assets]}")
        return False

    download_url = asset["browser_download_url"]
    archive_path = srt_dir / expected_pattern

    print(f"Downloading SRT {tag_name} for {platform_suffix}...")
    try:
        urllib.request.urlretrieve(download_url, archive_path)  # nosec B310 - GitHub release URL is trusted
        print(f"Downloaded: {archive_path.name}")
        return archive_path
    except Exception as e:
        print(f"Download failed: {e}")
        return False


def extract_srt(archive_path, srt_dir):
    """Extract SRT archive."""
    filename = archive_path.name

    print(f"Extracting: {filename}")

    success = False
    if filename.endswith(".tar.gz"):
        success = run_command(f"tar -xzf {filename}", cwd=srt_dir)
    else:
        print(f"Unsupported archive format: {filename}")
        return False

    # Remove macOS quarantine attribute if on macOS
    if success and platform.system().lower() == "darwin":
        srt_executable = srt_dir / "srt"
        if srt_executable.exists():
            print("Removing macOS quarantine attribute...")
            run_command(f"xattr -d com.apple.quarantine ./srt", cwd=srt_dir)

    return success


def get_installed_version(srt_dir):
    """Get the currently installed SRT version, or None if not installed."""
    srt_executable = srt_dir / "srt"
    if not srt_executable.exists():
        return None
    try:
        result = subprocess.run(
            [str(srt_executable), "--version"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            # Parse version from output like "srt version v0.1.0"
            output = result.stdout.strip()
            if "version" in output:
                return output.split()[-1].lstrip("v")
        return None
    except Exception:
        return None


def main():
    """Setup SRT tool."""
    project_root = Path(__file__).parent.parent.parent
    srt_dir = project_root / ".srt"

    # Check if running in CI/CD environment
    is_ci = bool(os.getenv("CI") or os.getenv("GITLAB_CI") or os.getenv("GITHUB_ACTIONS"))

    print("Setting up SRT (Sample Security Review Tool)...")

    # Create .srt directory
    srt_dir.mkdir(exist_ok=True)

    # Get latest release info
    tag_name, assets = get_latest_release()
    if not tag_name or not assets:
        print("Failed to fetch latest release information")
        sys.exit(1)

    desired_version = tag_name.lstrip("v")
    print(f"Latest version: v{desired_version}")

    # Check if desired version is already installed
    installed_version = get_installed_version(srt_dir)
    if installed_version == desired_version:
        print(f"SRT v{desired_version} is already installed. Skipping download.")
    else:
        if installed_version:
            print(f"Installed: v{installed_version}. Upgrading to: v{desired_version}.")

        # Remove old files
        for old_file in srt_dir.glob("srt*"):
            old_file.unlink()
            print(f"Removed old file: {old_file.name}")

        # Download SRT
        archive_path = download_srt(tag_name, assets, srt_dir)
        if not archive_path:
            print("Failed to download SRT tool")
            sys.exit(1)

        # Extract SRT tool
        if not extract_srt(archive_path, srt_dir):
            print("Failed to extract SRT tool")
            sys.exit(1)

        # Verify installed version after extraction
        installed_version = get_installed_version(srt_dir)
        if installed_version and installed_version != desired_version:
            print(
                f"Warning: Expected v{desired_version}, "
                f"but got v{installed_version}."
            )

        print(f"✅ SRT v{desired_version} installed successfully!")

    # Make srt executable
    srt_executable = srt_dir / "srt"
    if srt_executable.exists():
        srt_executable.chmod(0o755)

    # Configure SRT
    config_file = srt_dir / "srtconfig.json"

    if is_ci:
        # Create config file programmatically for CI/CD
        print("\n✅ Running in CI/CD - creating non-interactive configuration")
        config_data = {
            "AWS_PROFILE": os.getenv("AWS_PROFILE", "default"),
            "AWS_REGION": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            "TELEMETRY_ENABLED": False,
            "INSTALLATION_ID": os.getenv("CI_COMMIT_SHORT_SHA", "local-dev")
        }
        config_file.write_text(json.dumps(config_data, indent=2))
        print(f"   AWS Profile: {config_data['AWS_PROFILE']}")
        print(f"   AWS Region: {config_data['AWS_REGION']}")
        print(f"   Installation ID: {config_data['INSTALLATION_ID']}")

        # Install prerequisites non-interactively using yes command
        print("   Installing SRT prerequisites...")
        result = subprocess.run(
            "yes '' | timeout 180 ./srt config",
            shell=True,
            cwd=srt_dir,
            capture_output=True,
            text=True,
            check=False
        )
        if "Configuration saved!" in result.stdout or result.returncode == 0:
            print("   ✅ Prerequisites installed successfully")
        else:
            print(f"   ⚠️  Prerequisites installation completed with warnings")
            print(f"      (This is normal - semgrep may fail but SRT will work)")
    else:
        # Interactive configuration for local development
        if not config_file.exists():
            print("\nConfiguring SRT...")
            print("Please follow the prompts to configure SRT with your AWS settings.")

            result = subprocess.run(
                ["./srt", "config"],
                cwd=srt_dir,
                check=False
            )
            if result.returncode != 0:
                print("⚠️  SRT configuration incomplete. You can run 'cd .srt && ./srt config' later.")
            else:
                print("✅ SRT configuration complete!")
        else:
            print("✅ SRT already configured (run 'cd .srt && ./srt config' to reconfigure)")

    # Copy latest issues.json from scripts/srt to .srt (restore suppressions)
    issues_source = Path(__file__).parent / "issues.json"
    issues_target = srt_dir / "issues.json"

    if issues_source.exists():
        shutil.copy2(issues_source, issues_target)
        print(f"✅ Copied latest issues.json to .srt/ (restored suppressions)")
    else:
        print("ℹ️  No existing issues.json found - this is a fresh SRT setup")

    print("\n✅ SRT setup complete!")
    print(f"Binary location: {srt_executable}")
    if not is_ci:
        print("\nNext steps:")
        print("  - Run assessment: make srt-scan")
        print("  - Interactive fix: make srt-fix")


if __name__ == "__main__":
    main()
