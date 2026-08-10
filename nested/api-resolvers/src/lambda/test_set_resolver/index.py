import concurrent.futures
import json
import logging
import os
import re
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from idp_common.dynamodb import DynamoDBClient  # type: ignore
from idp_common.evaluation.confidence_curve import (  # type: ignore
    DEFAULT_FIELDS_PER_DOC,
    DEFAULT_PAGES_PER_DOC,
    estimate_for_target,
)
from idp_common.evaluation.curve_store import CurveStore  # type: ignore
from idp_common.s3 import find_matching_files  # type: ignore
from idp_common.testset_scope import (  # type: ignore
    TestSetAccessDenied,
    assert_can_access_test_set,
    caller_email,
    visible_test_sets,
)

# Constants
MAX_ZIP_SIZE_BYTES = 1073741824  # 1 GB

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def validate_test_set_name(name):
    """Validate test set name: alphanumeric, spaces, hyphens, underscores only, max 50 chars"""
    if not name or not isinstance(name, str):
        return False
    return re.match(r"^[a-zA-Z0-9\s_-]+$", name) and len(name) <= 50


def validate_description(description):
    """Validate description: max 500 chars only"""
    if description is None or description == "":
        return True  # Optional field
    if not isinstance(description, str):
        return False
    return len(description) <= 500


# Configure S3 client with S3v4 signature.
# When S3_ENDPOINT_URL is set (private VPC mode), use virtual-host addressing
# so the SigV4 host header matches the VPC endpoint DNS.
_s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL") or None
_s3_addressing = "virtual" if _s3_endpoint_url else "path"
s3_config = Config(
    signature_version="s3v4",
    s3={"addressing_style": _s3_addressing},
)
s3_client = boto3.client("s3", endpoint_url=_s3_endpoint_url, config=s3_config)
db_client = DynamoDBClient(table_name=os.environ["TRACKING_TABLE"])


def _caller_in_groups(event, allowed):
    """Defense-in-depth RBAC check against the caller's Cognito groups.

    The schema restricts these fields via @aws_cognito_user_pools(cognito_groups),
    but we also enforce the group server-side so the operation is never reachable
    by an unauthorized caller even if the schema directive is missing or
    misconfigured (e.g. the prior @aws_auth directive, which AppSync silently
    ignores on a multi-auth API).
    """
    groups = (event.get("identity") or {}).get("claims", {}).get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return bool(set(allowed).intersection(groups))


# Operations a scoped Annotator may reach. Everything else in this resolver is
# test-set *management* (create, publish, delete, run configs) and stays
# Admin/Author only, so an annotator onboarded for one labeling effort has no
# route to it. Each of these enforces per-set scope internally via
# assert_can_access_test_set — reaching the operation is not the same as being
# allowed to see a given set.
ANNOTATOR_ALLOWED_FIELDS = ("getAnnotationQueue", "getTestSetDocuments")


def handler(event, context):
    field_name = event["info"]["fieldName"]
    logger.info(f"Test set resolver invoked with field_name: {field_name}")

    # Defense-in-depth: Test Studio test-set operations are Admin+Author, plus a
    # narrow allowlist an Annotator may reach for their own queue.
    # Allow direct Lambda invocations (no 'identity' field or identity=None) for CI/automation.
    # AppSync invocations always have 'identity' with non-None value, so RBAC is still enforced for UI users.
    # Security: Direct invocation path is gated by IAM (lambda:InvokeFunction permission on this ARN),
    # not Cognito groups. CI/automation uses IAM credentials; UI users go through AppSync + Cognito.
    is_appsync_invoke = event.get("identity") is not None
    if is_appsync_invoke:
        allowed_groups = ["Admin", "Author"]
        if field_name in ANNOTATOR_ALLOWED_FIELDS:
            allowed_groups.append("Annotator")
        if not _caller_in_groups(event, tuple(allowed_groups)):
            logger.warning(
                f"Forbidden: caller attempted '{field_name}' without "
                f"{'/'.join(allowed_groups)} group"
            )
            raise Exception(
                f"Unauthorized: '{field_name}' requires "
                f"{' or '.join(allowed_groups)} group"
            )

    if field_name == "addTestSet":
        return add_test_set(event["arguments"])
    elif field_name == "addTestSetFromUpload":
        return add_test_set_from_upload(event["arguments"])
    elif field_name == "addDocumentsToTestSet":
        return add_documents_to_test_set(event["arguments"])
    elif field_name == "addDocumentsToTestSetFromUpload":
        return add_documents_to_test_set_from_upload(event["arguments"])
    elif field_name == "updateTestSet":
        return update_test_set(event["arguments"])
    elif field_name == "removeDocumentsFromTestSet":
        return remove_documents_from_test_set(event["arguments"])
    elif field_name == "deleteTestSets":
        return delete_test_sets(event["arguments"])
    elif field_name == "getTestSets":
        return get_test_sets()
    elif field_name == "getTestSetDocuments":
        # Annotators reach this to render their queue's documents, so it must
        # verify per-set scope — group membership alone would let one annotator
        # read another effort's documents.
        assert_can_access_test_set(event, event["arguments"].get("testSetId") or "")
        return get_test_set_documents(event["arguments"])
    elif field_name == "publishTestSetVersion":
        return publish_test_set_version(event["arguments"], event)
    elif field_name == "getTestSetVersions":
        return get_test_set_versions(event["arguments"])
    elif field_name == "generateDraftLabels":
        return generate_draft_labels(event["arguments"], event)
    elif field_name == "getDraftLabelJob":
        return get_draft_label_job(event["arguments"])
    elif field_name == "estimateReviewEffort":
        return estimate_review_effort(event["arguments"])
    elif field_name == "getAnnotationQueue":
        return get_annotation_queue(event["arguments"], event)
    elif field_name == "listBucketFiles":
        return list_bucket_files(event["arguments"])
    elif field_name == "validateTestFileName":
        return validate_test_file_name(event["arguments"])
    else:
        raise Exception(f"Unknown field: {field_name}")


def add_test_set_from_upload(args):
    logger.info(f"Adding test set from zip upload: {args}")

    input_data = args["input"]
    zip_filename = input_data["fileName"]
    description = input_data.get("description", "")  # Optional field
    document_class_type = input_data.get("documentClassType")  # Optional field

    # Validate zip file extension
    if not zip_filename.lower().endswith(".zip"):
        raise Exception("File must be a zip file")

    # Extract test set name from filename (remove .zip extension)
    test_set_name = zip_filename.replace(".zip", "").replace(".ZIP", "")

    # Validate test set name
    if not validate_test_set_name(test_set_name):
        raise Exception(
            "Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)"
        )

    # Validate description
    if description and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"

    test_set_bucket = os.environ["TEST_SET_BUCKET"]

    # Upload with .zip extension in the test set folder
    key = f"{test_set_id}/{zip_filename}"

    # Generate presigned URL for zip file
    presigned_post = s3_client.generate_presigned_post(
        Bucket=test_set_bucket,
        Key=key,
        Fields={"Content-Type": "application/zip"},
        Conditions=[
            ["content-length-range", 1, MAX_ZIP_SIZE_BYTES],
            {"Content-Type": "application/zip"},
        ],
        ExpiresIn=900,  # 15 minutes
    )

    logger.info(f"Generated presigned POST for zip file {key}")

    # Add test set entry to tracking table
    now = datetime.utcnow().isoformat() + "Z"

    item = {
        "PK": f"testset#{test_set_id}",
        "SK": "metadata",
        "ItemType": "testset",
        "InitialEventTime": now,
        "id": test_set_id,
        "name": test_set_name,
        "description": description,
        "filePattern": "",  # Empty for uploaded test sets
        "source": "uploaded",
        "status": "QUEUED",
        "createdAt": now,
    }

    # Add documentClassType if provided
    if document_class_type:
        item["documentClassType"] = document_class_type

    # Don't set fileCount for uploads - will be added after zip processing

    db_client.put_item(item)
    logger.info(f"Created test set {test_set_id} in tracking table with QUEUED status")

    logger.info(
        f"Test set {test_set_id} ready for zip upload - will be processed automatically on upload"
    )

    return {
        "testSetId": test_set_id,
        "presignedUrl": json.dumps(presigned_post),
        "objectKey": key,
    }


def add_test_set(args):
    logger.info(f"Adding test set: {args}")

    test_set_name = args["name"]
    description = args.get("description", "")  # Optional field
    file_count = args["fileCount"]
    document_class_type = args.get("documentClassType")  # Optional field

    # Validate test set name
    if not validate_test_set_name(test_set_name):
        raise Exception(
            "Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)"
        )

    # Validate description
    if description and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    # Generate test set ID with name format, replace spaces with dashes
    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"

    # Create initial test set record
    now = datetime.utcnow().isoformat() + "Z"

    item = {
        "PK": f"testset#{test_set_id}",
        "SK": "metadata",
        "ItemType": "testset",
        "InitialEventTime": now,
        "id": test_set_id,
        "name": test_set_name,
        "description": description,
        "filePattern": args["filePattern"],
        "fileCount": file_count,
        "source": "uploaded",
        "status": "QUEUED",
        "createdAt": now,
    }

    # Add documentClassType if provided
    if document_class_type:
        item["documentClassType"] = document_class_type

    db_client.put_item(item)
    logger.info(f"Created test set {test_set_id} in tracking table")

    # Send file copying job to SQS queue
    import boto3

    sqs = boto3.client("sqs")
    queue_url = os.environ["TEST_SET_COPY_QUEUE_URL"]

    message_body = {
        "testSetId": test_set_id,
        "filePattern": args["filePattern"],
        "bucketType": args["bucketType"],
        "trackingTable": os.environ["TRACKING_TABLE"],
    }
    if args.get("modifiedAfter"):
        message_body["modifiedAfter"] = args["modifiedAfter"]

    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message_body))

    logger.info(
        f"Queued test set creation job for {test_set_id} with pattern '{args['filePattern']}'"
    )

    result = {
        "id": test_set_id,
        "name": test_set_name,
        "description": description,
        "filePattern": args["filePattern"],
        "fileCount": file_count,
        "source": "uploaded",
        "status": "QUEUED",
        "createdAt": now,
    }

    # Add documentClassType to response if provided
    if document_class_type:
        result["documentClassType"] = document_class_type

    return result


