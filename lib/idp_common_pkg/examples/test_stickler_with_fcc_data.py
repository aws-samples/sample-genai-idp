#!/usr/bin/env python3
"""
Test SticklerEvaluationService with actual FCC invoice data.

This script demonstrates using SticklerEvaluationService to evaluate
real FCC invoice extraction results against ground truth labels.
"""

import json
import os
import pandas as pd
from pathlib import Path
from idp_common.evaluation import SticklerEvaluationService
from idp_common.models import Section


def load_ground_truth_from_csv(csv_path: str, doc_id: str):
    """
    Load ground truth labels from the refactored labels CSV.
    
    Args:
        csv_path: Path to the CSV file with refactored_labels column
        doc_id: Document ID to look up
        
    Returns:
        Dictionary of ground truth labels
    """
    df = pd.read_csv(csv_path)
    
    # Find the row for this document
    row = df[df['doc_id'] == doc_id]
    
    if row.empty:
        print(f"Warning: No ground truth found for doc_id: {doc_id}")
        return None
    
    # Parse the refactored_labels JSON
    labels_json = row['refactored_labels'].values[0]
    
    if pd.isna(labels_json):
        print(f"Warning: refactored_labels is empty for doc_id: {doc_id}")
        return None
    
    try:
        labels = json.loads(labels_json)
        return labels
    except json.JSONDecodeError as e:
        print(f"Error parsing refactored_labels JSON: {e}")
        return None


def create_fcc_stickler_config():
    """
    Create a Stickler configuration for FCC invoices.
    
    Returns:
        Configuration dictionary for SticklerEvaluationService
    """
    config = {
        "stickler_models": {
            "fcc-invoice": {
                "model_name": "FCCInvoice",
                "match_threshold": 0.7,
                "fields": {
                    "agency": {
                        "type": "str",
                        "comparator": "FuzzyComparator",
                        "threshold": 0.8,
                        "weight": 2.0,
                    },
                    "advertiser": {
                        "type": "str",
                        "comparator": "FuzzyComparator",
                        "threshold": 0.8,
                        "weight": 2.0,
                    },
                    "gross_total": {
                        "type": "str",  # Stored as string with commas
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 3.0,
                    },
                    "net_amount_due": {
                        "type": "str",  # Stored as string with commas
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 3.0,
                    },
                    "line_item__description": {
                        "type": "list",
                        "comparator": "LevenshteinComparator",
                        "threshold": 0.7,
                        "weight": 1.5,
                    },
                    "line_item__days": {
                        "type": "list",
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 1.0,
                    },
                    "line_item__rate": {
                        "type": "list",
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 2.0,
                    },
                    "line_item__start_date": {
                        "type": "list",
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 2.0,
                    },
                    "line_item__end_date": {
                        "type": "list",
                        "comparator": "ExactComparator",
                        "threshold": 1.0,
                        "weight": 2.0,
                    },
                },
            }
        }
    }
    
    return config


def main():
    """Run the FCC invoice evaluation test."""
    
    print("=" * 80)
    print("SticklerEvaluationService - FCC Invoice Data Test")
    print("=" * 80)
    
    # Paths
    csv_path = "sr_refactor_labels_5_5_25.csv"
    data_dir = "tmp_data/cli-batch-20251017-154358"
    
    # Check if paths exist
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    if not os.path.exists(data_dir):
        print(f"Error: Data directory not found: {data_dir}")
        return
    
    # Create Stickler configuration
    print("\n1. Creating Stickler configuration for FCC invoices...")
    config = create_fcc_stickler_config()
    print("   ✓ Configuration created")
    
    # Initialize service
    print("\n2. Initializing SticklerEvaluationService...")
    service = SticklerEvaluationService(config=config)
    print(f"   ✓ Service initialized with models: {list(service.stickler_models.keys())}")
    
    # Find a sample document to test
    doc_dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
    
    if not doc_dirs:
        print("Error: No document directories found")
        return
    
    # Use the first document
    sample_doc = doc_dirs[0]
    doc_path = os.path.join(data_dir, sample_doc)
    
    print(f"\n3. Testing with document: {sample_doc}")
    
    # Load the extraction result
    result_path = os.path.join(doc_path, "sections/1/result.json")
    
    if not os.path.exists(result_path):
        print(f"Error: Result file not found: {result_path}")
        return
    
    with open(result_path, 'r') as f:
        result_data = json.load(f)
    
    actual_results = result_data.get('inference_result', {})
    doc_class = result_data.get('document_class', {}).get('type', 'unknown')
    
    print(f"   Document class: {doc_class}")
    print(f"   Extracted fields: {list(actual_results.keys())}")
    
    # Load ground truth from CSV
    # Extract doc_id from filename (remove .pdf extension)
    doc_id_from_filename = sample_doc.replace('.pdf', '')
    
    print(f"\n4. Loading ground truth for doc_id: {doc_id_from_filename}")
    ground_truth = load_ground_truth_from_csv(csv_path, doc_id_from_filename)
    
    if ground_truth is None:
        print("   Warning: No ground truth available, using actual results as expected")
        print("   This will show perfect matches (for demonstration purposes)")
        expected_results = actual_results
    else:
        expected_results = ground_truth
        print(f"   ✓ Ground truth loaded with {len(expected_results)} fields")
    
    # Create a section
    section = Section(
        section_id="section1",
        classification="fcc-invoice",
        page_ids=["page1"]
    )
    
    # Evaluate
    print("\n5. Evaluating extraction results...")
    try:
        result = service.evaluate_section(
            section=section,
            expected_results=expected_results,
            actual_results=actual_results
        )
        
        print("   ✓ Evaluation completed")
        
        # Display results
        print("\n6. Evaluation Results")
        print("-" * 80)
        print(f"Section ID: {result.section_id}")
        print(f"Document Class: {result.document_class}")
        
        if result.metrics:
            print(f"\nMetrics:")
            for metric_name, metric_value in result.metrics.items():
                print(f"  {metric_name:25} {metric_value:.4f}")
        
        if result.attributes:
            print(f"\nAttribute Results ({len(result.attributes)} attributes):")
            print(f"{'Attribute':<30} {'Match':<8} {'Score':<8}")
            print("-" * 50)
            
            matched_count = 0
            for attr in result.attributes[:20]:  # Show first 20
                match_symbol = "✓" if attr.matched else "✗"
                if attr.matched:
                    matched_count += 1
                print(f"{attr.name:<30} {match_symbol:<8} {attr.score:<8.3f}")
            
            if len(result.attributes) > 20:
                print(f"... and {len(result.attributes) - 20} more attributes")
            
            print(f"\nSummary: {matched_count}/{len(result.attributes)} attributes matched")
        else:
            print("\nNo attributes evaluated (model may not be configured for this class)")
        
    except Exception as e:
        print(f"   ✗ Error during evaluation: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
