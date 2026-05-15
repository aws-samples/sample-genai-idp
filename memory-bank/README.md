# Memory Bank

This folder is the **Cline Memory Bank** referenced by
[`.clinerules`](../.clinerules) at the repo root. Cline is an AI
coding assistant whose context resets between sessions, so these files
are its only persistent record of project-level knowledge.

The folder is committed to the repo so that:

- Every teammate (and every Cline session) starts from the same
  project context on a fresh clone.
- Structural knowledge (architecture, conventions, tech choices) is
  versioned alongside the code that embodies it.
- Onboarding docs and AI onboarding docs stay in lockstep.

## Files

| File | Purpose | Tracked in git? |
|------|---------|-----------------|
| `projectbrief.md`  | Foundation doc — identity, goals, scope | ✅ yes |
| `productContext.md` | Why the project exists, personas, UX principles | ✅ yes |
| `systemPatterns.md` | Architecture, repo layout, key technical patterns | ✅ yes |
| `techContext.md`    | Runtimes, AWS services, dev setup, constraints | ✅ yes |
| `progress.md`       | What's released, what's in flight, known issues | ✅ yes |
| `activeContext.md`  | Current session's working focus / uncommitted diffs | ❌ gitignored |
| `README.md` (this file) | Explains the folder | ✅ yes |

`activeContext.md` is deliberately ignored (see
[`.gitignore`](../.gitignore)) because it captures per-session,
in-flight work — diffs not yet committed, current hypothesis, next
steps for *this* working branch. Committing it would create merge
noise and leak WIP notes across branches.

## When to update these files

From the hierarchy defined in `.clinerules`:

```
projectbrief.md ──┐
productContext.md ├──▶ activeContext.md ──▶ progress.md
systemPatterns.md │
techContext.md ───┘
```

- **projectbrief.md / productContext.md** — rarely; only when the
  project's identity, user personas, or scope changes.
- **systemPatterns.md** — when the architecture, repo layout, or a
  recurring implementation pattern shifts.
- **techContext.md** — when runtimes, AWS services in play, or
  dev-environment setup changes.
- **progress.md** — after every significant release or when a major
  feature ships / is cut.
- **activeContext.md** — continuously, by Cline, as it works. Not
  committed.

A human can also trigger an update by telling Cline
**"update memory bank"** — per `.clinerules`, Cline will then review
all files and refresh them based on the current repo state.

## Relationship to other AI context in this repo

- [`CLAUDE.md`](../CLAUDE.md) — equivalent project-overview pointer
  for Claude Code (claude.ai/code).
- [`.clinerules`](../.clinerules) — behavioural rules for Cline
  (memory-bank protocol, QA review gate, mermaid preference, etc.).
- [`.cline/skills/`](../.cline/skills/) — domain-specific skill files
  (backend, frontend, infra, extraction, testing, docs, review, pr-review).
  These are *committed conventions*; the memory bank is *committed
  context*.
- [`.claude/skills/`](../.claude/skills/) — equivalent skill files for
  Claude Code.