def add_documents_to_test_set(args):
    logger.info(f"Adding documents to existing test set: {args}")

    test_set_id = args["testSetId"]
    file_pattern = args["filePattern"]
    bucket_type = args["bucketType"]
    file_count = args["fileCount"]

    # Look up existing test set
    item = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    if item.get("status") != "COMPLETED":
        raise Exception(
            f"Test set '{test_set_id}' is not in COMPLETED status (current: {item.get('status')})"
        )

    # Update status to UPDATING
    tracking_table = os.environ["TRACKING_TABLE"]
    table = boto3.resource("dynamodb").Table(tracking_table)
    table.update_item(
        Key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
        UpdateExpression="SET #status = :status REMOVE lastAddResult",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "UPDATING"},
    )

    # Send file copying job to SQS queue
    sqs = boto3.client("sqs")
    queue_url = os.environ["TEST_SET_COPY_QUEUE_URL"]

    message_body = {
        "testSetId": test_set_id,
        "filePattern": file_pattern,
        "bucketType": bucket_type,
        "trackingTable": tracking_table,
        "mode": "append",
    }
    if args.get("modifiedAfter"):
        message_body["modifiedAfter"] = args["modifiedAfter"]

    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message_body))

    logger.info(
        f"Queued append job for test set {test_set_id} with pattern '{file_pattern}'"
    )

    return {
        "id": test_set_id,
        "name": item["name"],
        "description": item.get("description", ""),
        "filePattern": item.get("filePattern", ""),
        "fileCount": item.get("fileCount"),
        "status": "UPDATING",
        "createdAt": item["createdAt"],
    }


def add_documents_to_test_set_from_upload(args):
    logger.info(f"Adding documents to test set from zip upload: {args}")

    input_data = args["input"]
    test_set_id = input_data["testSetId"]
    zip_filename = input_data["fileName"]

    # Validate zip file extension
    if not zip_filename.lower().endswith(".zip"):
        raise Exception("File must be a zip file")

    # Look up existing test set
    item = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    if item.get("status") != "COMPLETED":
        raise Exception(
            f"Test set '{test_set_id}' is not in COMPLETED status (current: {item.get('status')})"
        )

    # Update status to UPDATING
    tracking_table = os.environ["TRACKING_TABLE"]
    table = boto3.resource("dynamodb").Table(tracking_table)
    table.update_item(
        Key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
        UpdateExpression="SET #status = :status REMOVE lastAddResult",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "UPDATING"},
    )

    test_set_bucket = os.environ["TEST_SET_BUCKET"]

    # Upload with .zip extension in the test set folder
    key = f"{test_set_id}/{zip_filename}"

    # Generate presigned URL for zip file
    presigned_post = s3_client.generate_presigned_post(
        Bucket=test_set_bucket,
        Key=key,
        Fields={"Content-Type": "application/zip"},
        Conditions=[
            ["content-length-range", 1, MAX_ZIP_SIZE_BYTES],
            {"Content-Type": "application/zip"},
        ],
        ExpiresIn=900,  # 15 minutes
    )

    logger.info(f"Generated presigned POST for append zip file {key}")

    return {
        "testSetId": test_set_id,
        "presignedUrl": json.dumps(presigned_post),
        "objectKey": key,
    }


# ---------------------------------------------------------------------------
# Versioning: a test set has a mutable working draft (the SK='metadata' item)
# plus zero or more immutable published versions (SK='version#<n>'). Publishing
# freezes the current document + label state into a numbered version and, by
# default, marks it the "active reference" that scoring runs compare against.
#
# The design is additive: existing test sets have no version items and read as
# latestVersion=0 / activeReference=None, so nothing breaks and no backfill is
# needed. See docs/proposals/ground-truth-hitl/implementation/.
# ---------------------------------------------------------------------------


def _version_sk(n):
    return f"version#{int(n):06d}"


def _list_version_items(test_set_id):
    """Return all version items for a test set, ascending by version number."""
    from boto3.dynamodb.conditions import Key as DDBKey

    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])
    items = []
    query_kwargs = {
        "KeyConditionExpression": (
            DDBKey("PK").eq(f"testset#{test_set_id}")
            & DDBKey("SK").begins_with("version#")
        ),
    }
    while True:
        resp = tracking_table.query(**query_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        query_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda it: it.get("versionNumber", 0))
    return items


def _version_to_result(item):
    return {
        "testSetId": item.get("testSetId"),
        "version": item.get("versionNumber"),
        "label": item.get("label"),
        "notes": item.get("notes"),
        "fileCount": item.get("fileCount"),
        "createdAt": item.get("createdAt"),
        "createdBy": item.get("createdBy"),
    }


def get_test_set_versions(args):
    """List the immutable published versions of a test set (ascending)."""
    test_set_id = args["testSetId"]
    return [_version_to_result(it) for it in _list_version_items(test_set_id)]


