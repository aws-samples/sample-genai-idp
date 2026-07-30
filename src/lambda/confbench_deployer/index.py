"""
Lambda function to deploy the ConfBench dataset from HuggingFace
to the TestSetBucket during stack deployment.

Source: amazon/ConfBench (https://huggingface.co/datasets/amazon/ConfBench)

Each row in the dataset is a (document x noise_variant) pair. All noise
variants are deployed — original, default, archetype*, and custom* — so the
Test Studio can evaluate model robustness across degradation levels.

Dataset schema (parquet columns):
  id            - "{doc_hash}__{noise_variant}.pdf" — unique row key and PDF filename
  noise_variant - "original", "default", "archetype3", "custom12", etc.
  page_count    - number of pages in the document (int)
  json_response - ground truth as a dict (same Invoice schema as RealKIE-FCC-Verified)

PDFs are stored at pdfs/{id} in the HuggingFace repo.

Chunked self-invocation pattern
--------------------------------
1,346 files × up to 35 MB each exceeds the 900s Lambda timeout in a single run.
This deployer processes files in CHUNK_SIZE batches. After each chunk it invokes
itself asynchronously with the next offset, then returns WITHOUT sending a CFN
response. Only the final chunk (offset + processed >= total) sends the CFN
SUCCESS response. The initial CFN invocation carries the full event; subsequent
invocations carry a minimal continuation payload.
"""

import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Dict, List

import boto3
import cfnresponse
from botocore.config import Config

# Set HuggingFace cache to /tmp (Lambda's writable directory)
os.environ["HF_HOME"] = "/tmp/huggingface"  # nosec B108 - isolated Lambda environment
os.environ["HUGGINGFACE_HUB_CACHE"] = "/tmp/huggingface/hub"  # nosec B108

# Lightweight HuggingFace access
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, hf_hub_url

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# AWS clients.
# When S3_ENDPOINT_URL is set (private VPC mode), force virtual-host
# addressing so the SigV4 host header matches the VPC interface endpoint
# bucket-vhost DNS. boto3's auto default usually picks virtual for
# DNS-compliant bucket names but is brittle (e.g. dotted bucket names fall
# back to path), so we set it explicitly to match the presigner Lambdas.
_s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL") or None
_s3_addressing = "virtual" if _s3_endpoint_url else "path"
s3_client = boto3.client(
    "s3",
    endpoint_url=_s3_endpoint_url,
    config=Config(signature_version="s3v4", s3={"addressing_style": _s3_addressing}),
)
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

# Environment variables
TESTSET_BUCKET = os.environ.get("TESTSET_BUCKET")
TRACKING_TABLE = os.environ.get("TRACKING_TABLE")
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")

# Constants
# HF_REPO_ID points at the official published dataset on HuggingFace.
HF_REPO_ID = "amazon/ConfBench"
DATASET_NAME = "ConfBench"
DATASET_PREFIX = "confbench/"
TEST_SET_ID = "confbench"

# Number of PDFs to process per Lambda invocation. Sized conservatively to
# complete well within 900s even for large PDFs (avg ~5 MB, some up to 35 MB).
CHUNK_SIZE = 100

# Retry settings for transient HuggingFace CDN errors (5xx, connection reset)
MAX_PDF_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # seconds; delay = RETRY_BACKOFF_BASE * 2^attempt


