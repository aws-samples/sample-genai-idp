"""Unit tests for _CredentialRefresher — the monitor's mid-run cred refresh.

The GitLab monitor's creds are a role-chained assume of idp-sdlc-GitLab, which
AWS hard-caps at 1h. To watch a >1h pipeline, the monitor re-assumes the role
(a fresh 1h session) before expiry and rebuilds its boto3 clients. These tests
mock STS/boto3 so no AWS is touched, and pin: role-ARN resolution from the
account id, a successful refresh swaps in the new session creds, build_clients
uses the current creds, and a refresh failure is swallowed (→ graceful handoff
fallback) rather than raising.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def itd():
    import integration_test_deployment as module

    return module


class _FakeSTS:
    def __init__(self, account="020432867916", fail=False):
        self._account = account
        self._fail = fail
        self.assume_calls = []

    def get_caller_identity(self):
        return {"Account": self._account}

    def assume_role(self, **kwargs):
        self.assume_calls.append(kwargs)
        if self._fail:
            raise RuntimeError("AccessDenied: not authorized to assume")
        return {
            "Credentials": {
                "AccessKeyId": "AKIA-NEW",
                "SecretAccessKey": "secret-new",
                "SessionToken": "token-new",
            }
        }


def _patch_boto3(itd, monkeypatch, sts, client_recorder=None):
    def fake_client(name, *a, **k):
        if name == "sts":
            return sts
        if client_recorder is not None:
            client_recorder.append((name, k))
        return object()

    monkeypatch.setattr(itd.boto3, "client", fake_client)


def test_resolves_role_arn_from_account(itd, monkeypatch):
    _patch_boto3(itd, monkeypatch, _FakeSTS(account="111122223333"))
    r = itd._CredentialRefresher("us-east-1")
    assert r._role_arn == "arn:aws:iam::111122223333:role/idp-sdlc-GitLab"


def test_refresh_success_swaps_in_new_creds(itd, monkeypatch):
    sts = _FakeSTS()
    _patch_boto3(itd, monkeypatch, sts)
    r = itd._CredentialRefresher("us-east-1")
    assert r.refresh() is True
    # subsequent STS/client construction uses the new session creds
    assert r._session_kwargs["aws_access_key_id"] == "AKIA-NEW"
    assert r._session_kwargs["aws_session_token"] == "token-new"
    # requested a chained-max 1h session
    assert sts.assume_calls[-1]["DurationSeconds"] == 3600
    assert sts.assume_calls[-1]["RoleArn"].endswith(":role/idp-sdlc-GitLab")


def test_build_clients_uses_current_creds(itd, monkeypatch):
    recorder = []
    sts = _FakeSTS()
    _patch_boto3(itd, monkeypatch, sts, client_recorder=recorder)
    r = itd._CredentialRefresher("us-west-2")
    r.refresh()
    cp, logs = r.build_clients()
    # both clients built with region + the refreshed creds
    names = [n for n, _ in recorder]
    assert "codepipeline" in names and "logs" in names
    for _, kw in recorder:
        assert kw.get("region_name") == "us-west-2"
        assert kw.get("aws_access_key_id") == "AKIA-NEW"


def test_refresh_failure_is_swallowed(itd, monkeypatch):
    sts = _FakeSTS(fail=True)
    _patch_boto3(itd, monkeypatch, sts)
    r = itd._CredentialRefresher("us-east-1")
    # must return False (→ caller keeps old clients, hands off later), not raise
    assert r.refresh() is False
    # creds unchanged (still ambient)
    assert r._session_kwargs == {}


def test_refresh_noop_when_role_arn_unresolved(itd, monkeypatch):
    # If get_caller_identity fails at construction, role_arn is None and
    # refresh() is a safe no-op returning False.
    class _BoomSTS:
        def get_caller_identity(self):
            raise RuntimeError("no creds")

    monkeypatch.setattr(itd.boto3, "client", lambda name, *a, **k: _BoomSTS())
    r = itd._CredentialRefresher("us-east-1")
    assert r._role_arn is None
    assert r.refresh() is False


def test_handoff_constants_allow_watching_past_one_hour(itd):
    # The whole point: handoff deadline exceeds the 1h chained-cred cap, and we
    # refresh before that cap.
    assert itd.MONITOR_HANDOFF_SECONDS > 3600
    assert itd.CREDENTIAL_REFRESH_SECONDS < 3600


class _ExpiredTokenException(Exception):
    """Mimic botocore's ExpiredTokenException by name (that's what we match)."""


def _drive_monitor(itd, monkeypatch, verdict):
    """Run monitor_pipeline_execution with a codepipeline that raises
    ExpiredTokenException on every poll, and a stubbed S3 verdict."""
    # A refresher whose refresh() always fails (the real-world bug: TagSession
    # denied) and whose clients raise expired-token on every call.
    class _ExpiredCP:
        def get_pipeline_execution(self, **k):
            raise _ExpiredTokenException("The security token ... is expired")

    class _FakeRefresher:
        def __init__(self, region):
            pass

        def refresh(self):
            return False

        def build_clients(self):
            return _ExpiredCP(), object()

    monkeypatch.setattr(itd, "_CredentialRefresher", _FakeRefresher)
    monkeypatch.setattr(itd, "resolve_codebuild_log_stream", lambda *a, **k: "stream-x")
    monkeypatch.setattr(itd, "fetch_summary_verdict", lambda *a, **k: verdict)
    monkeypatch.setattr(itd.time, "sleep", lambda *_a, **_k: None)
    # Force the handoff/refresh windows past so we exercise the expired branch
    # immediately on the first poll.
    return itd.monitor_pipeline_execution(
        "pipe", "exec-1", max_wait=120, handoff_after=999999
    )


def test_expired_creds_hand_off_neutral_when_no_fail_verdict(itd, monkeypatch):
    # A HEALTHY run whose creds expire mid-flight must NOT be failed: with no
    # OVERALL: FAIL in the summary, the monitor exits neutral (None), not False.
    assert _drive_monitor(itd, monkeypatch, verdict=None) is None
    assert _drive_monitor(itd, monkeypatch, verdict=True) is None


def test_expired_creds_still_fail_on_overall_fail_verdict(itd, monkeypatch):
    # But if the authoritative S3 summary already says OVERALL: FAIL, the
    # expired-creds path must still fail the job.
    assert _drive_monitor(itd, monkeypatch, verdict=False) is False
