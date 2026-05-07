# PR / MR Review Skill

Use this skill when the user asks to **review a pull request or merge request** —
typically with a prompt like:

> `review <MR/PR URL>`  (target develop branch)
>
> Is this a good PR?
> Safe? No regressions?
> Good UX?
> No security issues?
> Well documented?
> Safe to merge?

This skill is for reviewing **someone else's** PR/MR at a URL. It is distinct
from `.cline/skills/review.md`, which is the pre-commit self-review checklist
I run on my own changes before `attempt_completion`.

## Ground Rules

1. **Never push, merge, approve, or comment on the PR** from this skill unless
   the user explicitly asks. Produce a written review for the user to act on.
2. **Do not modify files** in the working copy as part of the review. Reviewing
   is read-only.
3. Reference specific **files and line numbers** whenever citing an issue.
4. If the PR targets a branch **other than `develop`**, call this out as the
   first finding. The expected target for this repo is `develop`.
5. Keep findings factual and specific — quote the diff where useful.

## Step 1 — Detect the URL and fetch PR metadata

Identify the host from the URL:

### GitHub PR (`github.com/<owner>/<repo>/pull/<NN>`)
Use the `github` MCP server tools (no shell needed):
- `pull_request_read` with `method=get` → title, body, author, base/head refs, mergeable state
- `pull_request_read` with `method=get_status` → CI / checks status on the head commit
- `pull_request_read` with `method=get_files` → list of changed files (paginate if > 100)
- `pull_request_read` with `method=get_diff` → unified diff
- `pull_request_read` with `method=get_reviews` → existing reviews
- `pull_request_read` with `method=get_comments` and `method=get_review_comments` → discussion
- `get_file_contents` on specific paths at `ref=refs/pull/<NN>/head` to read full files when the diff is not enough context

### GitLab MR (`gitlab.aws.dev/<group>/<project>/-/merge_requests/<NN>`)
Use the `glab` CLI (or `curl` to the GitLab API) via `execute_command`:
```bash
glab mr view <NN> --repo <group>/<project>
glab mr diff <NN> --repo <group>/<project>
glab mr note list <NN> --repo <group>/<project>
glab ci status --repo <group>/<project>   # or glab mr status
```
If `glab` is not available, fall back to `curl` against
`https://gitlab.aws.dev/api/v4/projects/<urlencoded-path>/merge_requests/<NN>`
with the token from `~/.config/glab-cli/config.yml` or `GITLAB_TOKEN`.

### Collect at minimum
- PR/MR title, description, author
- Source branch → target branch (confirm target is `develop`)
- CI / pipeline status
- List of changed files with insertions/deletions
- The full diff
- Existing reviews and comments
- Linked issues, if any

For larger PRs (> ~500 lines changed or touching unfamiliar modules), read key
changed files in full — not just the diff — to understand surrounding context.

## Step 2 — Evaluate the six review questions

Work through each question. Reuse the project's coding-standards knowledge from
the other skill files (`backend.md`, `frontend.md`, `infra.md`, `docs.md`,
`testing.md`, `review.md`).

### 1. Is this a good PR?
- Scope is focused (single feature / fix / refactor; not a grab-bag)
- Title is descriptive and follows convention (e.g. `feat:`, `fix:`, `docs:`)
- Description explains **what** and **why**, and links to an issue when applicable
- Targets `develop` (flag otherwise)
- CI is green (or failures are understood)
- Size is reviewable — very large PRs should be called out

### 2. Safe? No regressions?
- New/changed logic has **unit tests**; assertions are meaningful
- Existing tests are not deleted or weakened without justification
- Backward compatibility maintained for shared interfaces:
  - `Document` model and its serialization
  - Config schemas under `config_library/`
  - GraphQL schema and generated types in `src/ui/src/graphql/generated/`
  - Lambda handler event/response contracts
- No obvious race conditions, unbounded loops, or missing pagination
- Error handling uses explicit exceptions (no bare `except:`), with `exc_info=True`
- No removal of observability (X-Ray `patch_all`, structured logging)

### 3. Good UX?
- **Frontend** (`src/ui/`):
  - Cloudscape Design System components (not MUI / AntD / Bootstrap)
  - Loading, empty, and error states handled
  - Arrow-function components; hooks in kebab-case files
  - `ConsoleLogger` used, no stray `console.log`
  - Accessibility: labels on inputs, keyboard nav, focus management
  - `DOMPurify` used for any `dangerouslySetInnerHTML`
  - Responsive behavior reasonable
