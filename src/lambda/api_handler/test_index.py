"""Unit tests for jobs_api Lambda function."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add idp_common to path and import real Status
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../lib/idp_common_pkg"))
from idp_common.models import Status

# Mock idp_common before importing index
mock_document_service = MagicMock()
mock_job_service = MagicMock()
mock_docs_service_module = MagicMock()
mock_docs_service_module.create_document_service = MagicMock(return_value=mock_document_service)
mock_job_service_module = MagicMock()
mock_job_service_module.create_job_service = MagicMock(return_value=mock_job_service)
mock_models_module = MagicMock()
mock_models_module.Status = Status

sys.modules["idp_common"] = MagicMock()
sys.modules["idp_common.docs_service"] = mock_docs_service_module
sys.modules["idp_common.job_service"] = mock_job_service_module
sys.modules["idp_common.models"] = mock_models_module
sys.modules["idp_common.dynamodb"] = MagicMock()
sys.modules["idp_common.dynamodb.job_service"] = MagicMock()


@pytest.fixture(autouse=True)
def mock_env():
    """Set up environment variables for tests."""
    env_vars = {
        "STAGING_BUCKET_NAME": "test-staging-bucket",
        "OUTPUT_BUCKET_NAME": "test-output-bucket",
        "TRACKING_TABLE": "test-table",
        "DATA_RETENTION_IN_DAYS": "30",
        "MAX_FILE_SIZE_BYTES": "5368709120",
        "PRESIGNED_URL_EXPIRY_SECONDS": "900",
    }
    with patch.dict(os.environ, env_vars):
        yield


@pytest.fixture
def lambda_context():
    """Mock Lambda context."""
    context = MagicMock()
    context.request_id = "test-request-id"
    return context


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch("index.s3_client") as mock:
        yield mock


@pytest.fixture
def job_svc():
    """Reset and return mock job service."""
    mock_job_service.reset_mock()
    with patch("index.job_service", mock_job_service):
        yield mock_job_service


class TestGetContentType:
    """Tests for get_content_type function."""

    def test_zip_content_type(self):
        """Test ZIP content type detection."""
        from index import get_content_type

        assert get_content_type("archive.zip") == "application/zip"
        assert get_content_type("ARCHIVE.ZIP") == "application/zip"

    def test_unsupported_file_type(self):
        """Test unsupported file type raises ValueError."""
        from index import get_content_type

        with pytest.raises(ValueError, match="Unsupported file type"):
            get_content_type("document.pdf")
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_content_type("document.txt")


class TestComputeJobStatus:
    """Tests for compute_job_status function."""

    def test_empty_files(self):
        """Test empty files returns PENDING_UPLOAD."""
        from index import compute_job_status

        assert compute_job_status({}) == "PENDING_UPLOAD"

    def test_all_completed(self):
        """Test all COMPLETED returns SUCCEEDED."""
        from index import compute_job_status

        files = {"a.pdf": Status.COMPLETED, "b.pdf": Status.COMPLETED}
        assert compute_job_status(files) == "SUCCEEDED"

    def test_all_failed(self):
        """Test all FAILED returns FAILED."""
        from index import compute_job_status

        files = {"a.pdf": Status.FAILED, "b.pdf": Status.FAILED}
        assert compute_job_status(files) == "FAILED"

    def test_all_aborted(self):
        """Test all ABORTED returns ABORTED."""
        from index import compute_job_status

        files = {"a.pdf": Status.ABORTED, "b.pdf": Status.ABORTED}
        assert compute_job_status(files) == "ABORTED"

    def test_mixed_terminal(self):
        """Test mixed terminal states returns PARTIALLY_SUCCEEDED."""
        from index import compute_job_status

        files = {"a.pdf": Status.COMPLETED, "b.pdf": Status.FAILED}
        assert compute_job_status(files) == "PARTIALLY_SUCCEEDED"

    def test_in_progress(self):
        """Test non-terminal states returns IN_PROGRESS."""
        from index import compute_job_status

        files = {"a.pdf": Status.COMPLETED, "b.pdf": Status.IN_PROGRESS}
        assert compute_job_status(files) == "IN_PROGRESS"

        files = {"a.pdf": Status.IN_PROGRESS, "b.pdf": Status.IN_PROGRESS}
        assert compute_job_status(files) == "IN_PROGRESS"


class TestEnrichStatuses:
    """Tests for enrich_file_statuses function."""

    def test_no_pending_files(self):
        """Test returns unchanged when no IN_PROGRESS files."""
        import index

        files = {"a.pdf": Status.COMPLETED, "b.pdf": Status.FAILED}
        result = index.enrich_file_statuses("job-123", files)

        assert result == {"a.pdf": Status.COMPLETED, "b.pdf": Status.FAILED}

    def test_enriches_in_progress_files(self):
        """Test enriches IN_PROGRESS files with actual status."""
        import index

        index.document_service.batch_get_documents.return_value = [
            {"document_id": "jobs/job-123/a.pdf", "status": "EXTRACTING"},
            {"document_id": "jobs/job-123/b.pdf", "status": "CLASSIFYING"},
        ]

        files = {"a.pdf": Status.IN_PROGRESS, "b.pdf": Status.IN_PROGRESS, "c.pdf": Status.COMPLETED}
        result = index.enrich_file_statuses("job-123", files)

        assert result == {"a.pdf": Status.EXTRACTING, "b.pdf": Status.CLASSIFYING, "c.pdf": Status.COMPLETED}

    def test_keeps_in_progress_if_doc_not_found(self):
        """Test keeps IN_PROGRESS if document record not found."""
        import index

        index.document_service.batch_get_documents.return_value = [
            {"document_id": "jobs/job-123/a.pdf", "status": "EXTRACTING"},
        ]

        files = {"a.pdf": Status.IN_PROGRESS, "b.pdf": Status.IN_PROGRESS}
        result = index.enrich_file_statuses("job-123", files)

        assert result == {"a.pdf": Status.EXTRACTING, "b.pdf": Status.IN_PROGRESS}

    def test_preserves_terminal_states(self):
        """Test does not query for terminal state files."""
        import index

        index.document_service.batch_get_documents.reset_mock()
        files = {"a.pdf": Status.COMPLETED, "b.pdf": Status.FAILED, "c.pdf": Status.ABORTED}
        result = index.enrich_file_statuses("job-123", files)

        assert result == {"a.pdf": Status.COMPLETED, "b.pdf": Status.FAILED, "c.pdf": Status.ABORTED}
        index.document_service.batch_get_documents.assert_not_called()


class TestCreateJob:
    """Tests for POST /jobs endpoint."""

    def test_create_job_success(self, mock_s3, job_svc, lambda_context):
        """Test successful job creation with ZIP file."""
        from index import handler

        mock_s3.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com",
            "fields": {"key": "jobs/test-uuid/archive.zip", "Content-Type": "application/zip"},
        }

        event = {
            "httpMethod": "POST",
            "path": "/jobs",
            "body": json.dumps({"fileName": "archive.zip"}),
        }

        with patch("index.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = MagicMock(__str__=lambda s: "test-uuid")
            response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["jobId"] == "test-uuid"
        assert body["upload"]["uploadUrl"] == "https://test-bucket.s3.amazonaws.com"

        job_svc.create_job_record.assert_called_once()

    def test_create_job_missing_filename(self, mock_s3, job_svc, lambda_context):
        """Test job creation with missing fileName field."""
        from index import handler

        event = {"httpMethod": "POST", "path": "/jobs", "body": json.dumps({})}

        response = handler(event, lambda_context)
        assert response["statusCode"] == 422

    def test_create_job_unsupported_file_type(self, mock_s3, job_svc, lambda_context):
        """Test job creation with unsupported file type."""
        from index import handler

        event = {
            "httpMethod": "POST",
            "path": "/jobs",
            "body": json.dumps({"fileName": "document.pdf"}),
        }

        response = handler(event, lambda_context)
        assert response["statusCode"] == 400

    def test_create_job_with_metadata(self, mock_s3, job_svc, lambda_context):
        """Test job creation with metadata."""
        from index import handler

        mock_s3.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com",
            "fields": {"key": "test-key"},
        }

        event = {
            "httpMethod": "POST",
            "path": "/jobs",
            "body": json.dumps({
                "fileName": "archive.zip",
                "metadata": {"source": "test-system"},
            }),
        }

        with patch("index.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = MagicMock(__str__=lambda s: "test-uuid")
            response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        call_kwargs = job_svc.create_job_record.call_args[1]
        assert call_kwargs["metadata"] == {"source": "test-system"}

    def test_create_job_records_created_by_from_authorizer_claims(
        self, mock_s3, job_svc, lambda_context
    ):
        """POST /jobs persists the Cognito principal (sub) as CreatedBy."""
        from index import handler

        mock_s3.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com",
            "fields": {"key": "jobs/test-uuid/archive.zip"},
        }

        event = {
            "httpMethod": "POST",
            "path": "/jobs",
            "body": json.dumps({"fileName": "archive.zip"}),
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": "client-abc-123",
                        "client_id": "client-abc-123",
                        "token_use": "access",
                        "scope": "idp-api/jobs.write idp-api/jobs.read",
                    }
                }
            },
        }

        with patch("index.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = MagicMock(__str__=lambda s: "test-uuid")
            response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        call_kwargs = job_svc.create_job_record.call_args[1]
        assert call_kwargs["created_by"] == "client-abc-123"

    def test_create_job_without_authorizer_passes_none_created_by(
        self, mock_s3, job_svc, lambda_context
    ):
        """POST /jobs with no resolvable principal still succeeds but persists None for CreatedBy (logs a warning)."""
        from index import handler

        mock_s3.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com",
            "fields": {"key": "jobs/test-uuid/archive.zip"},
        }

        event = {
            "httpMethod": "POST",
            "path": "/jobs",
            "body": json.dumps({"fileName": "archive.zip"}),
            # No requestContext — e.g. a non-API-Gateway invocation path.
        }

        with patch("index.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = MagicMock(__str__=lambda s: "test-uuid")
            response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        call_kwargs = job_svc.create_job_record.call_args[1]
        assert call_kwargs["created_by"] is None


class TestGetJob:
    """Tests for GET /jobs/{job_id} endpoint."""

    def test_get_job_in_progress(self, mock_s3, job_svc, lambda_context):
        """Test GET /jobs/{jobId} when job is processing."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.COMPLETED, "b.pdf": Status.IN_PROGRESS},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:05:00Z",
        }

        event = {
            "httpMethod": "GET",
            "path": "/jobs/test-uuid",
            "pathParameters": {"job_id": "test-uuid"},
        }

        response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["jobId"] == "test-uuid"
        assert body["status"] == "IN_PROGRESS"
        assert body["result"] is None

    def test_get_job_succeeded(self, mock_s3, job_svc, lambda_context):
        """Test GET /jobs/{jobId} when job completed successfully."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.COMPLETED, "b.pdf": Status.COMPLETED},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:10:00Z",
            # JobTracker sets ResultsReady=True once results.zip is uploaded;
            # get_job only reports SUCCEEDED when this flag is true.
            "ResultsReady": True,
        }
        mock_s3.generate_presigned_url.return_value = "https://test-bucket.s3.amazonaws.com/results.zip"

        event = {
            "httpMethod": "GET",
            "path": "/jobs/test-uuid",
            "pathParameters": {"job_id": "test-uuid"},
        }

        response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "SUCCEEDED"
        assert body["result"]["downloadUrl"] == "https://test-bucket.s3.amazonaws.com/results.zip"

    def test_get_job_succeeded_but_results_not_ready_reports_in_progress(
        self, mock_s3, job_svc, lambda_context
    ):
        """All files complete but JobTracker hasn't uploaded results.zip yet → IN_PROGRESS."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.COMPLETED},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:10:00Z",
            # ResultsReady not set (or False) → keep the caller in IN_PROGRESS
            # so they do not race JobTracker into a 404 on the download URL.
        }

        event = {
            "httpMethod": "GET",
            "path": "/jobs/test-uuid",
            "pathParameters": {"job_id": "test-uuid"},
        }

        response = handler(event, lambda_context)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "IN_PROGRESS"
        assert body["result"] is None

    def test_get_job_not_found(self, mock_s3, job_svc, lambda_context):
        """Test GET /jobs/{jobId} when job doesn't exist."""
        from index import handler

        job_svc.get_job_record.return_value = None

        event = {
            "httpMethod": "GET",
            "path": "/jobs/nonexistent",
            "pathParameters": {"job_id": "nonexistent"},
        }

        response = handler(event, lambda_context)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "not found" in body["message"].lower()

    # -- Per-client job authorization (CreatedBy check) -----------------------

    @staticmethod
    def _get_event_with_principal(job_id: str, principal: str | None) -> dict:
        """Build a GET event carrying a Cognito authorizer principal."""
        event = {
            "httpMethod": "GET",
            "path": f"/jobs/{job_id}",
            "pathParameters": {"job_id": job_id},
        }
        if principal is not None:
            event["requestContext"] = {
                "authorizer": {"claims": {"sub": principal, "client_id": principal}}
            }
        return event

    def test_get_job_same_principal_visible(self, mock_s3, job_svc, lambda_context):
        """Creator of a job can read it back."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.IN_PROGRESS},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:05:00Z",
            "CreatedBy": "client-abc-123",
        }

        event = self._get_event_with_principal("test-uuid", "client-abc-123")
        response = handler(event, lambda_context)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["jobId"] == "test-uuid"
        assert body["status"] == "IN_PROGRESS"

    def test_get_job_different_principal_returns_404(
        self, mock_s3, job_svc, lambda_context
    ):
        """A different authenticated client cannot read another client's job — returns 404 (not 403) to avoid existence-leak."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.IN_PROGRESS},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:05:00Z",
            "CreatedBy": "client-abc-123",
        }

        event = self._get_event_with_principal("test-uuid", "client-xyz-789")
        response = handler(event, lambda_context)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "not found" in body["message"].lower()

    def test_get_job_missing_principal_returns_404(
        self, mock_s3, job_svc, lambda_context
    ):
        """An owned job is not readable by a caller whose principal cannot be resolved."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.IN_PROGRESS},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:05:00Z",
            "CreatedBy": "client-abc-123",
        }

        event = self._get_event_with_principal("test-uuid", principal=None)
        response = handler(event, lambda_context)

        assert response["statusCode"] == 404

    def test_get_job_legacy_record_without_created_by_is_readable(
        self, mock_s3, job_svc, lambda_context
    ):
        """Jobs created before the CreatedBy field existed remain readable by any caller."""
        from index import handler

        job_svc.get_job_record.return_value = {
            "Files": {"a.pdf": Status.IN_PROGRESS},
            "CreatedAt": "2026-01-23T10:00:00Z",
            "UpdatedAt": "2026-01-23T10:05:00Z",
            # No CreatedBy field at all.
        }

        event = self._get_event_with_principal("legacy-job", "any-client")
        response = handler(event, lambda_context)

        assert response["statusCode"] == 200


class TestInvalidRequests:
    """Tests for invalid requests."""

    def test_invalid_http_method(self, lambda_context):
        """Test invalid HTTP method."""
        from index import handler

        event = {"httpMethod": "DELETE", "path": "/jobs"}

        response = handler(event, lambda_context)
        assert response["statusCode"] == 404

    def test_invalid_json_body(self, mock_s3, job_svc, lambda_context):
        """Test invalid JSON in request body."""
        from index import handler

        event = {"httpMethod": "POST", "path": "/jobs", "body": "invalid json"}

        response = handler(event, lambda_context)
        assert response["statusCode"] == 422
