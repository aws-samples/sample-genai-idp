# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda resolver for listDocumentsByDateRange GraphQL query.

Performs server-side iteration through date/shard partitions and
batch-fetches document details, returning paginated results.

This avoids the client-side fan-out pattern used for short time periods,
making it suitable for custom date ranges of any length.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")

# Must match DOCUMENT_LIST_SHARDS_PER_DAY in the frontend
SHARDS_PER_DAY = 6
HOURS_PER_SHARD = 24 // SHARDS_PER_DAY  # 4 hours

# Limits
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
BATCH_GET_LIMIT = 100  # DynamoDB BatchGetItem limit


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal objects from DynamoDB."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_range(start_date: str, end_date: str):
    """Yield each date string (YYYY-MM-DD) from start_date to end_date inclusive."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start
    while current <= end:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


def _shard_pks_for_range(start_dt: datetime, end_dt: datetime):
    """
    Return an ordered list of (date_str, shard_index) tuples covering the
    time window [start_dt, end_dt].

    Each shard covers a 4-hour window.  We generate PKs from the earliest
    shard that contains start_dt through the latest shard that contains end_dt.
    """
    pairs = []
    current = start_dt.replace(minute=0, second=0, microsecond=0)
    # Align to shard boundary
    current = current.replace(hour=(current.hour // HOURS_PER_SHARD) * HOURS_PER_SHARD)

    while current <= end_dt:
        date_str = current.strftime("%Y-%m-%d")
        shard = current.hour // HOURS_PER_SHARD
        pairs.append((date_str, shard))
        current += timedelta(hours=HOURS_PER_SHARD)

    return pairs


def _query_shard(table, date_str: str, shard: int, start_iso: str, end_iso: str):
    """
    Query a single shard partition and return list entries whose SK timestamp
    falls within [start_iso, end_iso].
    """
    shard_pad = f"{shard:02d}"
    pk = f"list#{date_str}#s#{shard_pad}"

    # SK format: ts#{ISO_TIMESTAMP}#id#{OBJECT_KEY}
    # We can use begins_with on the date portion for a coarse filter,
    # then apply a fine-grained filter for exact timestamp boundaries.
    items = []
    query_kwargs = {
        "KeyConditionExpression": Key("PK").eq(pk),
        "Select": "ALL_ATTRIBUTES",
    }

    while True:
        response = table.query(**query_kwargs)
        for item in response.get("Items", []):
            # Extract timestamp from SK: ts#2026-02-07T14:22:00.000Z#id#doc.pdf
            sk = item.get("SK", "")
            if sk.startswith("ts#"):
                parts = sk.split("#id#", 1)
                ts_part = parts[0][3:]  # strip "ts#"
                # Only include items within the requested range
                if start_iso <= ts_part <= end_iso:
                    items.append(item)
        if "LastEvaluatedKey" not in response:
            break
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return items


def _batch_get_documents(table_name, object_keys):
    """
    Fetch full document records using BatchGetItem for efficiency.
    Returns a dict of ObjectKey -> document item.
    """
    if not object_keys:
        return {}

    ddb_client = boto3.client("dynamodb")
    documents = {}

    # Process in chunks of BATCH_GET_LIMIT
    for i in range(0, len(object_keys), BATCH_GET_LIMIT):
        chunk = object_keys[i : i + BATCH_GET_LIMIT]
        keys = [
            {"PK": {"S": f"doc#{key}"}, "SK": {"S": "none"}}
            for key in chunk
        ]

        request_items = {table_name: {"Keys": keys}}

        while request_items:
            response = ddb_client.batch_get_item(RequestItems=request_items)

            for item in response.get("Responses", {}).get(table_name, []):
                # Convert DynamoDB JSON to regular dict
                doc = _unmarshall_item(item)
                if doc and doc.get("ObjectKey"):
                    documents[doc["ObjectKey"]] = doc

            # Handle unprocessed keys (throttling)
            request_items = response.get("UnprocessedKeys", {})

    return documents


def _unmarshall_item(ddb_item):
    """Convert a DynamoDB JSON item to a regular Python dict."""
    deserializer = boto3.dynamodb.types.TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in ddb_item.items()}


def _serialize_next_token(shard_index: int, item_offset: int) -> str:
    """Encode pagination state as a JSON string."""
    return json.dumps({"si": shard_index, "io": item_offset})


def _deserialize_next_token(token: str):
    """Decode pagination state."""
    if not token:
        return 0, 0
    try:
        data = json.loads(token)
        return data.get("si", 0), data.get("io", 0)
    except (json.JSONDecodeError, AttributeError):
        return 0, 0


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event, context):
    """AppSync Lambda resolver handler."""
    logger.info(f"listDocumentsByDateRange invoked")
    logger.debug(f"Event: {json.dumps(event, default=str)}")

    args = event.get("arguments", {})
    start_date_time = args.get("startDateTime")
    end_date_time = args.get("endDateTime")
    limit = min(args.get("limit") or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    next_token = args.get("nextToken")

    if not start_date_time or not end_date_time:
        raise ValueError("startDateTime and endDateTime are required")

    # Parse ISO timestamps
    # Handle both formats: 2026-02-07T00:00:00.000Z and 2026-02-07T00:00:00Z
    start_dt = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_date_time.replace("Z", "+00:00"))

    if start_dt > end_dt:
        raise ValueError("startDateTime must be before endDateTime")

    table_name = os.environ["TRACKING_TABLE_NAME"]
    table = dynamodb.Table(table_name)

    # Generate all shard partition keys for the range
    shard_pairs = _shard_pks_for_range(start_dt, end_dt)
    logger.info(
        f"Date range {start_date_time} → {end_date_time}: "
        f"{len(shard_pairs)} shards to query"
    )

    # Resume from pagination token
    start_shard_idx, start_item_offset = _deserialize_next_token(next_token)

    # Collect list entries across shards until we have enough for a page
    collected_entries = []
    current_shard_idx = start_shard_idx
    current_item_offset = start_item_offset if current_shard_idx == start_shard_idx else 0

    # ISO strings for filtering
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    result_next_token = None

    while current_shard_idx < len(shard_pairs) and len(collected_entries) < limit:
        date_str, shard = shard_pairs[current_shard_idx]
        logger.debug(f"Querying shard: {date_str}#s#{shard:02d}")

        shard_items = _query_shard(table, date_str, shard, start_iso, end_iso)

        # Apply offset if resuming within a shard
        if current_item_offset > 0:
            shard_items = shard_items[current_item_offset:]
            current_item_offset = 0

        remaining_capacity = limit - len(collected_entries)
        if len(shard_items) > remaining_capacity:
            # Take only what we need and set next_token
            collected_entries.extend(shard_items[:remaining_capacity])
            result_next_token = _serialize_next_token(
                current_shard_idx,
                (start_item_offset if current_shard_idx == start_shard_idx else 0)
                + remaining_capacity,
            )
            break
        else:
            collected_entries.extend(shard_items)
            current_shard_idx += 1

    # If we ran out of shards, no next token
    if current_shard_idx >= len(shard_pairs):
        result_next_token = None

    logger.info(f"Collected {len(collected_entries)} list entries")

    # Extract ObjectKeys from list entries
    object_keys = [entry.get("ObjectKey") for entry in collected_entries if entry.get("ObjectKey")]

    # Batch-fetch full document records
    documents_map = _batch_get_documents(table_name, object_keys)
    logger.info(f"Fetched {len(documents_map)} document details")

    # Build response, preserving list entry PK/SK for compatibility
    documents = []
    for entry in collected_entries:
        obj_key = entry.get("ObjectKey")
        if obj_key and obj_key in documents_map:
            doc = documents_map[obj_key]
            # Add list entry PK/SK for potential deletion/reprocessing
            doc["ListPK"] = entry.get("PK")
            doc["ListSK"] = entry.get("SK")
            documents.append(doc)

    # Sort by InitialEventTime descending (most recent first)
    documents.sort(
        key=lambda d: d.get("InitialEventTime", ""),
        reverse=True,
    )

    response = {
        "Documents": documents,
        "nextToken": result_next_token,
    }

    logger.info(
        f"Returning {len(documents)} documents, "
        f"hasNextPage={result_next_token is not None}"
    )

    return response