def publish_test_set_version(args, event=None):
    """Freeze the current test-set state into a new immutable version.

    Optionally (default true) set the new version as the active reference. The
    metadata pointer tracks latestVersion / publishedVersion / activeReference.
    """
    input_data = args.get("input", args)
    test_set_id = input_data["testSetId"]
    label = input_data.get("label")
    notes = input_data.get("notes")
    set_active = input_data.get("setAsActiveReference", True)

    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not meta:
        raise Exception(f"Test set '{test_set_id}' not found")

    # Reserve the version number by atomically incrementing the counter on the
    # metadata item, and only then write the version item. Computing
    # latestVersion + 1 from the read above and writing it back would be a
    # read-modify-write race: two concurrent publishes both read N and both
    # write version N+1, so the second silently overwrites the first's
    # "immutable" version. ADD serializes the allocation in DynamoDB, so each
    # caller gets a distinct number. attribute_exists(PK) keeps update_item
    # from upserting a metadata row for a set deleted since the read above.
    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])
    try:
        reserve = tracking_table.update_item(
            Key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
            UpdateExpression="ADD latestVersion :one",
            ExpressionAttributeValues={":one": 1},
            ConditionExpression="attribute_exists(PK)",
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise Exception(f"Test set '{test_set_id}' not found")
        raise
    next_version = int(reserve["Attributes"]["latestVersion"])

    now = datetime.utcnow().isoformat() + "Z"
    created_by = None
    if event:
        try:
            created_by = event.get("identity", {}).get("claims", {}).get("email")
        except Exception:
            created_by = None

    # Immutable version item: snapshot the fields that describe this frozen set.
    version_item = {
        "PK": f"testset#{test_set_id}",
        "SK": _version_sk(next_version),
        "ItemType": "testset_version",
        "testSetId": test_set_id,
        "versionNumber": next_version,
        "label": label or f"v{next_version}",
        "notes": notes or "",
        "source": meta.get("source"),
        "fileCount": meta.get("fileCount"),
        "configVersion": meta.get("boundConfigVersion"),
        "createdAt": now,
        "createdBy": created_by,
    }
    # Belt-and-braces: never overwrite an existing version item, even if the
    # counter were ever reset or rewound by hand.
    db_client.put_item(version_item, condition_expression="attribute_not_exists(SK)")

    # Publish the pointers now that the version item exists. Kept separate from
    # the reservation so a failed version write leaves a gap in the numbering
    # rather than a publishedVersion pointing at a version that isn't there.
    #
    # Only ever advance the pointers. Concurrent publishes can reach this write
    # out of order (v2 before v1), and an unconditional SET would leave the
    # newest version published but the pointers referring to an older one.
    # A failed condition just means a newer publish already won, so it is not
    # an error for this caller — its version item is written either way.
    pointer_expr = "SET publishedVersion = :v"
    pointer_values = {":v": next_version}
    if set_active:
        pointer_expr += ", activeReference = :v"
    try:
        tracking_table.update_item(
            Key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
            UpdateExpression=pointer_expr,
            ExpressionAttributeValues=pointer_values,
            ConditionExpression=(
                "attribute_not_exists(publishedVersion) OR publishedVersion < :v"
            ),
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        logger.info(
            f"Test set '{test_set_id}' pointers already at a version newer than "
            f"{next_version}; leaving them unchanged"
        )

    logger.info(
        f"Published test set '{test_set_id}' version {next_version} "
        f"(active={set_active})"
    )
    result = _version_to_result(version_item)
    result["activeReference"] = (
        next_version if set_active else meta.get("activeReference")
    )
    return result


# ---------------------------------------------------------------------------
# Draft labeling: run the active config over a test set's documents to produce
# machine-generated ground-truth candidates ("draft labels") with per-field
# confidence, which a human then reviews and confirms.
#
# This deliberately reuses the *scoring* pipeline rather than a second
# extraction path: startTestRun already copies the set's inputs into the
# pipeline, and the pipeline already emits inference_result plus per-field
# confidence in explainability_info. Reimplementing OCR/classify/extract/assess
# here would duplicate that orchestration and let the confidence semantics
# drift from the ones real scoring runs (and the estimator) rely on. So a
# labeling job is an ordinary test run whose results are harvested back into the
# test set's baseline/ prefix as draft labels.
#
# The job item is SK='labeljob#<testRunId>' under the test set's PK, so jobs are
# listable per set and expire with it.
# ---------------------------------------------------------------------------

LABEL_SOURCE_DRAFT = "draft-machine"
LABEL_SOURCE_HUMAN = "reviewed-human"
# Ground truth supplied with the test set rather than produced or reviewed here.
# Authoritative (draft labeling will not overwrite it) but not review *work*, so
# it must not count toward annotation progress.
LABEL_SOURCE_UPLOADED = "uploaded"


def _label_job_sk(test_run_id):
    return f"labeljob#{test_run_id}"


def _as_int(value):
    """Coerce a DynamoDB number (Decimal) to int; None stays None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _harvest_active_label_job(test_set_id, meta):
    """Advance the set's most recent labeling job and return its current state.

    Labels are harvested on read, so whoever is polling has to drive the harvest.
    Without this an annotator who opens the workspace while labeling is running
    sees an empty queue that never fills: the job only advanced while someone
    watched the owner-facing detail page, which an annotator cannot open.

    Best-effort — a harvest failure must not fail the queue, which is still
    usable for any documents already labeled.
    """
    job_id = meta.get("labelJobId")
    if not job_id:
        return None

    job = db_client.get_item(
        {"PK": f"testset#{test_set_id}", "SK": _label_job_sk(job_id)}
    )
    if not job:
        return None
    if job.get("status") in ("COMPLETED", "FAILED"):
        return job

    try:
        return _harvest_label_job(job)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Queue harvest failed for labeling job {job_id}: {e}")
        return job


def _documents_needing_labels(test_set_id):
    """Object keys with no ground truth of their own, worst-first order aside.

    A document that already carries ground truth — uploaded, generated, or
    human-reviewed — has nothing for a labeling run to add: the harvester would
    process it and then decline to write, because only a prior machine draft is
    replaceable. On a mixed set (some generated ground truth, some bare
    documents) labeling everything therefore paid for inference on documents it
    would discard.

    Returns ``(needs_labels, already_labeled_count)``. An empty first element
    means the whole set is already labeled.
    """
    needs = []
    already = 0
    next_token = None

    while True:
        page = get_test_set_documents(
            {"testSetId": test_set_id, "limit": 200, "nextToken": next_token}
        )
        for doc in page.get("documents") or []:
            # A draft is replaceable, so a previously drafted document is still a
            # candidate — re-running to pick up a better config is legitimate.
            if doc.get("labelSource") in (None, LABEL_SOURCE_DRAFT):
                needs.append(doc["objectKey"])
            else:
                already += 1
        next_token = page.get("nextToken")
        if not next_token:
            break

    return needs, already


def generate_draft_labels(args, event=None):
    """Start a labeling job: run the active config over a test set's documents.

    Returns immediately with a jobId (the underlying test run id); the caller
    polls getDraftLabelJob, which harvests results as documents finish. Existing
    labels are only replaced when they are themselves machine drafts, so
    re-running never clobbers reviewed or hand-uploaded ground truth.

    Without an explicit ``objectKeys``, only documents that *need* labels are
    processed. Labeling a whole mixed set would spend inference on documents
    whose ground truth the harvester then refuses to overwrite — most visibly on
    a fully generated set, where every document already has ground truth and the
    run produced nothing but noise.
    """
    input_data = args.get("input", args)
    test_set_id = input_data["testSetId"]
    config_version = input_data.get("configVersion")
    object_keys = input_data.get("objectKeys") or []

    if not validate_test_set_name(test_set_id):
        raise Exception("Invalid test set id")

    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not meta:
        raise Exception(f"Test set '{test_set_id}' not found")

    file_count = int(meta.get("fileCount", 0) or 0)
    if file_count <= 0:
        raise Exception(f"Test set '{test_set_id}' has no documents to label")

    already_labeled = 0
    if not object_keys:
        object_keys, already_labeled = _documents_needing_labels(test_set_id)
        if not object_keys and already_labeled:
            raise Exception(
                f"Every document in '{test_set_id}' already has ground truth "
                f"({already_labeled} document(s)) — there is nothing to draft-label. "
                "Run a test to score the pipeline against it instead."
            )
        if already_labeled:
            logger.info(
                f"Draft labeling {len(object_keys)} document(s) in {test_set_id}; "
                f"skipping {already_labeled} that already have ground truth"
            )

    # Delegate the run itself to the test runner (single owner of run creation,
    # config capture and version pinning) via a direct Lambda invoke. objectKeys
    # passes through as an explicit document list, so labeling a subset processes
    # only those documents rather than the whole set.
    runner_arn = os.environ["TEST_RUNNER_FUNCTION_ARN"]
    run_input = {
        "testSetId": test_set_id,
        "context": "Draft labeling run",
        # Suppresses baseline staging (and therefore evaluation) for this run.
        "draftLabeling": True,
    }
    if config_version:
        run_input["configVersion"] = config_version
    if object_keys:
        run_input["objectKeys"] = object_keys

    lambda_client = boto3.client("lambda")
    response = lambda_client.invoke(
        FunctionName=runner_arn,
        InvocationType="RequestResponse",
        # No 'identity' key: this is a trusted service-to-service invoke, and the
        # caller was already authorized for generateDraftLabels above.
        Payload=json.dumps(
            {"info": {"fieldName": "startTestRun"}, "arguments": {"input": run_input}}
        ).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError"):
        raise Exception(f"Failed to start labeling run: {payload}")

    test_run_id = payload["testRunId"]
    now = datetime.utcnow().isoformat() + "Z"
    started_by = None
    if event:
        started_by = (event.get("identity") or {}).get("claims", {}).get("email")

    job_item = {
        "PK": f"testset#{test_set_id}",
        "SK": _label_job_sk(test_run_id),
        "ItemType": "testset_label_job",
        "testSetId": test_set_id,
        "jobId": test_run_id,
        "status": "RUNNING",
        "configVersion": config_version,
        "total": len(object_keys) or file_count,
        "labeled": 0,
        "objectKeys": object_keys,
        "skippedAlreadyLabeled": already_labeled,
        "createdAt": now,
        "startedBy": started_by,
    }
    db_client.put_item(job_item)

    # Mark the set as actively being labeled so the UI can show progress even if
    # the user navigates away and comes back.
    db_client.update_item(
        key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
        update_expression="SET labelJobId = :j, labelJobStatus = :s",
        expression_attribute_values={":j": test_run_id, ":s": "RUNNING"},
    )

    logger.info(
        f"Started draft-labeling job {test_run_id} for test set {test_set_id} "
        f"({job_item['total']} document(s), configVersion={config_version})"
    )
    return _label_job_to_result(job_item)


def _label_job_to_result(item):
    return {
        "jobId": item.get("jobId"),
        "testSetId": item.get("testSetId"),
        "status": item.get("status"),
        "total": int(item.get("total", 0) or 0),
        "labeled": int(item.get("labeled", 0) or 0),
        "configVersion": item.get("configVersion"),
        "error": item.get("error"),
        "createdAt": item.get("createdAt"),
        "completedAt": item.get("completedAt"),
        "skippedAlreadyLabeled": int(item.get("skippedAlreadyLabeled", 0) or 0),
    }


def get_draft_label_job(args):
    """Poll a labeling job, harvesting any newly-finished documents.

    Progress is computed by harvesting on read rather than from a subscription:
    test-run completion in this system is already poll-based (the results
    resolver recounts doc items on read), so there is no completion event to
    hook. Harvesting here keeps the primitive self-contained and idempotent.
    """
    test_set_id = args["testSetId"]
    job_id = args["jobId"]

    job = db_client.get_item(
        {"PK": f"testset#{test_set_id}", "SK": _label_job_sk(job_id)}
    )
    if not job:
        raise Exception(f"Labeling job '{job_id}' not found")

    if job.get("status") in ("COMPLETED", "FAILED"):
        return _label_job_to_result(job)

    return _label_job_to_result(_harvest_label_job(job))


def _walk_confidence(explainability_info):
    """Collect (confidence, confidence_threshold) pairs from explainability_info.

    The shape is nested and irregular — ``{field: {"confidence": 0.9}}`` for
    scalars, nested dicts for compound fields (``PayPeriod.StartDate``), lists of
    such dicts for tables — so walk it and collect every ``confidence`` leaf
    rather than assuming a depth.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            value = node.get("confidence")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                threshold = node.get("confidence_threshold")
                if not isinstance(threshold, (int, float)) or isinstance(
                    threshold, bool
                ):
                    threshold = None
                found.append((float(value), threshold))
            for key, child in node.items():
                if key != "confidence":
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(explainability_info)
    return found


def _absent_field_paths(inference_result):
    """Leaf names whose extracted value is absent (null / "" / empty container).

    A field the document genuinely does not contain gets confidence 0.0 with a
    reason like "No employer EIN found in OCR results". That is a *correct*
    reading of a blank box, not a low-quality extraction — but it is
    indistinguishable from real uncertainty once reduced to a number.
    """
    absent = set()

    def walk(node, name=None):
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, key)
        elif isinstance(node, list):
            if not node and name:
                absent.add(name)
            for child in node:
                walk(child, name)
        elif name and (node is None or node == ""):
            absent.add(name)

    walk(inference_result)
    return absent


def _min_confidence(explainability_info, inference_result=None):
    """Lowest confidence among fields the document actually *has* a value for.

    Returns None when the payload carries no confidence at all (e.g. assessment
    disabled), so callers can distinguish "no confidence data" from
    "confidence 0".

    Fields whose extracted value is absent are excluded. Scoring a blank W-2 box
    as 0.0 confidence dragged whole documents to "0.0%" in the browser even when
    every populated field scored >0.99 — the number described the emptiest box on
    the form rather than the quality of the extraction, and it made every
    generated set look worthless. Those fields keep their 0.0 in
    explainability_info (the per-field detail is still true); they just no longer
    define the document's headline score.
    """
    found = _walk_confidence(explainability_info)
    if not found:
        return None
    if inference_result is not None:
        absent = _absent_field_paths(inference_result)
        populated = [
            (c, t)
            for c, t, name in _walk_confidence_named(explainability_info)
            if name not in absent
        ]
        # Fall back to the unfiltered minimum when *every* field is absent, so a
        # genuinely empty extraction still reports 0 rather than "no data".
        if populated:
            return min(c for c, _ in populated)
    return min(c for c, _ in found)


def _walk_confidence_named(explainability_info):
    """As :func:`_walk_confidence`, plus the field name each score belongs to."""
    found = []

    def walk(node, name=None):
        if isinstance(node, dict):
            value = node.get("confidence")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                threshold = node.get("confidence_threshold")
                if not isinstance(threshold, (int, float)) or isinstance(
                    threshold, bool
                ):
                    threshold = None
                found.append((float(value), threshold, name))
            for key, child in node.items():
                if key != "confidence":
                    walk(child, key)
        elif isinstance(node, list):
            for child in node:
                walk(child, name)

    walk(explainability_info)
    return found


def _confidence_threshold(explainability_info, inference_result=None):
    """The configured alert threshold for the weakest field, if it carries one.

    Reported alongside minConfidence so the UI can color against the *config's*
    threshold instead of hardcoded bands — a 0.85 confidence is failing under a
    0.9 threshold and passing under 0.8, and inventing constants in the UI would
    contradict the assessment config on both.
    """
    found = _walk_confidence_named(explainability_info)
    if not found:
        return None
    if inference_result is not None:
        absent = _absent_field_paths(inference_result)
        populated = [f for f in found if f[2] not in absent]
        if populated:
            found = populated
    # Tie to the same field minConfidence reports.
    return min(found, key=lambda triple: triple[0])[1]


# ---------------------------------------------------------------------------
# Review-effort estimator: "how many documents must a human review to reach a
# target accuracy?" Reads the measured confidence→accuracy curve for this test
# set (see idp_common.evaluation.confidence_curve) and the set's per-document
# confidences, and returns the review depth, implied cutoff, effort, audit
# sample and — crucially — how much the numbers can be trusted.
# ---------------------------------------------------------------------------


def get_annotation_queue(args, event=None):
    """The worst-first annotation queue for one test set.

    Returns the set's documents ordered lowest-confidence first — so each review
    removes the most expected error — annotated with claim state so several
    annotators can work the same set in parallel without colliding. Documents
    already claimed by someone else, or already reviewed, are marked so they drop
    out of everyone else's "next in queue"; claim-to-lock (``claimReview``) is
    what actually enforces exclusivity, this query just reflects it.

    Access is scoped server-side: an ``Annotator`` may only read the queue for a
    test set in their ``allowedTestSets``. The shareable queue link is therefore
    a navigation aid, not a credential.
    """
    test_set_id = args["testSetId"]
    limit = max(1, min(int(args.get("limit") or 50), 200))
    include_completed = bool(args.get("includeCompleted"))

    if not validate_test_set_name(test_set_id):
        raise Exception("Invalid test set id")

    # Enforce test-set scope before reading anything about the set, so an
    # unauthorized caller learns nothing (not even whether the set exists).
    assert_can_access_test_set(event, test_set_id)

    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not meta:
        raise Exception(f"Test set '{test_set_id}' not found")

    label_job = _harvest_active_label_job(test_set_id, meta)

    documents = _collect_queue_documents(test_set_id)
    claims = _claim_state_for_documents(test_set_id, meta, documents)

    caller = caller_email(event)
    # Review operations (claimReview / completeSectionReview) key on the *pipeline*
    # copy of a document, "{runId}/{filename}", not the test-set key. Return it so
    # the UI never has to reconstruct that shape itself — the key layout is a
    # backend detail, and a client rebuilding it would break silently the moment
    # it changed.
    run_id = meta.get("labelJobId")
    entries = []
    for doc in documents:
        state = claims.get(doc["objectKey"], {})
        owner = state.get("owner") or ""
        status = state.get("status") or ""
        reviewed = doc.get("labelSource") == LABEL_SOURCE_HUMAN or status in (
            "Review Completed",
            "Completed",
            "Review Skipped",
            "Skipped",
        )
        # "Available" means this caller could claim it next: unreviewed and
        # either unclaimed or already theirs.
        claimed_by_other = bool(owner) and owner != caller
        # A pipeline copy only exists for documents the labeling run actually
        # processed. Ground truth is skipped by draft labeling, so offering a
        # review key for it produced "Document <runId>/<file> not found" the
        # moment an annotator reached it in the queue.
        has_pipeline_copy = bool(run_id) and state.get("exists", False)
        entries.append(
            {
                "objectKey": doc["objectKey"],
                "inputKey": doc["inputKey"],
                # None when this document has no pipeline copy to review: either
                # the set has no labeling run, or the run skipped this document
                # because it already carried ground truth.
                "reviewObjectKey": (
                    f"{run_id}/{doc['objectKey']}" if has_pipeline_copy else None
                ),
                "minConfidence": doc.get("minConfidence"),
                "confidenceThreshold": doc.get("confidenceThreshold"),
                "labelSource": doc.get("labelSource"),
                "sectionCount": len(doc.get("sections") or []),
                "sections": doc.get("sections") or [],
                "claimedBy": owner or None,
                "claimedByMe": bool(owner) and owner == caller,
                "reviewStatus": status or None,
                "reviewed": reviewed,
                "available": not reviewed and not claimed_by_other,
            }
        )

    def sort_key(entry):
        """Worst-first. Unlabeled sorts first, authored ground truth last.

        "No confidence" means two different things. An unlabeled document has had
        nothing attempted, so it needs the most attention. Ground truth was
        authored rather than predicted — there is no self-assessment to be low and
        nothing to correct — so it needs the least. Collapsing both to one
        sentinel pointed annotators at generated ground truth ahead of genuinely
        uncertain drafts, inverting what worst-first is for.
        """
        confidence = entry["minConfidence"]
        if confidence is not None:
            return (0, confidence, entry["objectKey"])
        if entry["labelSource"] in (None, LABEL_SOURCE_DRAFT):
            return (-1, 0.0, entry["objectKey"])
        return (1, 0.0, entry["objectKey"])

    entries.sort(key=sort_key)

    reviewed_count = sum(1 for e in entries if e["reviewed"])
    inspected = len(entries)
    # The set's real size. Counting only the inspected page would report a
    # 2008-document set as 500 (the queue cap) and show "0 remaining" once the
    # first page was reviewed, while most of the set was still untouched.
    total = int(meta.get("fileCount", 0) or 0) or inspected
    # Note: authored ground truth counts toward totalDocs but has no pipeline copy
    # to claim, so a mixed set cannot currently reach 100% in the progress banner.
    # Left as-is deliberately — excluding it would contradict
    # test_uploaded_ground_truth_is_not_counted_as_review_work, which encodes a
    # live-found regression (an uploaded set reporting itself fully annotated).
    # Resolving this needs a product decision, not a quiet accounting change.
    queue = [e for e in entries if include_completed or not e["reviewed"]]

    result = {
        "testSetId": test_set_id,
        "totalDocs": total,
        "inspectedDocs": inspected,
        "reviewedDocs": reviewed_count,
        # Documents beyond the inspected page have not been reviewed, so they
        # count as remaining.
        "remainingDocs": max(0, total - reviewed_count),
        "claimedByOthers": sum(
            1
            for e in entries
            if not e["reviewed"] and e["claimedBy"] and not e["claimedByMe"]
        ),
        "documents": queue[:limit],
        # The next document this caller should open — the whole point of
        # "Save & next". None when the queue is drained for them.
        "nextObjectKey": next((e["objectKey"] for e in queue if e["available"]), None),
        "labelJobStatus": (label_job or {}).get("status"),
        "labelJobLabeled": _as_int((label_job or {}).get("labeled")),
        "labelJobTotal": _as_int((label_job or {}).get("total")),
    }
    logger.info(
        f"getAnnotationQueue({test_set_id}) for {caller or 'service'}: "
        f"{result['remainingDocs']}/{total} remaining "
        f"({inspected} inspected), "
        f"{result['claimedByOthers']} claimed by others"
    )
    return result


def _collect_queue_documents(test_set_id):
    """All documents in the set with their label metadata, up to the queue cap."""
    documents = []
    next_token = None
    while len(documents) < MAX_DOCS_FOR_ESTIMATE:
        page = get_test_set_documents(
            {
                "testSetId": test_set_id,
                "limit": min(200, MAX_DOCS_FOR_ESTIMATE - len(documents)),
                "nextToken": next_token,
            }
        )
        documents.extend(page.get("documents") or [])
        next_token = page.get("nextToken")
        if not next_token:
            break
    return documents


def _claim_state_for_documents(test_set_id, meta, documents):
    """Map objectKey → claim/review state from the HITL document records.

    Review happens against the *pipeline* copy of a document (keyed
    ``doc#{testRunId}/{filename}``), not the test-set copy, because that is what
    sendTestRunToReview puts into the review hopper. The set's most recent
    labeling/scoring run therefore supplies the run prefix; without one there is
    nothing claimed yet and every document reads as available.
    """
    run_id = meta.get("labelJobId")
    if not run_id:
        return {}

    table_name = os.environ["TRACKING_TABLE"]
    resource = boto3.resource("dynamodb")
    state = {}

    # BatchGetItem rather than one GetItem per document: a 500-document queue was
    # 500 sequential round-trips, which dominated the response time. Batches cap
    # at 100 keys.
    keys_by_pk = {
        f"doc#{run_id}/{doc['objectKey']}": doc["objectKey"] for doc in documents
    }
    all_keys = list(keys_by_pk)
    for start in range(0, len(all_keys), 100):
        batch = [{"PK": pk, "SK": "none"} for pk in all_keys[start : start + 100]]
        try:
            pending = {table_name: {"Keys": batch}}
            # UnprocessedKeys is normal under throttling; retry what came back
            # short rather than silently reporting those documents as unclaimed.
            for _ in range(4):
                response = resource.batch_get_item(RequestItems=pending)
                for item in response.get("Responses", {}).get(table_name, []):
                    object_key = keys_by_pk.get(item.get("PK", ""))
                    if not object_key:
                        continue
                    state[object_key] = {
                        "owner": item.get("HITLReviewOwner") or "",
                        "status": item.get("HITLStatus") or "",
                        # Presence of the item is what proves the run actually
                        # processed this document, which is a precondition for
                        # claiming it.
                        "exists": True,
                    }
                pending = response.get("UnprocessedKeys") or {}
                if not pending:
                    break
        except Exception as e:  # noqa: BLE001 — a missing claim is not an error
            logger.warning(
                f"Could not read claim state for {len(batch)} document(s): {e}"
            )
    return state


def estimate_review_effort(args):
    """Server-side estimate for the "set up team annotation" flow.

    Replaces the prototype's fixture interpolation with the stored curve. The
    estimate always reports its own trustworthiness (``estimateConfidence`` plus
    the calibration block), because on a cold or miscalibrated set a bare
    docs-to-review number is actively misleading — it looks measured when it is a
    prior, and it understates effort when confidence hides errors in the
    auto-accepted zone.
    """
    test_set_id = args["testSetId"]
    target_accuracy = float(args.get("targetAccuracy") or 99.0)
    config_version = args.get("configVersion")

    if not validate_test_set_name(test_set_id):
        raise Exception("Invalid test set id")
    if not (0.0 < target_accuracy <= 100.0):
        raise Exception("targetAccuracy must be between 0 and 100")

    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not meta:
        raise Exception(f"Test set '{test_set_id}' not found")

    # Default to the config the set is bound to, so the curve matches the
    # confidence semantics that produced these labels.
    if not config_version:
        config_version = meta.get("boundConfigVersion")

    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])
    store = CurveStore(tracking_table)
    curve = store.get_curve(test_set_id, config_version)
    prior = store.get_global_prior()

    doc_confidences, fields_per_doc, pages_per_doc, ground_truth_docs = (
        _collect_doc_confidences(test_set_id)
    )

    # The set's real size, which may exceed the number of documents sampled for
    # confidences. These must not be conflated: reporting the sample size as the
    # total understates the work (and the effort, and the audit pool) by whatever
    # factor the set exceeds MAX_DOCS_FOR_ESTIMATE.
    total_docs = int(meta.get("fileCount", 0) or 0) or len(doc_confidences)
    # Ground truth is not reviewable work, so it comes off the total rather than
    # counting as documents awaiting review.
    total_docs = max(0, total_docs - ground_truth_docs)
    sampled_docs = len(doc_confidences)

    # When only a sample was read, treat it as representative and extrapolate its
    # confidence distribution across the whole set, so the ordering the estimator
    # walks has one entry per real document. Repeating the sample preserves its
    # shape, which is what the estimate depends on — the alternative (estimating
    # from the sample and scaling the answer) would also have to scale the
    # residual-error curve, and would silently assume the untouched documents
    # look like the sampled ones anyway.
    if doc_confidences and sampled_docs < total_docs:
        repeats = -(-total_docs // sampled_docs)  # ceil
        doc_confidences = (doc_confidences * repeats)[:total_docs]
        logger.info(
            f"estimateReviewEffort({test_set_id}): extrapolating {sampled_docs} "
            f"sampled confidences across {total_docs} documents"
        )

    estimate = estimate_for_target(
        curve,
        target_accuracy,
        total_docs,
        doc_confidences=doc_confidences or None,
        prior=prior,
        fields_per_doc=fields_per_doc,
        pages_per_doc=pages_per_doc,
    )

    result = estimate.to_dict()
    result["testSetId"] = test_set_id
    result["targetAccuracy"] = target_accuracy
    result["configVersion"] = config_version
    result["reliabilityTable"] = curve.reliability_table(prior)
    # Surfaced so a caller can say "estimated from a 500-document sample" rather
    # than implying every document was inspected.
    result["sampledDocs"] = sampled_docs
    logger.info(
        f"estimateReviewEffort({test_set_id}, target={target_accuracy}): "
        f"{estimate.docs_to_review}/{total_docs} docs, "
        f"confidence={estimate.estimate_confidence.value}"
    )
    return result


# Cap on how many documents the estimator will read confidences for. The
# estimate is a planning number, not an audit: past this many documents the
# sample is more than enough to shape the curve, and reading every section of a
# 5,000-document set would blow the resolver's timeout.
MAX_DOCS_FOR_ESTIMATE = 500


def _collect_doc_confidences(test_set_id):
    """Per-document minimum confidence, plus observed doc shape for the effort model.

    Reuses the same baseline read the document list uses, so the estimator orders
    documents exactly as the reviewer will see them — an estimate computed from a
    different ordering than the one the UI presents would not describe the work
    the user is actually about to do.

    Returns ``(confidences, fields_per_doc, pages_per_doc, ground_truth_docs)``.
    The two shape figures fall back to the module defaults when the baseline
    carries nothing to measure them from. ``ground_truth_docs`` is how many
    inspected documents already carry ground truth and were therefore left out
    of ``confidences``.
    """
    test_set_bucket = os.environ["TEST_SET_BUCKET"]
    documents = []
    next_token = None

    while len(documents) < MAX_DOCS_FOR_ESTIMATE:
        page = get_test_set_documents(
            {
                "testSetId": test_set_id,
                "limit": min(200, MAX_DOCS_FOR_ESTIMATE - len(documents)),
                "nextToken": next_token,
            }
        )
        documents.extend(page.get("documents") or [])
        next_token = page.get("nextToken")
        if not next_token:
            break

    confidences = []
    ground_truth_docs = 0
    for doc in documents:
        if doc.get("minConfidence") is not None or doc.get("labelSource") in (
            None,
            LABEL_SOURCE_DRAFT,
        ):
            confidences.append(doc.get("minConfidence"))
        else:
            ground_truth_docs += 1

    # Effort model inputs, measured rather than assumed where possible: the
    # number of fields a reviewer actually has to check drives the time far more
    # than a global average does.
    field_counts = []
    for doc in documents:
        for section in doc.get("sections") or []:
            key = section.get("baselineKey")
            if not key:
                continue
            count = _count_baseline_fields(test_set_bucket, key)
            if count:
                field_counts.append(count)
        if len(field_counts) >= 20:
            break  # A sample is enough to characterise the set.

    fields_per_doc = (
        sum(field_counts) / len(field_counts)
        if field_counts
        else DEFAULT_FIELDS_PER_DOC
    )
    # Sections stand in for pages: a section is the unit a reviewer opens, and
    # the baseline records sections, not page counts.
    section_counts = [len(doc.get("sections") or []) for doc in documents]
    pages_per_doc = (
        sum(section_counts) / len(section_counts)
        if section_counts
        else DEFAULT_PAGES_PER_DOC
    )
    return confidences, fields_per_doc, max(1.0, pages_per_doc), ground_truth_docs


def _count_baseline_fields(bucket, key):
    """Number of leaf fields in a baseline section result, or None if unreadable."""
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        result = json.loads(body)
    except Exception as e:  # noqa: BLE001 — effort model input is best-effort
        logger.warning(f"Could not read baseline for field count {key}: {e}")
        return None

    def count(node):
        if isinstance(node, dict):
            return sum(count(v) for v in node.values()) or len(node)
        if isinstance(node, list):
            return sum(count(v) for v in node)
        return 1

    inference = result.get("inference_result")
    return count(inference) if inference else None


def _harvest_label_job(job):
    """Copy finished pipeline results into the test set's baseline as drafts.

    For each of the run's documents whose processing has completed, read the
    section extraction results the pipeline wrote and store them at
    ``{test_set_id}/baseline/<doc>/sections/<n>/result.json`` — the same layout
    the ground-truth editor and scoring already read — tagged
    ``labelSource=draft-machine`` with the per-field confidence preserved.

    Idempotent and non-destructive: a document already carrying a human-reviewed
    label is skipped, so re-harvesting (or re-running a job) never overwrites
    confirmed ground truth.
    """
    test_set_id = job["testSetId"]
    job_id = job["jobId"]
    test_set_bucket = os.environ["TEST_SET_BUCKET"]
    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])

    run = tracking_table.get_item(
        Key={"PK": f"testrun#{job_id}", "SK": "metadata"}
    ).get("Item")
    if not run:
        return _fail_label_job(job, f"Labeling run '{job_id}' not found")
    if run.get("Status") == "FAILED":
        return _fail_label_job(job, run.get("Error") or "Labeling run failed")

    wanted = set(job.get("objectKeys") or [])
    files = [f for f in (run.get("Files") or []) if not wanted or f in wanted]

    labeled = 0
    pending = 0
    for file_name in files:
        doc = tracking_table.get_item(
            Key={"PK": f"doc#{job_id}/{file_name}", "SK": "none"}
        ).get("Item")
        if not doc or doc.get("ObjectStatus") != "COMPLETED":
            pending += 1
            continue

        try:
            if _write_draft_labels_for_doc(
                test_set_bucket,
                test_set_id,
                file_name,
                doc.get("Sections") or [],
                config_version=job.get("configVersion") or doc.get("ConfigVersion"),
            ):
                labeled += 1
            # Stamp the owning test set onto the pipeline document. Without this
            # the HITL review Lambda cannot tell that a reviewed document belongs
            # to a test set, so completeSectionReview silently skips the baseline
            # write-back, the reviewed-human tag, and the confidence-curve
            # observation — the save reports success while none of it happens.
            # Only sendTestRunToReview set this field before, and draft labeling
            # never goes through that path.
            if not doc.get("TestSetId"):
                tracking_table.update_item(
                    Key={"PK": f"doc#{job_id}/{file_name}", "SK": "none"},
                    UpdateExpression="SET TestSetId = :tsid",
                    ExpressionAttributeValues={":tsid": test_set_id},
                )
        except Exception as e:  # noqa: BLE001 — one bad doc must not fail the job
            logger.error(
                f"Draft labeling: failed to harvest '{file_name}' for job {job_id}: {e}"
            )

    status = "RUNNING" if pending else "COMPLETED"
    now = datetime.utcnow().isoformat() + "Z"
    update_expr = "SET #st = :s, labeled = :n"
    expr_values = {":s": status, ":n": labeled}
    if status == "COMPLETED":
        update_expr += ", completedAt = :c"
        expr_values[":c"] = now

    db_client.update_item(
        key={"PK": f"testset#{test_set_id}", "SK": _label_job_sk(job_id)},
        update_expression=update_expr,
        expression_attribute_names={"#st": "status"},
        expression_attribute_values=expr_values,
    )

    meta_expr = "SET labelJobStatus = :s"
    meta_values = {":s": status}
    if status == "COMPLETED":
        # The set now carries machine labels; publishing freezes them as-is and
        # flags them as unreviewed.
        meta_expr += ", labelState = :ls"
        meta_values[":ls"] = "draft"
    db_client.update_item(
        key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
        update_expression=meta_expr,
        expression_attribute_values=meta_values,
    )

    logger.info(
        f"Draft labeling job {job_id}: labeled={labeled} pending={pending} "
        f"status={status}"
    )
    updated = dict(job)
    updated.update({"status": status, "labeled": labeled})
    if status == "COMPLETED":
        updated["completedAt"] = now
    return updated


