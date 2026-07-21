"""Unit tests for the OWASP ZAP DAST probe.

Exercise the pure/seed/parse logic of the ZAP probe in
`scripts/sdlc/codebuild_deployment.py` WITHOUT any AWS, Docker, or subprocess
calls (rbac_common, run_command, and the report upload are monkeypatched). They
verify the behaviors that are easy to regress on:

  * the probe is registered in PROBE_VARIANTS and is NOT a VPC probe (a PRIVATE
    API would be unreachable from CodeBuild),
  * IDP_TEST_ZAP=false removes only the ZAP probe from the launcher,
  * the OpenAPI seed emits one POST /op/{field} path per operation in
    api_rbac_expectations.yaml, hung under the api_base's path + host,
  * the ZAP JSON report parser maps riskcode → human labels + counts, and
  * validate_zap_dast stays WARN-only (success=True even with High findings)
    and always restores the app-client auth flow + deletes its test user.
"""

import json

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_launch_stagger(monkeypatch):
    """Disable the probe launch stagger so the run_variant_probes tests here
    don't sleep index*DEFAULT_PROBE_LAUNCH_STAGGER_SECS (120s) — the gating
    tests (IDP_TEST_ZAP true/false) call the real launcher."""
    monkeypatch.setenv("IDP_PROBE_LAUNCH_STAGGER_SECS", "0")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_zap_probe_registered_and_not_vpc(cbd):
    zap = [p for p in cbd.PROBE_VARIANTS if p.stack_suffix == "zapdast"]
    assert len(zap) == 1, "exactly one ZAP DAST probe expected"
    probe = zap[0]
    assert probe.validate_fn is cbd.validate_zap_dast
    # Must be internet-reachable from CodeBuild → default hosting, NOT a VPC/
    # PRIVATE API (which CodeBuild can't reach).
    assert probe.requires_vpc is False
    assert probe.deploy_params == {}


def test_default_concurrency_still_covers_all_probes(cbd):
    # Adding the ZAP probe must not silently serialize the pool.
    assert cbd.DEFAULT_PROBE_MAX_CONCURRENCY >= len(cbd.PROBE_VARIANTS)


# --------------------------------------------------------------------------- #
# IDP_TEST_ZAP gate
# --------------------------------------------------------------------------- #


def test_idp_test_zap_false_skips_only_zap(cbd, monkeypatch):
    monkeypatch.setenv("IDP_TEST_ZAP", "false")
    launched = []
    monkeypatch.setattr(
        cbd,
        "deploy_and_test_probe",
        lambda probe, email, url: (
            launched.append(probe.stack_suffix)
            or {"success": True, "probe": probe.name}
        ),
    )
    cbd.run_variant_probes("admin@example.invalid", "https://tmpl")
    assert "zapdast" not in launched
    # The other probes still ran.
    assert "apigw" in launched


def test_idp_test_zap_true_includes_zap(cbd, monkeypatch):
    monkeypatch.setenv("IDP_TEST_ZAP", "true")
    launched = []
    monkeypatch.setattr(
        cbd,
        "deploy_and_test_probe",
        lambda probe, email, url: (
            launched.append(probe.stack_suffix)
            or {"success": True, "probe": probe.name}
        ),
    )
    cbd.run_variant_probes("admin@example.invalid", "https://tmpl")
    assert "zapdast" in launched


# --------------------------------------------------------------------------- #
# OpenAPI seed generation
# --------------------------------------------------------------------------- #


def test_generate_zap_openapi_one_path_per_op(cbd):
    api_base = "https://abc123.execute-api.us-east-1.amazonaws.com/api"
    fields = ["getDocument", "listDocuments", "deleteConfiguration"]
    spec = cbd.generate_zap_openapi(api_base, fields)

    assert spec["openapi"].startswith("3.")
    # Server is scheme+host; path prefix stays on each path.
    assert spec["servers"] == [
        {"url": "https://abc123.execute-api.us-east-1.amazonaws.com"}
    ]
    assert set(spec["paths"]) == {
        "/api/op/getDocument",
        "/api/op/listDocuments",
        "/api/op/deleteConfiguration",
    }
    op = spec["paths"]["/api/op/getDocument"]["post"]
    assert op["operationId"] == "getDocument"
    body = op["requestBody"]["content"]["application/json"]
    assert body["example"] == {"arguments": {}}


