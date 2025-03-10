import argparse
import boto3
import concurrent.futures
import io
import json
import logging

from botocore.config import Config
from datasets import load_dataset
from tqdm import tqdm


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


mapping = {
  0: "letter",
  1: "form",
  2: "email",
  3: "handwritten",
  4: "advertisement",
  5: "scientific report",
  6: "scientific publication",
  7: "specification",
  8: "file folder",
  9: "news article",
  10: "budget",
  11: "invoice",
  12: "presentation",
  13: "questionnaire",
  14: "resume",
  15: "memo"
}

mapping_split = {
    "train": "training",
    "test": "validation"
}

region = "us-west-2"

def save_json_2s3(client, data, bucket_name, keystr):
    """Saves JSON data to S3."""
    client.put_object(
        Bucket=bucket_name, Key=keystr,
        Body=json.dumps(data), ContentType="application/json"
    )


def save_image_2s3(client, image_bytes, bucket_name, keystr):
    """Saves image data to S3."""
    client.put_object(
        Bucket=bucket_name, Key=keystr,
        Body=image_bytes, ContentType="image/png"
    )


def textract_fn(image_bytes, client):
    """Calls AWS Textract to extract text from an image."""
    return client.detect_document_text(Document={'Bytes': image_bytes})


def process_each(data, textract_client):
    """Processes each data item, extracts text using Textract, and returns structured data."""
    buffer = io.BytesIO()
    buffer.truncate(0)
    buffer.seek(0)
    data['image'].save(buffer, format="png")
    image_bytes = buffer.getvalue()
    label = {"label": mapping[int(data['label'])]}
    textract_json = textract_fn(image_bytes, textract_client)
    
    return {
        "image": image_bytes,
        "label": label,
        "textract": textract_json
    }


def save_each2s3(data, bucket_name, prefix, file_name, split, s3_client):
    """Saves processed data to S3."""
    save_json_2s3(
        s3_client, data["label"], bucket_name,
        f"{prefix.rstrip('/')}/{mapping_split[split]}/labels/{file_name}.json",
    )
    save_image_2s3(
        s3_client, data["image"], bucket_name,
        f"{prefix.rstrip('/')}/{mapping_split[split]}/images/{file_name}.png",
    )
    save_json_2s3(
        s3_client, data["textract"], bucket_name,
        f"{prefix.rstrip('/')}/{mapping_split[split]}/textract/{file_name}.json",
    )


def process_and_save(data, idx, bucket_name, prefix, split, textract_client, s3_client, logger):
    """Processes a data item and saves it to S3."""
    try:
        processed = process_each(data, textract_client)
        save_each2s3(processed, bucket_name, prefix, str(idx), split, s3_client)
    except Exception as e:
        logger.error(f"Error processing item {idx}: {e}")


def load_data_from_huggingface(split):
    """Loads dataset from Hugging Face."""
    return load_dataset("jordyvl/rvl_cdip_100_examples_per_class", split=split)


def metadata(client, data, bucket_name, prefix, split):
    """Creates and saves metadata for the dataset."""
    meta_data = {
        'labels': mapping,
        'size': len(data),
        'name': 'RVLCDIP'
    }
    save_json_2s3(
        client, meta_data, bucket_name,
        f"{prefix.rstrip('/')}/{mapping_split[split]}/metadata.json",
    )


def generate(split, bucket_name, prefix, max_workers):
    """Generates the dataset and processes it in parallel."""
    adaptive_config = Config(
        retries={'max_attempts': 100, 'mode': 'adaptive'},
        max_pool_connections=max_workers * 3
    )

    s3_client = boto3.client('s3', region_name=region, config=adaptive_config)
    textract_client = boto3.client('textract', region_name=region, config=adaptive_config)

    data = load_data_from_huggingface(split)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_and_save, dt, idx, bucket_name, prefix, split, 
                textract_client, s3_client, logger
            ): idx
            for idx, dt in enumerate(data)
        }
        
        for future in tqdm(
            concurrent.futures.as_completed(futures), total=len(data), 
            desc=f"Processing {mapping_split[split]} data", unit="item"
        ):
            try:
                future.result()  # Handle exceptions if needed
            except Exception as e:
                logger.error(f"Error processing item {futures[future]}: {e}")

    metadata(s3_client, data, bucket_name, prefix, split)
    logger.info(f"Data is saved under 's3://{bucket_name}/{prefix}/{mapping_split[split]}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process and upload dataset to S3 with AWS Textract.")
    parser.add_argument("--data-bucket", type=str, required=True, help="Name of the S3 bucket for storing data.")
    parser.add_argument("--data-bucket-prefix", type=str, default="", help="Prefix for S3 bucket paths.")
    parser.add_argument("--max-workers", type=int, default=40, help="Number of parallel workers.")
    
    args = parser.parse_args()
    generate("test", args.data_bucket, args.data_bucket_prefix, args.max_workers)
    generate("train", args.data_bucket, args.data_bucket_prefix, args.max_workers)