def _write_draft_labels_for_doc(
    test_set_bucket, test_set_id, file_name, sections, config_version=None
):
    """Write one document's sections into the test-set baseline as draft labels.

    Returns True if anything was written. Sections already reviewed by a human
    are left untouched.

    Sections a previous run wrote that this one no longer produces are pruned —
    see :func:`_prune_superseded_draft_sections`.
    """
    wrote = False
    written_section_ids = set()
    for section in sections:
        section_id = str(section.get("Id") or section.get("SectionId") or "")
        output_uri = section.get("OutputJSONUri") or ""
        if not section_id or not output_uri.startswith("s3://"):
            continue

        baseline_key = (
            f"{test_set_id}/baseline/{file_name}/sections/{section_id}/result.json"
        )
        if _existing_label_is_human(test_set_bucket, baseline_key):
            logger.info(f"Draft labeling: keeping reviewed label at {baseline_key}")
            continue

        src_bucket, src_key = output_uri[len("s3://") :].split("/", 1)
        body = s3_client.get_object(Bucket=src_bucket, Key=src_key)["Body"].read()
        result = json.loads(body)

        explainability = result.get("explainability_info")
        inference = result.get("inference_result")
        min_conf = _min_confidence(explainability, inference)
        result["labelSource"] = LABEL_SOURCE_DRAFT
        # Record which config produced these labels. completeSectionReview reads
        # metadata.config_version to key the confidence curve, so without this
        # every review observation landed in the version-agnostic _aggregate curve
        # while scoring observations went to the per-version one — the two halves
        # of the calibration signal never combined.
        if config_version:
            metadata = result.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.setdefault("config_version", config_version)
            result["metadata"] = metadata
        if min_conf is not None:
            result["minConfidence"] = min_conf
            threshold = _confidence_threshold(explainability, inference)
            if threshold is not None:
                result["confidenceThreshold"] = threshold

        s3_client.put_object(
            Bucket=test_set_bucket,
            Key=baseline_key,
            Body=json.dumps(result, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        written_section_ids.add(section_id)
        wrote = True

    if wrote:
        _prune_superseded_draft_sections(
            test_set_bucket, test_set_id, file_name, written_section_ids
        )

    return wrote


def _prune_superseded_draft_sections(
    test_set_bucket, test_set_id, file_name, written_section_ids
):
    """Delete draft sections a previous run wrote that this one did not produce.

    Draft labeling writes one object per section, so a re-run that produces
    *fewer* sections than the last one leaves the extras behind. They are not
    inert: a document's confidence is the minimum across its sections, so a stale
    0.50 orphan keeps the document reading 50% even after a corrected run scores
    every real field above 0.94 — the fix is applied but invisible. Orphans also
    stay in the annotation queue and in scoring as sections of a document that no
    longer has them.

    Only a document's own ``draft-machine`` sections are eligible. Ground truth
    (uploaded, generated, or ``reviewed-human``) is never touched, and this only
    runs when the current run wrote at least one section for the document, so a
    partial failure cannot empty an existing baseline.
    """
    prefix = f"{test_set_id}/baseline/{file_name}/sections/"
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        existing = []
        for page in paginator.paginate(Bucket=test_set_bucket, Prefix=prefix):
            existing.extend(obj["Key"] for obj in page.get("Contents", []))
    except Exception as e:  # noqa: BLE001 — pruning must not fail the harvest
        logger.warning(f"Could not list baseline sections under {prefix}: {e}")
        return

    removed = 0
    for key in existing:
        if not key.endswith("/result.json"):
            continue
        section_id = key[len(prefix) :].split("/")[0]
        if section_id in written_section_ids:
            continue
        # Never prune anything this run could not have written: only a prior
        # machine draft is disposable.
        if _existing_label_is_human(test_set_bucket, key):
            continue
        try:
            s3_client.delete_object(Bucket=test_set_bucket, Key=key)
            removed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not prune superseded draft section {key}: {e}")

    if removed:
        logger.info(
            f"Pruned {removed} superseded draft section(s) for {file_name}: this "
            f"run produced sections {sorted(written_section_ids)}"
        )


def _existing_label_is_human(bucket, key):
    """True if an existing baseline label must not be overwritten by a draft.

    Anything already present counts as human-owned **unless** it is explicitly
    tagged as a machine draft. A hand-uploaded baseline carries no labelSource at
    all, and treating that as writable would let draft labeling silently destroy
    the ground truth a user supplied — so absence of the tag is protective, not
    permissive. Only a prior draft-machine label is safe to replace.
    """
    try:
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:
        return False  # No existing label (or unreadable) — safe to write.
    try:
        return json.loads(body).get("labelSource") != LABEL_SOURCE_DRAFT
    except Exception:
        # Existing but unparseable: leave it alone rather than clobbering data we
        # can't inspect.
        return True


def _fail_label_job(job, message):
    db_client.update_item(
        key={
            "PK": f"testset#{job['testSetId']}",
            "SK": _label_job_sk(job["jobId"]),
        },
        update_expression="SET #st = :s, #er = :e",
        expression_attribute_names={"#st": "status", "#er": "error"},
        expression_attribute_values={":s": "FAILED", ":e": message},
    )
    db_client.update_item(
        key={"PK": f"testset#{job['testSetId']}", "SK": "metadata"},
        update_expression="SET labelJobStatus = :s",
        expression_attribute_values={":s": "FAILED"},
    )
    logger.error(f"Draft labeling job {job['jobId']} failed: {message}")
    updated = dict(job)
    updated.update({"status": "FAILED", "error": message})
    return updated


def remove_documents_from_test_set(args):
    """Remove named documents from a test set (delete input + baseline objects).

    Deletes, for each requested file name, the ``{id}/input/<file>`` object and
    the whole ``{id}/baseline/<file>/`` folder, then recounts and updates
    fileCount. Editing membership targets the mutable working draft; a later
    publish cuts the next immutable version. Additive — no existing path changes.
    """
    test_set_id = args["testSetId"]
    file_names = args["fileNames"]
    logger.info(f"Removing {len(file_names)} document(s) from test set {test_set_id}")

    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not meta:
        raise Exception(f"Test set '{test_set_id}' not found")

    test_set_bucket = os.environ["TEST_SET_BUCKET"]
    s3_client = boto3.client("s3")

    removed = 0
    for file_name in file_names:
        keys_to_delete = []
        # The single input object.
        keys_to_delete.append(f"{test_set_id}/input/{file_name}")
        # The baseline folder for this file (may contain nested section results).
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=test_set_bucket, Prefix=f"{test_set_id}/baseline/{file_name}/"
        ):
            for obj in page.get("Contents", []):
                keys_to_delete.append(obj["Key"])

        if keys_to_delete:
            # delete_objects caps at 1000 keys/request; batch to be safe.
            for i in range(0, len(keys_to_delete), 1000):
                s3_client.delete_objects(
                    Bucket=test_set_bucket,
                    Delete={
                        "Objects": [{"Key": k} for k in keys_to_delete[i : i + 1000]]
                    },
                )
            removed += 1

    # Recount remaining inputs and update the metadata pointer. Only the count
    # is used here, and an unlabeled set must still recount correctly.
    validation = _validate_test_set_files(
        s3_client, test_set_bucket, test_set_id, allow_unlabeled=True
    )
    new_count = validation.get("input_count", 0)
    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])
    tracking_table.update_item(
        Key={"PK": f"testset#{test_set_id}", "SK": "metadata"},
        UpdateExpression="SET fileCount = :c, lastAddResult = :r",
        ExpressionAttributeValues={
            ":c": new_count,
            ":r": f"Removed {removed} document(s)",
        },
    )

    logger.info(
        f"Removed {removed} document(s) from test set {test_set_id}; "
        f"{new_count} remaining"
    )
    return {
        "id": test_set_id,
        "name": meta.get("name"),
        "fileCount": new_count,
        "status": meta.get("status"),
        "createdAt": meta.get("createdAt"),
        "lastAddResult": f"Removed {removed} document(s)",
    }


