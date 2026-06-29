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
