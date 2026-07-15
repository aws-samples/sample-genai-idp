"""Unit tests for the deployment-variant probe framework.

These exercise the probe launcher / quota cap / fail-fast isolation added to
`scripts/sdlc/codebuild_deployment.py` WITHOUT any AWS or subprocess calls:
boto3, run_command, and the deploy/cleanup helpers are all monkeypatched. They
verify the behaviors the harness is easy to regress on:

  * the per-variant concurrency/quota budget (resolve_probe_concurrency),
  * the deploy → validate → ALWAYS-cleanup lifecycle of a single probe,
  * CF-event capture before teardown on failure,
  * each probe thread opting out of the primary suite's fail-fast machinery
    (_thread_local.never_abort) so a primary failure can't kill a probe deploy,
  * the launcher folding independent per-probe results without one failure
    affecting the others, and honoring the concurrency cap.
"""

import threading
import time

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_probe(cbd, name="Test probe", suffix="test", params=None, validate=None):
    return cbd.Probe(
        name=name,
        stack_suffix=suffix,
        deploy_params=params if params is not None else {"Foo": "Bar"},
        validate_fn=validate or (lambda stack_name: {"success": True}),
    )


def _stub_lifecycle(cbd, monkeypatch, *, deploy_status="CREATE_COMPLETE"):
    """Stub out IAM/deploy/status/cleanup so a probe run touches no AWS.

    Records calls in the returned dict so tests can assert on ordering,
    parameters, and that cleanup always ran.
    """
    calls = {"iam": [], "commands": [], "cleanup": [], "cf_events": []}

    monkeypatch.setattr(
        cbd,
        "create_iam_resources",
        lambda stack_name: (calls["iam"].append(stack_name) or ("role-arn", "boundary-arn")),
    )
    monkeypatch.setattr(cbd, "generate_stack_name", lambda: "idp-0101-000000")

    def fake_run_command(cmd, check=True, timeout=cbd.DEFAULT_COMMAND_TIMEOUT):
        calls["commands"].append(cmd)
        if "describe-stacks" in cmd:
            return _Completed(stdout=deploy_status)
        return _Completed(stdout="")

    monkeypatch.setattr(cbd, "run_command", fake_run_command)
    monkeypatch.setattr(
        cbd, "cleanup_stack", lambda result: calls["cleanup"].append(result["stack_name"])
    )
    monkeypatch.setattr(
        cbd,
        "_capture_cf_events",
        lambda result, *names: calls["cf_events"].append(tuple(names)),
    )
    return calls


class _Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


# --------------------------------------------------------------------------- #
# resolve_probe_concurrency — the quota budget
# --------------------------------------------------------------------------- #


def test_concurrency_default_is_conservative(cbd, monkeypatch):
    monkeypatch.delenv("IDP_PROBE_MAX_CONCURRENCY", raising=False)
    # Default is 1 even when there are several probes: probes deploy full stacks
    # concurrently with the primary suite and other pipelines, so the safe
    # default is one-at-a-time.
    assert cbd.resolve_probe_concurrency(5) == cbd.DEFAULT_PROBE_MAX_CONCURRENCY
    assert cbd.DEFAULT_PROBE_MAX_CONCURRENCY == 1


def test_concurrency_env_override_is_clamped_to_probe_count(cbd, monkeypatch):
    # An override larger than the number of probes never spins up idle workers.
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "10")
    assert cbd.resolve_probe_concurrency(3) == 3
    assert cbd.resolve_probe_concurrency(1) == 1


def test_concurrency_env_override_honored_within_bounds(cbd, monkeypatch):
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "2")
    assert cbd.resolve_probe_concurrency(5) == 2


def test_concurrency_invalid_env_falls_back_to_default(cbd, monkeypatch):
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "not-a-number")
    assert cbd.resolve_probe_concurrency(5) == cbd.DEFAULT_PROBE_MAX_CONCURRENCY