def test_zap_op_fields_reads_expectations(cbd):
    # Reads the real repo file — asserts it is non-empty and includes a known op.
    fields = cbd._zap_op_fields()
    assert isinstance(fields, list) and fields
    assert "getDocument" in fields
    # Sorted for determinism.
    assert fields == sorted(fields)


# --------------------------------------------------------------------------- #
# ZAP JSON report parsing
# --------------------------------------------------------------------------- #


def test_parse_zap_alerts_maps_riskcode_to_labels(cbd, tmp_path):
    report = {
        "site": [
            {
                "alerts": [
                    {
                        "alert": "XSS",
                        "riskcode": "3",
                        "pluginid": "40012",
                        "instances": [{}, {}],
                    },
                    {
                        "alert": "CSP missing",
                        "riskcode": "2",
                        "pluginid": "10038",
                        "count": "1",
                    },
                    {
                        "alert": "Timestamp",
                        "riskcode": "0",
                        "pluginid": "10096",
                        "instances": [],
                    },
                ]
            }
        ]
    }
    path = tmp_path / "zap-report.json"
    path.write_text(json.dumps(report))
    counts, alerts = cbd._parse_zap_alerts(str(path))

    assert counts == {"High": 1, "Medium": 1, "Low": 0, "Informational": 1}
    high = next(a for a in alerts if a["risk"] == "High")
    assert high["name"] == "XSS" and high["count"] == 2


def test_parse_zap_alerts_empty_report(cbd, tmp_path):
    path = tmp_path / "zap-report.json"
    path.write_text(json.dumps({"site": []}))
    counts, alerts = cbd._parse_zap_alerts(str(path))
    assert counts == {"High": 0, "Medium": 0, "Low": 0, "Informational": 0}
    assert alerts == []


def test_parse_zap_alerts_drops_ignored_plugin_ids(cbd, tmp_path):
    # Informational alerts still appear in the JSON even when IGNORE'd in
    # zap-rules.conf (the -c file only gates WARN/FAIL/PASS). The parser must
    # apply the IGNORE list so the report matches intent.
    report = {
        "site": [
            {
                "alerts": [
                    {"alert": "CSP", "riskcode": "2", "pluginid": "10038", "count": 1},
                    {
                        "alert": "Non-Storable Content",
                        "riskcode": "0",
                        "pluginid": "10049",
                        "count": 5,
                    },
                    {
                        "alert": "Client Error",
                        "riskcode": "0",
                        "pluginid": "100000",
                        "count": 72,
                    },
                ]
            }
        ]
    }
    path = tmp_path / "zap-report.json"
    path.write_text(json.dumps(report))
    counts, alerts = cbd._parse_zap_alerts(str(path), ignore_ids={"10049", "100000"})
    # The two IGNORE'd info alerts are gone from both counts and the list.
    assert counts["Informational"] == 0
    assert counts["Medium"] == 1
    assert [a["name"] for a in alerts] == ["CSP"]


def test_zap_ignored_plugin_ids_reads_rules_conf(cbd):
    # Reads the real repo zap-rules.conf; must include the ids we IGNORE.
    ids = cbd._zap_ignored_plugin_ids(cbd.ZAP_RULES_CONF)
    assert {"10049", "100000", "10096"} <= ids


def test_persist_zap_report_copies_to_report_dir(cbd, tmp_path, monkeypatch):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "zap-report.html").write_text("<html>")
    (workdir / "zap-report.json").write_text("{}")
    dest = tmp_path / "out"
    monkeypatch.setenv("IDP_ZAP_REPORT_DIR", str(dest))
    out = cbd._persist_zap_report(str(workdir))
    assert out["zap-report.html"] == str((dest / "zap-report.html").resolve())
    assert (dest / "zap-report.html").exists()
    assert (dest / "zap-report.json").exists()