- **Backend / API**:
  - Actionable error messages; failures surface to the UI (e.g. status on `Document`)
  - Progress / status updated at meaningful checkpoints
  - Sensible defaults; new required config has migration guidance

### 4. No security issues?
- No hardcoded credentials, API keys, or tokens
- No full JWTs logged in plaintext (Talos finding #10)
- No hardcoded `arn:aws:` partitions — must use `${AWS::Partition}` (run
  `make check-arn-partitions` mentally)
- No hardcoded `amazonaws.com` — must use `${AWS::URLSuffix}`
- IAM policies scoped — no `Resource: "*"` or wildcard S3 ARNs without
  written justification
- `PermissionsBoundary` conditional present on new IAM roles
- New Lambdas have a dedicated `AWS::Logs::LogGroup` with KMS encryption
- Input validation on new API surfaces; DOMPurify on HTML render paths
- New Python/npm dependencies are pinned and from trusted sources
- `cfn-nag` / `checkov` suppressions include `reason:` metadata
- No new public S3 buckets, public SNS topics, or open security groups

### 5. Well documented?
- User-facing changes update `CHANGELOG.md`
- Feature docs added/updated under `docs/` with:
  - YAML frontmatter (`title:` required)
  - License header after frontmatter
- Cross-references to related docs added where helpful
- Public functions/classes have docstrings
- Complex logic has inline comments explaining *why*
- If GraphQL schema changed, `make codegen` has been run and generated files
  are included in the PR (or a note explains why not)

### 6. Safe to merge?
- Targets `develop` ✅
- CI / pipeline green ✅
- No unresolved review comments on the latest commit
- No merge conflicts
- `VERSION` / version bump done if required by change scope
- No leftover `TODO` / `FIXME` / debug prints / commented-out code blocks
- Migration notes provided for any breaking change

## Step 3 — Produce the review

Output the review in this exact structure so the user can paste it or act on it:

```markdown
## PR/MR Review: <title> (#<NN>)
**Repo:** <owner/repo>
**Author:** @<author>
**Source → Target:** `<source>` → `<target>`   <!-- ⚠️ if not develop -->
**CI status:** ✅ passing | ❌ failing | ⏳ pending
**Size:** +<insertions> / -<deletions> across <N> files

### Summary
<1–3 sentence plain-English description of what this PR does.>

### Verdict

| Question | Verdict | Notes |
|---|---|---|
| Good PR? | ✅ / ⚠️ / ❌ | … |
| Safe / no regressions? | … | … |
| Good UX? | … / N/A | … |
| No security issues? | … | … |
| Well documented? | … | … |
| **Safe to merge?** | ✅ Approve / ⚠️ Request changes / ❌ Block | … |

### Findings
- 🔴 **Blocking** — <file>:<line> — description + suggested fix
- 🟡 **Should fix** — <file>:<line> — description
- 🟢 **Nice to have** — <file>:<line> — description

### Recommendation
**Approve** / **Request changes** / **Comment**

<one-paragraph rationale>
```

Legend:
- ✅ pass / 🟢 nit — non-blocking
- ⚠️ / 🟡 — should fix before merge
- ❌ / 🔴 — blocking; must fix before merge

## Step 4 — After delivering the review

- Do **not** call `attempt_completion` with a comment posted to the PR unless
  the user explicitly said "post this as a review comment" or similar.
- If the user asks follow-up questions, re-use the already-fetched diff /
  metadata rather than re-fetching.
- If the user asks you to implement the requested changes, switch context:
  treat it as a new implementation task following the relevant skill files.

## Quick Reference — Common Red Flags

Flag these immediately when seen in any diff:

- `arn:aws:` literal in a CloudFormation / SAM template
- `amazonaws.com` literal (should be `${AWS::URLSuffix}`)
- `Resource: "*"` in a new IAM policy statement
- `Principal: "*"` in a new resource policy
- `console.log(` in production UI code
- `print(` used for logging in Lambda code
- New Lambda without dedicated LogGroup + KMS
- New IAM role without a `PermissionsBoundary` conditional
- Secrets / access keys / JWTs in code, logs, or tests
- Deleted tests without a replacement
- Schema change in `src/ui/src/graphql/schema.graphql` without regenerated
  files under `src/ui/src/graphql/generated/`
- `Document` model field removed or renamed without a migration path
- Wildcards in S3 bucket/object ARNs without `reason:` metadata
