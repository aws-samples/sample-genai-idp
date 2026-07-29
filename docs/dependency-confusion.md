---
title: "Dependency Confusion and First-Party Packages"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Dependency Confusion and First-Party Packages

This project ships several **first-party** Python packages that live in `lib/`
and are **not published to PyPI**. They must always be installed from a local
checkout. Installing one by bare name (`pip install idp_common`) reaches public
PyPI, where some of those names are registered by third parties — so you get
someone else's code in the environment that holds your AWS deployment
credentials.

This page explains the hazard, what we do about it, and what to do if you think
you are affected.

## The hazard

Some first-party packages depend on their siblings by bare name. For example
`lib/idp_sdk` requires `"idp_common"`, and `lib/idp_cli_pkg` requires
`"idp-sdk"`. A bare requirement tells pip "find this anywhere you can" — and if
the sibling is not already installed, pip resolves it from public PyPI.

That is **dependency confusion**: a name we treat as internal is satisfiable by
whoever registered it publicly.

It is not theoretical here. Two of our names were registered by an unrelated
third party before we thought to claim them:

| Name          | Status on public PyPI                                            |
| ------------- | ---------------------------------------------------------------- |
| `idp-common`  | Registered by a third party ("Poneglyph Security Research"), 0.1.0 |
| `idp-sdk`     | Registered by the same third party, 0.1.0                          |
| `idp-cli`     | Registered by an unrelated legitimate project, 1.0.0               |

The packages under those first two names are currently inert — they print a
banner and contain no install hooks or network calls. But the name owner can
publish a new version at any time, and it would be installed automatically.

The failure is also **quiet**, which makes it expensive to diagnose. The
squatted `idp_sdk` imports successfully but exports nothing, so
`from idp_sdk import IDPClient` raises `ImportError` — historically swallowed by
a blanket `except ImportError`, surfacing much later as an unrelated
`AttributeError`.

## What we do about it

Four layers, in order of how much they actually prevent:

### 1. Single-invocation installs

`make setup` and `make setup-venv` install **all** first-party packages in one
`pip install` call (`FIRST_PARTY_EDITABLES` in the `Makefile`). Within a single
resolution pass, pip satisfies the sibling names from the local checkout instead
of reaching for an index.

> ⚠️ Never split that list across multiple `pip install` calls. Installing
> `idp_cli_pkg` before `idp_sdk` is exactly the ordering that pulls the squatted
> package.

### 2. A tripwire

`scripts/check_first_party_deps.py` verifies that every first-party package was
installed from source. It uses [PEP 610][pep610] `direct_url.json`, which pip
writes for local and VCS installs and omits for index installs — so it works for
editable and non-editable installs alike.

```bash
python scripts/check_first_party_deps.py
```

Exit code 0 means everything resolved locally; 1 means something came from an
index (or is missing). `make setup` runs it automatically after installing.

### 3. Defensive name registration

Names we still own are registered on PyPI as **non-functional placeholders**, so
nobody else can take them. See `scripts/pypi-placeholders/`. Each placeholder
raises `RuntimeError` on import explaining what happened and how to install the
real package — deliberately loud, because a silent stub reproduces the very
failure mode described above.

Registration is strictly better than detection: a tripwire finds the wrong
package after it is installed, whereas owning the name means there is nothing
wrong to install.

### 4. Documentation that never suggests a bare install

Every install instruction in this repo uses a path (`pip install -e
lib/...`). If you find one that does not, it is a bug — please report it.

## Installing correctly

The normal path installs everything at once:

```bash
make setup          # into the current environment
make setup-venv     # into a fresh .venv
```

For a single component, use a path from the repository root:

```bash
pip install -e "lib/idp_common_pkg[extraction]"
pip install -e lib/idp_sdk
pip install -e lib/idp_feature_sdk
```

Lambda `requirements.txt` files already use relative paths, which are immune:

```
../../lib/idp_common_pkg[extraction]
```

## If you think you are affected

1. **Check.** Run the tripwire:

   ```bash
   python scripts/check_first_party_deps.py
   ```

2. **Inspect** what is actually installed. A first-party package showing a
   version like `0.1.0` (rather than the repo's version) is a strong signal:

   ```bash
   pip list | grep -i idp
   ```

3. **Clean up** and reinstall in one pass:

   ```bash
   pip uninstall -y idp_common idp-sdk idp-cli idp_feature_sdk idp_mcp_connector
   make setup
   ```

4. **Consider your credentials.** If a squatted package was installed in an
   environment with AWS credentials, treat it as you would any untrusted code
   execution: review what the installed version actually did (`pip download` the
   exact version and inspect it *without installing*), and rotate credentials if
   you cannot rule out execution. The versions we observed were inert, but
   verify the version you had.

## Related

- [Dependency Mirroring for Air-Gapped Builds](dependency-mirroring.md) — how to
  mirror dependencies into an internal artifact repository, which also removes
  public-index resolution from your builds.
- `scripts/check_first_party_deps.py` — the tripwire.
- `scripts/pypi-placeholders/README.md` — defensive registrations.

[pep610]: https://peps.python.org/pep-0610/
