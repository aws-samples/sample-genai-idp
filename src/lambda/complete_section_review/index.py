# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Lambda function to complete HITL section review."""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from idp_common.docs_service import create_document_service
from idp_common.models import Status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")

TRACKING_TABLE_NAME = os.environ.get("TRACKING_TABLE_NAME", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
TEST_SET_BUCKET = os.environ.get("TEST_SET_BUCKET", "")


def handler(event, context):
    """Handle section review completion from AppSync."""
    logger.info(f"Received event: {json.dumps(event)}")

    field_name = event.get("info", {}).get("fieldName", "")
    arguments = event.get("arguments", {})
    object_key = arguments.get("objectKey")
    section_id = arguments.get("sectionId")
    edited_data = arguments.get("editedData")

    # Extract user identity from AppSync event
    identity = event.get("identity", {})
    username = identity.get("username", "")
    user_email = identity.get("claims", {}).get("email", "")
    user_groups = identity.get("claims", {}).get("cognito:groups", [])
    if isinstance(user_groups, str):
        user_groups = [user_groups]
    is_admin = "Admin" in user_groups

    # Defense-in-depth RBAC: HITL review operations are Admin+Reviewer, plus
    # Annotator for test-set ground-truth annotation. The schema enforces this via
    # @aws_cognito_user_pools(cognito_groups), but we also gate it server-side so
    # a Viewer/Author can never reach these operations even if the schema
    # directive is missing or misconfigured (e.g. the prior @aws_auth directive,
    # which AppSync silently ignores on a multi-auth API).
    #
    # An Annotator's reach is narrower than a Reviewer's: group membership only
    # gets them to the operation, and _assert_annotator_scope below then requires
    # the document to belong to a test set in their allowedTestSets. So an
    # annotator onboarded for one labeling effort cannot review production
    # documents or another effort's set.
    if not ({"Admin", "Reviewer", "Annotator"}.intersection(user_groups)):
        logger.warning(
            f"Forbidden: caller {user_email} (groups={user_groups}) "
            f"attempted HITL operation '{field_name}'"
        )
        raise ValueError(
            "Unauthorized: review operations require Admin, Reviewer or Annotator group"
        )

    if field_name == "claimReview":
        if not object_key:
            raise ValueError("objectKey is required")
        _assert_annotator_scope(event, object_key)
        return claim_review(object_key, username, user_email)

    if field_name == "releaseReview":
        if not object_key:
            raise ValueError("objectKey is required")
        _assert_annotator_scope(event, object_key)
        return release_review(object_key, username, user_email, is_admin)

    if field_name == "skipAllSectionsReview":
        # Deliberately not extended to Annotator: skipping marks a document
        # reviewed without looking at it, which is a set-owner decision about
        # how much ground truth to accept, not an annotator's.
        is_reviewer = "Reviewer" in user_groups
        if not is_admin and not is_reviewer:
            raise ValueError(
                "Only administrators and reviewers can skip sections review"
            )
        if not object_key:
            raise ValueError("objectKey is required")
        return skip_all_sections_review(object_key, username, user_email)

    if not object_key or not section_id:
        raise ValueError("objectKey and sectionId are required")

    _assert_annotator_scope(event, object_key)
    return complete_section_review(
        object_key, section_id, edited_data, username, user_email
    )


def _assert_annotator_scope(event, object_key):
    """Verify a scoped Annotator may touch this document's test set.

    A review document carries the test set it came from (``TestSetId``, written
    when the run was sent to review). Annotators are checked against that;
    Admin/Reviewer are unaffected, and a document with no test set is production
    HITL work that an Annotator has no business in.
    """
    groups = (event.get("identity") or {}).get("claims", {}).get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    if "Annotator" not in groups or {"Admin", "Reviewer"}.intersection(groups):
        return

    from idp_common.test_set_scope import (
        TestSetAccessDenied,
        assert_can_access_test_set,
    )

    table = dynamodb.Table(TRACKING_TABLE_NAME)
    doc = (
        table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"}).get("Item") or {}
    )
    test_set_id = doc.get("TestSetId")
    if not test_set_id:
        logger.warning(
            f"Forbidden: annotator attempted review of non-test-set document "
            f"{object_key}"
        )
        raise ValueError("Unauthorized: annotators may only review test-set documents")
    try:
        assert_can_access_test_set(event, test_set_id)
    except TestSetAccessDenied as e:
        # Surface as ValueError so the dispatcher maps it the same way as the
        # other authorization failures in this handler.
        raise ValueError(str(e)) from e


def complete_section_review(
    object_key, section_id, edited_data=None, username="", user_email=""
):
    """Mark a section as review complete and update document status."""
    logger.info(
        f"Completing review for section {section_id} of document {object_key} by user {username}"
    )

    # Load document using document service
    document_service = create_document_service(mode="dynamodb")
    document = document_service.get_document(object_key)

    if not document:
        raise ValueError(f"Document {object_key} not found")

    # Find the section and get its output URI
    section_output_uri = None
    section_found = False
    for section in document.sections:
        if section.section_id == section_id:
            section_found = True
            section_output_uri = section.extraction_result_uri
            break

    # If the caller supplied edited data, we MUST be able to persist it. Fail
    # loudly instead of marking the section reviewed with the edits silently
    # dropped (which would return success while losing the reviewer's work).
    if edited_data:
        if not section_found:
            raise ValueError(
                f"Cannot save edited data: section '{section_id}' not found in "
                f"document '{object_key}'"
            )
        if not section_output_uri:
            raise ValueError(
                f"Cannot save edited data: section '{section_id}' in document "
                f"'{object_key}' has no output URI to write to"
            )
        save_edited_data_to_s3(section_output_uri, edited_data)
        # Test-set HITL: if this doc belongs to a test set, also write the
        # corrected labels back to the test set's baseline so a later
        # publishTestSetVersion captures the human annotation as ground truth.
        write_correction_to_test_set_baseline(object_key, section_id, edited_data)

    # Get current pending and completed sections from document model
    pending = set(document.hitl_sections_pending or [])
    completed = set(document.hitl_sections_completed or [])

    # Get skipped from DynamoDB (not in document model)
    table = dynamodb.Table(TRACKING_TABLE_NAME)
    response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    doc = response.get("Item", {})
    skipped = set(doc.get("HITLSectionsSkipped", []) or [])

    # If HITLSectionsPending was never initialized, initialize it from all sections
    if not pending and not completed and not skipped:
        all_section_ids = {
            section.section_id for section in document.sections if section.section_id
        }
        pending = all_section_ids - {section_id}
        logger.info(f"Initialized HITLSectionsPending from sections: {pending}")

    # Move section from pending to completed
    if section_id in pending:
        pending.remove(section_id)
    completed.add(section_id)

    # Check if all sections are reviewed (completed or skipped)
    all_completed = len(pending) == 0
    has_skipped = len(skipped) > 0

    # Determine new Review Status
    if all_completed:
        new_hitl_status = "Skipped" if has_skipped else "Completed"
    else:
        new_hitl_status = "InProgress"

    # Update document model with Review Status
    document.hitl_status = new_hitl_status
    document.hitl_sections_pending = list(pending)
    document.hitl_sections_completed = list(completed)

    # Update via document service
    document_service.update_document(document)
    logger.info(
        f"Updated HITLStatus to '{new_hitl_status}' for document {object_key}. "
        f"Pending: {list(pending)}, Completed: {list(completed)}, All done: {all_completed}"
    )

    # Update review-specific fields in DynamoDB (not in document model)
    review_record = {
        "sectionId": section_id,
        "reviewedBy": username or "unknown",
        "reviewedByEmail": user_email or "",
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
    }
    review_history = doc.get("HITLReviewHistory", []) or []
    review_history.append(review_record)

    update_expr = "SET HITLReviewHistory = :history"
    expr_values = {":history": review_history}

    if all_completed:
        update_expr += ", HITLCompleted = :hitlCompleted"
        expr_values[":hitlCompleted"] = True
        update_expr += " REMOVE HITLPendingReview"

    table.update_item(
        Key={"PK": f"doc#{object_key}", "SK": "none"},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    logger.info(
        f"Section {section_id} marked complete. Remaining: {len(pending)}. All done: {all_completed}"
    )

    # If all sections are completed, trigger reprocessing for summarization/evaluation
    if all_completed:
        trigger_reprocessing(object_key)

    # Return document data
    return build_document_response(object_key)


def save_edited_data_to_s3(s3_uri, edited_data):
    """Save edited JSON data back to S3."""
    try:
        # Parse S3 URI: s3://bucket/key
        if not s3_uri.startswith("s3://"):
            logger.error(f"Invalid S3 URI: {s3_uri}")
            return

        parts = s3_uri[5:].split("/", 1)
        if len(parts) != 2:
            logger.error(f"Invalid S3 URI format: {s3_uri}")
            return

        bucket = parts[0]
        key = parts[1]

        # Parse edited_data if it's a string
        if isinstance(edited_data, str):
            data = json.loads(edited_data)
        else:
            data = edited_data

        # UI sends full JSON structure (with inference_result, explainability_info, etc.)
        # Save it directly - no transformation needed
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, indent=2),
            ContentType="application/json",
        )
        logger.info(f"Saved edited data to {s3_uri}")

    except Exception as e:
        logger.error(f"Failed to save edited data to S3: {str(e)}")
        raise


