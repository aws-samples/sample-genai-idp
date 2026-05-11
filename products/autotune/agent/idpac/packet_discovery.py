# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""PacketSplittingDiscovery - Discover schemas from packet-splitting datasets.

Handles datasets where each input file contains multiple concatenated documents
of different classes. Extracts representative sections and runs standard
discovery on each to generate a multi-class IDP config.
"""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium

from idpac import IDPConfig
from idpac.discovery import Discovery


@dataclass
class SectionInfo:
    """Information about a section within a packet."""
    packet_name: str
    section_id: int
    page_indices: list[int]
    class_name: str


class PacketSplittingDiscovery:
    """Discover schemas from packet-splitting datasets.
    
    Example:
        discovery = PacketSplittingDiscovery('/path/to/docsplit-dataset')
        config = discovery.discover_and_create_config('output/config.yaml')
    """
    
    MULTIPAGE_EXTENSIONS = {'.pdf', '.tiff', '.tif'}
    
    def __init__(self, dataset_path: str, region: str = "us-east-1", profile: Optional[str] = None):
        self.dataset_path = Path(dataset_path)
        self.input_dir = self.dataset_path / "input"
        self.baseline_dir = self.dataset_path / "baseline"
        self.region = region
        self.profile = profile
        
        if not self.baseline_dir.exists():
            raise ValueError(f"baseline/ directory not found in {dataset_path}")
        if not self.input_dir.exists():
            raise ValueError(f"input/ directory not found in {dataset_path}")
        
        self._class_index: dict[str, list[SectionInfo]] = {}
        self._build_class_index()
    
    def _build_class_index(self) -> None:
        """Scan all ground truth and build index by class name."""
        for doc_dir in self.baseline_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            sections_dir = doc_dir / "sections"
            if not sections_dir.exists():
                continue
                
            for section_dir in sections_dir.iterdir():
                if not section_dir.is_dir() or not section_dir.name.isdigit():
                    continue
                result_file = section_dir / "result.json"
                if not result_file.exists():
                    continue
                    
                with open(result_file) as f:
                    data = json.load(f)
                
                class_name = data.get("document_class", {}).get("type")
                page_indices = data.get("split_document", {}).get("page_indices", [])
                
                if not class_name:
                    continue
                
                info = SectionInfo(
                    packet_name=doc_dir.name,
                    section_id=int(section_dir.name),
                    page_indices=page_indices,
                    class_name=class_name
                )
                
                if class_name not in self._class_index:
                    self._class_index[class_name] = []
                self._class_index[class_name].append(info)
    
    def get_classes_with_samples(self) -> dict[str, list[SectionInfo]]:
        """Return dict mapping class name to list of SectionInfo objects."""
        return self._class_index.copy()
    
    def extract_section_as_document(
        self, 
        packet_name: str, 
        page_indices: list[int],
        output_path: str
    ) -> str:
        """Extract specific pages from a packet PDF/TIFF into a new file."""
        input_path = self.input_dir / packet_name
        if not input_path.exists():
            raise ValueError(f"Input file not found: {input_path}")
        
        ext = input_path.suffix.lower()
        if ext not in self.MULTIPAGE_EXTENSIONS:
            raise ValueError(f"Unsupported format {ext}")
        
        src_doc = pdfium.PdfDocument(str(input_path))
        
        for idx in page_indices:
            if idx < 0 or idx >= len(src_doc):
                raise ValueError(f"Page index {idx} out of range (document has {len(src_doc)} pages)")
        
        dst_doc = pdfium.PdfDocument.new()
        dst_doc.import_pages(src_doc, page_indices)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'wb') as f:
            dst_doc.save(f)
        dst_doc.close()
        src_doc.close()
        
        return output_path
    
    def extract_section_ground_truth(
        self,
        packet_name: str,
        section_id: int,
        output_path: str
    ) -> str:
        """Extract and transform ground truth for a section to discovery format."""
        gt_path = self.baseline_dir / packet_name / "sections" / str(section_id) / "result.json"
        if not gt_path.exists():
            raise ValueError(f"Ground truth not found: {gt_path}")
        
        with open(gt_path) as f:
            packet_gt = json.load(f)
        
        # Transform to flat format expected by discovery
        discovery_gt = {
            "document_class": packet_gt.get("document_class", {}).get("type", "unknown")
        }
        discovery_gt.update(packet_gt.get("inference_result", {}))
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(discovery_gt, f, indent=2)
        
        return output_path
    
    def discover_all_classes(
        self,
        samples_per_class: int = 1,
        temp_dir: Optional[str] = None
    ) -> list[dict]:
        """Discover schemas for all classes in the dataset."""
        use_temp = temp_dir is None
        if use_temp:
            temp_dir = tempfile.mkdtemp(prefix="idpac_discovery_")
        
        try:
            discovery = Discovery(region=self.region, profile=self.profile)
            schemas = []
            
            for class_name, samples in self._class_index.items():
                selected = samples[:samples_per_class]
                
                for i, sample in enumerate(selected):
                    doc_path = os.path.join(temp_dir, f"{class_name}_{i}.pdf")
                    self.extract_section_as_document(
                        sample.packet_name,
                        sample.page_indices,
                        doc_path
                    )
                    
                    gt_path = os.path.join(temp_dir, f"{class_name}_{i}_gt.json")
                    self.extract_section_ground_truth(
                        sample.packet_name,
                        sample.section_id,
                        gt_path
                    )
                    
                    schema = discovery.discover(
                        document_path=doc_path,
                        ground_truth_path=gt_path
                    )
                    
                    if schema:
                        schemas.append(schema)
                        break
            
            return schemas
            
        finally:
            if use_temp:
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def discover_and_create_config(
        self,
        output_path: str,
        samples_per_class: int = 1
    ) -> IDPConfig:
        """Discover all classes and create a complete IDP config."""
        schemas = self.discover_all_classes(samples_per_class=samples_per_class)
        
        if not schemas:
            raise ValueError("No schemas discovered - check dataset structure")
        
        config = IDPConfig.from_defaults('pattern-2')
        config.data['classes'] = []
        for schema in schemas:
            config.add_class(schema)
        
        config.save(output_path)
        return config
