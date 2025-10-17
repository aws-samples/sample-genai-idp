#!/usr/bin/env python3
"""
Bulk evaluation script for FCC invoices using Stickler.

This script:
1. Loads ground truth from CSV
2. Loads inference results from a directory
3. Matches ground truth to inference results
4. Evaluates using Stickler's BulkStructuredModelEvaluator
5. Produces aggregated evaluation metrics
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any
import pandas as pd

from stickler import StructuredModel
from collections import defaultdict


class BulkEvaluator:
    """Handles bulk evaluation of FCC invoice extraction results."""
    
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
        
        # Load configuration and create model class
        self.stickler_config = self._load_stickler_config()
        self.model_class = StructuredModel.model_from_json(self.stickler_config)
        
        # Initialize aggregation state (same logic as BulkStructuredModelEvaluator)
        self.confusion_matrix = {
            "overall": defaultdict(int),
            "fields": defaultdict(lambda: defaultdict(int)),
        }
        self.non_matches = []
        self.errors = []
        self.processed_count = 0
        
        print(f"✓ Initialized evaluator")
        print(f"  Model: {self.stickler_config['model_name']}")
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
    
    def load_inference_results(self) -> Dict[str, Dict[str, Any]]:
        """
        Load all inference results from the results directory.
        
        Returns:
            Dictionary mapping doc_id to inference result data
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
                
                results[doc_id] = result_data.get("inference_result", {})
            except Exception as e:
                print(f"  ⚠️  Error loading {doc_id}: {e}")
                continue
        
        print(f"✓ Loaded {len(results)} inference results")
        return results
    
    def match_ground_truth_to_results(
        self,
        ground_truth_df: pd.DataFrame,
        inference_results: Dict[str, Dict[str, Any]]
    ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
        """
        Match ground truth labels to inference results.
        
        Args:
            ground_truth_df: DataFrame with ground truth
            inference_results: Dictionary of inference results
        
        Returns:
            List of tuples (doc_id, expected_results, actual_results)
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
                actual_results = inference_results[result_key]
                
                matched_pairs.append((doc_id, expected_results, actual_results))
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
    
    def _accumulate_confusion_matrix(self, cm_result: Dict[str, Any]):
        """
        Accumulate confusion matrix from a single result (same logic as BulkStructuredModelEvaluator).
        
        Args:
            cm_result: Confusion matrix result from comparison
        """
        # Accumulate overall metrics
        if "overall" in cm_result:
            for metric_name, value in cm_result["overall"].items():
                if isinstance(value, (int, float)) and metric_name in [
                    "tp", "fp", "tn", "fn", "fp1", "fp2", "fa", "fd"
                ]:
                    self.confusion_matrix["overall"][metric_name] += value
        
        # Accumulate field-level metrics
        if "fields" in cm_result:
            for field_path, field_data in cm_result["fields"].items():
                # Get the aggregate metrics for this field
                if "aggregate" in field_data:
                    for metric_name, value in field_data["aggregate"].items():
                        if isinstance(value, (int, float)) and metric_name in [
                            "tp", "fp", "tn", "fn", "fp1", "fp2", "fa", "fd"
                        ]:
                            self.confusion_matrix["fields"][field_path][metric_name] += value
    
    def evaluate_all(
        self,
        matched_pairs: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]
    ):
        """
        Evaluate all matched pairs, save individual results, and accumulate metrics.
        
        Args:
            matched_pairs: List of (doc_id, expected, actual) tuples
        """
        print(f"\n⚙️  Evaluating {len(matched_pairs)} documents...")
        
        for doc_id, expected_results, actual_results in matched_pairs:
            try:
                # Normalize both to list format (ground truth already has lists, predictions have strings)
                expected_results = self._normalize_to_list_format(expected_results)
                actual_results = self._normalize_to_list_format(actual_results)
                
                # Create model instances
                gt_model = self.model_class(**expected_results)
                pred_model = self.model_class(**actual_results)
                
                # Perform comparison for individual result
                comparison_result = gt_model.compare_with(
                    pred_model,
                    include_confusion_matrix=True,
                    document_non_matches=True
                )
                
                # Save individual result
                result_file = self.output_dir / f"{doc_id}.json"
                with open(result_file, 'w') as f:
                    json.dump({
                        "doc_id": doc_id,
                        "comparison_result": comparison_result
                    }, f, indent=2)
                
                # Accumulate confusion matrix for aggregation
                if "confusion_matrix" in comparison_result:
                    self._accumulate_confusion_matrix(comparison_result["confusion_matrix"])
                
                # Collect non-matches
                if "non_matches" in comparison_result:
                    for non_match in comparison_result["non_matches"]:
                        non_match_with_doc = non_match.copy()
                        non_match_with_doc["doc_id"] = doc_id
                        self.non_matches.append(non_match_with_doc)
                
                self.processed_count += 1
                
            except Exception as e:
                print(f"  ✗ Error evaluating {doc_id}: {e}")
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