def write_correction_to_test_set_baseline(object_key, section_id, edited_data):
    """Persist a HITL correction to the owning test set's baseline (ground truth).

    A test-set review document is keyed ``{test_run_id}/{filename}`` and carries
    ``TestSetId`` (written when it was sent to review). The test-set baseline
    layout is ``{test_set_id}/baseline/{filename}/sections/{section_id}/result.json``.
    Writing here (not just the doc's own output) is what turns HITL review into
    reusable, versionable golden-dataset annotation. Best-effort: never fail the
    review if the doc isn't part of a test set or the write hiccups.
    """
    if not TEST_SET_BUCKET:
        return
    try:
        table = dynamodb.Table(TRACKING_TABLE_NAME)
        doc = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"}).get(
            "Item", {}
        )
        test_set_id = doc.get("TestSetId")
        if not test_set_id:
            return  # Not a test-set review document — nothing to do.

        # object_key is "{test_run_id}/{filename}"; the baseline is keyed by filename.
        filename = object_key.split("/", 1)[1] if "/" in object_key else object_key
        baseline_key = (
            f"{test_set_id}/baseline/{filename}/sections/{section_id}/result.json"
        )
        data = json.loads(edited_data) if isinstance(edited_data, str) else edited_data

        # Read the label being replaced *before* overwriting it: comparing it to
        # what the reviewer saved is what tells the confidence curve whether the
        # model was right, and after the write that evidence is gone.
        previous = _read_json(TEST_SET_BUCKET, baseline_key)

        # Mark the label as human-reviewed so draft labeling never overwrites it
        # (the harvester only replaces labels tagged draft-machine).
        if isinstance(data, dict):
            data["labelSource"] = "reviewed-human"

        s3_client.put_object(
            Bucket=TEST_SET_BUCKET,
            Key=baseline_key,
            Body=json.dumps(data, indent=2),
            ContentType="application/json",
        )
        logger.info(
            f"Wrote HITL correction to test-set baseline "
            f"s3://{TEST_SET_BUCKET}/{baseline_key}"
        )

        record_curve_observations(test_set_id, previous, data)
    except Exception as e:  # noqa: BLE001 — best-effort; must not break the review
        logger.error(
            f"Failed to write correction to test-set baseline for {object_key}: {e}"
        )


