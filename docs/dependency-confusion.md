---
title: "Installing First-Party Packages Safely"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Installing First-Party Packages Safely

This project ships several **first-party** Python packages that live in `lib/`
(`idp_common`, `idp_sdk`, the CLI, the Feature Platform SDK, the MCP connector).
They are **not published to PyPI** and must always be installed from a local
checkout.

Some of those names exist on public PyPI, owned by unrelated parties. So
installing one by bare name — `pip install idp_common` — does not fail; it
installs **someone else's package** into the environment that holds your AWS
deployment credentials, and the mismatch usually surfaces later as a confusing
unrelated error rather than an obvious one.

Use `make setup`, or a path, and this cannot happen.

## Installing correctly

The normal path installs every first-party package in one pass:

```bash
make setup          # into the current environment
make setup-venv     # create a .venv and install into it
```

For a single component, use a path from the repository root — never a bare name:

```bash
pip install -e "lib/idp_common_pkg[extraction]"
pip install -e lib/idp_sdk
pip install -e lib/idp_feature_sdk
```

> ⚠️ Install first-party packages **together, in a single `pip install`**. They
> depend on each other by name, so installing them one at a time lets pip go
> looking for a sibling that is not on disk yet. `make setup` handles this.

Lambda `requirements.txt` files already use relative paths, which are unaffected:

```
../../lib/idp_common_pkg[extraction]
```

## Verifying an environment

`scripts/check_first_party_deps.py` checks that every installed first-party
package came from source rather than from a package index:

```bash
python scripts/check_first_party_deps.py
```

Exit code 0 means everything resolved locally. `make setup` runs it
automatically. It is also worth running in CI, and after any manual `pip install`
in a development environment.

## If the check fails

1. **See what is installed.** A first-party package whose version does not match
   the repository's is the tell:

   ```bash
   pip list | grep -i idp
   ```

2. **Clean up and reinstall in one pass:**

   ```bash
   pip uninstall -y idp_common idp-sdk idp-accelerator-cli idp_feature_sdk \
       idp_mcp_connector
   make setup
   ```

3. **Then re-run the check** to confirm the environment is clean.

If a package from an index was installed in an environment holding AWS
credentials, treat it as you would any untrusted code execution: inspect the
artifact you actually received (`pip download` it and read it *without*
installing), and rotate credentials if you cannot rule out that it ran.

## A note on package names

Four identifiers are easy to conflate, and only the first affects installation:

| Identifier | Example |
| --- | --- |
| **Distribution name** — what `pip install` resolves | `idp-accelerator-cli` |
| Import name — what Python sees | `import idp_cli` |
| Console command — what you type | `idp-cli` |
| Runtime string literals — S3 prefixes, resource tags | `"idp-cli"` |

A distribution can be renamed without changing any of the others. The CLI's
distribution is `idp-accelerator-cli` because `idp-cli` on PyPI belongs to an
unrelated project; the command you type is still `idp-cli`.

## Related

- [Dependency Mirroring for Air-Gapped Builds](dependency-mirroring.md) — mirror
  dependencies into an internal artifact repository, which removes public-index
  resolution from your builds entirely.
- `scripts/pypi-placeholders/README.md` — names we hold on PyPI so they cannot be
  claimed by others.
