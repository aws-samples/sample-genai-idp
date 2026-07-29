# PyPI takedown / name-reclamation requests

Filing kit for reclaiming two first-party package names registered on public
PyPI by a third party: **`idp-common`** and **`idp-sdk`**.

Background and the defensive fixes already shipped:
[docs/dependency-confusion.md](../../docs/dependency-confusion.md).

## Status

| Name          | Action                  | Filed | Issue |
| ------------- | ----------------------- | ----- | ----- |
| `idp-common`  | PEP 541 invalid-project | ☐     |       |
| `idp-sdk`     | PEP 541 invalid-project | ☐     |       |

## Which process applies

**PEP 541 "invalid project" → name squatting.** [PEP 541][pep541] lists grounds
for removing a project, one of which is verbatim: *"name squatting (package has
no functionality or is empty)."* Both packages qualify — each contains a single
`main()` that prints a banner and nothing else.

Two processes we deliberately did **not** use:

- **Mass name-squatter report.** There is a dedicated template for a user who
  has registered many names. It does not fit: of the 11 `idp-*` packages on
  PyPI, only these two carry this uploader's fingerprint (verified against the
  full simple index). This is a targeted registration, not a bulk sweep.
- **Trademark / IP claim.** Those go to `legal@python.org` and are decided by
  PSF counsel, not the issue tracker. Only pursue this if AWS Legal wants to
  assert a mark; the squatting ground above is simpler and sufficient.

> ⚠️ **PEP 541 requires you to attempt contact with the owner first**, and the
> formal request is "meant as a last resort." Both listed contact channels are
> fabricated (see Evidence), so document the attempt and that it is
> impossible — do not skip this step silently. Moderators contact owners
> independently regardless.

## Before you file — three things only you can do

1. **Get the uploader's PyPI username.** Required by the template. The project
   pages sit behind a bot challenge, so this must be read from a browser: open
   <https://pypi.org/project/idp-common/> and
   <https://pypi.org/project/idp-sdk/> and note the **Maintainers** sidebar.
   Confirm whether both names share one account.
2. **Attempt owner contact** and record the result (see the template below).
3. **Confirm who files.** These requests are public and name AWS. Coordinate
   with AWS Security / the solution owner before filing — the request is
   effectively a public statement that an AWS solution was targeted.

Then file one issue per name at <https://github.com/pypi/support/issues/new/choose>
using **"Name retention related request (PEP 541)"**, pasting the matching
draft from this directory.

## Evidence (verified 2026-07-29)

| Fact | `idp-common` | `idp-sdk` |
| --- | --- | --- |
| Version | 0.1.0 | 0.1.0 |
| Uploaded | 2026-01-26T20:34:40Z | 2026-01-26T11:36:34Z |
| Releases | 1 (no updates since) | 1 (no updates since) |
| sdist SHA256 | `1aaebf3467937c1ba318c34d70c3f8a54ad989f8f79f0728b9618f842e9ac266` | `19f62c69ea014c4877a775005776db0e6ef7d9b3023c277d70afcaaffb238593` |
| wheel SHA256 | `987aa82ba9065f3ec2016005d6d3da625f363933533baf19e9f8a3afb807ff3b` | `626feb796862404b59acb8302467b368a18c8475c783e16140920afdf643a336` |
| Declared author | `Poneglyph Security Research <security@poneglyph.research>` | same |
| Declared repo | `github.com/poneglyph-research/idp_common` | `github.com/poneglyph-research/idp-sdk` |

Both contact channels are **non-existent**, which is the strongest single point
in the filing — it establishes an unreachable owner and undercuts the
"security research" framing:

- `github.com/poneglyph-research` → **HTTP 404** (org does not exist; both
  declared repo URLs also 404)
- `poneglyph.research` → **does not resolve in DNS** (no A record), so the
  declared author email cannot receive mail

### Package contents

Each sdist contains only `LICENSE`, `MANIFEST.in`, `PKG-INFO`, `README.md`,
`pyproject.toml`, `setup.cfg`, and `src/<pkg>/{__init__.py,main.py}`. The whole
of `main.py` prints a banner and returns 0. `__init__.py` sets `__version__` and
`__author__`. There are **no** declared dependencies, no `setup.py`, no
`cmdclass`, no build or install hooks, and no network calls.

**Inspect without installing** (never `pip install` these):

```bash
pip download --no-deps --no-binary :all: "idp-sdk==0.1.0" -d /tmp/sq
tar tzf /tmp/sq/idp_sdk-0.1.0.tar.gz
```

The payload being inert is worth stating plainly in the filing: we are not
claiming a live attack, we are claiming an empty package holding a name that
creates dependency-confusion risk for a widely deployed AWS solution. That is
precisely PEP 541's squatting ground, and overclaiming malware would weaken the
request.

## Why we have a legitimate interest

`idp_common` and `idp_sdk` are first-party components of the
[GenAI Intelligent Document Processing Accelerator][repo], an AWS
solution-library project. Both names appear as bare requirements inside that
codebase (`lib/idp_sdk` requires `idp_common`; `lib/idp_cli_pkg` requires
`idp-sdk`), so a public registration of either name is directly resolvable by
pip during a developer or CI install of the accelerator. We have reproduced pip
installing the squatted `idp-sdk` from PyPI into a clean environment.

Note for the filing: our own first use of these names predates the
registrations, and the accelerator repo is public — link it as the notability
and prior-use evidence.

## What we are asking for

**Removal or transfer, either is acceptable.** State this explicitly; it widens
the moderators' options:

1. **Preferred — transfer** both names to our PyPI account, so we can hold them
   as non-functional placeholders exactly as we already do for
   `idp-feature-sdk` and `idp-mcp-connector` (see
   `scripts/pypi-placeholders/`).
2. **Acceptable — removal**, if transfer is declined. But note that a *deleted*
   name on PyPI becomes registrable again by anyone, which reopens the hole. If
   removal is the outcome, register the freed names immediately.

## If this is declined

The defensive fixes already shipped do not depend on the outcome: the
single-invocation install, the `scripts/check_first_party_deps.py` tripwire, CI
enforcement, and path-based install docs all hold regardless. A decline costs us
nothing already gained — it only means the names stay hostile, so the tripwire
stays load-bearing. The stronger long-term answer is renaming our distributions
into a namespace we can hold outright; that decision is deferred.

[pep541]: https://peps.python.org/pep-0541/
[repo]: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
