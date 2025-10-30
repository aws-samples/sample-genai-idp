#!/usr/bin/env python3
"""
Bulk evaluation script for FCC invoices using SticklerEvaluationService.

This script:
1. Loads ground truth from CSV
2. Loads inference results from a directory
3. Matches ground truth to inference results
4. Evaluates using SticklerEvaluationService (IDP framework integration)
5. Produces aggregated evaluation metrics
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
import pandas as pd
from collections import defaultdict
import numpy as np

# Add lib path for idp_common imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib" / "idp_common_pkg"))

from idp_common.evaluation.stickler_service import SticklerEvaluationService
from idp_common.models import Document, Section
from idp_common.evaluation.models import DocumentEvaluationResult


def convert_to_json_serializable(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(item) for item in obj]
    else:
        return obj


class BulkEvaluator:
    """Handles bulk evaluation of FCC invoice extraction results using SticklerEvaluationService."""
    
    def __init__(
        self,
        results_dir: str,
        csv_path: str,
        config_path: str,
        output_dir: str = "evaluation_output",
        doc_id_column: str = "doc_id",
        labels_column: str = "refactored_labels"
    ):
        """
        Initialize the bulk evaluator.
        
        Args:
            results_dir: Directory containing inference results
            csv_path: Path to CSV with ground truth labels
            config_path: Path to Stickler configuration JSON
            output_dir: Directory to save individual comparison results
            doc_id_column: Column name for document IDs in CSV
            labels_column: Column name for labels in CSV
        """
        self.results_dir = Path(results_dir)
        self.csv_path = csv_path
        self.config_path = config_path
        self.output_dir = Path(output_dir)
        self.doc_id_column = doc_id_column
        self.labels_column = labels_column
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load configuration and initialize SticklerEvaluationService
        self.stickler_config = self._load_stickler_config()
        
        # Initialize SticklerEvaluationService with the loaded config
        service_config = {
            "stickler_models": {
                "fcc_invoice": self.stickler_config
            }
        }
        self.evaluation_service = SticklerEvaluationService(config=service_config)
        
        # Initialize aggregation state
        self.confusion_matrix = {
            "overall": defaultdict(int),
            "fields": defaultdict(lambda: defaultdict(int)),
        }
        self.non_matches = []
        self.errors = []
        self.processed_count = 0
        
        print(f"✓ Initialized evaluator with SticklerEvaluationService")
        print(f"  Model: {self.stickler_config.get('model_name', 'fcc_invoice')}")
        print(f"  Output directory: {self.output_dir}")
    
    def _load_stickler_config(self) -> Dict[str, Any]:
        """Load Stickler configuration from JSON file."""
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        print(f"✓ Loaded Stickler config from {self.config_path}")
        return config
    
    def load_ground_truth(self) -> pd.DataFrame:
        """
        Load ground truth labels from CSV.
        
        Returns:
            DataFrame with doc_id and parsed labels
        """
        print(f"\n📊 Loading ground truth from {self.csv_path}...")
        df = pd.read_csv(self.csv_path)
        
        # Filter to rows with valid labels
        df = df[df[self.labels_column].notna()].copy()
        
        print(f"✓ Loaded {len(df)} documents with ground truth labels")
        return df
    
    def load_inference_results(self) -> Dict[str, Tuple[Dict[str, Any], str]]:
        """
        Load all inference results from the results directory.
        
        Returns:
            Dictionary mapping doc_id to tuple of (inference_result_data, result_file_path)
        """
        print(f"\n📁 Loading inference results from {self.results_dir}...")
        results = {}
        
        # Iterate through document directories
        for doc_dir in self.results_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            
            doc_id = doc_dir.name
            result_path = doc_dir / "sections" / "1" / "result.json"
            
            if not result_path.exists():
                continue
            
            try:
                with open(result_path, 'r') as f:
                    result_data = json.load(f)
                
                inference_result = result_data.get("inference_result", {})
                results[doc_id] = (inference_result, str(result_path))
            except Exception as e:
                print(f"  ⚠️  Error loading {doc_id}: {e}")
                continue
        
        print(f"✓ Loaded {len(results)} inference results")
        return results
    
    def match_ground_truth_to_results(
        self,
        ground_truth_df: pd.DataFrame,
        inference_results: Dict[str, Tuple[Dict[str, Any], str]]
    ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any], str]]:
        """
        Match ground truth labels to inference results.
        
        Args:
            ground_truth_df: DataFrame with ground truth
            inference_results: Dictionary of inference results with file paths
        
        Returns:
            List of tuples (doc_id, expected_results, actual_results, result_file_path)
        """
        print(f"\n🔗 Matching ground truth to inference results...")
        matched_pairs = []
        
        for _, row in ground_truth_df.iterrows():
            doc_id = row[self.doc_id_column]
            
            # Try to find matching inference result
            result_key = None
            if doc_id in inference_results:
                result_key = doc_id
            elif f"{doc_id}.pdf" in inference_results:
                result_key = f"{doc_id}.pdf"
            else:
                doc_id_no_ext = doc_id.replace('.pdf', '')
                if doc_id_no_ext in inference_results:
                    result_key = doc_id_no_ext
            
            if result_key is None:
                continue
            
            # Parse ground truth labels
            try:
                labels_json = row[self.labels_column]
                if pd.isna(labels_json):
                    continue
                
                expected_results = json.loads(labels_json)
                actual_results, result_file_path = inference_results[result_key]
                
                matched_pairs.append((doc_id, expected_results, actual_results, result_file_path))
            except Exception as e:
                print(f"  ⚠️  Error parsing labels for {doc_id}: {e}")
                continue
        
        print(f"✓ Matched {len(matched_pairs)} document pairs")
        return matched_pairs
    
    def _normalize_to_list_format(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize data to list format for all fields.
        Ground truth has lists, predictions have strings for simple fields.
        
        Args:
            data: Data to normalize
        
        Returns:
            Data with all values as lists
        """
        normalized = {}
        
        for key, value in data.items():
            if value is None:
                # Keep None as empty list for consistency
                normalized[key] = []
            elif isinstance(value, list):
                # Already a list
                normalized[key] = value
            elif isinstance(value, str):
                # Convert string to single-item list
                normalized[key] = [value]
            else:
                # Other types, wrap in list
                normalized[key] = [value]
        
        return normalized
    
    def _create_section_from_data(self, doc_id: str, classification: str = "fcc_invoice") -> Section:
        """
        Create a Section object for evaluation.
        
        Args:
            doc_id: Document identifier
            classification: Document classification
        
        Returns:
            Section object
        """
        return Section(
            section_id="1",
            classification=classification,
            confidence=1.0,
            page_ids=["1"]
        )
    
    def _save_ground_truth_to_temp(self, doc_id: str, expected_results: Dict[str, Any]) -> str:
        """
        Save ground truth to a temporary file for evaluation.
        
        Args:
            doc_id: Document identifier
            expected_results: Ground truth data (will be normalized to list format)
        
        Returns:
            Path to temporary file
        """
        temp_dir = self.output_dir / "temp_ground_truth"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Normalize to list format before saving
        normalized_results = self._normalize_to_list_format(expected_results)
        
        temp_file = temp_dir / f"{doc_id}_gt.json"
        with open(temp_file, 'w') as f:
            json.dump({"inference_result": normalized_results}, f, indent=2)
        
        return str(temp_file)
    
    def _save_actual_results_to_temp(self, doc_id: str, actual_results: Dict[str, Any]) -> str:
        """
        Save actual results to a temporary file for evaluation.
        
        Args:
            doc_id: Document identifier
            actual_results: Actual inference results (will be normalized to list format)
        
        Returns:
            Path to temporary file
        """
        temp_dir = self.output_dir / "temp_actual_results"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Normalize to list format before saving
        normalized_results = self._normalize_to_list_format(actual_results)
        
        temp_file = temp_dir / f"{doc_id}_actual.json"
        with open(temp_file, 'w') as f:
            json.dump({"inference_result": normalized_results}, f, indent=2)
        
        return str(temp_file)
    
    def _accumulate_metrics_from_evaluation(self, eval_result: DocumentEvaluationResult):
        """
        Accumulate metrics from DocumentEvaluationResult.
        
        Args:
            eval_result: Document evaluation result from SticklerEvaluationService
        """
        # Accumulate field-level metrics from section results
        for section_result in eval_result.section_results:
            for attr_result in section_result.attributes:
                field_name = attr_result.name
                
                # Determine metric contribution based on attribute result
                expected = attr_result.expected
                actual = attr_result.actual
                matched = attr_result.matched
                
                # Case 1: Expected value is None/empty
                if expected is None or (isinstance(expected, str) and not expected.strip()) or (isinstance(expected, list) and len(expected) == 0):
                    if actual is None or (isinstance(actual, str) and not actual.strip()) or (isinstance(actual, list) and len(actual) == 0):
                        self.confusion_matrix["fields"][field_name]["tn"] += 1
                        self.confusion_matrix["overall"]["tn"] += 1
                    else:
                        self.confusion_matrix["fields"][field_name]["fp"] += 1
                        self.confusion_matrix["fields"][field_name]["fp1"] += 1
                        self.confusion_matrix["overall"]["fp"] += 1
                        self.confusion_matrix["overall"]["fp1"] += 1
                
                # Case 2: Expected value exists but actual doesn't
                elif actual is None or (isinstance(actual, str) and not actual.strip()) or (isinstance(actual, list) and len(actual) == 0):
                    self.confusion_matrix["fields"][field_name]["fn"] += 1
                    self.confusion_matrix["overall"]["fn"] += 1
                
                # Case 3: Both values exist
                else:
                    if matched:
                        self.confusion_matrix["fields"][field_name]["tp"] += 1
                        self.confusion_matrix["overall"]["tp"] += 1
                    else:
                        self.confusion_matrix["fields"][field_name]["fp"] += 1
                        self.confusion_matrix["fields"][field_name]["fp2"] += 1
                        self.confusion_matrix["overall"]["fp"] += 1
                        self.confusion_matrix["overall"]["fp2"] += 1
    
    def evaluate_all(
        self,
        matched_pairs: List[Tuple[str, Dict[str, Any], Dict[str, Any], str]]
    ):
        """
        Evaluate all matched pairs using SticklerEvaluationService.
        
        Args:
            matched_pairs: List of (doc_id, expected, actual, result_file_path) tuples
        """
        print(f"\n⚙️  Evaluating {len(matched_pairs)} documents...")
        
        for doc_id, expected_results, actual_results, result_file_path in matched_pairs:
            try:
                # Create a Section object for evaluation
                section = self._create_section_from_data(doc_id)
                
                # Save ground truth and actual results to temporary files (normalized to list format)
                gt_file_path = self._save_ground_truth_to_temp(doc_id, expected_results)
                actual_file_path = self._save_actual_results_to_temp(doc_id, actual_results)
                
                # Use SticklerEvaluationService to evaluate
                # Note: We're adapting the service to work with local files
                eval_result = self.evaluation_service.evaluate_document(
                    document_id=doc_id,
                    sections=[section],
                    expected_results_uri=f"file://{gt_file_path}",
                    actual_results_uri=f"file://{actual_file_path}"
                )
                
                # Convert evaluation result to dict for saving
                result_dict = {
                    "doc_id": doc_id,
                    "evaluation_result": {
                        "document_id": eval_result.document_id,
                        "overall_metrics": eval_result.overall_metrics,
                        "execution_time": eval_result.execution_time,
                        "section_results": [
                            {
                                "section_id": sr.section_id,
                                "document_class": sr.document_class,
                                "metrics": sr.metrics,
                                "attributes": [
                                    {
                                        "name": ar.name,
                                        "expected": ar.expected,
                                        "actual": ar.actual,
                                        "matched": ar.matched,
                                        "score": ar.score,
                                        "reason": ar.reason,
                                        "evaluation_method": ar.evaluation_method
                                    }
                                    for ar in sr.attributes
                                ]
                            }
                            for sr in eval_result.section_results
                        ]
                    }
                }
                
                # Convert numpy types to JSON-serializable types
                result_dict = convert_to_json_serializable(result_dict)
                
                # Save individual result
                result_file = self.output_dir / f"{doc_id}.json"
                with open(result_file, 'w') as f:
                    json.dump(result_dict, f, indent=2)
                
                # Accumulate metrics for aggregation
                self._accumulate_metrics_from_evaluation(eval_result)
                
                # Collect non-matches (attributes that didn't match)
                for section_result in eval_result.section_results:
                    for attr_result in section_result.attributes:
                        if not attr_result.matched:
                            self.non_matches.append({
                                "doc_id": doc_id,
                                "field": attr_result.name,
                                "expected": attr_result.expected,
                                "actual": attr_result.actual,
                                "reason": attr_result.reason
                            })
                
                self.processed_count += 1
                
            except Exception as e:
                print(f"  ✗ Error evaluating {doc_id}: {e}")
                import traceback
                traceback.print_exc()
                
                # Save error result
                error_file = self.output_dir / f"{doc_id}.error.json"
                with open(error_file, 'w') as f:
                    json.dump({
                        "doc_id": doc_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }, f, indent=2)
                
                # Track error
                self.errors.append({
                    "doc_id": doc_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                })
        
        print(f"✓ Completed evaluation")
        print(f"  Individual results saved to: {self.output_dir}")
    

    
    def _calculate_metrics(self, cm: Dict[str, int]) -> Dict[str, float]:
        """
        Calculate derived metrics from confusion matrix.
        
        Args:
            cm: Confusion matrix with tp, fp, tn, fn counts
        
        Returns:
            Dictionary of calculated metrics
        """
        tp = cm.get("tp", 0)
        fp = cm.get("fp", 0)
        tn = cm.get("tn", 0)
        fn = cm.get("fn", 0)
        fp1 = cm.get("fp1", 0) + cm.get("fa", 0)  # fa is alias for fp1
        fp2 = cm.get("fp2", 0) + cm.get("fd", 0)  # fd is alias for fp2
        
        total = tp + fp + tn + fn
        
        # Calculate metrics with zero-division handling
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_score = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        accuracy = (tp + tn) / total if total > 0 else 0.0
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "accuracy": accuracy,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "fp1": fp1,
            "fp2": fp2,
            "total": total
        }
    
    def print_aggregated_results(self):
        """Print aggregated metrics summary."""
        print("\n" + "=" * 80)
        print("AGGREGATED EVALUATION RESULTS")
        print("=" * 80)
        
        print(f"\n📊 Processing Summary:")
        print(f"  Documents processed:  {self.processed_count}")
        print(f"  Errors encountered:   {len(self.errors)}")
        print(f"  Non-matches found:    {len(self.non_matches)}")
        
        # Overall metrics
        print(f"\n📈 Overall Metrics:")
        overall_metrics = self._calculate_metrics(self.confusion_matrix["overall"])
        print(f"  Precision:    {overall_metrics['precision']:.4f}")
        print(f"  Recall:       {overall_metrics['recall']:.4f}")
        print(f"  F1 Score:     {overall_metrics['f1_score']:.4f}")
        print(f"  Accuracy:     {overall_metrics['accuracy']:.4f}")
        
        print(f"\n  Confusion Matrix:")
        print(f"    TP: {overall_metrics['tp']:6d}  |  FP: {overall_metrics['fp']:6d}")
        print(f"    FN: {overall_metrics['fn']:6d}  |  TN: {overall_metrics['tn']:6d}")
        print(f"    FP1 (False Alarm): {overall_metrics['fp1']:6d}")
        print(f"    FP2 (Wrong Value): {overall_metrics['fp2']:6d}")
        
        # Field-level metrics
        if self.confusion_matrix["fields"]:
            print(f"\n📋 Field-Level Metrics (Top 10 by F1 Score):")
            field_metrics = []
            for field_path, cm in self.confusion_matrix["fields"].items():
                metrics = self._calculate_metrics(cm)
                metrics["field"] = field_path
                field_metrics.append(metrics)
            
            # Sort by F1 score
            field_metrics.sort(key=lambda x: x["f1_score"], reverse=True)
            
            print(f"  {'Field':<40} {'Precision':>10} {'Recall':>10} {'F1':>10}")
            print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*10}")
            for metrics in field_metrics[:10]:
                print(f"  {metrics['field']:<40} {metrics['precision']:>10.4f} {metrics['recall']:>10.4f} {metrics['f1_score']:>10.4f}")
        
        print("\n" + "=" * 80)
    
    def save_aggregated_results(self, output_path: str):
        """
        Save aggregated results to JSON file.
        
        Args:
            output_path: Path to save aggregated results
        """
        # Calculate metrics for all fields
        overall_metrics = self._calculate_metrics(self.confusion_matrix["overall"])
        
        field_metrics = {}
        for field_path, cm in self.confusion_matrix["fields"].items():
            field_metrics[field_path] = self._calculate_metrics(cm)
        
        output_data = {
            "summary": {
                "documents_processed": self.processed_count,
                "errors": len(self.errors),
                "non_matches": len(self.non_matches)
            },
            "overall_metrics": overall_metrics,
            "field_metrics": field_metrics,
            "non_matches": self.non_matches[:100],  # Limit to first 100 for file size
            "errors": self.errors
        }
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"\n💾 Aggregated results saved to {output_path}")
    
    def run(self):
        """Run the complete bulk evaluation workflow."""
        print("=" * 80)
        print("BULK FCC INVOICE EVALUATION")
        print("=" * 80)
        
        # Step 1: Load ground truth
        ground_truth_df = self.load_ground_truth()
        
        # Step 2: Load inference results
        inference_results = self.load_inference_results()
        
        # Step 3: Match ground truth to results
        matched_pairs = self.match_ground_truth_to_results(
            ground_truth_df,
            inference_results
        )
        
        if not matched_pairs:
            print("\n❌ No matched pairs found. Check doc_id column and file naming.")
            return
        
        # Step 4: Evaluate all pairs and save individual results
        self.evaluate_all(matched_pairs)
        
        # Step 5: Print aggregated results
        self.print_aggregated_results()
        
        # Step 6: Save aggregated results
        aggregated_path = self.output_dir / "aggregated_metrics.json"
        self.save_aggregated_results(str(aggregated_path))
        
        print("\n" + "=" * 80)
        print(f"✅ Evaluation complete!")
        print(f"   Individual results: {self.output_dir}")
        print(f"   Aggregated metrics: {aggregated_path}")
        print("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bulk evaluate FCC invoice extraction results using Stickler"
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Directory containing inference results"
    )
    parser.add_argument(
        "--csv-path",
        required=True,
        help="Path to CSV file with ground truth labels"
    )
    parser.add_argument(
        "--config-path",
        default="config_library/pattern-2/fcc-invoices/stickler_config.json",
        help="Path to Stickler configuration JSON"
    )
    parser.add_argument(
        "--doc-id-column",
        default="doc_id",
        help="Column name for document IDs in CSV"
    )
    parser.add_argument(
        "--labels-column",
        default="refactored_labels",
        help="Column name for labels in CSV"
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation_output",
        help="Output directory for individual evaluation results"
    )
    
    args = parser.parse_args()
    
    # Create evaluator and run
    evaluator = BulkEvaluator(
        results_dir=args.results_dir,
        csv_path=args.csv_path,
        config_path=args.config_path,
        output_dir=args.output_dir,
        doc_id_column=args.doc_id_column,
        labels_column=args.labels_column
    )
    
    evaluator.run()


if __name__ == "__main__":
    main()
