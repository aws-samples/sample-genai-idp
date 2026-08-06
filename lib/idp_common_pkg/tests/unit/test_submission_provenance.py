# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Provenance tagging: keeping non-production submissions out of the Document List.

Test Studio (and Auto Optimizer) submit documents through the same pipeline as
customer uploads — deliberately, so confidence and cost semantics match what real
runs produce. The consequence was that their documents landed in the production
Document List and the IDP metrics: on a dev stack 248 of 249 rows in that list
were test artifacts.

The fix tags the submission at the source and partitions the TypeDateIndex on it.
These tests pin the whole chain: S3 metadata -> Document -> serialization ->
DynamoDB ItemType.
"""

import importlib.util
import os
from unittest.mock import patch

import pytest

from idp_common.models import Document, Status

pytestmark = pytest.mark.unit


def _load_list_documents_resolver():
    """Import the listDocuments resolver by path (not an installed package)."""
    path = os.path.join(
        os.path.dirname(__file__),
        "../../../../nested/api-resolvers/src/lambda/list_documents_gsi_resolver/index.py",
    )
    spec = importlib.util.spec_from_file_location("list_docs_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_backfill_worker():
    path = os.path.join(
        os.path.dirname(__file__),
        "../../../../src/lambda/backfill_gsi_attributes/index.py",
    )
    spec = importlib.util.spec_from_file_location("backfill_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDocumentCarriesProvenance:
    def test_from_s3_event_reads_submission_metadata(self):
        """The copier writes provenance as S3 object metadata.

        from_s3_event already HEADs the object to read config-version, so reading
        two more keys costs no extra call.
        """
        event = {
            "detail": {
                "bucket": {"name": "input-bucket"},
                "object": {"key": "my-set-20260806-120000/a.pdf"},
            },
            "time": "2026-08-06T12:00:00Z",
        }
        head = {
            "Metadata": {
                "config-version": "v3",
                "submission-source": "test-studio",
                "test-set-id": "my-set",
            }
        }
        with patch("boto3.client") as mock_client:
            mock_client.return_value.head_object.return_value = head
            doc = Document.from_s3_event(event, "output-bucket")

        assert doc.submission_source == "test-studio"
        assert doc.test_set_id == "my-set"
        assert doc.config_version == "v3"

    def test_ordinary_upload_has_no_provenance(self):
        """Absence is the production signal — an upload carries no marker."""
        event = {
            "detail": {
                "bucket": {"name": "input-bucket"},
                "object": {"key": "invoice.pdf"},
            },
            "time": "2026-08-06T12:00:00Z",
        }
        with patch("boto3.client") as mock_client:
            mock_client.return_value.head_object.return_value = {"Metadata": {}}
            doc = Document.from_s3_event(event, "output-bucket")

        assert doc.submission_source is None
        assert doc.test_set_id is None

    def test_provenance_survives_the_serialization_round_trip(self):
        """The fields cross the Step Functions boundary via to_dict/from_dict.

        Losing them mid-pipeline would mean the tracking record is written without
        provenance even though the document was tagged on arrival.
        """
        doc = Document(
            id="k",
            input_key="k",
            submission_source="test-studio",
            test_set_id="my-set",
        )
        restored = Document.from_dict(doc.to_dict())
        assert restored.submission_source == "test-studio"
        assert restored.test_set_id == "my-set"


class TestTrackingRecordItemType:
    def _item_for(self, **kwargs):
        from idp_common.dynamodb.service import DocumentDynamoDBService

        doc = Document(
            id="k",
            input_key="k",
            status=Status.QUEUED,
            initial_event_time="2026-08-06T12:00:00Z",
            **kwargs,
        )
        service = DocumentDynamoDBService.__new__(DocumentDynamoDBService)
        return service._document_to_create_item(doc)

    def test_test_submission_gets_its_own_item_type(self):
        """ItemType is the TypeDateIndex hash key, so this is what hides the row.

        Filtering on a projected attribute would not work: DynamoDB applies
        FilterExpression after Limit, so a page of 50 could return 1 row with a
        nextToken and no indication the rest were dropped.
        """
        item = self._item_for(submission_source="test-studio", test_set_id="my-set")
        assert item["ItemType"] == "test-document"
        assert item["SubmissionSource"] == "test-studio"
        assert item["TestSetId"] == "my-set"

    def test_ordinary_upload_keeps_the_document_item_type(self):
        item = self._item_for()
        assert item["ItemType"] == "document"
        assert "SubmissionSource" not in item
        assert "TestSetId" not in item


class TestListDocumentsView:
    def test_default_view_is_production(self):
        module = _load_list_documents_resolver()
        assert module._item_type_for_view(None) == "document"
        assert module._item_type_for_view("production") == "document"

    def test_test_view_selects_the_test_item_type(self):
        module = _load_list_documents_resolver()
        assert module._item_type_for_view("test") == "test-document"
        assert module._item_type_for_view("TEST") == "test-document"

    def test_unknown_mode_falls_back_to_production(self):
        """An unrecognised value must not silently show test data."""
        module = _load_list_documents_resolver()
        assert module._item_type_for_view("nonsense") == "document"


class TestBackfillRetypesLegacyTestDocuments:
    def test_retypes_a_document_with_a_test_run_key(self):
        """Documents predating tagging carry no metadata, only a key shape.

        The copier writes into "<testSetId>-<YYYYMMDD>-<HHMMSS>/", so that is the
        only available signal for the rows already in the table.
        """
        module = _load_backfill_worker()
        item = {"ItemType": "document"}
        updates = module._determine_updates(item, "doc#my-set-20260806-120000/a.pdf")
        assert updates.get("ItemType") == "test-document"

    def test_leaves_an_ordinary_upload_alone(self):
        module = _load_backfill_worker()
        item = {"ItemType": "document"}
        updates = module._determine_updates(item, "doc#invoice.pdf")
        assert "ItemType" not in updates

    def test_metadata_is_preferred_over_the_key_shape(self):
        """Once tagging shipped the attributes are definitive."""
        module = _load_backfill_worker()
        item = {"ItemType": "document", "SubmissionSource": "test-studio"}
        updates = module._determine_updates(item, "doc#oddly-named.pdf")
        assert updates.get("ItemType") == "test-document"

    def test_already_retyped_item_needs_no_update(self):
        """Idempotent: a second backfill pass must be a no-op."""
        module = _load_backfill_worker()
        item = {"ItemType": "test-document", "SubmissionSource": "test-studio"}
        updates = module._determine_updates(item, "doc#my-set-20260806-120000/a.pdf")
        assert "ItemType" not in updates


def test_resolver_and_library_agree_on_item_type_values():
    """Two deploy artifacts hardcode these strings; a drift would hide documents."""
    from idp_common.dynamodb import service as ddb_service

    module = _load_list_documents_resolver()
    assert module.ITEM_TYPE_DOCUMENT == ddb_service.ITEM_TYPE_DOCUMENT
    assert module.ITEM_TYPE_TEST_DOCUMENT == ddb_service.ITEM_TYPE_TEST_DOCUMENT
    backfill = _load_backfill_worker()
    assert backfill.PK_PREFIX_TO_ITEM_TYPE["doc#"] == ddb_service.ITEM_TYPE_DOCUMENT
