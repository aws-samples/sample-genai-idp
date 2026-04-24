# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""DatasetAnalyzer - Analyze test datasets for IDP Accelerator optimization.

IDP Accelerator processes documents through two main stages:
1. CLASSIFICATION: Determine what type of document it is (e.g., invoice, receipt, form)
2. EXTRACTION: Extract structured data using a schema specific to that document type

Datasets can be:
- SINGLE-CLASS: All documents are the same type (e.g., all invoices). Classification
  is trivial/disabled, and optimization focuses only on extraction accuracy.
- MULTI-CLASS: Documents are different types mixed together. Both classification
  and extraction must be optimized.
- PACKET-SPLITTING: Each input file contains multiple concatenated documents.
  IDP must identify page boundaries, classify each section, then extract.

This module analyzes test datasets to:
- Detect whether a dataset is single-class, multi-class, or packet-splitting
- List all document classes present in the ground truth
- Provide sample documents per class for schema discovery
- Validate ground truth format

DATASET STRUCTURE:
    dataset/
    ├── input/                    # Source documents (PDF, PNG, etc.)
    │   ├── doc1.pdf
    │   └── doc2.png
    └── baseline/                 # Ground truth for each document
        ├── doc1.pdf/
        │   └── sections/1/result.json
        └── doc2.png/
            └── sections/1/result.json

PACKET-SPLITTING DATASET STRUCTURE:
    dataset/
    ├── input/
    │   └── packet_0001.pdf       # Contains multiple concatenated documents
    └── baseline/
        └── packet_0001.pdf/
            └── sections/
                ├── 1/result.json  # First document in packet
                ├── 2/result.json  # Second document in packet
                └── 3/result.json  # Third document in packet

GROUND TRUTH FORMAT (result.json):
    {
      "document_class": {"type": "INVOICE"},  # Required for multi-class
      "split_document": {"page_indices": [0, 1]},  # Required for packet-splitting
      "inference_result": { ... }              # Expected extraction output
    }