def update_test_set(args):
    logger.info(f"Updating test set: {args}")

    input_data = args["input"]
    test_set_id = input_data["id"]
    description = input_data.get("description")
    document_class_type = input_data.get("documentClassType")

    # Validate description if provided
    if description is not None and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    # Look up existing test set
    item = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    # Build update expression dynamically
    update_parts = []
    expression_values = {}
    expression_names = {}

    if description is not None:
        update_parts.append("#desc = :desc")
        expression_values[":desc"] = description
        expression_names["#desc"] = "description"

    # Check if we need to remove documentClassType
    remove_expression = False
    if "documentClassType" in input_data and document_class_type is None:
        # Explicitly remove documentClassType if set to None
        remove_expression = True
    elif document_class_type is not None:
        # Set documentClassType to the new value
        update_parts.append("documentClassType = :docType")
        expression_values[":docType"] = document_class_type

    if not update_parts and not remove_expression:
        # No updates requested, just return current item
        return {
            "id": item["id"],
            "name": item["name"],
            "description": item.get("description", ""),
            "filePattern": item.get("filePattern", ""),
            "fileCount": item.get("fileCount"),
            "status": item.get("status"),
            "createdAt": item["createdAt"],
            "documentClassType": item.get("documentClassType"),
        }

    # Perform the update
    tracking_table = os.environ["TRACKING_TABLE"]
    table = boto3.resource("dynamodb").Table(tracking_table)

    # Build update expression
    update_expression = ""
    if update_parts:
        update_expression = f"SET {', '.join(update_parts)}"
    if remove_expression:
        if update_expression:
            update_expression += " REMOVE documentClassType"
        else:
            update_expression = "REMOVE documentClassType"

    update_kwargs = {
        "Key": {"PK": f"testset#{test_set_id}", "SK": "metadata"},
        "UpdateExpression": update_expression,
        "ReturnValues": "ALL_NEW",
    }

    if expression_names:
        update_kwargs["ExpressionAttributeNames"] = expression_names
    if expression_values:
        update_kwargs["ExpressionAttributeValues"] = expression_values

    response = table.update_item(**update_kwargs)
    updated_item = response["Attributes"]

    logger.info(f"Updated test set {test_set_id}")

    return {
        "id": updated_item["id"],
        "name": updated_item["name"],
        "description": updated_item.get("description", ""),
        "filePattern": updated_item.get("filePattern", ""),
        "fileCount": updated_item.get("fileCount"),
        "status": updated_item.get("status"),
        "createdAt": updated_item["createdAt"],
        "documentClassType": updated_item.get("documentClassType"),
    }