def _read_json(bucket, key):
    """Read a JSON object from S3, or None if absent/unreadable."""
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body)
    except Exception:  # noqa: BLE001 — absence is normal (first review of a doc)
        return None


def record_curve_observations(test_set_id, previous, saved):
    """Teach the confidence→accuracy curve from what this reviewer just did.

    A field the reviewer left alone was predicted correctly; a field they changed
    was not. Paired with the confidence the model had claimed, that is exactly
    the ``(confidence, correct)`` observation the review-effort estimator's curve
    is built from — and because review is worst-first, these observations land in
    the low-confidence bins where the estimate is most sensitive.

    Best-effort by design: the curve is an optimization, and failing to record an
    observation must never fail a reviewer's save.
    """
    if not previous:
        return  # Nothing was predicted, so there is no verdict to record.
    try:
        from idp_common.evaluation.curve_store import (
            CurveStore,
            observations_from_baseline_review,
        )

        observations = observations_from_baseline_review(previous, saved)
        if not observations:
            return

        table = dynamodb.Table(TRACKING_TABLE_NAME)
        # Key the curve by the config that produced these labels, so a later
        # config change doesn't inherit a curve measured under different
        # confidence semantics.
        config_version = (previous.get("metadata") or {}).get("config_version")
        accepted = CurveStore(table).add_observations(
            test_set_id,
            observations,
            config_version=config_version,
            source="review",
        )
        logger.info(
            f"Recorded {accepted} confidence-curve observation(s) for test set "
            f"{test_set_id} from review"
        )
    except Exception as e:  # noqa: BLE001 — never break a review over the curve
        logger.warning(
            f"Could not record confidence-curve observations for {test_set_id}: {e}"
        )