def test_persist_zap_report_falls_back_to_workdir(cbd, tmp_path, monkeypatch):
    # No IDP_ZAP_REPORT_DIR → returns the workdir paths (not deleted) so the
    # report can still be pointed at.
    monkeypatch.delenv("IDP_ZAP_REPORT_DIR", raising=False)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "zap-report.html").write_text("<html>")
    out = cbd._persist_zap_report(str(workdir))
    assert out["zap-report.html"] == str((workdir / "zap-report.html").resolve())


def test_parse_zap_rule_tally_reads_summary_line(cbd):
    # The report should surface EVERY rule outcome (114 PASS is as meaningful as
    # the 3 WARN), parsed from zap-api-scan's stdout tally line.
    stdout = (
        "some log...\n"
        "FAIL-NEW: 0\tFAIL-INPROG: 0\tWARN-NEW: 3\tWARN-INPROG: 0\t"
        "INFO: 0\tIGNORE: 1\tPASS: 114\n"
        "...more log\n"
    )
    tally = cbd._parse_zap_rule_tally(stdout)
    assert tally["PASS"] == 114
    assert tally["WARN-NEW"] == 3
    assert tally["FAIL-NEW"] == 0
    assert tally["IGNORE"] == 1


def test_parse_zap_rule_tally_absent_returns_empty(cbd):
    assert cbd._parse_zap_rule_tally("no tally here") == {}
    assert cbd._parse_zap_rule_tally("") == {}


# --------------------------------------------------------------------------- #
# validate_zap_dast: WARN-only + always-restore
# --------------------------------------------------------------------------- #


class _FakeRbac:
    """Stand-in for the rbac_common module the probe imports."""

    def __init__(self):
        self.restored = False
        self.deleted = None

    def resolve_stack(self, stack, region):
        return {
            "stack": stack,
            "region": region,
            "user_pool": "pool",
            "client": "client",
            "api_base": "https://abc.execute-api.us-east-1.amazonaws.com/api",
            "users_table": "users",
            "circuit_breaker": False,
        }

    def enable_admin_auth(self, ctx):
        pass

    def create_cognito_user(self, ctx, email, group, password):
        pass

    def get_id_token(self, ctx, email, password):
        return "fake.jwt.token"

    def delete_cognito_user(self, ctx, email):
        self.deleted = email

    def restore_auth_flows(self, ctx):
        self.restored = True


def _install_fake_rbac(cbd, monkeypatch, fake):
    import sys

    monkeypatch.setitem(sys.modules, "rbac_common", fake)


