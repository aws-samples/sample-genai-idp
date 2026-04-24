# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Evaluation result parsing for IDP Accelerator."""

import json
from pathlib import Path
from typing import Any, Dict, Union


def _round_floats(obj: Any, sig_figs: int = 4) -> Any:
    """Recursively round floats to significant digits."""
    if isinstance(obj, float):
        return float(f'{obj:.{sig_figs}g}')
    elif isinstance(obj, dict):
        return {k: _round_floats(v, sig_figs) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_round_floats(item, sig_figs) for item in obj]
    return obj


class EvaluationResult:
    """Parser for IDP evaluation results."""

    EXCLUDE_KEYS = {'costBreakdown', 'config'}

    def __init__(self, data: Dict[str, Any]):
        self.data = data

    @classmethod
    def from_aggregated_file(cls, path: Union[str, Path]) -> 'EvaluationResult':
        """Load aggregated evaluation summary from JSON file."""
        with open(path) as f:
            return cls(json.load(f))

    @classmethod
    def from_individual_file(cls, path: Union[str, Path]) -> 'EvaluationResult':
        """Load individual file evaluation (results.json) from JSON file."""
        with open(path) as f:
            return cls(json.load(f))

    def print_aggregated_summary(self, top_bottom_n: int = 3) -> None:
        """Print minimal summary of aggregated test set results.
        
        Args:
            top_bottom_n: Show only top N and bottom N files from weightedOverallScores.
        
        Excludes costBreakdown and config, rounds floats to 4 significant digits.
        For individual file results, use print_individual_summary() (not yet implemented).
        """
        filtered = {k: v for k, v in self.data.items() if k not in self.EXCLUDE_KEYS}
        
        # Filter weightedOverallScores to top/bottom N
        if 'weightedOverallScores' in filtered and filtered['weightedOverallScores']:
            scores = filtered['weightedOverallScores']
            sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            top_n = dict(sorted_items[:top_bottom_n])
            bottom_n = dict(sorted_items[-top_bottom_n:])
            filtered['weightedOverallScores'] = {
                f'top_{top_bottom_n}': top_n,
                f'bottom_{top_bottom_n}': bottom_n,
            }
        
        rounded = _round_floats(filtered)
        self._print_recursive(rounded)

    def print_individual_summary(self, show_matched: bool = False, max_value_len: int = 80) -> None:
        """Print summary of individual file evaluation results.
        
        Args:
            show_matched: If True, show all attributes. If False, only show mismatched.
            max_value_len: Truncate expected/actual values longer than this.
        """
        d = self.data
        print(f"document_id: {d.get('document_id')}")
        metrics = _round_floats(d.get('overall_metrics', {}))
        print(f"overall: accuracy={metrics.get('accuracy')} precision={metrics.get('precision')} recall={metrics.get('recall')} f1={metrics.get('f1_score')}")
        
        for section in d.get('section_results', []):
            print(f"\nsection {section.get('section_id')} ({section.get('document_class')}):")
            for attr in section.get('attributes', []):
                if show_matched or not attr.get('matched'):
                    status = '✓' if attr.get('matched') else '✗'
                    exp = repr(attr.get('expected'))
                    act = repr(attr.get('actual'))
                    if len(exp) > max_value_len:
                        exp = exp[:max_value_len] + '...'
                    if len(act) > max_value_len:
                        act = act[:max_value_len] + '...'
                    print(f"  {status} {attr.get('name')}: expected={exp} actual={act} score={_round_floats(attr.get('score'))}")

    # --- Multi-Class Classification Metrics ---

    def get_classification_accuracy(self) -> float | None:
        """Extract classification accuracy from splitClassificationMetrics.
        
        Returns:
            Classification accuracy (0.0-1.0) or None if not available
        """
        metrics = self.data.get('splitClassificationMetrics', {})
        return metrics.get('accuracy')

    def get_per_class_accuracy(self) -> Dict[str, float]:
        """Return extraction accuracy breakdown by document class.
        
        Returns:
            Dict mapping class name to accuracy (0.0-1.0)
        """
        return self.data.get('accuracyBreakdown', {})

    def print_classification_summary(self) -> None:
        """Print classification metrics summary for multi-class evaluations."""
        metrics = self.data.get('splitClassificationMetrics', {})
        if not metrics:
            print("No classification metrics available (single-class dataset?)")
            return
        
        print("Classification Metrics:")
        print(f"  accuracy: {_round_floats(metrics.get('accuracy'))}")
        print(f"  precision: {_round_floats(metrics.get('precision'))}")
        print(f"  recall: {_round_floats(metrics.get('recall'))}")
        print(f"  f1_score: {_round_floats(metrics.get('f1_score'))}")
        
        # Per-class extraction accuracy
        breakdown = self.get_per_class_accuracy()
        if breakdown:
            print("\nPer-Class Extraction Accuracy:")
            for cls_name, accuracy in sorted(breakdown.items()):
                print(f"  {cls_name}: {_round_floats(accuracy)}")

    # --- Packet Splitting Metrics ---

    def get_split_metrics(self) -> dict | None:
        """Extract packet splitting metrics from evaluation results.
        
        Reads from the 'splitClassificationMetrics' field in the evaluation
        summary returned by IDP's get_evaluation_summary() API.
        
        Returns:
            Dict with split metrics, or None if not a packet-splitting evaluation.
            Example:
            {
                "page_level_accuracy": 0.85,
                "split_accuracy_without_order": 0.75,
                "split_accuracy_with_order": 0.60
            }
        """
        metrics = self.data.get('splitClassificationMetrics', {})
        if not metrics:
            return None
        
        # Check if packet-splitting metrics exist (handle both snake_case and camelCase)
        if 'page_level_accuracy' not in metrics and 'pageLevelAccuracy' not in metrics:
            return None
            
        return {
            "page_level_accuracy": metrics.get('page_level_accuracy') or metrics.get('pageLevelAccuracy'),
            "split_accuracy_without_order": metrics.get('split_accuracy_without_order') or metrics.get('splitAccuracyWithoutOrder'),
            "split_accuracy_with_order": metrics.get('split_accuracy_with_order') or metrics.get('splitAccuracyWithOrder'),
        }

    def print_split_summary(self) -> None:
        """Print packet splitting metrics summary.
        
        Output format:
            Packet Splitting Metrics:
              Page Level Accuracy: 85.0%
              Split Accuracy (without order): 75.0%
              Split Accuracy (with order): 60.0%
        """
        metrics = self.get_split_metrics()
        if not metrics:
            print("No packet splitting metrics available (not a packet-splitting dataset?)")
            return
        
        print("Packet Splitting Metrics:")
        
        page_acc = metrics.get('page_level_accuracy')
        if page_acc is not None:
            print(f"  Page Level Accuracy: {page_acc * 100:.1f}%")
        
        split_no_order = metrics.get('split_accuracy_without_order')
        if split_no_order is not None:
            print(f"  Split Accuracy (without order): {split_no_order * 100:.1f}%")
        
        split_with_order = metrics.get('split_accuracy_with_order')
        if split_with_order is not None:
            print(f"  Split Accuracy (with order): {split_with_order * 100:.1f}%")

    def _print_recursive(self, obj: Any, indent: int = 0) -> None:
        """Recursively print key-value pairs."""
        prefix = '  ' * indent
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    print(f'{prefix}{k}:')
                    self._print_recursive(v, indent + 1)
                else:
                    print(f'{prefix}{k}: {v}')
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    print(f'{prefix}[{i}]:')
                    self._print_recursive(item, indent + 1)
                else:
                    print(f'{prefix}- {item}')
