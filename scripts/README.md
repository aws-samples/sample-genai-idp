# IDP Accelerator Scripts

This directory contains utility scripts for building, testing, deploying, and operating the IDP Accelerator.

## Directory Structure

```
scripts/
├── setup/               # Development environment setup scripts
├── srt/                 # SRT (Sample Security Review Tool) integration
├── sdlc/                # SDLC CI/CD scripts and infrastructure
│   ├── cfn/             # CloudFormation templates for CI/CD pipeline
│   └── [scripts]        # CI/CD automation scripts
└── generate_govcloud_template.py  # GovCloud template generation (deprecated — use `idp-cli publish --headless`)
```

## Subdirectories

### `setup/` - Development Environment Setup
Setup scripts for different operating systems. See [setup/README.md](setup/README.md).

### `srt/` - SRT Security Scanning
SRT (Sample Security Review Tool) integration for automated security scanning. See [srt/README.md](srt/README.md).

### `sdlc/` - SDLC CI/CD Scripts and Infrastructure
CloudFormation templates and scripts for CI/CD pipeline infrastructure.

| Script | Purpose | Usage |
|--------|---------|-------|
| `codebuild_deployment.py` | CodeBuild deployment automation | Used by CI/CD pipeline |
| `integration_test_deployment.py` | Integration test deployment | Used by CI/CD pipeline |
| `validate_buildspec.py` | Validate buildspec.yml files | See [sdlc/README_validate_buildspec.md](sdlc/README_validate_buildspec.md) |
| `typecheck_pr_changes.py` | Type check Python files in PRs | Used by CI/CD pipeline |
| `validate_service_role_permissions.py` | Validate IAM service role permissions | `python scripts/sdlc/validate_service_role_permissions.py` |

See [sdlc/cfn/README.md](sdlc/cfn/README.md) for CloudFormation templates.

## Utility Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `generate_govcloud_template.py` | Generate GovCloud-compatible template (**deprecated** — use `idp-cli publish --headless`) | `idp-cli publish --source-dir . --region <region> --headless` |

## Operational Commands (via idp-cli)

The following operations are available through the IDP CLI tool:

| Operation | CLI Command |
|-----------|-------------|
| Document status lookup | `idp-cli status --stack-name <name> --document-id <id>` |
| Batch status | `idp-cli status --stack-name <name> --batch-id <id>` |
| Stop workflows | `idp-cli stop-workflows --stack-name <name>` |
| Load testing | `idp-cli load-test --stack-name <name> --rate 2500` |
| Remove residual resources | `idp-cli remove-deleted-stack-resources --dry-run` |

See [CLI Documentation](../docs/idp-cli.md) for complete command reference.

## Migration Notes

The following scripts were migrated to the `idp-cli` tool and removed from this directory:

| Removed Script | Replacement CLI Command |
|----------------|------------------------|
| `lookup_file_status.sh` | `idp-cli status --stack-name <name> --document-id <id>` |
| `simulate_load.py` | `idp-cli load-test --stack-name <name> --rate 100` |
| `simulate_dynamic_load.py` | `idp-cli load-test --stack-name <name> --schedule schedule.csv` |
| `stop_workflows.sh` | `idp-cli stop-workflows --stack-name <name>` |
| `cleanup_orphaned_resources.py` | `idp-cli remove-deleted-stack-resources --dry-run` |

The CLI provides a unified interface with better error handling, progress display, and consistent options.
See [IDP CLI Documentation](../docs/idp-cli.md) for complete usage.

## Related Documentation

- [IDP CLI Documentation](../docs/idp-cli.md)
- [Deployment Guide](../docs/deployment.md)
- [Development Setup](../docs/setup-development-env-macos.md)
- [GovCloud Deployment](../docs/govcloud-deployment.md)