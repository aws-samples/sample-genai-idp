"""Unit tests for batch_pre_processor Lambda function."""

import io
import os
import sys
import zipfile
from unittest.mock import MagicMock, patch

import pytest

# Add idp_common to path and import real Status
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../lib/idp_common_pkg"))
from idp_common.models import Status

# Mock idp_common before importing index
mock_models_module = MagicMock()
mock_models_module.Status = Status

sys.modules["idp_common"] = MagicMock()
sys.modules["idp_common.dynamodb"] = MagicMock()
sys.modules["idp_common.dynamodb.job_service"] = MagicMock()
sys.modules["idp_common.job_service"] = MagicMock()
sys.modules["idp_common.models"] = mock_models_module


@pytest.fixture(autouse=True)
def mock_env():
    """Set up environment variables for tests."""
    env_vars = {
        "INPUT_BUCKET_NAME": "test-input-bucket",
        "TRACKING_TABLE": "test-table",
        "LOG_LEVEL": "INFO",
    }
    with patch.dict(os.environ, env_vars):
        yield


@pytest.fixture
def mock_s3():
    """Mock S3 client.

    By default `upload_fileobj` silently drains the passed stream (to mirror
    real boto3 behavior — the stream is consumed). Individual tests can
    override `side_effect` to simulate partial failures.
    """

    def _drain(fileobj, bucket, key, **kwargs):
        # Consume the stream so subsequent reads don't see stale data and
        # so we get realistic call patterns.
        try:
            while fileobj.read(8192):
                pass
        except Exception:
            pass

    with patch("index.s3") as mock:
        mock.upload_fileobj.side_effect = _drain
        yield mock


@pytest.fixture
def mock_job_service():
    """Mock job service."""
    mock_svc = MagicMock()
    with patch("index.job_service", mock_svc):
        yield mock_svc


