# Shared module — `variants.py`

`variants.py` is the ConfBench noise-variant catalog: exact per-variant file
counts and byte sizes, the named size tiers, and the selection→test-set-id
mapping. Three consumers need the identical numbers:

| Consumer | Uses it for |
|---|---|
| `feature-api/` | `GET /variants` (what the picker renders), request validation |
| `ingest/` (planner) | filtering the parquet to the selected variants, expected totals |
| `feature-ui/` | rendering sizes — fetched from the API at runtime, never hardcoded |

It ships as a **Lambda layer** (`SharedLayer` in `template.yaml`) rather than
being copied into each function's `CodeUri`. A duplicated copy is the failure
mode worth designing against here: if the API's table and the planner's table
drift, the cost estimate an admin approves stops matching the bytes that
actually land — the exact problem this extension exists to solve.

The module lives at `shared/python/variants.py`. Lambda adds a layer's `python/`
directory to `sys.path`, so both functions `import variants` directly.

The layer resource deliberately has **no `BuildMethod: python3.12` metadata**:
that build method runs pip against a `requirements.txt` and packages only
installed dependencies, which would silently drop this hand-authored module.
Without it SAM copies `shared/` verbatim, which is what we want.

## Keeping it honest

`verify_against_hub()` re-derives the whole table from the live HuggingFace tree
API and diffs it against the committed constants. `tests/test_variants.py` calls
it when `CONFBENCH_NETWORK_TESTS=1`, so an upstream re-publish surfaces as a
test failure instead of a wrong number in the UI. The figures were measured
2026-08-05 against `amazon/ConfBench` @ `main`.
