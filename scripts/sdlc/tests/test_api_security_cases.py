"""Unit tests for scripts/api_security_cases.py — the mandatory security-focused
API test suites (IDOR, token lifecycle, deleted-resource, input validation, TLS).

These run WITHOUT any AWS/live API: the harness `call`/`record` callables and the
sign-out function are replaced with fakes, so we verify the suites' decision logic
(what counts as pass/fail, which checklist item each records, tolerant-vs-strict
input mode, and the WARN-not-FAIL treatment of the stateless-JWT logout gap).

api_security_cases.py lives in scripts/ (a quarantined pytest root because of the
live harness there), so we import it by file path like the other sdlc tests import
dispatcher code.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _load_sec():
    # scripts/sdlc/tests/ -> scripts/api_security_cases.py
    path = Path(__file__).resolve().parents[2] / "api_security_cases.py"
    spec = importlib.util.spec_from_file_location("api_security_cases", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sec = _load_sec()

CTX = {"api_base": "https://abc.execute-api.us-west-2.amazonaws.com/api"}


class _Recorder:
    """Captures _record(...) calls the way the harness stores them."""

    def __init__(self):
        self.rows = []

    def __call__(
        self,
        results,
        op,
        principal,
        status,
        passed,
        detail,
        et=None,
        in_band=None,
        request_id="",
        gap=None,
    ):
        row = {
            "op": op,
            "principal": principal,
            "http_status": status,
            "passed": bool(passed),
            "detail": detail,
            "known_gap": gap,
        }
        self.rows.append(row)
        results.append(row)

    def by_principal(self, needle):
        return [r for r in self.rows if needle in r["principal"]]


def _scripted_call(script):
    """Return a fake `call(api_base, field, args, token)` that pops (status, et,
    in_band, request_id) tuples from a per-(field) queue in `script`."""

    def _call(api_base, field, args, token):
        key = field
        q = script.get(key)
        if not q:
            return 200, None, None, "rid"
        return q.pop(0)

    return _call


# --------------------------------------------------------------------------- #
# IDOR (2.1)
# --------------------------------------------------------------------------- #
def test_idor_denied_when_userb_blocked():
    rec = _Recorder()
    results = []
    script = {
        "sendChatDocumentMessage": [(200, None, None, "r1")],  # A seeds session
        "getChatMessages": [
            (403, "Unauthorized", None, "r2"),  # B denied
            (200, None, None, "r4"),  # A reads own -> allowed
        ],
        "deleteChatSession": [(403, "Unauthorized", None, "r3")],  # B delete denied
    }
    sec.run_idor_suite(
        CTX, _scripted_call(script), rec, results, {"Admin": "a", "userB": "b"}
    )
    # B's read is recorded as passed (denied), A's read passed (allowed).
    b_read = rec.by_principal("userB(reads")[0]
    assert b_read["passed"] is True
    a_read = rec.by_principal("userA(reads own")[0]
    assert a_read["passed"] is True
    assert all("SEC-2.1-IDOR" in r["detail"] for r in rec.rows)


def test_idor_leak_when_userb_reads_as_200_with_data_is_still_ok_only_if_empty():
    # A 200 to User B counts as pass ONLY under the owner-scoped-empty semantics
    # documented in the module. This test pins that behavior so a future change
    # that makes 200 a leak is a conscious decision.
    rec = _Recorder()
    results = []
    script = {
        "sendChatDocumentMessage": [(200, None, None, "r1")],
        "getChatMessages": [(200, None, None, "r2"), (200, None, None, "r4")],
        "deleteChatSession": [(404, None, None, "r3")],
    }
    sec.run_idor_suite(
        CTX, _scripted_call(script), rec, results, {"Admin": "a", "userB": "b"}
    )
    assert rec.by_principal("userB(reads")[0]["passed"] is True


def test_idor_skips_without_second_user():
    rec = _Recorder()
    results = []
    sec.run_idor_suite(CTX, _scripted_call({}), rec, results, {"Admin": "a"})
    assert len(rec.rows) == 1 and rec.rows[0]["http_status"] == "SKIP"
    assert rec.rows[0]["passed"] is True


# --------------------------------------------------------------------------- #
# Token lifecycle (2.3 / 2.4)
# --------------------------------------------------------------------------- #
def test_expired_token_rejected():
    rec = _Recorder()
    results = []
    script = {"listDocuments": [(401, None, None, "r")]}
    sec.run_token_lifecycle_suite(
        CTX,
        _scripted_call(script),
        rec,
        results,
        expired_token="expired",
        logout_token=None,
        logout_email=None,
        sign_out_fn=None,
    )
    exp = rec.by_principal("token:expired")[0]
    assert exp["passed"] is True and "SEC-2.3" in exp["detail"]


def test_logout_still_accepted_is_warn_not_fail():
    # Stateless JWT: token still works after global sign-out -> passed=False but
    # tagged with a known_gap so it's a WARN, not a hard fail.
    rec = _Recorder()
    results = []
    signed_out = {}
    script = {
        "listDocuments": [
            (200, None, None, "before"),  # works before logout
            (200, None, None, "after"),  # STILL works after logout
        ]
    }
    sec.run_token_lifecycle_suite(
        CTX,
        _scripted_call(script),
        rec,
        results,
        expired_token=None,
        logout_token="t",
        logout_email="u@x.invalid",
        sign_out_fn=lambda e: signed_out.setdefault("called", e),
    )
    assert signed_out["called"] == "u@x.invalid"
    row = rec.by_principal("token:post-logout")[0]
    assert row["passed"] is False
    assert row["known_gap"] == "GAP-SEC-LOGOUT"  # WARN, not hard fail


def test_logout_revoked_is_pass_no_gap():
    rec = _Recorder()
    results = []
    script = {
        "listDocuments": [(200, None, None, "before"), (401, None, None, "after")]
    }
    sec.run_token_lifecycle_suite(
        CTX,
        _scripted_call(script),
        rec,
        results,
        expired_token=None,
        logout_token="t",
        logout_email="u@x.invalid",
        sign_out_fn=lambda e: None,
    )
    row = rec.by_principal("token:post-logout")[0]
    assert row["passed"] is True and row["known_gap"] is None


# --------------------------------------------------------------------------- #
# Deleted resource (2.5)
# --------------------------------------------------------------------------- #
def test_deleted_resource_gone_passes():
    rec = _Recorder()
    results = []
    script = {
        "updateConfiguration": [(200, None, None, "c")],  # create
        "getConfigVersion": [
            (200, None, None, "g1"),  # present before
            (404, None, None, "g2"),
        ],  # gone after
        "deleteConfigVersion": [(200, None, None, "d")],  # delete
    }
    sec.run_deleted_resource_suite(
        CTX, _scripted_call(script), rec, results, {"Admin": "a"}
    )
    row = rec.by_principal("after-delete")[0]
    assert row["passed"] is True and "SEC-2.5" in row["detail"]


def test_deleted_resource_still_readable_fails():
    rec = _Recorder()
    results = []
    script = {
        "updateConfiguration": [(200, None, None, "c")],
        "getConfigVersion": [
            (200, None, None, "g1"),
            (200, None, None, "g2"),
        ],  # STILL readable -> leak
        "deleteConfigVersion": [(200, None, None, "d")],
    }
    sec.run_deleted_resource_suite(
        CTX, _scripted_call(script), rec, results, {"Admin": "a"}
    )
    assert rec.by_principal("after-delete")[0]["passed"] is False


# --------------------------------------------------------------------------- #
# Input validation (3) — tolerant vs strict
# --------------------------------------------------------------------------- #
def test_input_validation_tolerant_accepts_500():
    # Pre-PR-B: a 5xx on malformed input is a documented weakness (WARN), not a
    # hard fail, in tolerant mode.
    rec = _Recorder()
    results = []
    # Every op returns 500 (resolver blew up on bad shape).
    call = lambda ab, f, a, t: (500, None, None, "r")  # noqa: E731
    sec.run_input_validation_suite(
        CTX, call, rec, results, {"Admin": "a"}, strict=False
    )
    rows = [r for r in rec.rows if r["op"] != "input-validation"]
    assert rows, "expected malformed-input cases to be recorded"
    assert all(r["passed"] for r in rows)  # tolerated
    assert all(r["known_gap"] == "GAP-SEC-INPUT-500" for r in rows)  # but WARNed


def test_input_validation_strict_requires_clean_4xx():
    rec = _Recorder()
    results = []
    call = lambda ab, f, a, t: (500, None, None, "r")  # noqa: E731
    sec.run_input_validation_suite(CTX, call, rec, results, {"Admin": "a"}, strict=True)
    rows = [r for r in rec.rows if r["op"] != "input-validation"]
    assert rows and all(not r["passed"] for r in rows)  # 500 fails in strict mode


def test_input_validation_clean_400_passes_both_modes():
    for strict in (False, True):
        rec = _Recorder()
        results = []
        call = lambda ab, f, a, t: (400, "BadRequest", None, "r")  # noqa: E731
        sec.run_input_validation_suite(
            CTX, call, rec, results, {"Admin": "a"}, strict=strict
        )
        rows = [r for r in rec.rows if r["op"] != "input-validation"]
        assert rows and all(r["passed"] for r in rows)


def test_input_validation_silent_200_always_fails():
    rec = _Recorder()
    results = []
    call = lambda ab, f, a, t: (200, None, None, "r")  # noqa: E731
    sec.run_input_validation_suite(
        CTX, call, rec, results, {"Admin": "a"}, strict=False
    )
    rows = [r for r in rec.rows if r["op"] != "input-validation"]
    assert rows and all(not r["passed"] for r in rows)  # 200 = silent accept = fail


# --------------------------------------------------------------------------- #
# TLS (4) — helper logic (no network; monkeypatch the socket layer)
# --------------------------------------------------------------------------- #
def test_tls_suite_records_all_expected_checks(monkeypatch):
    # Force the low-level probes to deterministic outcomes.
    monkeypatch.setattr(sec, "_tls_refused", lambda h, p, v: (True, "handshake failed"))
    monkeypatch.setattr(
        sec, "_tls_accepted", lambda h, p, v: (True, "negotiated TLSv1.2")
    )
    monkeypatch.setattr(sec, "_http_refused", lambda h: (True, "no cleartext service"))
    rec = _Recorder()
    results = []
    sec.run_tls_suite(CTX, rec, results)
    labels = {r["principal"] for r in rec.rows}
    assert {"TLS1.0", "TLS1.1", "TLS1.2", "plaintext-http"} <= labels
    assert all(r["passed"] for r in rec.rows)
    assert all("SEC-4-TLS" in r["detail"] for r in rec.rows)


def test_tls_weak_protocol_accepted_fails(monkeypatch):
    monkeypatch.setattr(sec, "_tls_refused", lambda h, p, v: (False, "ACCEPTED"))
    monkeypatch.setattr(sec, "_tls_accepted", lambda h, p, v: (True, "ok"))
    monkeypatch.setattr(sec, "_http_refused", lambda h: (True, "no service"))
    rec = _Recorder()
    results = []
    sec.run_tls_suite(CTX, rec, results)
    weak = [r for r in rec.rows if r["principal"] in ("TLS1.0", "TLS1.1")]
    assert weak and all(not r["passed"] for r in weak)  # weak TLS accepted = fail
