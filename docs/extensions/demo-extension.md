---
title: "Demo Extension (Docs By Status)"
---
# Demo Extension (Docs By Status)

The **Demo Extension** is the bundled reference feature for the
[Feature Platform](../feature-platform.md). It demonstrates the host contract
end-to-end and is the recommended starting point for authoring your own
extension.

## What it does

Adds a **Docs By Status** page to the IDP web UI: a pie chart showing how many
documents are currently in each processing status — NEW, QUEUED, RUNNING,
COMPLETED, FAILED. Counts are fetched live from the main stack's document
tracking table through a small feature-owned HTTP API.

## How it works

It exercises every part of the host contract, making it a complete, working
template:

- **UI bundle** — a React UMD module rendered inside the host UI, sharing the
  host's React/Cloudscape instances via `window.IdpFeatures.register(...)`.
- **Backend API** — an HTTP API + Lambda that reads the main stack's
  `TrackingTable` (granted a scoped cross-stack read role) and returns
  per-status counts. The UI calls it with a Cognito-issued bearer token.
- **Registration** — a `RegisterFeature` custom resource registers the feature
  with the host on stack create and unregisters on delete, so it appears in the
  **Extensions** nav automatically.

## Installing

The Demo Extension is bundled with the accelerator and listed in the catalog,
so it appears under **Extensions** in the nav as soon as the Feature Platform is
enabled (the default). An admin installs it from its feature page with one
click — there's no subscription step for open-source extensions.

## Source & authoring

The full source lives in
[`feature-platform/sample-feature/`](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/tree/main/feature-platform/sample-feature).
To build your own extension starting from this pattern, see the
[Feature Platform Developer Guide](../feature-platform-developer-guide.md).
