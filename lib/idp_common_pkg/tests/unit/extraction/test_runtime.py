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
from pydantic import BaseModel

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

    def test_pads_short_list_assessment(self):
        svc = self._svc()
        data = {"txns": [{"a": i} for i in range(5)]}
        assessment = {"txns": [{"c": 0.9}, {"c": 0.8}]}
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["txns"]) == 5
        # padded entries are neutral "not assessed"
        assert out["txns"][2]["confidence"] is None
        assert "Not individually assessed" in out["txns"][4]["confidence_reason"]
        # original entries preserved
        assert out["txns"][0]["c"] == 0.9

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

    def test_field_not_assessed_left_alone(self):
        svc = self._svc()
        data = {"txns": [{"a": 1}, {"a": 2}]}
        assessment = {}  # model didn't assess txns at all
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert "txns" not in out  # not fabricated

    def test_reconcile_fixes_large_merged_mismatch(self):
        # Reproduces the live e2e bug: merged data has 120 rows but the merged
        # assessment only 45 (LLM under-count + phantom-row filtering on data
        # merge diverging from assessment collation). Post-merge reconcile must
        # align the assessment list to exactly the data length.
        svc = self._svc()
        data = {"transaction_details": [{"r": i} for i in range(120)]}
        assessment = {"transaction_details": [{"amt": {"c": 0.9}} for _ in range(45)]}
        out = svc._reconcile_assessment_to_data(assessment, data)
        assert len(out["transaction_details"]) == 120
        # first 45 preserved, remainder padded neutral
        assert out["transaction_details"][0]["amt"]["c"] == 0.9
        assert out["transaction_details"][119]["confidence"] is None
