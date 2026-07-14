# Prepare CHANGELOG — GenAI IDP Accelerator

Use this skill to review and clean up the **`## [Unreleased]`** section of
`CHANGELOG.md` before a release, so it reads as a crisp, user-facing summary of
what actually changed **since the last published release** — not a running log
of the dev cycle.

## Goal

Turn the raw, accreted `[Unreleased]` section into a release-ready changelog with:

1. **Exactly three subsections, in this order: `### Added`, `### Changed`, `### Fixed`.**
   (Fold any `### Removed` content into `### Changed` — a removal is a
   user-facing change. Do not create other subsections.)
2. Entries that describe only the **net change since the last release** — the
   thing a user upgrading from the last published version will experience.
3. **Compact, clear entries** — a bold lead phrase plus a few sentences at most,
   with a link to the relevant doc and/or the PR.

## The core rule: net-since-release, not intra-cycle churn

The `[Unreleased]` section accumulates entries across the whole dev cycle
(many `dev`/`rc` builds). Much of that churn **cancels out** and must NOT appear
in the released changelog:

- **Drop fixes for bugs that were introduced by other Unreleased work.** If a
  feature added this cycle later needed a fix this cycle, the user upgrading from
  the last release never saw the bug — so the fix is invisible to them. Fold the
  fix silently into the feature's entry (or drop it) rather than listing it.
  - *Example:* an entry like "X no longer gets stuck in PENDING after the
    AppSync→REST migration" is pointless when the AppSync→REST migration is
    itself still Unreleased — the user never had the old AppSync path. Remove it.
- **Collapse a feature that was added then reworked** into a single entry
  describing the final shipped behavior. The intermediate states never shipped.
- **Merge duplicate/overlapping entries** about the same feature into one.
- **Keep** anything that is a genuine delta vs. the last released version —
  including fixes to bugs that existed **in that last release** (those are real,
  user-visible fixes).

When unsure whether a bug pre-dates the last release, check with git:
`git log <last-tag>..HEAD -- <path>` and `git log -S"<symbol>" <last-tag>..HEAD`.
If the buggy code was introduced after the last tag, the fix is intra-cycle → drop/fold.

## Procedure

1. **Find the release baseline.** The last published version:
   ```bash
   git describe --tags --abbrev=0        # e.g. v0.5.16
   ```
   Cross-check against the second `## [x.y.z]` heading in `CHANGELOG.md` (the one
   below `[Unreleased]`). That heading's version is the baseline; everything in
   `[Unreleased]` should be a change relative to it.

2. **Inventory what really shipped since the baseline** (to catch omissions and
   to date-check "intra-cycle" claims):
   ```bash
   git log --oneline <last-tag>..HEAD
   ```
   Read the current `[Unreleased]` body in full.

3. **Classify every existing entry** as: keep-as-is / rewrite-shorter /
   merge-with-another / **drop (intra-cycle churn)**. Apply the net-since-release
   rule above. Move each survivor into the right one of the three subsections.

4. **Rewrite survivors to be compact.** Each entry:
   - Starts with a **bold lead phrase** naming the change (feature, behavior, or
     bug), matching the existing house style (`- **Lead phrase.** ...`).
   - Is **a few clear sentences** — what changed and, briefly, why it matters or
     what a user must do. Cut deep implementation detail, internal symbol names,
     resolver/Lambda plumbing, and benchmark minutiae unless they are the point.
   - Links to the relevant **doc** (`[guide](docs/...md)` / module README)
     **and/or the PR** (`(#NNN)`) where one exists. Prefer a doc link for
     features; a PR link is fine for pure fixes.
   - Keeps any **migration / action-required / breaking** note — that is exactly
     what upgraders need. Preserve `⚠️` markers and "Request … access" notices.

5. **Order within each subsection** most-significant first (breaking changes and
   headline features at the top; minor items last).

6. **Keep the intro paragraph** under `## [Unreleased]` if present, but make sure
   it still matches the pruned content.

7. **Do not** add the release date or version number, and do not renumber the
   section — releasing (turning `[Unreleased]` into `## [x.y.z] - DATE` and adding
   the template URLs block) is a separate step the maintainer does at tag time.

## Style reference (match the existing file)

```markdown
### Added

- **Short bold lead phrase.** One to three sentences on what it does and why it
  matters. See the [Feature guide](docs/feature.md).

### Changed

- **What changed, stated as the new behavior.** Include a migration note if a
  user must act. (#123)

### Fixed

- **The user-visible symptom that is now fixed.** One sentence of cause if it
  aids understanding. (#124)
```

## Output

Present the proposed rewritten `[Unreleased]` section for review, and — unless
told otherwise — apply it to `CHANGELOG.md` with the Edit tool. Call out, in a
short list, every entry you **dropped as intra-cycle churn** and every set you
**merged**, so the maintainer can veto any judgment call. Do not touch any
released section below `[Unreleased]`.