def trigger_reprocessing(object_key):
    """Trigger reprocessing via SQS queue after HITL completion.

    Uses the same pattern as processChanges - sends document to queue,
    workflow runs with intelligent skip logic (OCR/Classification/Extraction/Assessment
    are skipped since data exists), only Summarization and Evaluation re-run.
    """
    try:
        # Load document from DynamoDB
        dynamodb_service = create_document_service(mode="dynamodb")
        document = dynamodb_service.get_document(object_key)

        if not document:
            logger.error(f"Document {object_key} not found for reprocessing")
            return

        # Set bucket names from environment
        document.input_bucket = os.environ.get("INPUT_BUCKET")
        document.output_bucket = os.environ.get("OUTPUT_BUCKET")

        # Reset status for reprocessing
        document.status = Status.QUEUED
        document.start_time = None
        document.completion_time = None
        document.workflow_execution_arn = None

        # Compress and send to queue (same pattern as processChanges)
        working_bucket = os.environ.get("WORKING_BUCKET")
        if working_bucket:
            sqs_message = document.serialize_document(
                working_bucket, "hitl_complete", logger
            )
        else:
            sqs_message = document.to_dict()

        queue_url = os.environ.get("QUEUE_URL")
        if queue_url:
            sqs_client.send_message(
                QueueUrl=queue_url, MessageBody=json.dumps(sqs_message, default=str)
            )
            logger.info(
                f"Queued document {object_key} for reprocessing after HITL completion"
            )
        else:
            logger.warning("QUEUE_URL not configured, skipping reprocessing trigger")

    except Exception as e:
        logger.error(f"Failed to trigger reprocessing for {object_key}: {str(e)}")


def skip_all_sections_review(object_key, username="", user_email=""):
    """Skip all pending section reviews and mark document as complete (Admin only)."""
    logger.info(
        f"Skipping all sections review for document {object_key} by admin {username}"
    )

    # Load document using document service to verify it exists
    document_service = create_document_service(mode="dynamodb")
    document = document_service.get_document(object_key)

    if not document:
        raise ValueError(f"Document {object_key} not found")

    completed = set(document.hitl_sections_completed or [])

    # Get skipped from DynamoDB (not in document model)
    table = dynamodb.Table(TRACKING_TABLE_NAME)
    response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    doc = response.get("Item", {})
    existing_skipped = set(doc.get("HITLSectionsSkipped", []) or [])

    # Get all section IDs from the document
    all_section_ids = {
        section.section_id for section in document.sections if section.section_id
    }

    # Sections to skip = all sections that are not already completed
    sections_to_skip = all_section_ids - completed - existing_skipped
    all_skipped = list(sections_to_skip | existing_skipped)

    # Update review-specific fields directly in DynamoDB
    review_record = {
        "sectionId": "ALL_SKIPPED",
        "reviewedBy": username or "unknown",
        "reviewedByEmail": user_email or "",
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
        "action": "skip_all",
        "skippedSections": list(sections_to_skip),
    }
    review_history = doc.get("HITLReviewHistory", []) or []
    review_history.append(review_record)

    table.update_item(
        Key={"PK": f"doc#{object_key}", "SK": "none"},
        UpdateExpression="SET HITLStatus = :status, HITLSectionsPending = :pending, HITLSectionsSkipped = :skipped, HITLReviewHistory = :history, HITLCompleted = :hitlCompleted, HITLReviewedBy = :reviewedBy, HITLReviewedByEmail = :reviewedByEmail REMOVE HITLPendingReview",
        ExpressionAttributeValues={
            ":status": "Review Skipped",
            ":pending": [],
            ":skipped": all_skipped,
            ":history": review_history,
            ":hitlCompleted": True,
            ":reviewedBy": username or "unknown",
            ":reviewedByEmail": user_email or "",
        },
    )

    logger.info(
        f"All sections skipped for document {object_key}. Skipped: {all_skipped}, Completed: {list(completed)}"
    )

    # Skipping all reviews resolves every pending section, so the document is now
    # fully reviewed — exactly like completing the final section via
    # complete_section_review (which calls trigger_reprocessing on all_completed).
    # Trigger the same downstream reprocessing here so the two "finish review"
    # paths behave identically: it re-runs Summarization/Evaluation with the
    # existing (unedited) data and, on workflow success, emits the Step Functions
    # "SUCCEEDED" event that drives the optional post-processing Lambda hook
    # (PostProcessingLambdaHookFunctionArn). Without this call, skipping reviews
    # would finalize the document but never run post-processing — an inconsistency
    # with the section-by-section completion path.
    trigger_reprocessing(object_key)

    return build_document_response(object_key)