"""

import json
from pathlib import Path


class DatasetAnalyzer:
    """Analyze test datasets to determine class structure and provide samples.
    
    Use this class to:
    - Check if a dataset is single-class or multi-class before optimization
    - Get the list of document classes to configure in IDP
    - Get sample documents per class for schema discovery
    
    Example:
        analyzer = DatasetAnalyzer('/path/to/dataset')
        
        if analyzer.is_multi_class():
            print(f"Multi-class dataset with classes: {analyzer.get_class_names()}")
            # Need to enable classification and create schemas for each class
        else:
            print("Single-class dataset, classification not needed")
    """

    def __init__(self, dataset_path: str):
        """Load dataset from directory with input/ and baseline/ subdirs.
        
        Args:
            dataset_path: Path to dataset directory containing input/ and baseline/
        """
        self.dataset_path = Path(dataset_path)
        self.input_dir = self.dataset_path / "input"
        self.baseline_dir = self.dataset_path / "baseline"
        
        if not self.baseline_dir.exists():
            raise ValueError(f"baseline/ directory not found in {dataset_path}")
        
        self._ground_truth_cache: dict[str, dict] = {}
        self._packet_splitting: bool | None = None  # cached detection result
        self._load_ground_truth()

    def _load_ground_truth(self) -> None:
        """Load all ground truth files into cache.
        
        For packet-splitting datasets, loads all sections (sections/1/, sections/2/, etc.)
        Cache key format: "packet_0001.pdf/1" for section 1 of packet_0001.pdf
        """
        for doc_dir in self.baseline_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            sections_dir = doc_dir / "sections"
            if not sections_dir.exists():
                continue
                
            for section_dir in sections_dir.iterdir():
                if not section_dir.is_dir():
                    continue
                result_file = section_dir / "result.json"
                if result_file.exists():
                    with open(result_file) as f:
                        cache_key = f"{doc_dir.name}/{section_dir.name}"
                        self._ground_truth_cache[cache_key] = json.load(f)

    def is_packet_splitting(self) -> bool:
        """Return True if dataset has multiple sections per document.
        
        Checks if any document in baseline/ has sections/2/, sections/3/, etc.
        This distinguishes packet-splitting from multi-class datasets.
        """
        if self._packet_splitting is not None:
            return self._packet_splitting
            
        for doc_dir in self.baseline_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            sections_dir = doc_dir / "sections"
            if sections_dir.exists():
                section_nums = [d.name for d in sections_dir.iterdir() if d.is_dir() and d.name.isdigit()]
                if len(section_nums) > 1:
                    self._packet_splitting = True
                    return True
        self._packet_splitting = False
        return False

    def get_sections_per_document(self) -> dict[str, list[int]]:
        """Return dict mapping document name to list of section numbers.
        
        Example return:
            {
                "packet_0001.pdf": [1, 2, 3],
                "packet_0400.pdf": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            }
        """
        result = {}
        for doc_dir in self.baseline_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            sections_dir = doc_dir / "sections"
            if sections_dir.exists():
                section_nums = sorted([
                    int(d.name) for d in sections_dir.iterdir() 
                    if d.is_dir() and d.name.isdigit()
                ])
                result[doc_dir.name] = section_nums
        return result

    def get_page_indices_by_section(self, doc_name: str) -> dict[int, list[int]]:
        """Return page indices for each section of a document.
        
        Args:
            doc_name: Document filename, e.g., "packet_0001.pdf"
            
        Returns:
            Dict mapping section_id to page indices list.
            Example: {1: [0], 2: [1], 3: [2], 4: [3, 4, 5, 6]}
        """
        result = {}
        sections_dir = self.baseline_dir / doc_name / "sections"
        if not sections_dir.exists():
            return result
        for section_dir in sections_dir.iterdir():
            if not section_dir.is_dir() or not section_dir.name.isdigit():
                continue
            result_file = section_dir / "result.json"
            if result_file.exists():
                with open(result_file) as f:
                    data = json.load(f)
                    page_indices = data.get("split_document", {}).get("page_indices", [])
                    result[int(section_dir.name)] = page_indices
        return result

    def get_class_names(self) -> list[str]:
        """Return sorted list of unique class names from ground truth."""
        classes = set()
        for gt in self._ground_truth_cache.values():
            doc_class = gt.get("document_class", {}).get("type")
            if doc_class:
                classes.add(doc_class)
        return sorted(classes)

    def get_samples_by_class(self, n: int = 1) -> dict[str, list[str]]:
        """Get n sample document paths per class for discovery.
        
        Args:
            n: Number of samples per class
            
        Returns:
            Dict mapping class name to list of document paths
        """
        samples: dict[str, list[str]] = {}
        for cache_key, gt in self._ground_truth_cache.items():
            doc_class = gt.get("document_class", {}).get("type")
            if not doc_class:
                continue
            if doc_class not in samples:
                samples[doc_class] = []
            if len(samples[doc_class]) < n:
                # Extract doc_name from cache_key (format: "doc_name/section_num")
                doc_name = cache_key.rsplit("/", 1)[0]
                doc_path = self.input_dir / doc_name
                if doc_path.exists() and str(doc_path) not in samples[doc_class]:
                    samples[doc_class].append(str(doc_path))
        return samples

    def get_ground_truth_by_class(self, n: int = 1) -> dict[str, list[str]]:
        """Get n ground truth file paths per class.
        
        Args:
            n: Number of samples per class
            
        Returns:
            Dict mapping class name to list of ground truth paths
        """
        gt_paths: dict[str, list[str]] = {}
        for cache_key, gt in self._ground_truth_cache.items():
            doc_class = gt.get("document_class", {}).get("type")
            if not doc_class:
                continue
            if doc_class not in gt_paths:
                gt_paths[doc_class] = []
            if len(gt_paths[doc_class]) < n:
                # Extract doc_name and section from cache_key
                doc_name, section = cache_key.rsplit("/", 1)
                gt_path = self.baseline_dir / doc_name / "sections" / section / "result.json"
                if gt_path.exists():
                    gt_paths[doc_class].append(str(gt_path))
        return gt_paths

    def validate_ground_truth_format(self) -> list[str]:
        """Check all ground truth files have required fields.
        
        For packet-splitting datasets, also validates:
        - split_document.page_indices exists and is a list
        
        Returns:
            List of error messages (empty if all valid)
            
        Note: Currently allows overlapping page_indices between sections.
        TODO: May want to enforce non-overlapping in the future.
        """
        errors = []
        is_packet = self.is_packet_splitting()
        for cache_key, gt in self._ground_truth_cache.items():
            if "document_class" not in gt:
                errors.append(f"{cache_key}: missing 'document_class' field")
            elif "type" not in gt.get("document_class", {}):
                errors.append(f"{cache_key}: missing 'document_class.type' field")
            
            # Packet-splitting validation
            if is_packet:
                split_doc = gt.get("split_document", {})
                if "page_indices" not in split_doc:
                    errors.append(f"{cache_key}: missing 'split_document.page_indices'")
                elif not isinstance(split_doc["page_indices"], list):
                    errors.append(f"{cache_key}: 'split_document.page_indices' must be a list")
        return errors

    def is_multi_class(self) -> bool:
        """Return True if dataset has multiple document classes."""
        return len(self.get_class_names()) > 1

    def get_field_density(self, doc_class: str | None = None) -> dict[str, float]:
        """Compute population density for each leaf field in ground truth.

        Density = (number of documents where field is non-empty) / (total documents).
        Only considers top-level scalar fields in inference_result (not array items).

        Args:
            doc_class: If provided, only analyze documents of this class.
                       If None, analyze all documents.

        Returns:
            Dict mapping field name to density (0.0-1.0), sorted by density ascending.

        Example:
            analyzer = DatasetAnalyzer('/path/to/dataset')
            density = analyzer.get_field_density()
            sparse = {k: v for k, v in density.items() if v < 0.1}
            print(f"Sparse fields (<10% populated): {len(sparse)}")
        """
        field_counts: dict[str, int] = {}
        doc_count = 0

        for cache_key, gt in self._ground_truth_cache.items():
            if doc_class:
                gt_class = gt.get("document_class", {}).get("type")
                if gt_class != doc_class:
                    continue

            result = gt.get("inference_result", {})
            if not result:
                continue
            doc_count += 1

            for field_name, value in result.items():
                if isinstance(value, list):
                    # For array fields, just track whether the array is non-empty
                    is_populated = len(value) > 0
                else:
                    is_populated = value not in [None, "", []]
                field_counts.setdefault(field_name, 0)
                if is_populated:
                    field_counts[field_name] += 1

        if doc_count == 0:
            return {}

        density = {k: v / doc_count for k, v in field_counts.items()}
        return dict(sorted(density.items(), key=lambda x: x[1]))