def delete_test_sets(args):
    logger.info(f"Deleting test sets: {args['testSetIds']}")

    test_set_ids = args["testSetIds"]
    test_set_bucket = os.environ["TEST_SET_BUCKET"]

    for test_set_id in test_set_ids:
        # Delete files from test set bucket.
        #
        # Both APIs used here are page-limited, so both must be looped:
        #   * list_objects_v2 returns at most 1000 keys per call
        #   * delete_objects accepts at most 1000 keys per call
        # A single unpaginated pass silently orphaned every object past the
        # first 1000 — the DynamoDB record disappeared from the UI while the
        # files stayed in the bucket, invisible and still billed. Real test sets
        # exceed this easily: Fake-W2-Tax-Forms is 2000 documents (~4000 objects
        # counting baselines).
        try:
            deleted_count = 0
            continuation_token = None
            while True:
                list_kwargs = {
                    'Bucket': test_set_bucket,
                    'Prefix': f"{test_set_id}/",
                }
                if continuation_token:
                    list_kwargs['ContinuationToken'] = continuation_token
                response = s3_client.list_objects_v2(**list_kwargs)

                objects_to_delete = [
                    {'Key': key}
                    for key in (
                        obj.get('Key') for obj in response.get('Contents', [])
                    )
                    if key
                ]
                # One list page is at most 1000 keys, which is also the
                # delete_objects maximum, so this is a single batch in practice —
                # the slice keeps it correct regardless.
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i:i + 1000]
                    s3_client.delete_objects(
                        Bucket=test_set_bucket,
                        Delete={'Objects': batch}
                    )
                    deleted_count += len(batch)

                if not response.get('IsTruncated'):
                    break
                continuation_token = response.get('NextContinuationToken')
                if not continuation_token:
                    # Defensive: a truncated response without a token would
                    # otherwise loop forever.
                    logger.warning(
                        f"Truncated listing without a continuation token for "
                        f"test set {test_set_id}; stopping after {deleted_count} objects"
                    )
                    break

            if deleted_count:
                logger.info(f"Deleted {deleted_count} files for test set {test_set_id}")

        except Exception as e:
            logger.error(f"Failed to delete files for test set {test_set_id}: {str(e)}")

        # Delete tracking table record
        db_client.delete_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})

    logger.info(f"Deleted {len(test_set_ids)} test sets")
    return True


