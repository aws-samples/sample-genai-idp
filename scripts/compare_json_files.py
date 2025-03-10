#!/usr/bin/env python3
# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
from botocore.config import Config
import json
from deepdiff import DeepDiff
from collections import defaultdict
import pandas as pd
from datetime import datetime
import argparse
import logging
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ComparisonError:
    def __init__(self, error_type, message):
        self.error_type = error_type
        self.message = message

    def to_dict(self):
        return {
            'error_type': self.error_type,
            'message': str(self.message)
        }

def get_s3_files(bucket_name, folder_prefix):
    """
    Get list of JSON files from an S3 bucket folder
    """
    s3_client = boto3.client('s3')
    files = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=folder_prefix)
        
        for page in pages:
            if 'Contents' in page:
                files.extend([obj['Key'] for obj in page['Contents'] if obj['Key'].endswith('.json')])
        
        logger.info(f"Found {len(files)} JSON files in {folder_prefix}")
    except Exception as e:
        logger.error(f"Error listing files from S3: {str(e)}")
        raise
    
    return files

def read_json_from_s3(bucket_name, file_key):
    """
    Read JSON content from S3 file
    """
    s3_client = boto3.client('s3')
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        content = response['Body'].read().decode('utf-8')
        
        if not content.strip():
            return ComparisonError('empty_content', f"Empty content in file: {file_key}")
            
        return json.loads(content)
    except s3_client.exceptions.NoSuchKey:
        return ComparisonError('file_not_found', f"File not found in S3: {file_key}")
    except json.JSONDecodeError as e:
        return ComparisonError('invalid_json', f"JSON decode error: {str(e)}")
    except Exception as e:
        return ComparisonError('unknown_error', f"Error reading file: {str(e)}")

def compare_json_sets(bucket_name, folder1, folder2):
    """
    Compare two sets of JSON files and generate detailed comparison
    """
    # Get file lists
    files1 = get_s3_files(bucket_name, folder1)
    files2 = get_s3_files(bucket_name, folder2)
    
    # Extract base filenames for comparison
    base_files1 = {f.split('/')[-1]: f for f in files1}
    base_files2 = {f.split('/')[-1]: f for f in files2}
    
    # Analyze file presence
    missing_in_set1 = set(base_files2.keys()) - set(base_files1.keys())
    missing_in_set2 = set(base_files1.keys()) - set(base_files2.keys())
    common_files = set(base_files1.keys()) & set(base_files2.keys())
    
    # Initialize result containers
    comparison_results = []
    summary_stats = defaultdict(int)
    field_differences = defaultdict(int)
    invalid_files = defaultdict(list)
    
    # Process missing files
    for filename in missing_in_set1:
        comparison_results.append({
            'filename': filename,
            'status': 'Missing in Set 1',
            'differences': None,
            'error': None
        })
        summary_stats['missing_in_set1'] += 1
    
    for filename in missing_in_set2:
        comparison_results.append({
            'filename': filename,
            'status': 'Missing in Set 2',
            'differences': None,
            'error': None
        })
        summary_stats['missing_in_set2'] += 1
    
    # Compare common files
    for filename in common_files:
        result = {
            'filename': filename,
            'status': '',
            'differences': None,
            'error': None
        }
        
        # Read JSON contents
        json1 = read_json_from_s3(bucket_name, base_files1[filename])
        json2 = read_json_from_s3(bucket_name, base_files2[filename])
        
        # Handle reading errors
        if isinstance(json1, ComparisonError):
            invalid_files['set1'].append((filename, json1))
            result['status'] = 'Error in Set 1'
            result['error'] = json1.to_dict()
            summary_stats['invalid_json_set1'] += 1
        elif isinstance(json2, ComparisonError):
            invalid_files['set2'].append((filename, json2))
            result['status'] = 'Error in Set 2'
            result['error'] = json2.to_dict()
            summary_stats['invalid_json_set2'] += 1
        else:
            # Compare valid JSON files
            try:
                diff = DeepDiff(json1, json2, ignore_order=True)
                if diff:
                    result['status'] = 'Different'
                    result['differences'] = str(diff)  # Convert to string to avoid serialization issues
                    summary_stats['different'] += 1
                    
                    # Track field-level differences
                    for change_type, changes in diff.items():
                        if change_type in ['values_changed', 'type_changes']:
                            for path in changes:
                                field = path.split('[')[0].replace('root', '').strip('.')
                                field_differences[field] += 1
                else:
                    result['status'] = 'Identical'
                    summary_stats['identical'] += 1
            except Exception as e:
                result['status'] = 'Comparison Error'
                result['error'] = {'error_type': 'comparison_error', 'message': str(e)}
                summary_stats['comparison_error'] += 1
        
        comparison_results.append(result)
    
    return comparison_results, summary_stats, field_differences, invalid_files