def test_concurrency_nonpositive_env_falls_back_to_default(cbd, monkeypatch):
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "0")
    assert cbd.resolve_probe_concurrency(5) == cbd.DEFAULT_PROBE_MAX_CONCURRENCY
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "-3")
    assert cbd.resolve_probe_concurrency(5) == cbd.DEFAULT_PROBE_MAX_CONCURRENCY


def test_concurrency_never_zero_even_with_zero_probes(cbd, monkeypatch):
    # Defensive: max(1, min(cap, n)) must never return 0 (ThreadPoolExecutor
    # rejects max_workers<1). run_variant_probes never calls this with 0 probes,
    # but the clamp should still hold.
    monkeypatch.delenv("IDP_PROBE_MAX_CONCURRENCY", raising=False)
    assert cbd.resolve_probe_concurrency(0) == 1


# --------------------------------------------------------------------------- #
# deploy_and_test_probe — single-probe lifecycle
# --------------------------------------------------------------------------- #


def test_probe_happy_path_deploys_validates_cleans_up(cbd, monkeypatch):
    calls = _stub_lifecycle(cbd, monkeypatch)
    validated = []
    probe = _make_probe(
        cbd,
        suffix="apigw",
        params={"WebUIHosting": "APIGateway", "ApiGatewayVisibility": "GLOBAL"},
        validate=lambda stack_name: validated.append(stack_name)
        or {"success": True, "web_url": "https://x/api"},
    )

    result = cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")

    assert result["success"] is True
    assert result["probe"] == probe.name
    assert result["stack_name"] == "idp-0101-000000-apigw"
    assert result["web_url"] == "https://x/api"
    # validator ran against the deployed stack
    assert validated == ["idp-0101-000000-apigw"]
    # cleanup ALWAYS runs (finally)
    assert calls["cleanup"] == ["idp-0101-000000-apigw"]
    # deploy command carried the probe's extra params + the boundary
    deploy_cmd = next(c for c in calls["commands"] if "idp-cli deploy" in c)
    assert "PermissionsBoundaryArn=boundary-arn" in deploy_cmd
    assert "WebUIHosting=APIGateway" in deploy_cmd
    assert "ApiGatewayVisibility=GLOBAL" in deploy_cmd
    assert "--stack-name idp-0101-000000-apigw" in deploy_cmd


def test_probe_sets_never_abort_on_its_thread(cbd, monkeypatch):
    _stub_lifecycle(cbd, monkeypatch)
    seen = {}

    def capture(stack_name):
        # by the time validation runs, the thread must be non-abortable
        seen["never_abort"] = getattr(cbd._thread_local, "never_abort", False)
        return {"success": True}

    probe = _make_probe(cbd, validate=capture)
    cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")
    assert seen["never_abort"] is True


def test_probe_deploy_status_not_complete_is_deploy_failure(cbd, monkeypatch):
    # CREATE_FAILED (not *_COMPLETE): the harness's "COMPLETE" not in <status>
    # check — matching the primary suite's deploy_and_test_stack — treats it as
    # a deploy failure.
    calls = _stub_lifecycle(cbd, monkeypatch, deploy_status="CREATE_FAILED")
    probe = _make_probe(cbd)

    result = cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")

    assert result["success"] is False
    assert result["failure_type"] == "deploy"
    assert "CREATE_FAILED" in result["error"]
    # CF events captured BEFORE teardown, and teardown still ran
    assert calls["cf_events"] == [("idp-0101-000000-test",)]
    assert calls["cleanup"] == ["idp-0101-000000-test"]


def test_probe_validation_failure_is_test_failure(cbd, monkeypatch):
    calls = _stub_lifecycle(cbd, monkeypatch)
    probe = _make_probe(
        cbd, validate=lambda stack_name: {"success": False, "error": "bad endpoint"}
    )

    result = cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")

    assert result["success"] is False
    assert result["failure_type"] == "test"
    assert result["error"] == "bad endpoint"
    # a validation (not deploy) failure still tears down
    assert calls["cleanup"] == ["idp-0101-000000-test"]