def get_test_sets():
    logger.info("Retrieving all test sets and scanning for direct uploads")

    # Use GSI to find testset PK/SK keys efficiently, then BatchGetItem for full records.
    # This avoids scanning the entire TrackingTable (which includes all documents).
    tracking_table = boto3.resource("dynamodb").Table(os.environ["TRACKING_TABLE"])
    items = []
    try:
        from boto3.dynamodb.conditions import Key as DDBKey

        # Step 1: GSI query to get testset keys (lightweight - only projected attrs)
        gsi_items = []
        query_kwargs = {
            "IndexName": "TypeDateIndex",
            "KeyConditionExpression": DDBKey("ItemType").eq("testset"),
            "ProjectionExpression": "PK, SK",
        }
        while True:
            response = tracking_table.query(**query_kwargs)
            gsi_items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        logger.info(f"GSI query found {len(gsi_items)} testset keys")

        if gsi_items:
            # Step 2: BatchGetItem to fetch full records from base table
            keys = [{"PK": item["PK"], "SK": item["SK"]} for item in gsi_items]
            # DynamoDB BatchGetItem supports max 100 keys per call
            for i in range(0, len(keys), 100):
                batch_keys = keys[i : i + 100]
                batch_response = boto3.resource("dynamodb").batch_get_item(
                    RequestItems={os.environ["TRACKING_TABLE"]: {"Keys": batch_keys}}
                )
                items.extend(
                    batch_response.get("Responses", {}).get(
                        os.environ["TRACKING_TABLE"], []
                    )
                )
            logger.info(f"BatchGetItem returned {len(items)} full testset records")
    except Exception as e:
        logger.warning(f"GSI+BatchGet failed, falling back to scan: {e}")
        items = []

    # Fallback to scan only if GSI approach failed
    if not items:
        items = db_client.scan_all(
            filter_expression="begins_with(PK, :pk) AND SK = :sk",
            expression_attribute_values={":pk": "testset#", ":sk": "metadata"},
        )

    existing_test_sets = {}
    result = []

    for item in items:
        # GSI projection may not include 'id' - derive from PK if needed
        test_set_id = item.get("id") or item.get("PK", "").replace("testset#", "")
        existing_test_sets[test_set_id] = item
        result.append(
            {
                "id": test_set_id,
                "name": item["name"],
                "description": item.get("description", ""),
                "filePattern": item.get("filePattern", ""),
                "fileCount": item.get(
                    "fileCount"
                ),  # Returns None if attribute doesn't exist
                "source": item.get(
                    "source"
                ),  # 'uploaded' | 'synthetic'; None for pre-existing records
                "latestVersion": item.get(
                    "latestVersion"
                ),  # highest published version (None if never published)
                "activeReference": item.get(
                    "activeReference"
                ),  # version scoring runs compare against
                "labelState": item.get(
                    "labelState"
                ),  # 'unlabeled' | 'draft' | 'labeled'; None for pre-existing records
                "labelJobId": item.get("labelJobId"),
                "labelJobStatus": item.get("labelJobStatus"),
                "status": item.get("status"),
                "createdAt": item["createdAt"],
                "error": item.get(
                    "error"
                ),  # Include error message for failed test sets
                "lastAddResult": item.get("lastAddResult"),
                "documentClassType": item.get("documentClassType"),
                # Optional: a test set may declare which configuration version Test
                # Studio should preselect for it. Absent for the stack-managed
                # benchmark sets, which rely on the id==version-name convention.
                "configVersion": item.get("configVersion"),
            }
        )
    # Scan TestSetBucket for direct uploads
    try:
        test_set_bucket = os.environ["TEST_SET_BUCKET"]
        s3_client = boto3.client("s3")

        # Track which test sets still exist in S3
        s3_test_sets = set()

        # List all top-level prefixes (potential test sets)
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=test_set_bucket, Delimiter="/")

        for page in page_iterator:
            # Check common prefixes (folders)
            for prefix_info in page.get("CommonPrefixes", []):
                prefix = prefix_info["Prefix"].rstrip("/")
                s3_test_sets.add(prefix)

                # Skip if already exists in DynamoDB
                if prefix in existing_test_sets:
                    continue

                # Check if this looks like a test set (has an input/ folder)
                if _is_valid_test_set_structure(s3_client, test_set_bucket, prefix):
                    logger.info(f"Found direct upload test set: {prefix}")

                    # Get creation timestamp from first file in the test set
                    created_at = _get_test_set_creation_time(
                        s3_client, test_set_bucket, prefix
                    )

                    # Validate file matching and get counts. A set with no
                    # baseline at all is valid-but-unlabeled (the
                    # upload-documents-only on-ramp), so it registers and can be
                    # draft-labeled rather than being rejected as FAILED.
                    validation_result = _validate_test_set_files(
                        s3_client, test_set_bucket, prefix, allow_unlabeled=True
                    )

                    # Source: synthetic generator drops a '.source' marker; otherwise a user upload
                    source = _get_test_set_source(s3_client, test_set_bucket, prefix)

                    # Create tracking entry
                    status = "COMPLETED" if validation_result["valid"] else "FAILED"
                    error_message = validation_result.get("error")
                    label_state = (
                        "labeled" if validation_result.get("labeled") else "unlabeled"
                    )

                    _create_test_set_tracking_entry(
                        prefix,
                        prefix,  # Use prefix as name
                        validation_result["input_count"],
                        status,
                        error_message,
                        created_at,
                        source,
                        label_state,
                    )

                    # Add to results
                    result.append(
                        {
                            "id": prefix,
                            "name": prefix,
                            "description": "",  # Direct uploads don't have descriptions
                            "filePattern": "",
                            "fileCount": validation_result["input_count"],
                            "source": source,
                            "labelState": label_state,
                            "status": status,
                            "createdAt": created_at,
                            "documentClassType": None,
                        }
                    )

                    logger.info(
                        f"Registered direct upload test set {prefix} with status {status}"
                    )

        # Check for deleted test sets (exist in DynamoDB but not in S3)
        # Only delete old FAILED test sets or any COMPLETED test sets
        from datetime import datetime, timedelta

        deleted_test_sets = []
        cutoff_time = datetime.utcnow() - timedelta(
            hours=1
        )  # Only delete FAILED if older than 1 hour

        for test_set_id in existing_test_sets:
            test_set_item = existing_test_sets[test_set_id]
            test_set_status = test_set_item.get("status")
            created_at_str = test_set_item.get("createdAt", "")

            # Parse creation time
            try:
                created_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )
            except:
                continue  # Skip if can't parse date

            # Only delete if S3 folder missing AND:
            # - Status is COMPLETED (any time), OR
            # - Status is FAILED and older than cutoff time
            if test_set_id not in s3_test_sets and (
                test_set_status == "COMPLETED"
                or (test_set_status == "FAILED" and created_at < cutoff_time)
            ):
                deleted_test_sets.append(test_set_id)

        # Delete orphaned test sets from DynamoDB
        for test_set_id in deleted_test_sets:
            try:
                db_client.delete_item(
                    {"PK": f"testset#{test_set_id}", "SK": "metadata"}
                )
                logger.info(f"Deleted orphaned test set from DynamoDB: {test_set_id}")

                # Remove from result list
                result = [item for item in result if item["id"] != test_set_id]

            except Exception as e:
                logger.error(
                    f"Failed to delete orphaned test set {test_set_id}: {str(e)}"
                )

    except Exception as e:
        logger.error(f"Error scanning for direct uploads: {str(e)}")

    logger.info(f"Returning {len(result)} test sets")
    return result


def get_test_set_documents(args):
    """List the documents in a test set with their baseline (ground truth) sections.

    Paginated over the set's `input/` prefix; the S3 continuation token is
    passed through opaquely as `nextToken`. For each page of input files, the
    whole `baseline/` prefix is listed once (bulk) and section result.json
    keys are matched to their document in memory — one extra LIST per page
    regardless of page size, and it handles nested input file names.
    """
    test_set_id = args["testSetId"]
    limit = args.get("limit") or 100
    next_token = args.get("nextToken")
    # Optional exact-match filter: return just this document (used by the UI's
    # document detail page when deep-linked, so it doesn't page through the
    # whole set to find one doc).
    object_key = args.get("objectKey")

    # The id is derived from a validated name (validate_test_set_name), so it
    # must match the same charset (with '-' for spaces). Rejects '/' and '..'
    # so it can't traverse outside the test set's S3 prefix.
    if not validate_test_set_name(test_set_id):
        raise Exception("Invalid test set id")
    if object_key and ".." in object_key:
        raise Exception("Invalid object key")
    limit = max(1, min(int(limit), 1000))

    item = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    test_set_bucket = os.environ["TEST_SET_BUCKET"]
    input_prefix = f"{test_set_id}/input/"

    list_kwargs = {
        "Bucket": test_set_bucket,
        # Exact-name prefix narrows the listing to (at most) the one document;
        # the objectKey equality check below drops same-prefix siblings.
        "Prefix": f"{input_prefix}{object_key}" if object_key else input_prefix,
        "MaxKeys": limit,
    }
    if next_token:
        list_kwargs["ContinuationToken"] = next_token
    response = s3_client.list_objects_v2(**list_kwargs)

    documents = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue  # skip folder placeholder objects
        relative_name = key[len(input_prefix) :]
        if object_key and relative_name != object_key:
            continue
        documents.append(
            {
                "objectKey": relative_name,
                "inputKey": key,
                "size": obj.get("Size"),
                "lastModified": obj["LastModified"].isoformat(),
                "sections": [],
            }
        )

    if documents:
        # Bulk-list baseline section files once and match to this page's docs.
        # Baseline layout: <id>/baseline/<relative_name>/sections/<n>/result.json
        baseline_prefix = f"{test_set_id}/baseline/"
        sections_by_doc = {d["objectKey"]: d["sections"] for d in documents}
        section_re = re.compile(r"^(.+)/sections/([^/]+)/result\.json$")
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=test_set_bucket, Prefix=baseline_prefix):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(baseline_prefix) :]
                match = section_re.match(rel)
                if not match:
                    continue
                doc_name, section_id = match.groups()
                sections = sections_by_doc.get(doc_name)
                if sections is not None:
                    sections.append(
                        {
                            "sectionId": section_id,
                            "baselineKey": obj["Key"],
                        }
                    )

        # Sort sections numerically where possible so "10" doesn't precede "2"
        for doc in documents:
            doc["sections"].sort(
                key=lambda s: (
                    (0, int(s["sectionId"]))
                    if s["sectionId"].isdigit()
                    else (1, s["sectionId"])
                )
            )

        _attach_label_metadata(test_set_bucket, documents)

    result = {
        "documents": documents,
        "nextToken": response.get("NextContinuationToken"),
    }

    # Surface any in-flight labeling job so a page load can resume polling it.
    # Labels are harvested on read, so a job only advances while something polls;
    # a browser refresh mid-run previously dropped the poll and left the job
    # RUNNING forever, which the Test Sets list then reported as "Labeling"
    # indefinitely even though every document had finished.
    meta = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})
    if meta and meta.get("labelJobStatus") == "RUNNING" and meta.get("labelJobId"):
        result["activeLabelJobId"] = meta["labelJobId"]

    logger.info(
        f"getTestSetDocuments({test_set_id}): {len(documents)} documents"
        f"{' (more available)' if result['nextToken'] else ''}"
    )
    return result


