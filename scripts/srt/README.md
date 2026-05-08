# SRT (Sample Security Review Tool) Integration

This directory contains scripts to integrate the AWS Sample Security Review Tool (SRT) into the IDP accelerator build and CI/CD pipeline.

## Overview

The Sample Security Review Tool is an open-source security scanning tool that helps identify security vulnerabilities and compliance issues in your codebase.

- **GitHub Repository**: https://github.com/aws-samples/sample-security-review-tool
- **Latest Releases**: https://github.com/aws-samples/sample-security-review-tool/releases

## Quick Start

### Local Development

```bash
# Full workflow (setup → scan → optional fix)
make srt

# Or run individual steps:
make srt-setup     # Download and configure SRT
make srt-scan      # Run security assessment
make srt-fix       # Interactive fix mode
```

### Running Tests

```bash
# Run all tests (excludes SRT)
make test

# Run SRT security scan separately
make srt
```

SRT has a dedicated target and is not part of `make test` to avoid slowing down the development test loop. It runs automatically in CI/CD on merge requests to `develop`.

## CI/CD Integration

### GitLab CI

The SRT tool is integrated into the GitLab CI pipeline with a dedicated `security_review` stage that:

- **Only runs on merge requests targeting `develop` branch** (not on feature branches or after merge)
- Downloads the latest SRT version automatically
- Runs configuration and assessment
- **Fails the pipeline if security findings are detected**
- Runs after integration tests complete successfully

This ensures that security issues are caught before code is merged to `develop` while not blocking development velocity on other feature branches.

## Scripts

### setup.py

Downloads and configures the SRT tool:

1. Detects the current platform (Linux/macOS, x86_64/ARM64)
2. Fetches the latest release from GitHub
3. Downloads the appropriate binary for your platform
4. Extracts and makes it executable
5. Runs one-time configuration (AWS profile + PATH setup)

**Features:**
- Automatic version detection and upgrades
- Skips download if latest version already installed
- Platform-specific binary selection
- Interactive configuration

### run.py

Runs the SRT security assessment on the project:

- Executes `srt` command in the project root
- Fails with exit code 1 if security issues are found
- Suitable for CI/CD integration

### fix.py

Runs interactive fixing mode:

- Executes `srt fix` to iterate through findings
- Allows interactive remediation of issues
- Best used in local development, not CI/CD

## Configuration

SRT configuration is stored in `.srt/.srt-config` and includes:

- AWS profile to use for assessments
- PATH configuration for tool execution

Run `cd .srt && ./srt config` to reconfigure.

## Suppression Persistence

SRT tracks issue suppressions and resolutions in `issues.json`. To persist suppressions across runs and in CI/CD:

**File Locations:**
- `scripts/srt/issues.json` - **Committed to git** (source of truth for team)
- `.srt/issues.json` - **Gitignored** (working copy for SRT tool)

**Workflow:**
1. **Setup** (`make srt-setup`) - Copies `scripts/srt/issues.json` → `.srt/issues.json` (restore suppressions)
2. **Fix** (`make srt-fix`) - Copies `.srt/issues.json` → `scripts/srt/issues.json` (save suppressions)
3. **Commit** - After fixing/suppressing issues, commit updated `scripts/srt/issues.json` to git

This ensures suppressions persist across:
- Local development (between runs)
- CI/CD pipeline (across builds)
- Team members (via git)

## Files Generated

- `.srt/` - SRT installation directory (gitignored)
  - `srt` - The SRT binary
  - `srt-*.tar.gz` - Downloaded archives
  - `srtconfig.json` - Tool configuration
  - `issues.json` - Working copy (copied from scripts/srt/)
  - Assessment results and reports
- `scripts/srt/issues.json` - **Committed to git** (suppression database)

## GitLab CI Stage Details

The `security_review` stage in `.gitlab-ci.yml`:

```yaml
srt_security_review:
  stage: security_review
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: on_success
  script:
    - make srt-setup
    - make srt-scan
```

### Why only on MRs to `develop`?

Running automated security scans only on merge requests targeting `develop` provides the right balance:

✅ **Pros:**
- Catches security issues before merging to `develop`
- Provides clear security gate before code reaches `develop`
- Doesn't slow down feature branch pushes
- Reduces CI/CD queue time for work-in-progress branches

❌ **Running on every feature branch push would:**
- Slow down developer iteration
- Create noise with frequent updates
- Block early commits for security issues that may be fixed during development

## Best Practices

1. **Local Development**: Run `make srt` before pushing to catch issues early
2. **CI/CD**: Let the pipeline catch issues on develop branch
3. **Fix Promptly**: Address security findings before merging to main/production
4. **Stay Updated**: The tool auto-downloads latest versions to catch new vulnerability patterns

## Troubleshooting

### SRT not found

```bash
make srt-setup
```

### Configuration issues

```bash
cd .srt && ./srt config
```

### Platform not supported

SRT currently supports:
- Linux (x86_64, ARM64)
- macOS (x86_64, ARM64)

Windows support may be added in future releases.

## Learn More

- [SRT GitHub Repository](https://github.com/aws-samples/sample-security-review-tool)
- [Latest Releases](https://github.com/aws-samples/sample-security-review-tool/releases)
- [Documentation](https://github.com/aws-samples/sample-security-review-tool#readme)
