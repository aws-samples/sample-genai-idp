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
- **Node.js** (only if the feature's `ui.build` steps run a bundler).

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

# Validate → build → upload → update latest.json → print Launch Stack URL.
# --bucket-basename is a basename — the region is appended automatically (so
# `idp-marketplace-dev` in us-east-1 becomes `idp-marketplace-dev-us-east-1`),
# matching `idp-cli publish`. Omit it to use the per-account default bucket.
idp-feature-cli publish ./my-feature \
    --bucket-basename idp-marketplace-dev \
    --region us-east-1

# Also register with the local simulator (for end-to-end testing)
idp-feature-cli publish ./my-feature \
    --bucket-basename idp-marketplace-dev \
    --region us-east-1 \
    --register-with-simulator http://127.0.0.1:8080 \
    --simulator-product-code prod-docs-by-status

# Install one feature into a RUNNING host stack (per-extension analogue of
# `idp-cli deploy`). Two modes, mirroring `idp-cli deploy`:
#
#   A) --from-code: publish from source, then create-or-update the feature's
#      CloudFormation stack — the same stack a console install creates, so
#      re-running it upgrades in place.
idp-feature-cli deploy --from-code ./my-feature \
    --host-stack-name IDP-FeaturePlatform
    # --region defaults to the AWS session region (like `idp-cli deploy`)
    # --bucket-basename defaults to idp-accelerator-artifacts-<account>-<region>
    # --wait (opt-in) blocks until the stack reaches a terminal state
#
#   B) --template-url: deploy an ALREADY-published template (no rebuild). The
#      feature bucket is parsed from the URL unless --bucket-basename is given.
idp-feature-cli deploy \
    --template-url https://<bucket>.s3.<region>.amazonaws.com/extensions/<id>/template.yaml \
    --host-stack-name IDP-FeaturePlatform

# Inspect the manifest schema
idp-feature-cli show-schema
```

### `deploy` vs `publish` vs `deploy-pack`

| Command       | What it does                                                                 |
|---------------|------------------------------------------------------------------------------|
| `publish`     | Uploads artifacts to S3; prints a Launch Stack URL. Does **not** touch CFN.  |
| `deploy`      | Create-or-update **this feature's** stack into an existing host — either `--from-code` (publish first) or `--template-url` (already published). |
| `deploy-pack` | Create-or-update a self-contained *pack* that stands up its **own** host stack — re-running against an existing wrapper stack updates it in place. |

A **pack** (`publish-pack` / `deploy-pack`) publishes its feature artifacts
exactly like `publish` — shared publisher, so the same `extensions/<id>/`
version-free layout and the same baked tokens — then bakes the publish
**bucket + version-free prefix + version** into its wrapper template's
parameter defaults. The pack's feature stack reads those artifacts *in place*
via IAM; there is no seller bucket and no pre-stage copy. Declare the wrapper
parameter names under `pack.wrapperParameters` in `feature.yaml`:

```yaml
pack:
  wrapperTemplatePath: deploy.yaml
  wrapperParameters:
    hostTemplateUrlParam: IdpAcceleratorTemplateUrl
    featureBucketParam:   FeatureBucket          # bucket holding the artifacts
    prefixParam:          FeatureArtifactPrefix  # e.g. extensions/<id>
    versionParam:         FeatureVersion
```

(The pre-`#375` `artifactSourceParam` / seller-bucket model is gone; wrappers
that still declare it must migrate to `featureBucketParam` + `prefixParam`.)

`deploy-pack` is **create-or-update** (like `deploy`, `idp-cli deploy`, and
`idp-mp-sim deploy`): it creates the wrapper stack if absent and **updates** it
if it already exists, so re-running pushes pack changes to a deployed wrapper
instead of failing with `AlreadyExistsException`. A no-op update (nothing
changed) exits 0 with an "already up to date" message. For a pack whose feature
install is a nested `AWS::CloudFormation::Stack`, an in-place wrapper update with
a bumped `FeatureVersion` cascades into the nested stack and picks up the
republished version-pinned artifacts; the wrapper's host custom resource treats
`Update` as a no-op, so the running host is left undisturbed.

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

## Artifacts-bucket security

The artifacts bucket (`idp-accelerator-artifacts-<account>-<region>` when you
omit `--bucket-basename`) is hardened by `ensure_artifacts_bucket`:

| Control | New bucket | Pre-existing bucket |
|---|---|---|
| `EnforceSSLOnly` bucket policy (deny `s3:*` when `aws:SecureTransport` is false) | Applied; failure is fatal | Applied best-effort — a `PutBucketPolicy` denial warns and continues |
| S3 Block Public Access (all four flags) | Enabled | **Left untouched** |
| `PackPublicArtifactsRead` public-read on `extensions/*` + `host/*` | Only with `--public` | Only with `--public` |

Two deliberate asymmetries:

- **Block Public Access is never changed on a bucket the CLI didn't create.**
  Relaxing it could silently revert a manual security remediation, so a
  pre-existing bucket keeps whatever BPA settings its operator set.
- **`EnforceSSLOnly` *is* applied to pre-existing buckets**, because it only
  ever *tightens* access. It's merged additively: your own statements survive,
  and a stale `EnforceSSLOnly` is replaced rather than duplicated, so
  re-publishing is idempotent. On a bucket you own but haven't granted us
  `s3:PutBucketPolicy` on, the publish warns and continues rather than failing
  — add the statement manually in that case.

ARNs use the region's real partition (`arn:aws-us-gov:` in GovCloud), mirroring
`arn:${AWS::Partition}:` in the CloudFormation templates.

## Build & package commands in `feature.yaml`

The publisher can (re)build the UI bundle and package agent source before
uploading. Declare the commands as **structured step lists** — each step is an
`argv` array executed directly (`shell=False`, so no `&&`, pipes, globs, or
variable expansion), with an optional `cwd` relative to the project root:

```yaml
ui:
  bundlePath: feature-ui/dist/ui-bundle.js
  build:
    - cwd: feature-ui
      argv: ["npm", "ci"]
    - cwd: feature-ui
      argv: ["npm", "run", "build"]

agentSource:
  artifactPath: dist/agent-source.zip
  package:
    - argv: ["python3", "scripts/package_agent.py"]
```

Steps run in order; publishing aborts on the first non-zero exit. Because no
shell is involved, there is no command-injection surface (Bandit B602) and the
manifest stays portable across shells/OSes. Anything that genuinely needs shell
features belongs in a script the step invokes (e.g.
`argv: ["bash", "scripts/build.sh"]`).

The legacy single-string forms (`ui.buildCommand`, `agentSource.packageCommand`)
are still accepted for existing manifests but are **deprecated** — they run
through a shell and emit a runtime deprecation notice. A manifest may declare
either the structured or the legacy form, not both.

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