def test_validate_zap_dast_warn_only_with_high_findings(cbd, monkeypatch, tmp_path):
    fake = _FakeRbac()
    _install_fake_rbac(cbd, monkeypatch, fake)

    # Docker/scan is a no-op; write a report with a High finding into the workdir.
    def fake_run_command(cmd, check=True, timeout=None):
        # The Docker-availability preflight must pass so we reach the scan.
        if cmd.strip() == "docker info":
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        # The workdir is the -v mount source in the docker cmd.
        workdir = cmd.split("-v ", 1)[1].split(":", 1)[0]
        report = {
            "site": [
                {
                    "alerts": [
                        {
                            "alert": "SQLi",
                            "riskcode": "3",
                            "pluginid": "40018",
                            "instances": [{}],
                        },
                    ]
                }
            ]
        }
        with open(f"{workdir}/zap-report.json", "w") as fh:
            json.dump(report, fh)
        return type("R", (), {"returncode": 2, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(cbd, "run_command", fake_run_command)
    monkeypatch.setattr(cbd, "_upload_zap_report", lambda s, w: "s3://b/zap.html")

    result = cbd.validate_zap_dast("idp-test-zapdast")

    # WARN-only: High findings do NOT fail the probe.
    assert result["success"] is True
    assert result["zap_alerts"]["High"] == 1
    assert result["report_url"] == "s3://b/zap.html"
    # Always cleaned up the auth-flow flip + test user.
    assert fake.restored is True
    assert fake.deleted == "zap-dast@example.invalid"


def test_validate_zap_dast_restores_on_error(cbd, monkeypatch):
    fake = _FakeRbac()
    _install_fake_rbac(cbd, monkeypatch, fake)

    # Preflight passes (docker available); the SCAN blows up AFTER auth was enabled.
    def boom(cmd, check=True, timeout=None):
        if cmd.strip() == "docker info":
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        raise RuntimeError("docker exploded")

    monkeypatch.setattr(cbd, "run_command", boom)

    result = cbd.validate_zap_dast("idp-test-zapdast")
    assert result["success"] is False
    assert "docker exploded" in result["error"]
    # Even on error, the app client auth flow is restored and the user removed.
    assert fake.restored is True
    assert fake.deleted == "zap-dast@example.invalid"


def test_validate_zap_dast_skips_when_docker_unavailable(cbd, monkeypatch):
    # No Docker daemon (PrivilegedMode not deployed) -> SKIP, not FAIL, and never
    # touches Cognito (preflight returns before user/token setup).
    fake = _FakeRbac()
    _install_fake_rbac(cbd, monkeypatch, fake)

    def no_docker(cmd, check=True, timeout=None):
        assert cmd.strip() == "docker info", f"should not run {cmd!r} without docker"
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "no daemon"})()

    monkeypatch.setattr(cbd, "run_command", no_docker)

    result = cbd.validate_zap_dast("idp-test-zapdast")
    assert result["success"] is True and result["skipped"] is True
    assert "Docker daemon unavailable" in result["detail"]
    # Preflight ran before any auth mutation, so nothing to restore/delete.
    assert fake.restored is False and fake.deleted is None


def test_validate_zap_dast_skips_when_no_report(cbd, monkeypatch, tmp_path):
    # Daemon up but the scan produced no report (e.g. image pull failed) -> SKIP,
    # and still restore auth flow + delete the test user.
    fake = _FakeRbac()
    _install_fake_rbac(cbd, monkeypatch, fake)

    def fake_run_command(cmd, check=True, timeout=None):
        # docker info passes; the scan runs but writes NO report file.
        rc = 0 if cmd.strip() == "docker info" else 1
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(cbd, "run_command", fake_run_command)

    result = cbd.validate_zap_dast("idp-test-zapdast")
    assert result["success"] is True and result["skipped"] is True
    assert "no JSON report" in result["detail"]
    assert fake.restored is True
    assert fake.deleted == "zap-dast@example.invalid"


def test_validate_zap_dast_workdir_is_world_writable(cbd, monkeypatch):
    # PROVEN root cause (verified in real CodeBuild): the bind-mounted workdir is
    # root-owned, but the ZAP image runs zap-api-scan.py as the non-root `zap`
    # user, which cannot write the report → PermissionError → no report → skip.
    # The workdir MUST be world-writable (0o777) so the container can write it.
    import os
    import stat

    fake = _FakeRbac()
    _install_fake_rbac(cbd, monkeypatch, fake)

    seen = {}

    def fake_run_command(cmd, check=True, timeout=None):
        if cmd.strip() == "docker info":
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        # Capture the mount source (== workdir) and its perms at scan time, then
        # write a report (as the "container" would once it can write).
        mount_src = cmd.split("-v ", 1)[1].split(":", 1)[0]
        seen["mode"] = stat.S_IMODE(os.stat(mount_src).st_mode)
        with open(f"{mount_src}/zap-report.json", "w") as fh:
            json.dump({"site": []}, fh)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(cbd, "run_command", fake_run_command)
    monkeypatch.setattr(cbd, "_upload_zap_report", lambda s, w: "")

    result = cbd.validate_zap_dast("idp-test-zapdast")
    assert result["success"] is True
    # World-writable so the container's non-root `zap` user can write the report.
    assert seen["mode"] & 0o002, (
        f"workdir mode {oct(seen['mode'])} is not world-writable"
    )
