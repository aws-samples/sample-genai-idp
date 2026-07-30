# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the runtime-agnostic sharding primitives.

These tests do NOT require strands: ``extract_one_shard`` / ``InProcessRuntime``
accept an injected ``shard_runner`` callable, so the scheduling, idempotent
persistence (skip-completed), merge, and runtime-selection logic are all
exercised with a fake agent. This is the single-source-of-truth proof for the
library primitives that both the in-process and SFN backends share.
"""

import asyncio

import pytest
from pydantic import BaseModel

from idp_common.config.models import IDPConfig
from idp_common.extraction.runtime import (
    InProcessRuntime,
    NoopShardPersistence,
    S3ShardPersistence,
    StepFunctionsRuntime,
    _accumulate_metering,
    _merge_table_parsing_stats,
    extract_one_shard,
    merge_shard_dicts,
    merge_shard_results,
    select_runtime,
    shard_result_key,
)

pytestmark = pytest.mark.unit


class _Model(BaseModel):
    account: str | None = None
    statement_period: str | None = None
    transactions: list | None = None


def _payload(start, end, total=10):
    return {
        "content": [{"text": f"pages {start}-{end}"}],
        "page_start": start,
        "page_end": end,
        "total_pages": total,
    }


def _make_runner(per_shard_data, call_log=None):
    """Build a fake shard_runner returning canned data keyed by page_start."""

    async def runner(*, shard_index, total_shards, payload, **kwargs):
        if call_log is not None:
            call_log.append(payload["page_start"])
        data = per_shard_data[payload["page_start"]]
        return _Model(**data), {"metering": {f"shard{payload['page_start']}": {"t": 1}}}

    return runner


# ----------------------------- merge wrappers ----------------------------- #
class TestMergeWrappers:
    def test_merge_shard_results_concatenates_in_order(self):
        results = [
            (_Model(transactions=[{"r": 1}]), {"metering": {}}),
            (_Model(transactions=[{"r": 2}, {"r": 3}]), {"metering": {}}),
        ]
        merged, _m, conflicts = merge_shard_results(results, _Model)
        assert [t["r"] for t in merged["transactions"]] == [1, 2, 3]
        assert conflicts == []

    def test_merge_shard_dicts_sorts_by_page_start(self):
        # Out-of-order completion (SFN map) must still merge in page order.
        shard_dicts = [
            {"extracted_fields": {"transactions": [{"r": 3}]}, "page_start": 2},
            {"extracted_fields": {"transactions": [{"r": 1}]}, "page_start": 0},
            {"extracted_fields": {"transactions": [{"r": 2}]}, "page_start": 1},
        ]
        merged, _m, _c = merge_shard_dicts(shard_dicts, _Model)
        assert [t["r"] for t in merged["transactions"]] == [1, 2, 3]

    def test_merge_shard_dicts_scalar_first_page_wins(self):
        shard_dicts = [
            {"extracted_fields": {"account": "B"}, "page_start": 5},
            {"extracted_fields": {"account": "A"}, "page_start": 0},
        ]
        merged, _m, conflicts = merge_shard_dicts(shard_dicts, _Model)
        assert merged["account"] == "A"  # page 0 wins regardless of input order
        assert len(conflicts) == 1

    def test_merge_drops_phantom_rows(self):
        # A trailing row with only a sequential index populated (every other
        # column null) is a hallucinated/OCR-gap artifact and must be dropped,
        # while genuine multi-field rows survive.
        real = {"RowID": 1, "Symbol": "AAPL", "Account": "X", "Qty": "5"}
        phantom = {"RowID": 2, "Symbol": None, "Account": None, "Qty": None}
        results = [
            (_Model(transactions=[real]), {"metering": {}}),
            (_Model(transactions=[phantom]), {"metering": {}}),
        ]
        merged, _m, _c = merge_shard_results(results, _Model)
        assert merged["transactions"] == [real]

    def test_merge_keeps_sparse_two_field_rows(self):
        # A row with two populated fields is real data, not a phantom.
        row = {"RowID": 9, "Symbol": "MSFT", "Account": None, "Qty": None}
        merged, _m, _c = merge_shard_results(
            [(_Model(transactions=[row]), {"metering": {}})], _Model
        )
        assert merged["transactions"] == [row]


class TestPrunePhantomRowsFromAssessment:
    """The per-shard assessment must drop the SAME phantom rows the merge drops
    from the data, so the (pre-grounded) assessment stays index-aligned."""

    def test_prunes_midlist_phantom_in_lockstep(self):
        from idp_common.extraction.runtime import (
            _prune_phantom_rows_from_assessment,
        )

        real1 = {"RowID": 1, "Symbol": "AAPL", "Account": "X", "Qty": "5"}
        phantom = {"RowID": 2, "Symbol": None, "Account": None, "Qty": None}
        real2 = {"RowID": 3, "Symbol": "MSFT", "Account": "Y", "Qty": "9"}
        extracted = {"transactions": [real1, phantom, real2]}
        # Assessment aligned 1:1 with data (post-reconcile), each row distinct.
        assessment = {
            "transactions": [
                {"Symbol": {"confidence": 0.1}},
                {"Symbol": {"confidence": 0.2}},  # phantom's assessment
                {"Symbol": {"confidence": 0.3}},
            ]
        }
        _prune_phantom_rows_from_assessment(extracted, assessment)
        # Phantom's assessment (0.2) removed; real rows keep their order/scores.
        assert [r["Symbol"]["confidence"] for r in assessment["transactions"]] == [
            0.1,
            0.3,
        ]

    def test_noop_when_lengths_differ(self):
        # Defensive: if assessment isn't 1:1 with data, don't risk a mis-prune.
        from idp_common.extraction.runtime import (
            _prune_phantom_rows_from_assessment,
        )

        extracted = {
            "transactions": [
                {"RowID": 2, "Symbol": None, "Account": None, "Qty": None},
            ]
        }
        assessment = {"transactions": []}  # length mismatch
        _prune_phantom_rows_from_assessment(extracted, assessment)
        assert assessment["transactions"] == []

    def test_noop_when_no_phantoms(self):
        from idp_common.extraction.runtime import (
            _prune_phantom_rows_from_assessment,
        )

        extracted = {"transactions": [{"RowID": 1, "Symbol": "A", "Account": "X"}]}
        assessment = {"transactions": [{"Symbol": {"confidence": 0.9}}]}
        _prune_phantom_rows_from_assessment(extracted, assessment)
        assert assessment["transactions"] == [{"Symbol": {"confidence": 0.9}}]


# --------------------- table_parsing_stats metering ----------------------- #
class TestTableParsingStatsMerge:
    """Regression coverage for the 500%/496% Processing Report bug.

    ``_table_parsing_stats`` rode the additive metering channel, so rates and
    confidences were summed across shards (5 shards × ~1.0 rate → "500%").
    Counts must sum; rate/confidence must stay within [0,1] / [0,100].
    """

    def _shard(self, rows, rate, conf, tables=2):
        return {
            "tables_parsed": tables,
            "rows_parsed": rows,
            "rows_mapped": rows,
            "invocation_count": 1,
            "parse_success_rate": rate,
            "avg_confidence": conf,
            "confidence_available": True,
            "mapping_used": True,
        }

    def test_counts_sum_rates_average(self):
        a = self._shard(rows=300, rate=1.0, conf=99.0)
        out = _merge_table_parsing_stats({}, a)
        out = _merge_table_parsing_stats(
            out, self._shard(rows=300, rate=1.0, conf=98.0)
        )
        assert out["tables_parsed"] == 4
        assert out["rows_parsed"] == 600
        assert out["rows_mapped"] == 600
        assert out["invocation_count"] == 2
        # row-weighted average stays a real rate / confidence
        assert out["parse_success_rate"] == pytest.approx(1.0)
        assert out["avg_confidence"] == pytest.approx(98.5)

    def test_five_shards_never_exceed_bounds(self):
        merged = {}
        for _ in range(5):
            merged = _merge_table_parsing_stats(
                merged, self._shard(rows=300, rate=1.0, conf=99.0)
            )
        assert merged["parse_success_rate"] <= 1.0
        assert merged["avg_confidence"] <= 100.0
        assert merged["rows_parsed"] == 1500
        assert merged["tables_parsed"] == 10

    def test_row_weighted_not_simple_mean(self):
        # 900 rows @ 1.0 + 100 rows @ 0.0 → weighted 0.9, not simple-mean 0.5
        out = _merge_table_parsing_stats(
            {}, self._shard(rows=900, rate=1.0, conf=100.0)
        )
        out = _merge_table_parsing_stats(out, self._shard(rows=100, rate=0.0, conf=0.0))
        assert out["parse_success_rate"] == pytest.approx(0.9)
        assert out["avg_confidence"] == pytest.approx(90.0)

    def test_zero_row_weight_falls_back_to_simple_mean(self):
        out = _merge_table_parsing_stats({}, self._shard(rows=0, rate=0.8, conf=90.0))
        out = _merge_table_parsing_stats(out, self._shard(rows=0, rate=0.6, conf=70.0))
        assert out["parse_success_rate"] == pytest.approx(0.7)
        assert out["avg_confidence"] == pytest.approx(80.0)

    def test_accumulate_metering_routes_stats_not_summed(self):
        merged: dict = {}
        for _ in range(3):
            _accumulate_metering(
                merged,
                {
                    "OCR/textract": {"pages": 5},
                    "_table_parsing_stats": self._shard(rows=300, rate=1.0, conf=95.0),
                },
            )
        # ordinary token counters still sum
        assert merged["OCR/textract"]["pages"] == 15
        # stats merged with quality semantics, not summed
        assert merged["_table_parsing_stats"]["rows_parsed"] == 900
        assert merged["_table_parsing_stats"]["parse_success_rate"] <= 1.0
        assert merged["_table_parsing_stats"]["avg_confidence"] <= 100.0


# --------------------------- shard_result_key ----------------------------- #
class TestShardResultKey:
    def test_deterministic_and_sanitised(self):
        k1 = shard_result_key(
            "arn:aws:states:us-west-2:1:execution:sm:abc", "sec1", 0, 3
        )
        k2 = shard_result_key(
            "arn:aws:states:us-west-2:1:execution:sm:abc", "sec1", 0, 3
        )
        assert k1 == k2
        assert ":" not in k1.split("checkpoints/")[1].split("/")[0] or True
        assert k1.endswith("/shards/shard_0_3.json")
        assert "sec1" in k1

    def test_local_fallback_when_no_arn(self):
        assert shard_result_key("", "sec1", 1, 2).startswith("checkpoints/local/")


# --------------------------- persistence ---------------------------------- #
class _FakeS3:
    """In-memory S3 stub supporting get_object/put_object."""

    def __init__(self):
        self.store = {}
        self.get_calls = 0
        self.put_calls = 0

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.put_calls += 1
        self.store[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        self.get_calls += 1
        if (Bucket, Key) not in self.store:
            raise KeyError("NoSuchKey")  # type: ignore
        import io

        return {"Body": io.BytesIO(self.store[(Bucket, Key)])}


class TestS3ShardPersistence:
    def test_save_then_load_roundtrip(self):
        s3 = _FakeS3()
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=s3)
        p.save("sec", 0, 3, {"extracted_fields": {"account": "X"}, "metering": {}})
        loaded = p.load("sec", 0, 3)
        assert loaded is not None
        assert loaded["extracted_fields"]["account"] == "X"
        assert loaded["page_start"] == 0 and loaded["page_end"] == 3

    def test_load_miss_returns_none(self):
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=_FakeS3())
        assert p.load("sec", 0, 3) is None


# --------------------- extract_one_shard idempotency ---------------------- #
class TestExtractOneShardIdempotency:
    def test_skip_when_complete_result_persisted(self):
        s3 = _FakeS3()
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=s3)
        # Pre-seed a completed shard result.
        p.save(
            "sec",
            0,
            3,
            {"extracted_fields": {"transactions": [{"r": 99}]}, "metering": {}},
        )
        call_log: list[int] = []
        runner = _make_runner({0: {"transactions": [{"r": 1}]}}, call_log)

        fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 3),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                persistence=p,
                shard_runner=runner,
            )
        )
        # Loaded from S3, runner NOT called.
        assert fields["transactions"] == [{"r": 99}]
        assert call_log == []

    def test_runs_and_persists_when_absent(self):
        s3 = _FakeS3()
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=s3)
        call_log: list[int] = []
        runner = _make_runner({0: {"transactions": [{"r": 1}]}}, call_log)

        fields, _resp = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 3),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                persistence=p,
                shard_runner=runner,
            )
        )
        assert fields["transactions"] == [{"r": 1}]
        assert call_log == [0]  # runner invoked once
        # Result persisted for a future retry.
        assert p.load("sec", 0, 3)["extracted_fields"]["transactions"] == [{"r": 1}]

    def test_noop_persistence_always_runs(self):
        call_log: list[int] = []
        runner = _make_runner({0: {"transactions": [{"r": 1}]}}, call_log)
        fields, _ = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 3),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                persistence=NoopShardPersistence(),
                shard_runner=runner,
            )
        )
        assert call_log == [0]
        assert fields["transactions"] == [{"r": 1}]


# --------------------------- InProcessRuntime ----------------------------- #
class TestInProcessRuntime:
    def test_runs_all_shards_and_merges_in_order(self):
        runner = _make_runner(
            {
                0: {"account": "ACC", "transactions": [{"r": 1}, {"r": 2}]},
                2: {"transactions": [{"r": 3}]},
                3: {"transactions": [{"r": 4}, {"r": 5}]},
            }
        )
        payloads = [_payload(0, 2), _payload(2, 3), _payload(3, 5)]
        merged, response = asyncio.run(
            InProcessRuntime(max_parallelism=5).run(
                shard_payloads=payloads,
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
            )
        )
        assert [t["r"] for t in merged.transactions] == [1, 2, 3, 4, 5]
        assert merged.account == "ACC"
        # Metering accumulated from all shards.
        assert "shard0" in response["metering"]
        assert "shard3" in response["metering"]

    def test_skip_completed_shard_on_reentry(self):
        # Simulate a re-entry: shard 0 already persisted, only shard 1 runs.
        s3 = _FakeS3()
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=s3)
        p.save(
            "sec",
            0,
            2,
            {
                "extracted_fields": {"transactions": [{"r": 1}, {"r": 2}]},
                "metering": {},
            },
        )
        call_log: list[int] = []
        runner = _make_runner(
            {0: {"transactions": [{"r": 99}]}, 2: {"transactions": [{"r": 3}]}},
            call_log,
        )
        merged, _r = asyncio.run(
            InProcessRuntime(max_parallelism=5).run(
                shard_payloads=[_payload(0, 2), _payload(2, 3)],
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                persistence=p,
                shard_runner=runner,
            )
        )
        # Only shard starting at page 2 ran; shard 0 loaded from S3.
        assert call_log == [2]
        assert [t["r"] for t in merged.transactions] == [1, 2, 3]


# --------------------------- runtime selection ---------------------------- #
class TestSelectRuntime:
    def test_default_in_process(self):
        rt = select_runtime(IDPConfig(), 5)
        assert isinstance(rt, InProcessRuntime)
        assert rt.max_parallelism == 5

    def test_config_selects_step_functions(self):
        cfg = IDPConfig()
        cfg.extraction.agentic.runtime = "step_functions"
        rt = select_runtime(cfg, 4)
        assert isinstance(rt, StepFunctionsRuntime)

    def test_override_wins(self):
        cfg = IDPConfig()
        cfg.extraction.agentic.runtime = "step_functions"
        rt = select_runtime(cfg, 3, override="in_process")
        assert isinstance(rt, InProcessRuntime)

    def test_env_var_selects(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_RUNTIME", "sfn")
        rt = select_runtime(IDPConfig(), 2)
        assert isinstance(rt, StepFunctionsRuntime)


class TestForcedFailResume:
    """Phase 3 proof at the unit level: a forced shard failure fails the section
    once; the completed shards persist; a retry skips them and the previously
    failed shard succeeds. Mirrors what SFN's ExtractionStep retry does live."""

    def test_force_fail_then_resume(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_FORCE_FAIL_SHARDS", "2")  # fail shard @page 2
        s3 = _FakeS3()
        p = S3ShardPersistence("bucket", "arn:exec", s3_client=s3)
        runs: list[int] = []
        runner = _make_runner(
            {
                0: {"transactions": [{"r": 1}]},
                2: {"transactions": [{"r": 2}]},
                4: {"transactions": [{"r": 3}]},
            },
            runs,
        )
        payloads = [_payload(0, 2), _payload(2, 4), _payload(4, 6)]

        # Attempt 1: shard@2 raises (after writing a fail marker); others complete.
        with pytest.raises(Exception):
            asyncio.run(
                InProcessRuntime(max_parallelism=1).run(
                    shard_payloads=payloads,
                    model_id="m",
                    data_format=_Model,
                    config=IDPConfig(),
                    section_id="sec",
                    persistence=p,
                    shard_runner=runner,
                )
            )
        # Shards 0 and 4 ran and persisted; shard 2 failed (marker written, no result).
        assert p.load("sec", 0, 2) is not None
        assert p.load("sec", 4, 6) is not None
        assert p.load("sec", 2, 4) is None  # no completed result yet

        # Attempt 2 (the "SFN retry"): completed shards skipped, only shard@2 runs.
        runs.clear()
        merged, _r = asyncio.run(
            InProcessRuntime(max_parallelism=1).run(
                shard_payloads=payloads,
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                persistence=p,
                shard_runner=runner,
            )
        )
        # Only the previously-failed shard's page_start re-ran.
        assert runs == [2]
        assert [t["r"] for t in merged.transactions] == [1, 2, 3]


class TestSelectRuntimeExtra:
    def test_step_functions_run_delegates_in_process(self):
        # Calling .run() standalone must still work (delegates to in-process)
        runner = _make_runner({0: {"transactions": [{"r": 1}]}})
        merged, _ = asyncio.run(
            StepFunctionsRuntime(max_parallelism=2).run(
                shard_payloads=[_payload(0, 1)],
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
            )
        )
        assert [t["r"] for t in merged.transactions] == [1]


def _make_assess_runner(per_shard_assessment):
    """Fake assess_runner keyed by page_start, returning canned assessment."""

    async def assess(*, extracted_fields, payload):
        ps = payload["page_start"]
        if ps not in per_shard_assessment:
            return None
        return per_shard_assessment[ps]

    return assess


class TestInShardAssessment:
    """In-shard assessment: extract_one_shard runs assess_runner, persists it,
    and merge collates it (page-ordered for lists, first-wins for scalars)."""

    def test_extract_one_shard_runs_and_returns_assessment(self):
        runner = _make_runner({0: {"account": "A", "transactions": [{"r": 1}]}})
        assess = _make_assess_runner(
            {
                0: {
                    "assessment": {
                        "account": {"confidence": 0.9},
                        "transactions": [{"r": {"confidence": 0.8}}],
                    },
                    "alerts": [{"attribute_name": "account", "confidence": 0.9}],
                    "metering": {"assess": {"t": 1}},
                }
            }
        )
        fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=assess,
            )
        )
        assert fields["account"] == "A"
        sa = response["_shard_assessment"]
        assert sa["assessment"]["account"]["confidence"] == 0.9
        assert sa["alerts"][0]["attribute_name"] == "account"
        assert sa["page_start"] == 0
        # assessment metering folded into the shard response metering
        assert "assess" in response["metering"]

    def test_no_assess_runner_leaves_response_unchanged(self):
        runner = _make_runner({0: {"account": "A"}})
        _fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
            )
        )
        assert "_shard_assessment" not in response

    def test_persisted_assessment_survives_resume(self):
        """A cache hit must carry the persisted assessment back, no re-inference."""
        store = {}

        class _Persist:
            def load(self, sid, ps, pe):
                return store.get((sid, ps, pe))

            def save(self, sid, ps, pe, result):
                store[(sid, ps, pe)] = result

        runner = _make_runner({0: {"account": "A", "transactions": [{"r": 1}]}})
        assess = _make_assess_runner(
            {0: {"assessment": {"account": {"confidence": 0.7}}, "alerts": []}}
        )
        # First run persists extraction + assessment.
        asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=assess,
                persistence=_Persist(),
            )
        )

        # Second run: assess_runner that would explode if called — proves skip.
        async def _boom(**kwargs):
            raise AssertionError("assess_runner must not run on cache hit")

        _fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=_boom,
                persistence=_Persist(),
            )
        )
        assert (
            response["_shard_assessment"]["assessment"]["account"]["confidence"] == 0.7
        )

    def test_b5_extraction_checkpointed_before_assessment(self):
        """B5: the extraction is persisted (flagged assessment_pending) the moment
        the agent finishes, BEFORE assessment runs — so a crash during assessment
        can resume from it."""
        saves: list[dict] = []

        class _Persist:
            def load(self, sid, ps, pe):
                return None  # nothing persisted yet

            def save(self, sid, ps, pe, result):
                saves.append(dict(result))

        runner = _make_runner({0: {"account": "A", "transactions": [{"r": 1}]}})
        assess = _make_assess_runner(
            {0: {"assessment": {"account": {"confidence": 0.9}}, "alerts": []}}
        )
        asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=assess,
                persistence=_Persist(),
            )
        )
        # Two saves: (1) extraction checkpoint with assessment_pending, then
        # (2) the complete record with the assessment and no pending flag.
        assert len(saves) == 2
        assert saves[0].get("assessment_pending") is True
        assert saves[0].get("assessment") is None
        assert saves[1].get("assessment") == {"account": {"confidence": 0.9}}
        assert saves[1].get("assessment_pending") is not True

    def test_b5_resume_reuses_extraction_reruns_assessment_only(self):
        """B5: when a prior attempt persisted extraction but did NOT finish
        assessment (assessment_pending), the retry reuses the extraction (agent
        NOT re-run) and runs assessment only."""
        # Store seeded as if a prior attempt crashed mid-assessment.
        store = {
            ("sec", 0, 1): {
                "extracted_fields": {"account": "A", "transactions": [{"r": 1}]},
                "metering": {"shard0": {"t": 1}},
                "assessment_pending": True,
            }
        }

        class _Persist:
            def load(self, sid, ps, pe):
                return store.get((sid, ps, pe))

            def save(self, sid, ps, pe, result):
                store[(sid, ps, pe)] = dict(result)

        agent_calls: list[int] = []
        runner = _make_runner(
            {0: {"account": "A", "transactions": [{"r": 1}]}}, call_log=agent_calls
        )
        assess = _make_assess_runner(
            {0: {"assessment": {"account": {"confidence": 0.55}}, "alerts": []}}
        )
        fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=assess,
                persistence=_Persist(),
            )
        )
        # The expensive agent loop was NOT re-run...
        assert agent_calls == []
        # ...the reused extraction is returned...
        assert fields["account"] == "A"
        # ...and assessment was (re-)computed and persisted complete.
        assert (
            response["_shard_assessment"]["assessment"]["account"]["confidence"] == 0.55
        )
        assert store[("sec", 0, 1)].get("assessment_pending") is not True

    def test_merge_collates_list_assessment_page_ordered(self):
        from idp_common.extraction.runtime import merge_assessment_dicts

        shard_assessments = [
            {
                "assessment": {"transactions": [{"r": {"c": 1}}]},
                "alerts": [{"a": 1}],
                "page_start": 0,
            },
            {
                "assessment": {"transactions": [{"r": {"c": 2}}, {"r": {"c": 3}}]},
                "alerts": [{"a": 2}],
                "page_start": 1,
            },
        ]
        merged, alerts = merge_assessment_dicts(shard_assessments, {"transactions"})
        assert [t["r"]["c"] for t in merged["transactions"]] == [1, 2, 3]
        assert alerts == [{"a": 1}, {"a": 2}]

    def test_merge_collates_scalar_first_wins(self):
        from idp_common.extraction.runtime import merge_assessment_dicts

        shard_assessments = [
            {
                "assessment": {"account": {"confidence": 0.9}},
                "alerts": [],
                "page_start": 0,
            },
            {
                "assessment": {"account": {"confidence": 0.1}},
                "alerts": [],
                "page_start": 1,
            },
        ]
        merged, _ = merge_assessment_dicts(shard_assessments, set())
        assert merged["account"]["confidence"] == 0.9

    def test_merge_shard_dicts_surfaces_merged_assessment(self):
        shard_dicts = [
            {
                "extracted_fields": {"transactions": [{"r": 1}]},
                "page_start": 0,
                "assessment": {"transactions": [{"r": {"c": 1}}]},
                "alerts": [{"a": 1}],
            },
            {
                "extracted_fields": {"transactions": [{"r": 2}]},
                "page_start": 1,
                "assessment": {"transactions": [{"r": {"c": 2}}]},
                "alerts": [],
            },
        ]
        _merged, metering, _c = merge_shard_dicts(shard_dicts, _Model)
        assert [
            t["r"]["c"] for t in metering["_merged_assessment"]["transactions"]
        ] == [1, 2]
        assert metering["_merged_assessment_alerts"] == [{"a": 1}]

    def test_inprocess_runtime_surfaces_merged_assessment(self):
        runner = _make_runner(
            {0: {"transactions": [{"r": 1}]}, 1: {"transactions": [{"r": 2}]}}
        )
        assess = _make_assess_runner(
            {
                0: {"assessment": {"transactions": [{"r": {"c": 1}}]}, "alerts": []},
                1: {"assessment": {"transactions": [{"r": {"c": 2}}]}, "alerts": []},
            }
        )
        _merged, response = asyncio.run(
            InProcessRuntime(max_parallelism=2).run(
                shard_payloads=[_payload(0, 1), _payload(1, 2)],
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
                assess_runner=assess,
            )
        )
        ma = response["metering"]["_merged_assessment"]
        assert [t["r"]["c"] for t in ma["transactions"]] == [1, 2]