def create_test_zip(files: dict[str, bytes]) -> io.BytesIO:
    """Create an in-memory ZIP file with given files."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    zip_buffer.seek(0)
    return zip_buffer


def make_event(bucket: str, key: str) -> dict:
    """Create an EventBridge S3 event."""
    return {
        "detail": {
            "bucket": {"name": bucket},
            "object": {"key": key},
        }
    }


class TestHandler:
    """Tests for handler function."""

    def test_handler_processes_zip(self, mock_s3, mock_job_service):
        """Test handler processes ZIP and updates job record with IN_PROGRESS per file."""
        from index import handler

        zip_content = create_test_zip({"doc1.pdf": b"pdf1", "doc2.pdf": b"pdf2"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        event = make_event("staging-bucket", "jobs/test-uuid/archive.zip")

        response = handler(event, None)

        assert response["statusCode"] == 200
        assert mock_s3.upload_fileobj.call_count == 2
        mock_job_service.update_job_files.assert_called_once()
        call_args = mock_job_service.update_job_files.call_args
        assert call_args[0][0] == "test-uuid"
        assert call_args[0][1] == {
            "doc1.pdf": Status.IN_PROGRESS,
            "doc2.pdf": Status.IN_PROGRESS,
        }

    def test_handler_skips_non_zip(self, mock_s3, mock_job_service):
        """Test handler skips non-ZIP files."""
        from index import handler

        event = make_event("staging-bucket", "jobs/test-uuid/document.pdf")

        response = handler(event, None)

        assert response["statusCode"] == 200
        mock_s3.download_fileobj.assert_not_called()
        mock_job_service.update_job_files.assert_not_called()

    def test_handler_skips_invalid_key_format(self, mock_s3, mock_job_service):
        """Test handler skips keys with invalid format."""
        from index import handler

        event = make_event("staging-bucket", "invalid/path.zip")

        response = handler(event, None)

        assert response["statusCode"] == 200
        mock_s3.download_fileobj.assert_not_called()

    def test_handler_marks_job_rejected_on_bounds_violation(
        self, mock_s3, mock_job_service, monkeypatch
    ):
        """Oversized zip is rejected terminally; job record gets a FAILED marker."""
        import index
        from index import handler

        # Lower the cap below the size of our test content so a small zip
        # trips it. Using monkeypatch on the module constant is cleaner than
        # trying to spoof ZipInfo.file_size, which zipfile.writestr
        # overrides with the actual content length.
        monkeypatch.setattr(index, "MAX_UNCOMPRESSED_BYTES", 10)

        zip_content = create_test_zip({"too_big.pdf": b"x" * 100})  # 100 bytes > 10
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        event = make_event("staging-bucket", "jobs/test-uuid/archive.zip")

        response = handler(event, None)

        # Handler swallows the bound violation (terminal state for the job)
        # and returns 200 so the EventBridge delivery succeeds.
        assert response["statusCode"] == 200

        # Nothing was uploaded — bounds check fires before the upload loop.
        mock_s3.upload_fileobj.assert_not_called()

        # Job record carries a synthetic FAILED marker so the API surfaces
        # a terminal state rather than leaving the caller in PENDING_UPLOAD.
        mock_job_service.update_job_files.assert_called_once()
        call_args = mock_job_service.update_job_files.call_args
        assert call_args[0][0] == "test-uuid"
        assert call_args[0][1] == {"__rejected__": Status.FAILED}

    def test_handler_records_partial_failure(self, mock_s3, mock_job_service):
        """One per-entry upload failure is isolated; the rest still process."""
        from index import handler

        zip_content = create_test_zip({
            "good1.pdf": b"ok",
            "bad.pdf": b"will-fail",
            "good2.pdf": b"ok",
        })
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        call_log = []

        def fake_upload(fileobj, bucket, key, **kwargs):
            call_log.append(key)
            if key.endswith("/bad.pdf"):
                raise RuntimeError("simulated S3 failure")
            # Drain stream on successful path.
            while fileobj.read(8192):
                pass

        mock_s3.upload_fileobj.side_effect = fake_upload

        event = make_event("staging-bucket", "jobs/test-uuid/archive.zip")
        response = handler(event, None)

        assert response["statusCode"] == 200
        assert mock_s3.upload_fileobj.call_count == 3

        # Job record reflects mixed outcomes: survivors IN_PROGRESS, failure FAILED.
        mock_job_service.update_job_files.assert_called_once()
        updated = mock_job_service.update_job_files.call_args[0][1]
        assert updated["good1.pdf"] == Status.IN_PROGRESS
        assert updated["good2.pdf"] == Status.IN_PROGRESS
        assert updated["bad.pdf"] == Status.FAILED


class TestExtractAndUpload:
    """Tests for extract_and_upload function."""

    def test_extracts_files_to_input_bucket(self, mock_s3):
        """Files are streamed to the input bucket; function returns (succeeded, failed)."""
        from index import extract_and_upload

        zip_content = create_test_zip({"file1.pdf": b"content1", "file2.pdf": b"content2"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert set(succeeded) == {"file1.pdf", "file2.pdf"}
        assert failed == []
        assert mock_s3.upload_fileobj.call_count == 2

        # Verify upload keys
        calls = mock_s3.upload_fileobj.call_args_list
        # upload_fileobj(fileobj, bucket, key) — positional args
        keys = {c[0][2] for c in calls}
        assert keys == {"jobs/uuid/file1.pdf", "jobs/uuid/file2.pdf"}

    def test_skips_directories(self, mock_s3):
        """Directory entries in ZIP are skipped."""
        from index import extract_and_upload

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("subdir/", "")
            zf.writestr("subdir/file.pdf", b"content")
        zip_buffer.seek(0)

        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_buffer.read())

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert succeeded == ["file.pdf"]
        assert failed == []
        assert mock_s3.upload_fileobj.call_count == 1

    def test_flattens_nested_paths(self, mock_s3):
        """Nested paths are flattened to basename."""
        from index import extract_and_upload

        zip_content = create_test_zip({"folder/subfolder/doc.pdf": b"content"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert succeeded == ["doc.pdf"]
        assert failed == []
        call_args = mock_s3.upload_fileobj.call_args
        assert call_args[0][2] == "jobs/uuid/doc.pdf"

    def test_handles_filename_collisions(self, mock_s3):
        """Duplicate filenames in different folders get renamed deterministically."""
        from index import extract_and_upload

        zip_content = create_test_zip({
            "invoices/report.pdf": b"invoice",
            "contracts/report.pdf": b"contract",
            "other/report.pdf": b"other",
        })
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert failed == []
        assert len(succeeded) == 3
        assert "report.pdf" in succeeded
        assert "report_1.pdf" in succeeded
        assert "report_2.pdf" in succeeded


class TestZipBounds:
    """Tests for MAX_UNCOMPRESSED_BYTES and MAX_ENTRIES enforcement."""

    def test_rejects_oversized_uncompressed_declared(
        self, mock_s3, monkeypatch
    ):
        """Raises ZipBoundsExceeded when declared uncompressed total exceeds cap."""
        import index
        from index import ZipBoundsExceeded, extract_and_upload

        monkeypatch.setattr(index, "MAX_UNCOMPRESSED_BYTES", 10)

        zip_content = create_test_zip({"whopper.pdf": b"x" * 100})  # 100 > 10
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        with pytest.raises(ZipBoundsExceeded) as excinfo:
            extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert "MAX_UNCOMPRESSED_BYTES" in str(excinfo.value)
        # No uploads should have started.
        mock_s3.upload_fileobj.assert_not_called()

    def test_rejects_too_many_entries(self, mock_s3, monkeypatch):
        """Raises ZipBoundsExceeded when entry count exceeds cap."""
        import index
        from index import ZipBoundsExceeded, extract_and_upload

        # Lower MAX_ENTRIES for this test so we can trip it with a small zip.
        monkeypatch.setattr(index, "MAX_ENTRIES", 2)

        zip_content = create_test_zip({
            "a.pdf": b"a",
            "b.pdf": b"b",
            "c.pdf": b"c",
        })
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        with pytest.raises(ZipBoundsExceeded) as excinfo:
            extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert "MAX_ENTRIES" in str(excinfo.value)
        mock_s3.upload_fileobj.assert_not_called()

    def test_bounds_not_tripped_by_small_zip(self, mock_s3):
        """A normal-sized zip under the defaults processes cleanly."""
        from index import extract_and_upload

        zip_content = create_test_zip({"small.pdf": b"x" * 1024})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")
        assert succeeded == ["small.pdf"]
        assert failed == []


class TestPerEntryFailureIsolation:
    """Tests for M3 — per-entry errors don't abort the batch."""

    def test_upload_error_isolated_per_entry(self, mock_s3):
        """A single upload_fileobj exception doesn't abort the rest of the batch."""
        from index import extract_and_upload

        zip_content = create_test_zip({
            "ok1.pdf": b"ok",
            "bomb.pdf": b"will-throw",
            "ok2.pdf": b"ok",
        })
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        def fake_upload(fileobj, bucket, key, **kwargs):
            if key.endswith("/bomb.pdf"):
                raise RuntimeError("injected failure")
            while fileobj.read(8192):
                pass

        mock_s3.upload_fileobj.side_effect = fake_upload

        succeeded, failed = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert set(succeeded) == {"ok1.pdf", "ok2.pdf"}
        assert failed == ["bomb.pdf"]
        assert mock_s3.upload_fileobj.call_count == 3