def _attach_label_metadata(test_set_bucket, documents):
    """Add labelSource + minConfidence to each document on a page.

    The label state lives inside each section's baseline result.json, so this
    reads them — bounded to one page of documents (<=1000 sections) and fetched
    concurrently, since the calls are pure I/O and would otherwise serialize
    into a slow page load. A document's confidence is the *minimum* across its
    sections' fields: worst-first review should surface a document because of
    its weakest field, not an average that hides it.

    Best-effort per section: an unreadable result.json leaves that section out
    rather than failing the whole listing.
    """
    tasks = []
    for doc in documents:
        for section in doc["sections"]:
            tasks.append((doc, section["baselineKey"]))
    if not tasks:
        for doc in documents:
            doc["labelSource"] = None
            doc["minConfidence"] = None
            doc["confidenceThreshold"] = None
        return

    def read(key):
        try:
            body = s3_client.get_object(Bucket=test_set_bucket, Key=key)["Body"].read()
            return json.loads(body)
        except Exception as e:  # noqa: BLE001 — best-effort enrichment
            logger.warning(f"Could not read baseline label {key}: {e}")
            return None

    per_doc = {id(doc): {"sources": [], "confidences": []} for doc, _ in tasks}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(tasks), 16)
    ) as executor:
        results = executor.map(lambda t: (t[0], read(t[1])), tasks)
        for doc, result in results:
            if not result:
                continue
            bucket_for_doc = per_doc[id(doc)]
            # A baseline with no labelSource was supplied as ground truth when the
            # set was created (zip upload, pattern-based, or synthetic) — it is
            # authoritative, but nobody reviewed it *here*. Reporting it as
            # LABEL_SOURCE_UPLOADED rather than reviewed-human keeps that
            # distinction: overwrite safety still protects it (see
            # _existing_label_is_human, which only replaces explicit drafts),
            # while the annotation queue does not count it as completed review
            # work and claim 100% progress on a set nobody has annotated.
            bucket_for_doc["sources"].append(
                result.get("labelSource") or LABEL_SOURCE_UPLOADED
            )
            inference = result.get("inference_result")
            # Recompute rather than trusting a stored minConfidence: labels
            # written before absent fields were excluded carry a 0.0 that came
            # from a blank box, and reading it back would keep reporting "0.0%"
            # for documents whose populated fields all score >0.99. Recomputing
            # repairs those in place; the stored value is only a fallback for
            # payloads with no explainability_info to recompute from.
            confidence = _min_confidence(result.get("explainability_info"), inference)
            if confidence is None:
                confidence = result.get("minConfidence")
            if confidence is not None:
                threshold = _confidence_threshold(
                    result.get("explainability_info"), inference
                )
                if threshold is None:
                    threshold = result.get("confidenceThreshold")
                bucket_for_doc["confidences"].append((float(confidence), threshold))

    for doc in documents:
        collected = per_doc.get(id(doc), {"sources": [], "confidences": []})
        sources = collected["sources"]
        confidences = collected["confidences"]
        # A document counts as reviewed only when every section is.
        if not sources:
            doc["labelSource"] = None
        elif all(s == LABEL_SOURCE_HUMAN for s in sources):
            doc["labelSource"] = LABEL_SOURCE_HUMAN
        elif any(s == LABEL_SOURCE_DRAFT for s in sources):
            doc["labelSource"] = LABEL_SOURCE_DRAFT
        else:
            doc["labelSource"] = sources[0]
        if confidences:
            worst, threshold = min(confidences, key=lambda pair: pair[0])
            doc["minConfidence"] = worst
            doc["confidenceThreshold"] = threshold
        else:
            doc["minConfidence"] = None
            doc["confidenceThreshold"] = None


def _is_valid_test_set_structure(s3_client, bucket, prefix):
    """Check if prefix contains an input/ folder (baseline/ optional).

    Also checks for a .uploading marker file which indicates the CLI is still
    uploading files. This prevents a race condition where the resolver auto-detects
    and validates a test set before all files (especially baselines) are uploaded.
    See: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/193

    baseline/ is NOT required: a set uploaded as documents-only is a legitimate
    unlabeled set awaiting generateDraftLabels. Requiring it here made such sets
    invisible to discovery entirely. The .uploading marker (written by the CLI
    and the UI upload path) is what protects against reading a half-done upload,
    so dropping the baseline requirement doesn't reintroduce that race. A
    partially-labeled set is still reported as FAILED by
    _validate_test_set_files.
    """
    try:
        # Check for upload-in-progress marker
        try:
            s3_client.head_object(Bucket=bucket, Key=f"{prefix}/.uploading")
            logger.info(
                f"Skipping {prefix} - upload in progress (.uploading marker found)"
            )
            return False
        except Exception:
            pass  # No marker = not uploading, proceed with validation

        # Check for input/ folder
        input_response = s3_client.list_objects_v2(
            Bucket=bucket, Prefix=f"{prefix}/input/", MaxKeys=1
        )

        return input_response.get("KeyCount", 0) > 0

    except Exception as e:
        logger.error(f"Error checking test set structure for {prefix}: {str(e)}")
        return False


def _validate_test_set_files(s3_client, bucket, prefix, allow_unlabeled=False):
    """Validate that input and baseline files match.

    Each input file must have a corresponding baseline folder with the exact same name
    (including extension). For example, input file 'doc.png' requires baseline folder 'doc.png/'.
    Any file extension is supported, and mixed extensions within a test set are allowed.

    ``allow_unlabeled=True`` permits a set with **no** baseline files at all —
    the "upload documents only, then draft-label them" on-ramp. Such a set is
    valid but unlabeled: generateDraftLabels runs the active config over it to
    produce machine labels, which a human then reviews. A *partially* labeled
    set is still an error either way, since that indicates a botched upload
    rather than a deliberate label-later flow.
    """
    try:
        input_files = set()
        baseline_files = set()

        # Get input files
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/input/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith("/"):  # Skip directories
                    filename = key.split("/")[-1]
                    input_files.add(filename)

        # Get baseline folder names (first folder after /baseline/)
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/baseline/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith("/"):  # Skip directories
                    # Extract folder name after /baseline/
                    parts = key.split(f"{prefix}/baseline/", 1)
                    if len(parts) == 2 and "/" in parts[1]:
                        # First path component is the baseline folder name
                        folder_name = parts[1].split("/")[0]
                        if folder_name:
                            baseline_files.add(folder_name)

        # Validate matching
        if len(input_files) == 0:
            return {"valid": False, "error": "No input files found", "input_count": 0}

        if len(baseline_files) == 0:
            if allow_unlabeled:
                return {
                    "valid": True,
                    "input_count": len(input_files),
                    "labeled": False,
                }
            return {
                "valid": False,
                "error": "No baseline files found",
                "input_count": len(input_files),
            }

        missing_baselines = input_files - baseline_files
        if missing_baselines:
            return {
                "valid": False,
                "error": f"Missing baseline files for: {', '.join(list(missing_baselines)[:3])}{'...' if len(missing_baselines) > 3 else ''}",
                "input_count": len(input_files),
            }

        extra_baselines = baseline_files - input_files
        if extra_baselines:
            return {
                "valid": False,
                "error": f"Extra baseline files: {', '.join(list(extra_baselines)[:3])}{'...' if len(extra_baselines) > 3 else ''}",
                "input_count": len(input_files),
            }

        return {"valid": True, "input_count": len(input_files), "labeled": True}

    except Exception as e:
        logger.error(f"Error validating test set files for {prefix}: {str(e)}")
        return {
            "valid": False,
            "error": f"Validation error: {str(e)}",
            "input_count": 0,
        }


def _get_test_set_creation_time(s3_client, bucket, prefix):
    """Get the earliest creation time from files in the test set"""
    earliest_time = None

    # Check input folder for earliest file
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=bucket, Prefix=f"{prefix}/input/", MaxKeys=10
    ):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith("/"):  # Skip directories
                if earliest_time is None or obj["LastModified"] < earliest_time:
                    earliest_time = obj["LastModified"]

    if earliest_time is None:
        raise Exception(f"No files found in {prefix}/input/ to determine creation time")

    return earliest_time.isoformat()


def _get_test_set_source(s3_client, bucket, prefix):
    """Return 'synthetic' if the generator left a '.source' marker, else 'uploaded'."""
    try:
        s3_client.head_object(Bucket=bucket, Key=f"{prefix}/.source")
        return "synthetic"
    except Exception:
        return "uploaded"


def _create_test_set_tracking_entry(
    test_set_id,
    name,
    file_count,
    status,
    error=None,
    created_at=None,
    source=None,
    label_state=None,
):
    """Create tracking table entry for direct upload test set"""
    try:
        now = datetime.utcnow().isoformat() + "Z"
        item = {
            "PK": f"testset#{test_set_id}",
            "SK": "metadata",
            "ItemType": "testset",
            "InitialEventTime": now,
            "id": test_set_id,
            "name": name,
            "description": "",  # Direct uploads don't have descriptions
            "filePattern": "",
            "fileCount": file_count,
            "status": status,
            "createdAt": now,
        }

        if source:
            item["source"] = source
        if label_state:
            item["labelState"] = label_state
        if error:
            item["error"] = error

        db_client.put_item(item)
        logger.info(f"Created tracking entry for direct upload test set {test_set_id}")

    except Exception as e:
        logger.error(f"Error creating tracking entry for {test_set_id}: {str(e)}")


def list_bucket_files(args):
    logger.info(
        f"Listing files with pattern: {args['filePattern']} from bucket type: {args['bucketType']}"
    )

    file_pattern = args["filePattern"]
    bucket_type = args["bucketType"]
    modified_after = args.get("modifiedAfter")

    # Determine which bucket to use based on bucket type
    if bucket_type == "input":
        bucket = os.environ["INPUT_BUCKET"]
    elif bucket_type == "testset":
        bucket = os.environ["TEST_SET_BUCKET"]
    else:
        raise Exception(f"Invalid bucket type: {bucket_type}")

    files = find_matching_files(bucket, file_pattern, modified_after=modified_after)
    logger.info(f"Found {len(files)} matching files in {bucket_type} bucket")

    return files


def validate_test_file_name(args):
    logger.info(f"Validating test file name: {args['fileName']}")

    test_set_name = args["fileName"]
    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"

    # Check if test set already exists in tracking table
    try:
        item = db_client.get_item({"PK": f"testset#{test_set_id}", "SK": "metadata"})

        if item:
            logger.info(f"Test set {test_set_id} already exists")
            return {"exists": True, "testSetId": test_set_id}
        else:
            logger.info(f"Test set {test_set_id} does not exist")
            return {"exists": False, "testSetId": None}
    except Exception as e:
        logger.error(f"Error checking test set existence: {str(e)}")
        return {"exists": False, "testSetId": None}