def test_probe_exception_captures_events_and_cleans_up(cbd, monkeypatch):
    calls = _stub_lifecycle(cbd, monkeypatch)

    def boom(stack_name):
        raise RuntimeError("kaboom")

    probe = _make_probe(cbd, validate=boom)
    result = cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")

    assert result["success"] is False
    assert result["failure_type"] == "deploy"
    assert "kaboom" in result["error"]
    assert calls["cf_events"] == [("idp-0101-000000-test",)]
    # cleanup STILL runs on exception (finally)
    assert calls["cleanup"] == ["idp-0101-000000-test"]


def test_probe_iam_failure_still_cleans_up(cbd, monkeypatch):
    calls = _stub_lifecycle(cbd, monkeypatch)
    monkeypatch.setattr(cbd, "create_iam_resources", lambda stack_name: (None, None))

    probe = _make_probe(cbd)
    result = cbd.deploy_and_test_probe(probe, "a@b.com", "https://tmpl")

    assert result["success"] is False
    assert "IAM" in result["error"]
    assert calls["cleanup"] == ["idp-0101-000000-test"]


# --------------------------------------------------------------------------- #
# fail-fast isolation — a primary-suite abort must not kill a probe's commands
# --------------------------------------------------------------------------- #


def test_never_abort_thread_ignores_abort_tests(cbd, monkeypatch):
    """A run_command on a never_abort thread must run even when ABORT_TESTS is set.

    This is the core isolation guarantee: the primary suite fails fast and sets
    ABORT_TESTS, but a probe thread (never_abort=True) must keep going so its
    independent-stack deploy isn't killed mid-flight. We stub Popen so no real
    process starts and assert the command was NOT refused.
    """
    cbd.ABORT_TESTS.set()
    started = []

    class FakePopen:
        def __init__(self, *a, **k):
            started.append(a[0] if a else k.get("args"))
            self.pid = 4242
            self.returncode = 0

        def communicate(self, timeout=None):
            return ("ok", "")

    monkeypatch.setattr(cbd.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(cbd.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(cbd.os, "killpg", lambda *a: None)

    result_box = {}

    def worker():
        cbd._thread_local.never_abort = True
        try:
            res = cbd.run_command("echo hi", check=False)
            result_box["stdout"] = res.stdout
        except Exception as e:  # noqa: BLE001
            result_box["error"] = str(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)

    assert "error" not in result_box, result_box
    assert result_box.get("stdout") == "ok"
    assert started == ["echo hi"]


def test_abortable_thread_is_refused_when_abort_set(cbd, monkeypatch):
    """Control case: a NON-never_abort background thread IS refused on abort.

    Confirms the isolation in the previous test comes from never_abort, not
    from the command never being abortable at all.
    """
    cbd.ABORT_TESTS.set()
    monkeypatch.setattr(
        cbd.subprocess, "Popen", lambda *a, **k: pytest.fail("Popen should not run")
    )
    result_box = {}

    def worker():
        # note: never_abort NOT set → abortable
        try:
            cbd.run_command("echo hi", check=False)
            result_box["ran"] = True
        except Exception as e:  # noqa: BLE001
            result_box["error"] = str(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)

    assert "error" in result_box
    assert "failed fast" in result_box["error"]


# --------------------------------------------------------------------------- #
# run_variant_probes — the concurrent launcher
# --------------------------------------------------------------------------- #


def test_launcher_runs_all_probes_and_folds_results(cbd, monkeypatch):
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "3")
    ran = []

    def fake_deploy(probe, admin_email, template_url):
        ran.append(probe.name)
        return {"stack_name": f"s-{probe.stack_suffix}", "success": True, "probe": probe.name}

    monkeypatch.setattr(cbd, "deploy_and_test_probe", fake_deploy)

    probes = [
        _make_probe(cbd, name="A", suffix="a"),
        _make_probe(cbd, name="B", suffix="b"),
        _make_probe(cbd, name="C", suffix="c"),
    ]
    results = cbd.run_variant_probes("a@b.com", "https://tmpl", probes=probes)

    assert sorted(ran) == ["A", "B", "C"]
    assert len(results) == 3
    assert {r["probe"] for r in results} == {"A", "B", "C"}
    assert all(r["success"] for r in results)


def test_launcher_isolates_one_probe_failure(cbd, monkeypatch):
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "3")

    def fake_deploy(probe, admin_email, template_url):
        if probe.name == "B":
            return {
                "stack_name": "s-b",
                "success": False,
                "error": "B blew up",
                "failure_type": "deploy",
                "probe": "B",
            }
        return {"stack_name": f"s-{probe.stack_suffix}", "success": True, "probe": probe.name}

    monkeypatch.setattr(cbd, "deploy_and_test_probe", fake_deploy)
    probes = [_make_probe(cbd, name=n, suffix=n.lower()) for n in ("A", "B", "C")]

    results = cbd.run_variant_probes("a@b.com", "https://tmpl", probes=probes)

    by_name = {r["probe"]: r for r in results}
    assert by_name["A"]["success"] is True
    assert by_name["C"]["success"] is True
    assert by_name["B"]["success"] is False
    assert by_name["B"]["error"] == "B blew up"