def claim_review(object_key, username="", user_email=""):
    """Claim a document for review (assigns reviewer as owner)."""
    logger.info(f"Claiming review for document {object_key} by {username}")

    # Load document using document service to verify it exists
    document_service = create_document_service(mode="dynamodb")
    document = document_service.get_document(object_key)

    if not document:
        raise ValueError(f"Document {object_key} not found")

    table = dynamodb.Table(TRACKING_TABLE_NAME)
    response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    doc = response.get("Item", {})
    current_owner = doc.get("HITLReviewOwner", "")

    if current_owner and current_owner != username:
        raise ValueError(f"Document is already claimed by {current_owner}")

    # Update Review Status and review owner directly in DynamoDB
    # This avoids re-serializing metering data which could cause issues
    table.update_item(
        Key={"PK": f"doc#{object_key}", "SK": "none"},
        UpdateExpression="SET HITLStatus = :status, HITLReviewOwner = :owner, HITLReviewOwnerEmail = :email",
        ExpressionAttributeValues={
            ":status": "InProgress",
            ":owner": username,
            ":email": user_email,
        },
    )

    logger.info(
        f"Review claimed for document {object_key} by {username}, HITLStatus set to InProgress"
    )
    return build_document_response(object_key)


def release_review(object_key, username="", user_email="", is_admin=False):
    """Release a document review (removes owner assignment)."""
    logger.info(f"Releasing review for document {object_key} by {username}")

    # Load document using document service to verify it exists
    document_service = create_document_service(mode="dynamodb")
    document = document_service.get_document(object_key)

    if not document:
        raise ValueError(f"Document {object_key} not found")

    table = dynamodb.Table(TRACKING_TABLE_NAME)
    response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    doc = response.get("Item", {})
    current_owner = doc.get("HITLReviewOwner", "")

    if not is_admin and current_owner and current_owner != username:
        raise ValueError("Only the review owner or an admin can release this review")

    # Update Review Status and remove review owner directly in DynamoDB
    # This avoids re-serializing metering data which could cause issues
    table.update_item(
        Key={"PK": f"doc#{object_key}", "SK": "none"},
        UpdateExpression="SET HITLStatus = :status, HITLPendingReview = :pending REMOVE HITLReviewOwner, HITLReviewOwnerEmail",
        ExpressionAttributeValues={":status": "Review Pending", ":pending": "true"},
    )

    logger.info(
        f"Review released for document {object_key}, HITLStatus set to Review Pending"
    )
    return build_document_response(object_key)


def _convert_decimals(obj):
    """Recursively convert Decimal values to int/float for JSON serialization."""
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    elif isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_decimals(i) for i in obj]
    elif isinstance(obj, set):
        return [_convert_decimals(i) for i in obj]
    return obj


def build_document_response(object_key):
    """Build standard document response."""
    table = dynamodb.Table(TRACKING_TABLE_NAME)
    response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    doc = response.get("Item", {})

    # Convert all Decimal values for JSON serialization
    doc = _convert_decimals(doc)

    result = {
        "ObjectKey": object_key,
        "ObjectStatus": doc.get("ObjectStatus", ""),
        "InitialEventTime": doc.get("InitialEventTime", ""),
        "QueuedTime": doc.get("QueuedTime", ""),
        "WorkflowStartTime": doc.get("WorkflowStartTime", ""),
        "CompletionTime": doc.get("CompletionTime", ""),
        "WorkflowExecutionArn": doc.get("WorkflowExecutionArn", ""),
        "WorkflowStatus": doc.get("WorkflowStatus", ""),
        "PageCount": doc.get("PageCount", 0),
        "Sections": doc.get("Sections", []),
        "Pages": doc.get("Pages", []),
        "Metering": doc.get("Metering", ""),
        "EvaluationReportUri": doc.get("EvaluationReportUri", ""),
        "EvaluationStatus": doc.get("EvaluationStatus", ""),
        "SummaryReportUri": doc.get("SummaryReportUri", ""),
        "HITLStatus": doc.get("HITLStatus", ""),
        "HITLTriggered": doc.get("HITLTriggered", False),
        "HITLCompleted": doc.get("HITLCompleted", False),
        "HITLReviewURL": doc.get("HITLReviewURL", ""),
        "HITLSectionsPending": doc.get("HITLSectionsPending", []),
        "HITLSectionsCompleted": doc.get("HITLSectionsCompleted", []),
        "HITLSectionsSkipped": doc.get("HITLSectionsSkipped", []),
        "HITLReviewOwner": doc.get("HITLReviewOwner", ""),
        "HITLReviewOwnerEmail": doc.get("HITLReviewOwnerEmail", ""),
        "HITLReviewedBy": doc.get("HITLReviewedBy", ""),
        "HITLReviewedByEmail": doc.get("HITLReviewedByEmail", ""),
        "HITLReviewHistory": doc.get("HITLReviewHistory", []),
        "TraceId": doc.get("TraceId", ""),
    }
    # Final safety conversion to ensure no Decimals slip through
    return _convert_decimals(result)
