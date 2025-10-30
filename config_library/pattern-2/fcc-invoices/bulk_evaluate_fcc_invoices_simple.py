#!/usr/bin/env python3
"""
Simple bulk evaluation script for FCC invoices using Stickler.

This script evaluates FCC invoice extraction results against ground truth
from a CSV file, producing aggregated metrics.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import numpy as np
from collections import defaultdict

# Add lib path for idp_common imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib" / "idp_common_pkg"))

from idp_common.evaluation.stickler_service import SticklerEvaluationService
from idp_common.models import Section


def to_json_serializable(obj):
    """Convert numpy types to Python native types."""
    if isinstance(obj, (np.bool_, np.integer, np.floating)):
        return obj.item()
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_json_serializable(item) for item in obj]
    return obj


def load_stickler_config(config_path: str) -> Dict[str, Any]:
    """Load Stickler configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def normalize_to_list_format(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize data to list format for all fields."""
    normalized = {}
    for key, value in data.items():
        if value is None:
            normalized[key] = []
        elif isinstance(value, list):
            normalized[key] = value
        elif isinstance(value, str):
            normalized[key] = [value]
        else:
            normalized[key] = [value]
    return normalized


def main():
    parser = argparse.ArgumentParser(
        description="Bulk evaluate FCC invoice extraction results"
    )
    parser.add_argument("--results-dir", required=True, help="Directory containing inference results")
    parser.add_argument("--csv-path", required=True, help="Path to CSV file with ground truth labels")
    parser.add_argument("--config-path", required=True, help="Path to Stickler configuration JSON")
    parser.add_argument("--doc-id-column", default="doc_id", help="Column name for document IDs")
    parser.add_argument("--labels-column", default="refactored_labels", help="Column name for labels")
    parser.add_argument("--output-dir", default="evaluation_output", help="Output directory")
    
    args = parser.parse_args()
    
    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("BULK FCC INVOICE EVALUATION")
    print("=" * 80)
    
    # Load configuration and initialize service
    print(f"\n📋 Loading Stickler config from {args.config_path}...")
    stickler_config = load_stickler_config(args.config_path)
    
    service_config = {
        "stickler_models": {
            "fcc_invoice": stickler_config
        }
    }
    service = SticklerEvaluationService(config=service_config)
    print(f"✓ Service initialized")
    
    # Load ground truth
    print(f"\n📊 Loading ground truth from {args.csv_path}...")
    df = pd.read_csv(args.csv_path)
    df = df[df[args.labels_column].notna()].copy()
    print(f"✓ Loaded {len(df)} documents with ground truth")
    
    # Load inference results
    print(f"\n📁 Loading inference results from {results_dir}...")
    inference_results = {}
    for doc_dir in results_dir.iterdir():
        if not doc_dir.is_dir():
            continue
        result_path = doc_dir / "sections" / "1" / "result.json"
        if result_path.exists():
            with open(result_path, 'r') as f:
                result_data = json.load(f)
                inference_results[doc_dir.name] = result_data.get("inference_result", {})
    print(f"✓ Loaded {len(inference_results)} inference results")
    
    # Match and evaluate
    print(f"\n⚙️  Evaluating documents...")
    
    # Accumulation state
    overall_metrics = defaultdict(int)
    field_metrics = defaultdict(lambda: defaultdict(int))
    processed = 0
    errors = []
    
    for _, row in df.iterrows():
        doc_id = row[args.doc_id_column]
        
        # Find matching result
        result_key = None
        for key in [doc_id, f"{doc_id}.pdf", doc_id.replace('.pdf', '')]:
            if key in inference_results:
                result_key = key
                break
        
        if not result_key:
            continue
        
        try:
            # Parse ground truth and get actual results
            expected = json.loads(row[args.labels_column])
            actual = inference_results[result_key]
            
            # Normalize to list format
            expected = normalize_to_list_format(expected)
            actual = normalize_to_list_format(actual)
            
            # Create section and evaluate
            section = Section(section_id="1", classification="fcc_invoice", page_ids=["1"])
            result = service.evaluate_section(section, expected, actual)
            
            # Accumulate metrics from attributes
            for attr in result.attributes:
                field = attr.name
                exp_val = attr.expected
                act_val = attr.actual
                matched = attr.matched
                
                # Determine metric type
                exp_empty = not exp_val or (isinstance(exp_val, list) and len(exp_val) == 0)
                act_empty = not act_val or (isinstance(act_val, list) and len(act_val) == 0)
                
                if exp_empty and act_empty:
                    overall_metrics["tn"] += 1
                    field_metrics[field]["tn"] += 1
                elif exp_empty and not act_empty:
                    overall_metrics["fp"] += 1
                    overall_metrics["fp1"] += 1
                    field_metrics[field]["fp"] += 1
                    field_metrics[field]["fp1"] += 1
                elif not exp_empty and act_empty:
                    overall_metrics["fn"] += 1
                    field_metrics[field]["fn"] += 1
                elif matched:
                    overall_metrics["tp"] += 1
                    field_metrics[field]["tp"] += 1
                else:
                    overall_metrics["fp"] += 1
                    overall_metrics["fp2"] += 1
                    field_metrics[field]["fp"] += 1
                    field_metrics[field]["fp2"] += 1
            
            # Save individual result
            result_file = output_dir / f"{doc_id}.json"
            result_data = {
                "doc_id": doc_id,
                "metrics": result.metrics,
                "attributes": [
                    {
                        "name": a.name,
                        "expected": a.expected,
                        "actual": a.actual,
                        "matched": a.matched,
                        "score": float(a.score),
                        "reason": a.reason
                    }
                    for a in result.attributes
                ]
            }
            with open(result_file, 'w') as f:
                json.dump(to_json_serializable(result_data), f, indent=2)
            
            processed += 1
            
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})
            print(f"  ✗ Error evaluating {doc_id}: {e}")
    
    print(f"✓ Completed evaluation of {processed} documents")
    
    # Calculate metrics
    def calc_metrics(cm):
        tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]
        total = tp + fp + tn + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = (tp + tn) / total if total > 0 else 0.0
        return {
            "precision": precision, "recall": recall, "f1_score": f1, "accuracy": accuracy,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "fp1": cm["fp1"], "fp2": cm["fp2"], "total": total
        }
    
    overall = calc_metrics(overall_metrics)
    fields = {field: calc_metrics(cm) for field, cm in field_metrics.items()}
    
    # Print results
    print("\n" + "=" * 80)
    print("AGGREGATED RESULTS")
    print("=" * 80)
    print(f"\n📊 Summary: {processed} processed, {len(errors)} errors")
    print(f"\n📈 Overall Metrics:")
    print(f"  Precision: {overall['precision']:.4f}")
    print(f"  Recall:    {overall['recall']:.4f}")
    print(f"  F1 Score:  {overall['f1_score']:.4f}")
    print(f"  Accuracy:  {overall['accuracy']:.4f}")
    print(f"\n  Confusion Matrix:")
    print(f"    TP: {overall['tp']:6d}  |  FP: {overall['fp']:6d}")
    print(f"    FN: {overall['fn']:6d}  |  TN: {overall['tn']:6d}")
    print(f"    FP1: {overall['fp1']:6d}  |  FP2: {overall['fp2']:6d}")
    
    # Top fields
    sorted_fields = sorted(fields.items(), key=lambda x: x[1]["f1_score"], reverse=True)
    print(f"\n📋 Field-Level Metrics (Top 10):")
    print(f"  {'Field':<40} {'Precision':>10} {'Recall':>10} {'F1':>10}")
    print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*10}")
    for field, metrics in sorted_fields[:10]:
        print(f"  {field:<40} {metrics['precision']:>10.4f} {metrics['recall']:>10.4f} {metrics['f1_score']:>10.4f}")
    
    # Save aggregated results
    output_file = output_dir / "aggregated_metrics.json"
    with open(output_file, 'w') as f:
        json.dump({
            "summary": {"documents_processed": processed, "errors": len(errors)},
            "overall_metrics": overall,
            "field_metrics": fields,
            "errors": errors
        }, f, indent=2)
    
    print(f"\n💾 Results saved to {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
