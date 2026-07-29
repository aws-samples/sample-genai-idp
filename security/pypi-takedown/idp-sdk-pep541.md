# PEP 541 request — `idp-sdk`

File at <https://github.com/pypi/support/issues/new/choose> → **"Name retention
related request (PEP 541)"**.

**Issue title:**

```
PEP 541 Request: idp-sdk
```

Fill `<YOUR_PYPI_USERNAME>` and the contact-attempt placeholder before
submitting. Everything else is verified — see `README.md` in this directory.

If both names turn out to belong to the same PyPI account, cross-link this issue
and the `idp-common` one so moderators can handle them together.

---

## Project to be claimed

`idp-sdk`: https://pypi.org/project/idp-sdk

## Your PyPI username

`<YOUR_PYPI_USERNAME>`: https://pypi.org/user/<YOUR_PYPI_USERNAME>

## Reasons for the request

I am requesting this name under PEP 541's **invalid project** criterion for
*"name squatting (package has no functionality or is empty)"*, and would accept
either transfer or removal. This is a companion to a parallel request for
`idp-common`, registered by the same uploader on the same day.

**The package is empty.** `idp-sdk` 0.1.0 (uploaded 2026-01-26, the only
release) contains no functionality — its entire runtime is a `main()` that prints
a banner identifying it as a "security research package". The sdist contains only
packaging boilerplate plus `src/idp_sdk/{__init__.py,main.py}`. No declared
dependencies, no `setup.py`, no `cmdclass`, no build or install hooks.

To be precise: **I am not reporting malware.** I inspected both distributions
statically (via `pip download`, without installing); they make no network access
and execute nothing at install time. The request rests on an empty package
holding the name.

**The name is a first-party component name of a public AWS project, and this
registration has already caused a real incident.** `idp_sdk` is a component of
the [GenAI Intelligent Document Processing Accelerator][repo], published by AWS
in the AWS Solutions Library. Our use of the name predates this registration and
the repository is public.

The name appears as a **bare requirement** in that codebase — `lib/idp_cli_pkg`
declares a dependency on `idp-sdk`, expected to resolve from the local checkout.
When it is not already installed, pip resolves it from public PyPI. Reproduced
from a clean virtual environment:

```
$ pip install ./lib/idp_cli_pkg
Collecting idp-sdk (from idp-cli==0.6.2)
  Using cached idp_sdk-0.1.0-py3-none-any.whl.metadata (1.8 kB)
Would install ... idp-cli-0.6.2 idp-sdk-0.1.0 ...
```

This is not hypothetical: a developer on our team unknowingly ran the squatted
`idp-sdk` in their environment for several months. Because the package imports
successfully but exports none of the expected symbols, the failure was silent and
misdiagnosed as an unrelated bug, costing real debugging time. The environments
concerned hold AWS deployment credentials. The current payload is inert, but
whoever controls this name controls what those environments install next.

**Declared owner appears unreachable — both stated contact channels do not
exist:**

- Declared repository `https://github.com/poneglyph-research/idp-sdk` →
  **HTTP 404**; the `poneglyph-research` GitHub organization does not exist.
- Declared author email `security@poneglyph.research` → the domain
  `poneglyph.research` **has no DNS record** and cannot receive mail.

## Maintenance or replacement?

Replacement

## Source code repositories URLs

**Current project:** the declared repository does not exist —
`https://github.com/poneglyph-research/idp-sdk` returns HTTP 404, and the package
metadata gives no other source.

**Project I maintain, which uses this name:**
https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
— `idp_sdk` lives at `lib/idp_sdk` (see its `pyproject.toml`, where
`name = "idp-sdk"`).

If transferred, I do **not** plan to publish the real SDK to PyPI. I intend to
hold the name as a deliberately non-functional placeholder that raises on import
with a pointer to the real install path, matching what we already do for our
other names (`scripts/pypi-placeholders/` in the repo above).

## Contact and additional research

**Attempt to contact the owner.** PEP 541 asks that I contact the owner first.
Neither channel the package declares is functional:

- Email to `security@poneglyph.research` cannot be delivered — `dig
  poneglyph.research` returns no A or MX record.
- No issue can be opened on the declared repository — the GitHub org and the
  declared repo URL both return 404.
- <`<Describe any additional attempt you made and its result — or state that no
  other channel exists>`>

**Additional research.**

- Verified this is **not** mass squatting: of the 11 `idp-*` packages currently
  on PyPI, only `idp-sdk` and `idp-common` carry this uploader's fingerprint
  (checked against the full simple index).
- Release history: a single release, 2026-01-26T11:36:34Z, no subsequent
  activity. `idp-common` was uploaded by the same author roughly nine hours
  later the same day.
- Artifact digests (sdist / wheel SHA256):
  `19f62c69ea014c4877a775005776db0e6ef7d9b3023c277d70afcaaffb238593` /
  `626feb796862404b59acb8302467b368a18c8475c783e16140920afdf643a336`
- We have already shipped defenses independent of this request: single-invocation
  installs of all first-party packages, a PEP 610 `direct_url.json` check that
  fails our builds if a first-party package came from an index, and local-path
  installation docs throughout. This request is to remove the hazard at its
  source.

**If removal is chosen over transfer**, note that a deleted PyPI name becomes
registrable again by anyone, reopening the same hazard; I would register it
immediately as a placeholder.

[repo]: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
