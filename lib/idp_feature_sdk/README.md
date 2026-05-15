# idp_feature_sdk

Publisher package for the IDP Accelerator Feature Platform. Exposes the
`idp-feature-cli` command used to:

1. Validate a feature project against the Feature Platform manifest schema.
2. Build the feature's CloudFormation template, Lambda code, and UMD UI bundle.
3. Validate the built UI bundle against the host's registration contract.
4. Zip, hash, and upload all artifacts to the "seller bucket" (or to the local
   marketplace-simulator's bucket).
5. Write/update `features/<featureId>/latest.json` so the main stack's
   `listInstalledFeatures` resolver picks up the new version.
6. Optionally register the feature with the marketplace-simulator so it can
   flow through `GetEntitlements` during local testing.

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
    --seller-bucket idp-marketplace-dev \
    --region us-east-1

# Also register with the local simulator (for end-to-end testing)
idp-feature-cli publish ./my-feature \
    --seller-bucket idp-marketplace-dev \
    --region us-east-1 \
    --register-with-simulator http://127.0.0.1:8080 \
    --simulator-product-code prod-docs-by-status

# Inspect the manifest schema
idp-feature-cli show-schema
```

Typical output of `publish`:

```
✓ Validated feature.yaml
✓ Built template.yaml             (SHA-256 a1b2c3...)
✓ Built ui-bundle.js               (42 KiB, SHA-256 d4e5f6...)
✓ Validated UI bundle  (registers 'docs-by-status' v1.0.0)
✓ Uploaded 3 artifacts to s3://idp-marketplace-dev/features/docs-by-status/v1.0.0/
✓ Updated s3://idp-marketplace-dev/features/docs-by-status/latest.json → 1.0.0

🚀 Launch Stack URL:
https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?...

Paste this into an IDP admin's browser to install the feature.
```

## Library API

```python
from idp_feature_sdk import FeaturePublisher

FeaturePublisher(project_dir="./my-feature").publish(
    seller_bucket="idp-marketplace-dev",
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