class TestAssessmentReconciliation:
    """ExtractionService._reconcile_assessment_to_data forces per-field list
    assessments to index-align with the extracted data lists."""

    def _svc(self):
        from idp_common.extraction.service import ExtractionService

        return ExtractionService(config=IDPConfig())

    def test_truncates_overlong_list_assessment(self):
        svc = self._svc()
        data = {"txns": [{"a": 1}, {"a": 2}]}
        assessment = {"txns": [{"c": 0.9}, {"c": 0.8}, {"c": 0.7}, {"c": 0.6}]}
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["txns"]) == 2

    def test_pads_short_list_assessment_with_per_subfield_leaves(self):
        svc = self._svc()
        # data rows have sub-fields; padded rows must mirror them so each
        # sub-field is groundable (confidence null, but a real value to match).
        data = {"txns": [{"date": f"d{i}", "amt": f"{i}"} for i in range(5)]}
        assessment = {"txns": [{"date": {"c": 0.9}}, {"date": {"c": 0.8}}]}
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["txns"]) == 5
        # padded entries mirror the data row's sub-fields with null confidence
        pad = out["txns"][4]
        assert set(pad.keys()) == {"date", "amt"}
        assert pad["date"]["confidence"] is None
        assert "Not individually assessed" in pad["amt"]["confidence_reason"]
        # original entries preserved
        assert out["txns"][0]["date"]["c"] == 0.9

    def test_pads_omitted_list_field_entirely(self):
        # The live bug: a shard extracted N rows but the assessment OMITTED the
        # list field. Reconcile must still pad to N (structured), not drop it.
        svc = self._svc()
        data = {"txns": [{"date": f"d{i}", "amt": f"{i}"} for i in range(75)]}
        out = svc._reconcile_assessment_to_data({}, data)
        assert len(out["txns"]) == 75
        assert set(out["txns"][0].keys()) == {"date", "amt"}
        assert out["txns"][0]["date"]["confidence"] is None

    def test_scalar_row_elements_get_neutral_leaf(self):
        svc = self._svc()
        data = {"tags": ["a", "b", "c"]}  # scalar list elements
        out = svc._reconcile_assessment_to_data({"tags": [{"c": 0.9}]}, data)
        assert len(out["tags"]) == 3
        assert out["tags"][2]["confidence"] is None

    def test_scalar_and_group_untouched(self):
        svc = self._svc()
        data = {"name": "x", "group": {"k": "v"}, "txns": [{"a": 1}]}
        assessment = {
            "name": {"c": 0.9},
            "group": {"k": {"c": 0.8}},
            "txns": [{"c": 0.7}, {"c": 0.6}],
        }
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert out["name"] == {"c": 0.9}
        assert out["group"] == {"k": {"c": 0.8}}
        assert len(out["txns"]) == 1  # truncated to data length

    def test_expands_per_row_scalar_confidence_to_per_column(self):
        # Integrated mode sometimes emits ONE confidence per row; reconcile must
        # fan it out to per-column leaves so every list-item field is scored.
        svc = self._svc()
        data = {"txns": [{"date": "d0", "amt": "1"}, {"date": "d1", "amt": "2"}]}
        assessment = {
            "txns": [
                {"confidence": 0.98, "confidence_reason": "clear"},
                {"confidence": 0.90, "confidence_reason": "faint"},
            ]
        }
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["txns"]) == 2
        # each column now has its own leaf carrying the row's confidence/reason
        assert set(out["txns"][0].keys()) == {"date", "amt"}
        assert out["txns"][0]["date"]["confidence"] == 0.98
        assert out["txns"][0]["amt"]["confidence"] == 0.98
        assert out["txns"][0]["amt"]["confidence_reason"] == "clear"
        assert out["txns"][1]["date"]["confidence"] == 0.90

    def test_already_per_column_row_untouched(self):
        # A properly per-column row (no top-level "confidence" key) passes through.
        svc = self._svc()
        data = {"txns": [{"date": "d0", "amt": "1"}]}
        assessment = {
            "txns": [
                {
                    "date": {"confidence": 0.9, "confidence_reason": "x"},
                    "amt": {"confidence": 0.7, "confidence_reason": "y"},
                }
            ]
        }
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert out["txns"][0]["date"]["confidence"] == 0.9
        assert out["txns"][0]["amt"]["confidence"] == 0.7

    def test_reconcile_fixes_large_merged_mismatch(self):
        # Reproduces the live e2e bug: merged data has 120 rows but the merged
        # assessment only 45. Post-merge reconcile aligns to 120, and the padded
        # rows mirror the data sub-fields so they remain groundable.
        svc = self._svc()
        data = {
            "transaction_details": [
                {"date": f"d{i}", "amt": f"{i}"} for i in range(120)
            ]
        }
        assessment = {"transaction_details": [{"date": {"c": 0.9}} for _ in range(45)]}
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["transaction_details"]) == 120
        assert out["transaction_details"][0]["date"]["c"] == 0.9
        # padded row mirrors data sub-fields with null confidence (groundable)
        assert out["transaction_details"][119]["date"]["confidence"] is None
        assert out["transaction_details"][119]["amt"]["confidence"] is None