def get_ai_summary(comparison_results, summary_stats, field_differences):
    """
    Generate an AI-powered summary of the differences using Amazon Bedrock
    """
    # Configure Bedrock client
    bedrock = boto3.client(
        service_name='bedrock-runtime',
        config=Config(region_name='us-east-1')
    )
    
    # Prepare the analysis prompt
    differences_examples = []
    for result in comparison_results:
        if result['status'] == 'Different' and result['differences']:
            differences_examples.append(f"File: {result['filename']}\n{result['differences']}")
    
    # Create a summary of field differences
    field_diff_summary = "\n".join([f"{field}: {count} differences" 
                                  for field, count in sorted(field_differences.items(), 
                                                          key=lambda x: x[1], 
                                                          reverse=True)])
    
    prompt = f"""Analyze the following JSON file differences and provide a detailed summary. 
    Focus on:
    1. Most commonly different fields
    2. Whether differences are substantial (affecting meaning/operations) or cosmetic (formatting)
    3. Patterns in the differences
    4. Potential data quality issues or concerns

    Summary Statistics:
    {json.dumps(summary_stats, indent=2)}

    Field-level Differences:
    {field_diff_summary}

    Representative Examples of Differences:
    {differences_examples[:5]}  # Include first 5 examples

    Provide a structured analysis similar to this format:
    1. Most Common Types of Differences
    2. Substantial Differences
    3. Cosmetic Differences
    4. Overall Assessment
    """

    # Call Bedrock
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.5
        })
        
        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
    
    except Exception as e:
        logger.error(f"Error generating AI summary: {str(e)}")
        return f"Error generating AI summary: {str(e)}"

def generate_report(comparison_results, summary_stats, field_differences, invalid_files, output_dir='.'):
    """
    Generate detailed report of the comparison
    """
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate AI summary
    ai_summary = get_ai_summary(comparison_results, summary_stats, field_differences)
    
    # Generate detailed report
    report_path = f'{output_dir}/comparison_report_{timestamp}.txt'
    with open(report_path, 'w') as f:
        f.write("JSON Files Comparison Report\n")
        f.write("==========================\n\n")
        
        # Write AI Summary
        f.write("AI-Generated Analysis\n")
        f.write("====================\n")
        f.write(ai_summary)
        f.write("\n\n" + "="*50 + "\n\n")
        
        # Write summary statistics
        f.write("Summary Statistics:\n")
        f.write(f"Total files processed: {sum(summary_stats.values())}\n")
        f.write(f"Identical files: {summary_stats['identical']}\n")
        f.write(f"Different files: {summary_stats['different']}\n")
        f.write(f"Files missing in Set 1: {summary_stats['missing_in_set1']}\n")
        f.write(f"Files missing in Set 2: {summary_stats['missing_in_set2']}\n")
        f.write(f"Invalid JSON files in Set 1: {summary_stats['invalid_json_set1']}\n")
        f.write(f"Invalid JSON files in Set 2: {summary_stats['invalid_json_set2']}\n")
        f.write(f"Comparison errors: {summary_stats['comparison_error']}\n\n")
        
        # Write invalid files details
        f.write("\nInvalid Files Details:\n")
        f.write("=====================\n")
        
        f.write("\nSet 1 Invalid Files:\n")
        for filename, error in invalid_files['set1']:
            f.write(f"  {filename}: {error.message}\n")
        
        f.write("\nSet 2 Invalid Files:\n")
        for filename, error in invalid_files['set2']:
            f.write(f"  {filename}: {error.message}\n")
        
        # Write field-level differences summary
        f.write("\nField-level Differences Summary:\n")
        f.write("==============================\n")
        for field, count in sorted(field_differences.items(), key=lambda x: x[1], reverse=True):
            f.write(f"{field}: {count} differences\n")
        
        # Write detailed comparison results
        f.write("\nDetailed Comparison Results:\n")
        f.write("==========================\n")
        for result in comparison_results:
            f.write(f"\nFile: {result['filename']}\n")
            f.write(f"Status: {result['status']}\n")
            
            if result['error']:
                f.write(f"Error: {result['error']['error_type']} - {result['error']['message']}\n")
            
            if result['differences']:
                f.write("Differences:\n")
                f.write(result['differences'])
            f.write("\n" + "-"*50 + "\n")
      
    return report_path

def parse_args():
    parser = argparse.ArgumentParser(description='Compare JSON files between two S3 folders')
    parser.add_argument('bucket', help='S3 bucket name')
    parser.add_argument('folder1', help='Path to first folder in S3')
    parser.add_argument('folder2', help='Path to second folder in S3')
    parser.add_argument('--output-dir', '-o', default='.',
                      help='Output directory for reports (default: current directory)')
    parser.add_argument('--debug', action='store_true',
                      help='Enable debug logging')
    return parser.parse_args()

def main():
    args = parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    logger.info(f"Starting comparison between:")
    logger.info(f"Bucket: {args.bucket}")
    logger.info(f"Folder 1: {args.folder1}")
    logger.info(f"Folder 2: {args.folder2}")
    
    comparison_results, summary_stats, field_differences, invalid_files = compare_json_sets(
        args.bucket, args.folder1, args.folder2
    )
    
    logger.info("\nGenerating reports...")
    report_path = generate_report(
        comparison_results, summary_stats, field_differences, invalid_files, args.output_dir
    )
    logger.info(f"\nComparison complete! Reports generated:")
    logger.info(f"Detailed report: {report_path}")

if __name__ == "__main__":
    main()