def test_launcher_supervisor_guard_records_thread_death(cbd, monkeypatch):
    # deploy_and_test_probe catches its own exceptions, but if a probe thread
    # dies hard the launcher must still record a failure rather than dropping
    # the probe from the summary.
    def fake_deploy(probe, admin_email, template_url):
        raise RuntimeError("thread died")

    monkeypatch.setattr(cbd, "deploy_and_test_probe", fake_deploy)
    probes = [_make_probe(cbd, name="A", suffix="a")]

    results = cbd.run_variant_probes("a@b.com", "https://tmpl", probes=probes)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["probe"] == "A"
    assert "thread died" in results[0]["error"]


def test_launcher_respects_concurrency_cap(cbd, monkeypatch):
    # With cap=2 and 4 probes, no more than 2 should ever run at once.
    monkeypatch.setenv("IDP_PROBE_MAX_CONCURRENCY", "2")
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    def fake_deploy(probe, admin_email, template_url):
        with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return {"stack_name": "s", "success": True, "probe": probe.name}

    monkeypatch.setattr(cbd, "deploy_and_test_probe", fake_deploy)
    probes = [_make_probe(cbd, name=str(i), suffix=str(i)) for i in range(4)]

    results = cbd.run_variant_probes("a@b.com", "https://tmpl", probes=probes)

    assert len(results) == 4
    assert state["peak"] <= 2, f"peak concurrency {state['peak']} exceeded cap 2"


def test_launcher_empty_table_is_noop(cbd, monkeypatch):
    monkeypatch.setattr(
        cbd,
        "deploy_and_test_probe",
        lambda *a, **k: pytest.fail("should not deploy with no probes"),
    )
    assert cbd.run_variant_probes("a@b.com", "https://tmpl", probes=[]) == []


# --------------------------------------------------------------------------- #
# The default probe table (regression guard on the migrated GLOBAL probe)
# --------------------------------------------------------------------------- #


def test_default_probe_table_has_global_apigw_row(cbd):
    names = [p.name for p in cbd.PROBE_VARIANTS]
    assert any("APIGateway" in n and "GLOBAL" in n for n in names)
    apigw = next(p for p in cbd.PROBE_VARIANTS if "APIGateway" in p.name)
    assert apigw.stack_suffix == "apigw"
    assert apigw.deploy_params == {
        "WebUIHosting": "APIGateway",
        "ApiGatewayVisibility": "GLOBAL",
    }
    assert apigw.validate_fn is cbd.validate_apigw_global_hosting
