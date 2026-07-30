# PyPI name placeholders (defensive registration)

These are **not** real packages. Each is a minimal, deliberately non-functional
distribution published solely to **hold a first-party name on public PyPI** so a
third party cannot register it and turn a bare requirement in this repo into a
dependency-confusion vector.

## Background

Packages in `lib/` depend on their siblings by bare name (e.g. `idp_sdk`
requires `"idp_common"`). Those packages are first-party — they live in this
repo and are installed from the local checkout — but a bare requirement is
satisfiable from public PyPI whenever the sibling is not already installed. If
an attacker owns the name, pip installs their code.

That already happened to us. `idp-common` and `idp-sdk` were registered by a
third party ("Poneglyph Security Research") before we thought to claim them; see
`docs/dependency-confusion.md`. For those two, registration is no longer
available and the remedy is a PyPI takedown request.

`idp-feature-sdk` and `idp-mcp-connector` were still unclaimed, so we register
them ourselves. Prevention beats detection: the tripwire
(`scripts/check_first_party_deps.py`) catches a wrong package after the fact,
but owning the name means there is nothing wrong to install.

## Why these stubs fail loudly

Each placeholder raises `RuntimeError` on import with an explanation and a
pointer to the real install path.

This is deliberate. A stub that imports silently and exports nothing is exactly
the failure mode that cost us an afternoon of debugging: the squatted `idp_sdk`
imported fine, so `from idp_sdk import IDPClient` raised a confusing
`ImportError` far from the cause. If someone ever installs one of these
placeholders by accident, they should be told immediately and precisely.

## Do not depend on these

Nothing in this repo should ever install from these directories. They exist only
to be uploaded to PyPI. The real packages live in `lib/`:

| Placeholder name    | Real package               |
| ------------------- | -------------------------- |
| `idp-feature-sdk`   | `lib/idp_feature_sdk`      |
| `idp-mcp-connector` | `lib/idp_mcp_connector_pkg`|

## Publishing

Only needs doing once per name. See `docs/dependency-confusion.md` for the full
procedure, including the version strategy (`0.0.0`, yanked after upload) that
keeps a placeholder from ever satisfying a real requirement.

```bash
cd scripts/pypi-placeholders/<name>
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*        # requires a PyPI API token
```

After upload, **yank** the release (`0.0.0`) on PyPI. Yanking keeps the name
reserved while telling pip never to resolve it for an unpinned requirement.
