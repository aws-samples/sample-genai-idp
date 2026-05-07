# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Discovery - Document class schema discovery via idp-cli.

Thin wrapper around `idp-cli discover` (local mode) that replaces the former
StandaloneDiscovery stopgap. Uses the same subprocess pattern as IDPACClient.

Local mode only (no --stack-name): Discovery runs locally against Bedrock with
no deployed stack required. This is intentional — a common IDPAC workflow is to
kick off stack deployment async, then do data analysis and schema discovery
locally in parallel while the stack is still deploying.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class Discovery:
    """Discover document class schemas from sample documents using idp-cli.

    Runs `idp-cli discover` in local mode (no stack required). Calls Bedrock
    directly using system default prompts and model settings.

    Args:
        region: AWS region for Bedrock calls.
        profile: AWS profile name (passed as `idp-cli --profile`).
        model_id: Deprecated, ignored. Kept for backward compat.
        temperature: Deprecated, ignored. Kept for backward compat.
        top_p: Deprecated, ignored. Kept for backward compat.
        max_tokens: Deprecated, ignored. Kept for backward compat.
        verbose: If True, log subprocess commands.
    """

    def __init__(
        self,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        model_id: str = "us.amazon.nova-pro-v1:0",
        temperature: float = 1.0,
        top_p: float = 0.1,
        max_tokens: int = 10000,
        verbose: bool = False,
    ):
        self.region = region
        self.profile = profile
        self.verbose = verbose

        # Warn if caller passes non-default model params (they're ignored now)
        if model_id != "us.amazon.nova-pro-v1:0" or temperature != 1.0 or top_p != 0.1 or max_tokens != 10000:
            logger.warning(
                "model_id/temperature/top_p/max_tokens are ignored — "
                "idp-cli discover uses system default settings"
            )

    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run idp-cli discover with common options."""
        cmd = ["idp-cli"]
        if self.profile:
            cmd += ["--profile", self.profile]
        cmd += ["discover"] + args
        if self.region:
            cmd += ["--region", self.region]
        if self.verbose:
            logger.info(f"Running: {' '.join(cmd)}")
        env = None
        if self.region:
            env = {**os.environ, "AWS_DEFAULT_REGION": self.region}
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def discover(
        self,
        document_path: str,
        ground_truth_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discover document class schema from a local document.

        Args:
            document_path: Path to document (PDF or image).
            ground_truth_path: Optional path to ground truth JSON file.

        Returns:
            Generated JSON Schema dict for the document class.

        Raises:
            FileNotFoundError: If document or ground truth file doesn't exist.
            RuntimeError: If idp-cli discover fails.
        """
        doc = Path(document_path)
        if not doc.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        args = ["-d", str(doc), "-o", tmp_path]
        gt_symlink = None
        if ground_truth_path:
            gt = Path(ground_truth_path)
            if not gt.exists():
                raise FileNotFoundError(f"Ground truth not found: {ground_truth_path}")
            # idp-cli matches GT to documents by filename stem. The GT file is
            # typically "result.json" which won't match. Symlink it with the
            # document's stem so idp-cli picks it up.
            gt_symlink = Path(tempfile.gettempdir()) / f"{doc.stem}.json"
            gt_symlink.unlink(missing_ok=True)
            gt_symlink.symlink_to(gt.resolve())
            args += ["-g", str(gt_symlink)]

        result = self._run_cli(args)
        if gt_symlink:
            gt_symlink.unlink(missing_ok=True)
        if result.returncode != 0:
            Path(tmp_path).unlink(missing_ok=True)
            raise RuntimeError(
                f"idp-cli discover failed (exit {result.returncode}): {result.stderr or result.stdout}"
            )
        if "did not match any document" in (result.stdout or ""):
            Path(tmp_path).unlink(missing_ok=True)
            raise RuntimeError(
                f"idp-cli discover: ground truth was not matched to document. stdout: {result.stdout}"
            )

        schema = json.loads(Path(tmp_path).read_text())
        Path(tmp_path).unlink(missing_ok=True)
        return schema

    def discover_and_save(
        self,
        document_path: str,
        output_path: str,
        ground_truth_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discover schema and save to local JSON file."""
        schema = self.discover(document_path, ground_truth_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(schema, indent=2))
        return schema

    def discover_multi_class(
        self,
        samples_by_class: Dict[str, list[str]],
        ground_truth_by_class: Optional[Dict[str, list[str]]] = None,
    ) -> list[Dict[str, Any]]:
        """Discover schemas for multiple document classes.

        Args:
            samples_by_class: Map of class name to list of sample document paths.
            ground_truth_by_class: Optional map of class name to ground truth paths.

        Returns:
            List of JSON schemas, one per class.
        """
        schemas = []
        for class_name, doc_paths in samples_by_class.items():
            if not doc_paths:
                logger.warning(f"No samples for class {class_name}, skipping")
                continue

            doc_path = doc_paths[0]
            gt_path = None
            if ground_truth_by_class and class_name in ground_truth_by_class:
                gt_paths = ground_truth_by_class[class_name]
                if gt_paths:
                    gt_path = gt_paths[0]

            logger.info(f"Discovering schema for class: {class_name}")
            schema = self.discover(doc_path, gt_path)

            schema["$id"] = class_name
            schema["x-aws-idp-document-type"] = class_name
            schemas.append(schema)

        return schemas
