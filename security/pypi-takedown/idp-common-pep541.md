# PEP 541 request — `idp-common`

File at <https://github.com/pypi/support/issues/new/choose> → **"Name retention
related request (PEP 541)"**.

**Issue title:**

```
PEP 541 Request: idp-common
```

Fill `<YOUR_PYPI_USERNAME>` and the two `<...>` contact-attempt placeholders
before submitting. Everything else is verified — see `README.md` in this
directory.

---

## Project to be claimed

`idp-common`: https://pypi.org/project/idp-common

## Your PyPI username

`<YOUR_PYPI_USERNAME>`: https://pypi.org/user/<YOUR_PYPI_USERNAME>

## Reasons for the request

I am requesting this name under PEP 541's **invalid project** criterion for
*"name squatting (package has no functionality or is empty)"*, and would accept
either transfer or removal.

**The package is empty.** `idp-common` 0.1.0 (uploaded 2026-01-26, the only
release) contains no functionality. Its entire runtime is a `main()` that prints
a banner:

```
idp_common
Created by Poneglyph for security research
...
This is a security research package.
```

The sdist contains only packaging boilerplate plus
`src/idp_common/{__init__.py,main.py}`. There are no declared dependencies, no
`setup.py`, no `cmdclass`, and no build or install hooks. `__init__.py` sets
`__version__` and `__author__` only.

To be fair and precise: **I am not reporting malware.** I inspected both
distributions statically (via `pip download`, without installing) and they
perform no network access and execute nothing at install time. My request rests
on the name being held by an empty package, not on observed harm.

**The name is a first-party component name of a public AWS project, and the
registration creates a live dependency-confusion hazard.** `idp_common` is a
core library of the [GenAI Intelligent Document Processing Accelerator][repo],
published by AWS in the AWS Solutions Library. Our use of the name predates this
registration, and the repository is public.

Critically, the name appears as a **bare requirement** inside that codebase —
`lib/idp_sdk` declares a dependency on `idp_common`, which is expected to
resolve from the local checkout. When it is not already installed, pip resolves
it from public PyPI instead and installs this package. I have reproduced this
from a clean virtual environment:

```
$ pip install ./lib/idp_sdk
Collecting idp_common (from idp-sdk==0.6.2)
  ...
Would install idp-sdk-0.6.2 idp_common-0.1.0
```

The environments affected are developer and CI environments holding AWS
deployment credentials. The current payload is inert, but whoever controls this
name controls what those environments install next.

**Declared owner appears unreachable — both stated contact channels do not
exist:**

- Declared repository `https://github.com/poneglyph-research/idp_common` →
  **HTTP 404**; the `poneglyph-research` GitHub organization does not exist.
- Declared author email `security@poneglyph.research` → the domain
  `poneglyph.research` **has no DNS record**, so it cannot receive mail.

## Maintenance or replacement?

Replacement

## Source code repositories URLs

**Current project:** the declared repository does not exist —
`https://github.com/poneglyph-research/idp_common` returns HTTP 404, and no
other source is given in the package metadata.

**Project I maintain, which uses this name:**
https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
— `idp_common` lives at `lib/idp_common_pkg` (see its `pyproject.toml`, where
`name = "idp_common"`).

Note on intent: if this name is transferred, I do **not** plan to publish the
real library to PyPI. I intend to hold the name as a deliberately
non-functional placeholder that raises on import with a pointer to the real
install path — the same approach we already use for our other names (see
`scripts/pypi-placeholders/` in the repo above). The goal is purely to prevent
the name from being used against our users.

## Contact and additional research

**Attempt to contact the owner.** PEP 541 asks that I contact the owner first. I
attempted this and it is not possible via either channel the package declares:

- Email to `security@poneglyph.research` cannot be delivered — `dig
  poneglyph.research` returns no A or MX record.
- No issue can be opened on the declared repository — the GitHub org and both
  declared repo URLs return 404.
- <`<Describe any additional attempt you made, e.g. a message via the PyPI
  maintainer profile, and its result — or state that no other channel exists>`>

**Additional research.**

- Verified this is **not** mass squatting: of the 11 `idp-*` packages currently
  on PyPI, only `idp-common` and `idp-sdk` carry this uploader's fingerprint
  (checked against the full simple index). I am filing a separate, parallel
  request for `idp-sdk`.
- Release history: a single release, 2026-01-26, with no subsequent activity.
- Artifact digests (sdist / wheel SHA256):
  `1aaebf3467937c1ba318c34d70c3f8a54ad989f8f79f0728b9618f842e9ac266` /
  `987aa82ba9065f3ec2016005d6d3da625f363933533baf19e9f8a3afb807ff3b`
- On our side, we have already shipped defenses that do not depend on the
  outcome of this request: all first-party packages install in a single pip
  invocation, a PEP 610 `direct_url.json` check fails our builds if any
  first-party package was resolved from an index, and all installation
  documentation now uses local paths. I am filing this to remove the hazard at
  its source, not because we are currently exposed.

**If removal is chosen over transfer**, please note that a deleted PyPI name
becomes registrable again by anyone, which would reopen the same hazard; I would
register it immediately as a placeholder.

[repo]: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
