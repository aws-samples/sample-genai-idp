# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Offline tests for Step 14, the pipeline-hook end-to-end CI step.

Step 14 itself needs a live stack, so what is testable here is the part that
fails *silently in CI* if it is wrong — the hook Lambda's package and its handler
logic. Both bugs these tests pin were real, found while writing the step:

1. **The zip built without pydantic.** The first version located dependencies by
   assuming they were siblings of `idp_common` in one site-packages directory.
   With an editable install they are not, so it produced a zip containing
   `idp_common` but no `pydantic` — which imports fine locally and dies with
   `ModuleNotFoundError` only at Lambda cold start, in CI.

2. **The marker was written to a field that is never serialized.** The handler
   first wrote its marker into `Document.metadata`, which `Document.to_dict()`
   drops entirely — so the mutation could never reach the persisted document and
   the step's central assertion would always have failed.

Together these are the "does the test itself work" layer: a broken Step 14 that
always fails is noisy, but a broken Step 14 that always *passes* would be worse
than having no test at all.
"""

import ast
import json
import os
import zipfile

import pytest


@pytest.mark.unit
class TestHookZipBuild:
    """The Lambda package must actually contain what the handler imports."""

    def test_zip_contains_handler_and_runtime_deps(self, cbd, tmp_path):
        """idp_common alone is not enough — its import chain reaches pydantic."""
        pytest.importorskip("idp_common")
        path = cbd._build_hook_zip(str(tmp_path / "hook.zip"))
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()

        assert "index.py" in names
        assert "idp_common/hooks/__init__.py" in names, (
            "the handler imports idp_common.hooks"
        )
        # config.models imports pydantic at module scope, and models.py is on
        # the load_hook_document path.
        assert any(n.startswith("pydantic/") for n in names), (
            "pydantic missing — the Lambda would fail at import time"
        )
        assert any(n.startswith("pydantic_core/") for n in names)

    def test_zip_stays_under_the_direct_upload_limit(self, cbd, tmp_path):
        """create_function with ZipFile= caps at 50MB; a site-packages sweep
        would blow past it, so the dependency list is deliberately explicit."""
        pytest.importorskip("idp_common")
        path = cbd._build_hook_zip(str(tmp_path / "hook.zip"))
        assert os.path.getsize(path) < 50 * 1024 * 1024

    def test_zip_excludes_bytecode(self, cbd, tmp_path):
        pytest.importorskip("idp_common")
        path = cbd._build_hook_zip(str(tmp_path / "hook.zip"))
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert not [n for n in names if n.endswith((".pyc", ".pyo"))]
        assert not [n for n in names if "__pycache__" in n]

    def test_build_fails_loudly_when_a_required_dep_is_missing(
        self, cbd, tmp_path, monkeypatch
    ):
        """The whole point of the validation step: a zip missing a required
        package must raise HERE, not at Lambda cold start in CI."""
        pytest.importorskip("idp_common")
        import importlib

        real_import = importlib.import_module

        def fake_import(name, *a, **k):
            # Fail ONLY pydantic — idp_common must still import, so the builder
            # gets far enough to produce the exact silent-failure zip this
            # validation exists to catch.
            if name == "pydantic":
                raise ImportError("simulated missing pydantic")
            return real_import(name, *a, **k)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        with pytest.raises(RuntimeError, match="pydantic"):
            cbd._build_hook_zip(str(tmp_path / "hook.zip"))


@pytest.mark.unit
class TestHookHandlerSource:
    """The inline handler source is shipped as a string, so nothing type-checks
    or imports it in the normal build — these tests are its only guard."""

    def test_source_parses(self, cbd):
        ast.parse(cbd._HOOK_SOURCE)

    def _run(self, cbd, monkeypatch, point, document):
        monkeypatch.setenv("MARKER_KEY", cbd._HOOK_MARKER_KEY)
        ns = {}
        exec(  # noqa: S102 — executing our own shipped source under test
            compile(cbd._HOOK_SOURCE, "index.py", "exec"), ns
        )
        event = {
            "hookPoint": point,
            "args": [{"key": "note", "value": f"ci-{point}"}],
            "document": document,
        }
        return ns["lambda_handler"](event, None)

    def _doc(self, **over):
        doc = {
            "id": "w2.pdf",
            "input_key": "w2.pdf",
            "status": "COMPLETED",
            "num_pages": 2,
            "sections": [
                {"section_id": "1", "classification": "Invoice", "page_ids": ["1"]}
            ],
        }
        doc.update(over)
        return doc

    def test_marker_survives_serialization(self, cbd, monkeypatch):
        """The regression: `Document.metadata` is a runtime-only field that
        to_dict() drops, so a marker written there never reaches the persisted
        document. It must land somewhere that round-trips."""
        pytest.importorskip("idp_common")
        result = self._run(cbd, monkeypatch, "postprocessing", self._doc())
        serialized = json.dumps(result["updatedDocument"])
        assert cbd._HOOK_MARKER_KEY in serialized, (
            "marker absent from the serialized document — Step 14's persisted-"
            "marker assertion could never pass"
        )

    def test_marker_lands_in_section_attributes(self, cbd, monkeypatch):
        """Section attributes are what a real mutating hook changes, and they
        round-trip — so that is where the marker goes."""
        pytest.importorskip("idp_common")
        result = self._run(cbd, monkeypatch, "postprocessing", self._doc())
        section = result["updatedDocument"]["sections"][0]
        assert cbd._HOOK_MARKER_KEY in (section.get("attributes") or {})

    def test_marker_records_the_hook_point(self, cbd, monkeypatch):
        """Both points share one Lambda, so the marker must say which fired."""
        pytest.importorskip("idp_common")
        result = self._run(cbd, monkeypatch, "postprocessing", self._doc())
        section = result["updatedDocument"]["sections"][0]
        marker = section["attributes"][cbd._HOOK_MARKER_KEY]
        assert marker["hookPoint"] == "postprocessing"
        assert marker["note"] == "ci-postprocessing"
        assert result["ciHookPoint"] == "postprocessing"

    def test_returns_the_documented_update_key(self, cbd, monkeypatch):
        """The dispatcher only honors `updatedDocument`; any other shape is a
        silent no-op mutation."""
        pytest.importorskip("idp_common")
        result = self._run(cbd, monkeypatch, "postprocessing", self._doc())
        assert "updatedDocument" in result
        assert result["ciHookRan"] is True

    def test_survives_a_sectionless_document(self, cbd, monkeypatch):
        """At `preprocessing` there are no sections yet (OCR/classification have
        not run). The handler must not crash, and must still write the
        document-level backstop."""
        pytest.importorskip("idp_common")
        result = self._run(
            cbd, monkeypatch, "preprocessing", self._doc(sections=[])
        )
        doc = result["updatedDocument"]
        assert doc["summary_report_uri"] == f"{cbd._HOOK_MARKER_KEY}:preprocessing"

    def test_reports_the_hitl_status_it_observed(self, cbd, monkeypatch):
        """postprocessing fires while a HITL review is pending, so the hook has
        to be able to see that state to branch on it."""
        pytest.importorskip("idp_common")
        result = self._run(
            cbd, monkeypatch, "postprocessing", self._doc(hitl_status="PendingReview")
        )
        marker = result["updatedDocument"]["sections"][0]["attributes"][
            cbd._HOOK_MARKER_KEY
        ]
        assert marker["saw_hitl_status"] == "PendingReview"

    def test_absent_hitl_status_reads_as_none(self, cbd, monkeypatch):
        """HITL fields are omitted when falsy, so absent must mean "no HITL"
        rather than raising."""
        pytest.importorskip("idp_common")
        result = self._run(cbd, monkeypatch, "postprocessing", self._doc())
        marker = result["updatedDocument"]["sections"][0]["attributes"][
            cbd._HOOK_MARKER_KEY
        ]
        assert marker["saw_hitl_status"] is None


@pytest.mark.unit
class TestStepRegistration:
    """A step that exists but is never registered is dead code — and the suite
    derives its summary and failure analysis from these lists."""

    def test_step14_is_in_the_parallel_pool(self, cbd):
        names = [entry[1] for entry in cbd.PARALLEL_TEST_STEPS]
        assert "Step 14" in names

    def test_step14_is_reachable_from_all_test_steps(self, cbd):
        funcs = [entry[0] for entry in cbd.ALL_TEST_STEPS]
        assert cbd.test_step14_pipeline_hooks in funcs

    def test_hook_resources_are_named_for_the_ci_role_scope(self, cbd):
        """The CI CodeBuild role scopes `iam:*` to `role/idp-*` and `lambda:*` to
        `function:idp-*`, so a `GENAIIDP-` prefixed name is AccessDenied — which
        is exactly how this step first failed in the pipeline. The `idp-` prefix
        is therefore load-bearing, not cosmetic."""
        assert cbd._HOOK_FN_PREFIX.startswith("idp-")
        assert not cbd._HOOK_FN_PREFIX.startswith("GENAIIDP-"), (
            "GENAIIDP-* is outside the CI role's iam:*/lambda:* resource scope"
        )

    def test_hook_uses_the_tag_path_to_clear_the_dispatcher_iam_condition(self, cbd):
        """Because the function is NOT named `GENAIIDP-*`, the dispatcher's other
        allow path — the `idp:feature-id` ABAC tag — is the only thing
        authorizing the invoke. A non-empty tag value is required (the policy
        condition is StringLike '*')."""
        assert cbd._HOOK_FEATURE_ID
        assert isinstance(cbd._HOOK_FEATURE_ID, str)

    def test_step_tags_the_function_it_creates(self, cbd):
        """Guard the wiring itself: the step must actually apply the tag, or the
        dispatcher fails closed with AccessDenied at every dispatch. Asserted on
        the source because the call needs live AWS to execute."""
        import inspect

        src = inspect.getsource(cbd.test_step14_pipeline_hooks)
        assert "tag_resource" in src, (
            "the hook Lambda must be tagged idp:feature-id — without it the "
            "dispatcher cannot invoke a function not named GENAIIDP-*"
        )
        assert "list_tags" in src, "the tag should be verified, not assumed"


@pytest.mark.unit
class TestStepInvocationCorrectness:
    """Pins the three bugs found auditing Step 14 before its second pipeline run.

    All three would have failed the step (or, worse, passed/failed it for the
    wrong reason) and none are reachable without a live stack, so they are
    asserted against the step's source.
    """

    def _src(self, cbd):
        import inspect

        return inspect.getsource(cbd.test_step14_pipeline_hooks)

    def test_run_inference_uses_dir_plus_file_pattern(self, cbd):
        """`run-inference` declares NO short flags and its `--dir` is
        `file_okay=False`, so `-d samples/lending_package.pdf` is rejected twice
        over: unknown option, and a file where a directory is required."""
        src = self._src(cbd)
        assert "--dir samples/" in src
        assert "--file-pattern lending_package.pdf" in src
        assert "-d samples/" not in src, "run-inference has no -d short flag"

    def test_execution_scan_filters_on_config_version(self, cbd):
        """Step 14 shares the state machine with the other parallel steps, whose
        hook-less documents ALSO emit `{hookPoint: ..., invoked: 0}` at both
        points. Without a configVersion filter the scan latches onto one of those
        and reports a false failure."""
        src = self._src(cbd)
        assert 'payload.get("configVersion") != config_version' in src, (
            "the scan must accept only OUR document's dispatcher results"
        )

    def test_execution_scan_does_not_stop_on_a_foreign_result(self, cbd):
        """The original `if len(found) == 2: break` could satisfy itself with two
        invoked=0 records from another step. With the configVersion filter a
        `found` entry is by definition ours, so the break is safe — assert the
        filter precedes it rather than the break being removed."""
        src = self._src(cbd)
        filter_at = src.index('payload.get("configVersion") != config_version')
        break_at = src.index("if len(found) == 2:")
        assert filter_at < break_at, (
            "the configVersion filter must run before the early break"
        )

    def test_feature_id_is_shared_between_tag_and_config(self, cbd):
        """The Lambda's idp:feature-id tag and the config section's featureId must
        come from the same constant; drift would leave the ABAC grant and the
        registered owner disagreeing."""
        src = self._src(cbd)
        assert '"featureId": _HOOK_FEATURE_ID' in src


@pytest.mark.unit
class TestLambdaRuntimeAlignment:
    """pydantic_core is a COMPILED extension, so the zip and the Lambda runtime
    must agree on the Python minor version or the hook dies at cold start."""

    def test_runtime_matches_the_building_interpreter(self, cbd):
        import sys

        assert cbd._hook_lambda_runtime() == f"python3.{sys.version_info.minor}"

    def test_runtime_is_a_supported_lambda_value(self, cbd):
        assert cbd._hook_lambda_runtime() in {
            f"python3.{m}" for m in range(9, 14)
        }

    def test_create_function_does_not_hardcode_a_runtime(self, cbd):
        import inspect

        src = inspect.getsource(cbd.test_step14_pipeline_hooks)
        assert "Runtime=_hook_lambda_runtime()" in src
        assert 'Runtime="python3.12"' not in src, (
            "a hardcoded runtime silently breaks when the buildspec python moves"
        )