def _is_retryable_http_error(exc: Exception) -> bool:
    """Return True for transient HTTP errors worth retrying (5xx, connection issues)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, (urllib.error.URLError, ConnectionResetError, OSError)):
        return True
    return False


def handler(event, context):
    """
    Main Lambda handler for deploying the ConfBench dataset.

    Handles two event shapes:
    - CFN custom resource event (RequestType = Create/Update/Delete)
    - Continuation event (RequestType = "Continue") — internal async invocation
    """
    logger.info(f"Event type: {event.get('RequestType')}, offset: {event.get('Offset', 0)}")

    try:
        request_type = event["RequestType"]

        if request_type == "Delete":
            # On stack deletion, leave the data in place
            logger.info("Delete request - keeping dataset in place")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return

        if request_type == "Continue":
            # Internal continuation: process next chunk, no CFN response unless done
            _handle_continuation(event, context)
            return

        # CFN Create/Update — check idempotency then kick off chunk 0
        properties = event["ResourceProperties"]
        dataset_version = properties.get("DatasetVersion", "1.0")
        dataset_description = properties.get("DatasetDescription", "")

        logger.info(f"Processing dataset version: {dataset_version}")

        if check_existing_version(dataset_version):
            logger.info(
                f"Dataset version {dataset_version} already deployed, updating description only"
            )
            update_description_only(dataset_description)
            cfnresponse.send(
                event,
                context,
                cfnresponse.SUCCESS,
                {"Message": f"Dataset version {dataset_version} already exists, description updated"},
            )
            return

        # Load parquet to get total row count, then kick off chunk 0
        cache_dir = "/tmp/huggingface/hub"  # nosec B108
        os.makedirs(cache_dir, exist_ok=True)

        logger.info(f"Downloading parquet metadata from HuggingFace: {HF_REPO_ID}")
        parquet_path = hf_hub_download(  # nosec B615 - trusted HuggingFace dataset
            repo_id=HF_REPO_ID,
            filename="data/test-00000-of-00001.parquet",
            repo_type="dataset",
            cache_dir=cache_dir,
        )
        logger.info("Downloaded parquet metadata file")

        table = pq.read_table(parquet_path)
        data_dict = table.to_pydict()
        num_rows = len(data_dict["id"])

        logger.info(f"Loaded {num_rows} rows from parquet")
        logger.info(f"Parquet schema: {table.schema}")
        logger.info(f"Available columns: {list(data_dict.keys())}")

        # Sample first document to see structure (if exists)
        if num_rows > 0:
            sample_keys = list(data_dict.keys())
            logger.info(f"Sample document column names: {sample_keys}")
            # Log a few sample values (avoiding large data)
            for key in sample_keys[:5]:
                value = data_dict[key][0]
                if isinstance(value, (list, dict)):
                    logger.info(
                        f"  {key}: {type(value).__name__} with {len(value) if hasattr(value, '__len__') else 'N/A'} items"
                    )
                else:
                    logger.info(f"  {key}: {type(value).__name__}")

        # Store row data in S3 as a compact continuation payload so subsequent
        # chunks don't re-download the parquet. Only IDs and json_response are
        # needed; page_count and noise_variant are lightweight columns.
        _store_row_data(data_dict, dataset_version)

        # Process chunk 0 and chain the rest
        _process_chunk(
            cfn_event=event,
            context=context,
            data_dict=data_dict,
            offset=0,
            num_rows=num_rows,
            dataset_version=dataset_version,
            dataset_description=dataset_description,
            file_count_so_far=0,
            skipped_count_so_far=0,
            total_pages_so_far=0,
            failed_ids_so_far=[],
        )

    except Exception as e:
        logger.error(f"Error in handler: {str(e)}", exc_info=True)
        try:
            properties = event.get("ResourceProperties", {})
            create_failed_testset_record(
                version=properties.get("DatasetVersion", "1.0"),
                error_message=str(e),
            )
        except Exception as record_err:
            logger.error(f"Failed to create error test set record: {record_err}")
        # Only send CFN response for CFN-originated events
        if event.get("RequestType") not in ("Continue",):
            cfnresponse.send(
                event,
                context,
                cfnresponse.SUCCESS,
                {
                    "Status": "DEPLOYMENT_FAILED",
                    "Message": f"Test set deployment failed (non-blocking): {str(e)[:200]}",
                },
            )


def _store_row_data(data_dict: dict, version: str):
    """
    Persist the lightweight parquet columns to S3 so continuation chunks
    can read them without re-downloading the parquet file.
    """
    rows = []
    for i in range(len(data_dict["id"])):
        rows.append({
            "id": data_dict["id"][i],
            "noise_variant": data_dict["noise_variant"][i],
            "page_count": data_dict["page_count"][i],
            "json_response": data_dict["json_response"][i],
        })
    key = f"{DATASET_PREFIX}_deploy_state/{version}/rows.json"
    s3_client.put_object(
        Bucket=TESTSET_BUCKET,
        Key=key,
        Body=json.dumps(rows),
        ContentType="application/json",
    )
    logger.info(f"Stored {len(rows)} row descriptors to s3://{TESTSET_BUCKET}/{key}")


def _load_row_data(version: str) -> list:
    """Load row descriptors from S3 for continuation chunks."""
    key = f"{DATASET_PREFIX}_deploy_state/{version}/rows.json"
    response = s3_client.get_object(Bucket=TESTSET_BUCKET, Key=key)
    return json.loads(response["Body"].read())


def _handle_continuation(event, context):
    """Handle a continuation (async self-invocation) event."""
    offset = event["Offset"]
    num_rows = event["NumRows"]
    dataset_version = event["DatasetVersion"]
    dataset_description = event["DatasetDescription"]
    file_count_so_far = event["FileCountSoFar"]
    skipped_count_so_far = event["SkippedCountSoFar"]
    total_pages_so_far = event["TotalPagesSoFar"]
    failed_ids_so_far = event.get("FailedIdsSoFar", [])
    cfn_event = event["CfnEvent"]

    # Reload row data from S3
    rows = _load_row_data(dataset_version)

    # Rebuild data_dict slice for this chunk
    data_dict = {
        "id": [r["id"] for r in rows],
        "noise_variant": [r["noise_variant"] for r in rows],
        "page_count": [r["page_count"] for r in rows],
        "json_response": [r["json_response"] for r in rows],
    }

    _process_chunk(
        cfn_event=cfn_event,
        context=context,
        data_dict=data_dict,
        offset=offset,
        num_rows=num_rows,
        dataset_version=dataset_version,
        dataset_description=dataset_description,
        file_count_so_far=file_count_so_far,
        skipped_count_so_far=skipped_count_so_far,
        total_pages_so_far=total_pages_so_far,
        failed_ids_so_far=failed_ids_so_far,
    )


def _process_chunk(
    cfn_event,
    context,
    data_dict: dict,
    offset: int,
    num_rows: int,
    dataset_version: str,
    dataset_description: str,
    file_count_so_far: int,
    skipped_count_so_far: int,
    total_pages_so_far: int,
    failed_ids_so_far: List[dict],
):
    """
    Process CHUNK_SIZE rows starting at offset. If more rows remain,
    invoke self asynchronously with the next offset. If this is the
    last chunk, finalize and send CFN SUCCESS.
    """
    cache_dir = "/tmp/huggingface/hub"  # nosec B108

    # Wipe the HF cache at the start of each chunk to ensure we begin
    # with a clean /tmp regardless of what the previous chunk left behind.
    try:
        shutil.rmtree(cache_dir, ignore_errors=True)
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as cleanup_err:
        logger.warning(f"Could not clean cache dir at chunk start: {cleanup_err}")

    end = min(offset + CHUNK_SIZE, num_rows)
    logger.info(f"Processing rows {offset}–{end - 1} of {num_rows}")

    file_count = 0
    skipped_count = 0
    total_pages = 0
    noise_variant_counts: Dict[str, int] = {}
    failed_ids: List[dict] = []

    def _iter_parts(response, part_size):
        """Yield fixed-size byte chunks from an HTTP response."""
        buf = bytearray()
        while True:
            chunk = response.read(1024 * 1024)  # 1 MB reads
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) >= part_size:
                yield bytes(buf[:part_size])
                buf = buf[part_size:]
        if buf:
            yield bytes(buf)  # final partial part

    for idx in range(offset, end):
        try:
            document_id = data_dict["id"][idx]
            noise_variant = data_dict["noise_variant"][idx]
            json_response = data_dict["json_response"][idx]

            if not json_response:
                logger.warning(f"Skipping {document_id}: no json_response")
                skipped_count += 1
                continue

            page_count = get_page_count(data_dict, idx)
            if page_count == 0:
                logger.warning(f"Skipping {document_id}: no pages found (page_count=0)")
                skipped_count += 1
                continue

            total_pages += page_count
            noise_variant_counts[noise_variant] = noise_variant_counts.get(noise_variant, 0) + 1

            logger.info(f"Processing {document_id} ({page_count} pages, variant={noise_variant})")

            # Stream PDF directly from HuggingFace to S3 — no /tmp storage needed.
            # hf_hub_url() returns the CDN URL; we stream the response body through
            # a multipart upload in fixed-size parts so peak memory stays bounded
            # regardless of file size (~64 MB per part).
            # Retries up to MAX_PDF_RETRIES times on transient 5xx/connection errors.
            pdf_url = hf_hub_url(
                repo_id=HF_REPO_ID,
                filename=f"pdfs/{document_id}",
                repo_type="dataset",
            )
            pdf_key = f"{DATASET_PREFIX}input/{document_id}"
            PART_SIZE = 64 * 1024 * 1024  # 64 MB (S3 minimum is 5 MB)

            last_pdf_error = None
            for attempt in range(MAX_PDF_RETRIES):
                mpu = s3_client.create_multipart_upload(
                    Bucket=TESTSET_BUCKET,
                    Key=pdf_key,
                    ContentType="application/pdf",
                )
                upload_id = mpu["UploadId"]
                parts = []
                total_bytes = 0
                try:
                    with urllib.request.urlopen(pdf_url) as response:  # nosec B310 - trusted HF CDN URL
                        for part_num, part_data in enumerate(_iter_parts(response, PART_SIZE), start=1):
                            part = s3_client.upload_part(
                                Bucket=TESTSET_BUCKET,
                                Key=pdf_key,
                                UploadId=upload_id,
                                PartNumber=part_num,
                                Body=part_data,
                            )
                            parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
                            total_bytes += len(part_data)

                    s3_client.complete_multipart_upload(
                        Bucket=TESTSET_BUCKET,
                        Key=pdf_key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )
                    logger.info(f"Downloaded PDF for {document_id} ({total_bytes:,} bytes)")
                    last_pdf_error = None
                    break  # success

                except Exception as pdf_err:
                    s3_client.abort_multipart_upload(
                        Bucket=TESTSET_BUCKET, Key=pdf_key, UploadId=upload_id
                    )
                    last_pdf_error = pdf_err
                    if _is_retryable_http_error(pdf_err) and attempt < MAX_PDF_RETRIES - 1:
                        delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                        logger.warning(
                            f"Transient error for {document_id} (attempt {attempt + 1}/{MAX_PDF_RETRIES}): "
                            f"{pdf_err} — retrying in {delay}s"
                        )
                        time.sleep(delay)
                    else:
                        break  # non-retryable or exhausted retries

            if last_pdf_error is not None:
                raise last_pdf_error

            # Upload ground truth baseline
            page_indices = list(range(page_count))
            result_json = {
                "document_class": {"type": "Invoice"},
                "split_document": {"page_indices": page_indices},
                "inference_result": json_response,
            }
            result_key = f"{DATASET_PREFIX}baseline/{document_id}/sections/1/result.json"
            s3_client.put_object(
                Bucket=TESTSET_BUCKET,
                Key=result_key,
                Body=json.dumps(result_json, indent=2),
                ContentType="application/json",
            )

            file_count += 1

            if file_count % 10 == 0:
                logger.info(f"Chunk progress: {file_count} files in this chunk")

        except Exception as e:
            logger.error(f"Error processing row {idx} ({document_id}): {e}")
            failed_ids.append({"id": document_id, "error": str(e)})
            skipped_count += 1
            continue

    # Accumulate totals
    total_file_count = file_count_so_far + file_count
    total_skipped_count = skipped_count_so_far + skipped_count
    total_pages_count = total_pages_so_far + total_pages
    all_failed_ids = failed_ids_so_far + failed_ids

    logger.info(
        f"Chunk {offset}–{end - 1} done: {file_count} uploaded, {skipped_count} skipped. "
        f"Running total: {total_file_count}/{num_rows}"
    )

    if end < num_rows:
        # More rows remain — invoke self asynchronously with next offset
        continuation_event = {
            "RequestType": "Continue",
            "Offset": end,
            "NumRows": num_rows,
            "DatasetVersion": dataset_version,
            "DatasetDescription": dataset_description,
            "FileCountSoFar": total_file_count,
            "SkippedCountSoFar": total_skipped_count,
            "TotalPagesSoFar": total_pages_count,
            "FailedIdsSoFar": all_failed_ids,
            "CfnEvent": cfn_event,
        }
        logger.info(f"Invoking continuation at offset {end}")
        lambda_client.invoke(
            FunctionName=FUNCTION_NAME,
            InvocationType="Event",  # async
            Payload=json.dumps(continuation_event).encode(),
        )
        # Do NOT send CFN response — CFN waits for the final chunk
        return

    # This is the final chunk — finalize and respond to CFN
    logger.info(
        f"All chunks complete. Total: {total_file_count} deployed, "
        f"{total_skipped_count} skipped, {total_pages_count} pages"
    )

    # Write failed files report to S3 (always, even if empty — acts as a receipt)
    failed_report_key = f"{DATASET_PREFIX}_deploy_state/{dataset_version}/failed_files.json"
    failed_report = {
        "dataset_version": dataset_version,
        "total_rows": num_rows,
        "deployed": total_file_count,
        "skipped": total_skipped_count,
        "failed_files": all_failed_ids,
    }
    s3_client.put_object(
        Bucket=TESTSET_BUCKET,
        Key=failed_report_key,
        Body=json.dumps(failed_report, indent=2),
        ContentType="application/json",
    )
    if all_failed_ids:
        logger.warning(
            f"Deployment completed with {len(all_failed_ids)} failed file(s). "
            f"Report written to s3://{TESTSET_BUCKET}/{failed_report_key}"
        )
        for f in all_failed_ids:
            logger.warning(f"  FAILED: {f['id']} — {f['error']}")
    else:
        logger.info(f"All files deployed successfully. Report: s3://{TESTSET_BUCKET}/{failed_report_key}")

    create_testset_record(dataset_version, dataset_description, total_file_count)

    # Clean up deploy state from S3
    try:
        s3_client.delete_object(
            Bucket=TESTSET_BUCKET,
            Key=f"{DATASET_PREFIX}_deploy_state/{dataset_version}/rows.json",
        )
    except Exception:
        pass  # non-critical

    result = {
        "DatasetVersion": dataset_version,
        "FileCount": total_file_count,
        "SkippedCount": total_skipped_count,
        "FailedCount": len(all_failed_ids),
        "TotalPages": total_pages_count,
        "Message": f"Deployed {total_file_count} ConfBench documents"
        + (f" ({len(all_failed_ids)} failed — see s3://{TESTSET_BUCKET}/{failed_report_key})" if all_failed_ids else ""),
    }
    logger.info(f"Dataset deployment completed: {result}")
    cfnresponse.send(cfn_event, context, cfnresponse.SUCCESS, result)


def update_description_only(description: str):
    """
    Update only the description field in the existing DynamoDB record.
    """
    try:
        table = dynamodb.Table(TRACKING_TABLE)  # type: ignore[attr-defined]
        table.update_item(
            Key={"PK": f"testset#{TEST_SET_ID}", "SK": "metadata"},
            UpdateExpression="SET description = :desc",
            ExpressionAttributeValues={":desc": description},
        )
        logger.info(f"Updated description for test set {TEST_SET_ID}")
    except Exception as e:
        logger.error(f"Failed to update description: {e}")
        raise


def check_existing_version(version: str) -> bool:
    """
    Return True if the dataset with the specified version is already successfully
    deployed (DynamoDB record exists with matching version, non-FAILED status,
    and at least one S3 file present).
    """
    try:
        table = dynamodb.Table(TRACKING_TABLE)  # type: ignore[attr-defined]
        response = table.get_item(
            Key={"PK": f"testset#{TEST_SET_ID}", "SK": "metadata"}
        )

        if "Item" in response:
            existing_version = response["Item"].get("datasetVersion", "")
            logger.info(f"Found existing dataset version: {existing_version}")

            if existing_version == version:
                existing_status = response["Item"].get("status", "")
                if existing_status == "FAILED":
                    logger.info("Previous deployment failed, retrying deployment")
                    return False
                try:
                    s3_response = s3_client.list_objects_v2(
                        Bucket=TESTSET_BUCKET,
                        Prefix=f"{DATASET_PREFIX}input/",
                        MaxKeys=1,
                    )
                    if s3_response.get("KeyCount", 0) > 0:
                        logger.info("Files exist in S3, skipping deployment")
                        return True
                except Exception as e:
                    logger.warning(f"Error checking S3 files: {e}")

        return False

    except Exception as e:
        logger.warning(f"Error checking existing version: {e}")
        return False


def get_page_count(data_dict: dict, idx: int) -> int:
    """
    Get the number of pages for a document from the page_count column.

    The ConfBench dataset contains a 'page_count' integer column set when
    the dataset was built, so no PDF parsing is needed.

    Args:
        data_dict: Parquet data dictionary
        idx: Document index

    Returns:
        Number of pages
    """
    page_count = data_dict["page_count"][idx]
    if page_count and int(page_count) > 0:
        return int(page_count)

    logger.warning(f"Could not determine page count for document index {idx}")
    return 0


def create_failed_testset_record(version: str, error_message: str):
    """
    Create a FAILED test set record in DynamoDB so the error is visible in Test Studio UI.
    On the next stack update, check_existing_version will detect the FAILED status and retry.
    """
    table = dynamodb.Table(TRACKING_TABLE)  # type: ignore[attr-defined]
    timestamp = datetime.utcnow().isoformat() + "Z"

    item = {
        "PK": f"testset#{TEST_SET_ID}",
        "SK": "metadata",
        "ItemType": "testset",
        "InitialEventTime": timestamp,
        "id": TEST_SET_ID,
        "name": DATASET_NAME,
        "filePattern": "",
        "fileCount": 0,
        "status": "FAILED",
        "createdAt": timestamp,
        "datasetVersion": version,
        "source": f"huggingface:{HF_REPO_ID}",
        "description": (
            f"⚠️ Deployment failed: {error_message[:500]}. "
            f"This test set could not be downloaded from its source. "
            f"It will be retried on the next stack update."
        ),
    }

    table.put_item(Item=item)
    logger.info(f"Created FAILED test set record in DynamoDB: {TEST_SET_ID}")


def create_testset_record(version: str, description: str, file_count: int):
    """
    Create or update the test set record in DynamoDB.
    """
    table = dynamodb.Table(TRACKING_TABLE)  # type: ignore[attr-defined]
    timestamp = datetime.utcnow().isoformat() + "Z"

    item = {
        "PK": f"testset#{TEST_SET_ID}",
        "SK": "metadata",
        "ItemType": "testset",
        "InitialEventTime": timestamp,
        "id": TEST_SET_ID,
        "name": DATASET_NAME,
        "description": description or (
            "An augmentation of FCC Invoices Verified, each document degraded by up to 18 "
            "distinct pipelines to support confidence calibration research, OCR robustness "
            "evaluation, and key information extraction (KIE) under realistic noise conditions."
        ),
        "filePattern": "",
        "fileCount": file_count,
        "status": "COMPLETED",
        "createdAt": timestamp,
        "datasetVersion": version,
        "source": f"huggingface:{HF_REPO_ID}",
    }

    table.put_item(Item=item)
    logger.info(f"Created test set record in DynamoDB: {TEST_SET_ID}")