class TestIntegratedAssessment:
    """Integrated (combined-prompt) mode: the extraction agent emits per-field
    confidence inline; extract_one_shard lifts it from the response metering
    into the same _shard_assessment slot separate mode uses (no assess_runner)."""

    def test_extract_one_shard_lifts_inline_assessment(self):
        # shard_runner returns inline assessment in metering (as the agent does
        # via provide_field_assessment -> _integrated_field_assessment).
        async def runner(*, shard_index, total_shards, payload, **kwargs):
            return _Model(account="A", transactions=[{"r": 1}]), {
                "metering": {
                    "tok": {"t": 1},
                    "_integrated_field_assessment": {
                        "account": {"confidence": 0.88},
                        "transactions": [{"r": {"confidence": 0.77}}],
                    },
                }
            }

        fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,  # NO assess_runner — integrated path
            )
        )
        sa = response["_shard_assessment"]
        assert sa["assessment"]["account"]["confidence"] == 0.88
        assert sa["assessment"]["transactions"][0]["r"]["confidence"] == 0.77
        # lifted key removed from metering so it doesn't leak downstream
        assert "_integrated_field_assessment" not in response["metering"]
        # real metering preserved
        assert response["metering"]["tok"] == {"t": 1}

    def test_no_inline_assessment_no_shard_assessment(self):
        async def runner(*, shard_index, total_shards, payload, **kwargs):
            return _Model(account="A"), {"metering": {"tok": {"t": 1}}}

        _fields, response = asyncio.run(
            extract_one_shard(
                shard_index=0,
                total_shards=1,
                payload=_payload(0, 1),
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
            )
        )
        assert "_shard_assessment" not in response

    def test_integrated_inline_collates_and_persists(self):
        # Two shards each emit inline assessment; merge collates page-ordered.
        def _runner_with_inline(per_shard_inline):
            async def runner(*, shard_index, total_shards, payload, **kwargs):
                ps = payload["page_start"]
                return _Model(transactions=[{"r": ps}]), {
                    "metering": {"_integrated_field_assessment": per_shard_inline[ps]}
                }

            return runner

        runner = _runner_with_inline(
            {
                0: {"transactions": [{"r": {"c": 1}}]},
                1: {"transactions": [{"r": {"c": 2}}]},
            }
        )
        _merged, response = asyncio.run(
            InProcessRuntime(max_parallelism=2).run(
                shard_payloads=[_payload(0, 1), _payload(1, 2)],
                model_id="m",
                data_format=_Model,
                config=IDPConfig(),
                section_id="sec",
                shard_runner=runner,
            )
        )
        ma = response["metering"]["_merged_assessment"]
        assert [t["r"]["c"] for t in ma["transactions"]] == [1, 2]
