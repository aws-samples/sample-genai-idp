# idp_feature_sdk

Publisher package for the IDP Accelerator Feature Platform. Exposes the
`idp-feature-cli` command used to build and publish installable extensions. For
the end-to-end authoring walkthrough see the
[Feature Platform Developer Guide](../../docs/feature-platform-developer-guide.md).

`idp-feature-cli` is used to:

1. Validate a feature project against the Feature Platform manifest schema.
2. Build the feature's UMD UI bundle and run `sam build` + `sam package` so the
   template's Lambda `CodeUri:` paths are rewritten to `s3://...` (required:
   CloudFormation runs the SAM transform server-side when deploying via
   TemplateURL and rejects local paths).
3. Validate the built UI bundle against the host's registration contract.
4. Zip, hash, and upload all artifacts to the "feature bucket" (or to the local
   marketplace-simulator's bucket) in the version-free extension layout
   (`<prefix>/extensions/<featureId>/…`).
5. Write/update `<prefix>/extensions/<featureId>/latest.json` so the main
   stack's `listInstalledFeatures` resolver picks up the new version.
6. Optionally register the feature with the marketplace-simulator so it can
   flow through `GetEntitlements` during local testing.

## Prerequisites

- **Python 3.12+**
- **AWS SAM CLI** (`sam`) on `PATH` — required by `build`, `publish`, and
  `deploy` to package the feature's Lambda functions. Without it those commands
  fail fast with a clear message.
- **Node.js** (only if the feature's `ui.buildCommand` runs a bundler).

## Install (editable)

```bash
pip install -e lib/idp_feature_sdk
```

## CLI

```bash
# Validate a feature project in-place
idp-feature-cli validate ./my-feature

# Build artifacts into ./my-feature/dist/
idp-feature-cli build ./my-feature

# Validate → build → upload → update latest.json → print Launch Stack URL
idp-feature-cli publish ./my-feature \
    --feature-bucket idp-marketplace-dev \
    --region us-east-1

# Also register with the local simulator (for end-to-end testing)
idp-feature-cli publish ./my-feature \
    --feature-bucket idp-marketplace-dev \
    --region us-east-1 \
    --register-with-simulator http://127.0.0.1:8080 \
    --simulator-product-code prod-docs-by-status

# Publish AND install one feature into a RUNNING host stack (per-extension
# analogue of `idp-cli deploy`). Publishes the feature, then create-or-updates
# its feature CloudFormation stack against the named host stack — the same
# stack a console install creates, so re-running it upgrades in place.
idp-feature-cli deploy ./my-feature \
    --host-stack-name IDP-FeaturePlatform
    # --region defaults to the AWS session region (like `idp-cli deploy`)
    # --feature-bucket defaults to idp-accelerator-artifacts-<account>-<region>
    # --wait (opt-in) blocks until the stack reaches a terminal state

# Inspect the manifest schema
idp-feature-cli show-schema
```

### `deploy` vs `publish` vs `deploy-pack`

| Command       | What it does                                                                 |
|---------------|------------------------------------------------------------------------------|
| `publish`     | Uploads artifacts to S3; prints a Launch Stack URL. Does **not** touch CFN.  |
| `deploy`      | `publish` + create-or-update **this feature's** stack into an existing host. |
| `deploy-pack` | Deploys a self-contained *pack* that stands up its **own** host stack.       |

`deploy` is the fast inner loop for iterating one extension from source against
a live IDP deployment. The feature stack is named
`<host-stack-name>-feature-<feature-id>` by default (override with
`--stack-name`) — identical to what the host's `getFeatureLaunchUrl` resolver
uses for a console install, so a CLI deploy updates that same stack rather than
creating a duplicate. The `RegisterFeature` custom resource in the template runs
on every deploy, self-registering the feature and copying its UI bundle.

Typical output of `publish`:

```
✓ Validated feature.yaml (docs-by-status v1.0.0)
✓ Validated UI bundle (42,103 bytes, sha256 d4e5f6…)
▸ Running sam build…
▸ Running sam package…
✓ SAM package complete → .aws-sam/packaged.yaml
✓ Uploaded s3://idp-marketplace-dev/features/extensions/docs-by-status/template.yaml
✓ Uploaded s3://idp-marketplace-dev/features/extensions/docs-by-status/1.0.0/ui-bundle.js
✓ Uploaded s3://idp-marketplace-dev/features/extensions/docs-by-status/1.0.0/manifest.json
✓ Updated s3://idp-marketplace-dev/features/extensions/docs-by-status/latest.json → 1.0.0

🚀 Launch Stack URL (placeholder MAINSTACKNAME):
https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?...
```

## Library API

```python
from idp_feature_sdk import FeaturePublisher

FeaturePublisher(project_dir="./my-feature").publish(
    feature_bucket="idp-marketplace-dev",
    region="us-east-1",
)
```

## Relationship to other packages

```
lib/
├── idp_common_pkg/   # shared runtime (Document model, OCR, config)
├── idp_sdk/          # CLI for invoking the main IDP stack's API
├── idp_cli_pkg/      # CLI for deploying / operating the main IDP stack
└── idp_feature_sdk/  # THIS — publisher for installable features
```

None of these depend on each other (except at test time).
