# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Strands tool wrappers for the idpac package.

Each tool wraps one or more idpac class methods, providing clear docstrings
for the LLM and structured error handling. The IDPACClient is initialized
lazily on first use from environment variables.
"""

import json
import os
from typing import Optional

from strands import tool

# Lazy-initialized singleton
_client = None
_deployer = None
_optimization_state = None

# Accumulated eval pipeline cost (seeded from DDB on resume, updated by get_evaluation_summary)
_eval_cost_usd: float = 0.0
_eval_cost_seen_batches: set = set()


def get_eval_cost_usd() -> float:
    """Return current accumulated eval cost."""
    return _eval_cost_usd


def get_eval_seen_batches() -> str:
    """Return comma-separated batch IDs already counted for eval cost."""
    return ",".join(sorted(_eval_cost_seen_batches))


def seed_eval_cost(value: float, seen_batches: str = "") -> None:
    """Seed the eval cost accumulator (e.g. from DDB on resume).
    
    Args:
        value: Total eval cost so far.
        seen_batches: Comma-separated batch IDs already counted.
    """
    global _eval_cost_usd
    _eval_cost_usd = value
    if seen_batches:
        _eval_cost_seen_batches.update(seen_batches.split(","))


def _auto_update_status(status: str, detail: str) -> None:
    """Best-effort DynamoDB status update from within tools."""
    try:
        state = _get_optimization_state()
        if state:
            state.set_status(status, detail)
    except Exception:
        pass  # Never let state updates break tool execution


def _list_dir_files(directory: str, max_files: int = 100) -> list[str]:
    """List files in a directory recursively (for enriching download tool responses)."""
    files = []
    for root, _, filenames in os.walk(directory):
        for name in sorted(filenames):
            files.append(os.path.join(root, name))
            if len(files) >= max_files:
                return files
    return files


def _get_client():
    """Get or create the IDPACClient singleton from env vars."""
    global _client
    if _client is None:
        from idpac import IDPACClient

        stack_name = os.environ.get("IDP_STACK_NAME")
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        profile = os.environ.get("AWS_PROFILE") or None
        if not stack_name:
            raise ValueError("IDP_STACK_NAME environment variable is required")
        _client = IDPACClient(stack_name=stack_name, region=region, profile=profile)
    return _client


def _get_deployer():
    """Get or create the IDPACDeployer singleton from env vars."""
    global _deployer
    if _deployer is None:
        from idpac import IDPACDeployer

        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        profile = os.environ.get("AWS_PROFILE") or None
        _deployer = IDPACDeployer(region=region, profile=profile)
    return _deployer


# --- Stack Operations ---


@tool
def deploy_stack(stack_name: str, admin_email: str) -> str:
    """Deploy a new IDP Accelerator stack.

    Args:
        stack_name: CloudFormation stack name (max 25 chars).
        admin_email: Admin email for the stack.

    Returns:
        JSON with stack_name, status, stdout, stderr.
    """
    deployer = _get_deployer()
    result = deployer.deploy_stack(stack_name, admin_email)
    return json.dumps(result, indent=2)


@tool
def upload_test_set(
    test_set_name: str,
    documents_dir: str,
    baselines_dir: str,
    file_pattern: str = "*.pdf",
) -> str:
    """Upload a test set (documents + ground truth baselines) to the IDP stack.

    Args:
        test_set_name: Name for the test set.
        documents_dir: Local directory containing test documents.
        baselines_dir: Local directory containing baseline ground truth files.
        file_pattern: Glob pattern for document files (default: *.pdf).

    Returns:
        JSON with test_set_name, test_set_id, status, file_count.
    """
    client = _get_client()
    deployer = _get_deployer()
    result = deployer.upload_test_set(
        client.stack_name, test_set_name, documents_dir, baselines_dir, file_pattern
    )
    return json.dumps(result, indent=2)


# --- Config Operations ---


@tool
def upload_config(config_path: str, config_version: str, description: str) -> str:
    """Upload a config file to the IDP stack as a named version.

    Writes directly to DynamoDB, completes in seconds.

    IMPORTANT: Config version names MUST include the test set name as a prefix,
    e.g. 'davids-test-set-v3', 'realkie-fcc-v7'. Short names like 'v3' are rejected.

    Args:
        config_path: Path to config YAML file.
        config_version: Version name (e.g., 'davids-test-set-v3', 'realkie-fcc-v7').
        description: Description of what changed in this version.

    Returns:
        JSON with status, stdout, stderr.
    """
    if len(config_version) < 5:
        return json.dumps({"error": f"Config version name '{config_version}' is too short. Include the test set name as prefix, e.g. 'davids-test-set-v3'."})
    _auto_update_status("configuring", f"Uploading config {config_version}")
    client = _get_client()
    result = client.upload_config(config_path, config_version, description)
    return json.dumps(result, indent=2)


@tool
def download_config(config_version: str) -> str:
    """Download a config version from the deployed stack.

    Downloads to a 'downloaded/' subdirectory to avoid overwriting local working
    configs. Use copy_config to copy a downloaded config into your working configs.

    Args:
        config_version: Version to download (e.g., 'v1', 'Production').

    Returns:
        JSON with status and path where config was saved.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_path = os.path.join(scratch, "configs", "downloaded", f"{config_version}.yaml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    client = _get_client()
    result = client.config_download(output_path, config_version)
    result["output_path"] = output_path
    return json.dumps(result, indent=2)


@tool
def list_configs() -> str:
    """List all configuration versions in the deployed stack.

    Returns:
        JSON with status and version table.
    """
    client = _get_client()
    result = client.config_list()
    return json.dumps(result, indent=2)


@tool
def create_default_config(features: str = "min") -> str:
    """Generate a config template from system defaults.

    Args:
        features: Feature set - 'min', 'core', or 'all'.

    Returns:
        JSON with status and path where config was saved.
    """
    import subprocess

    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_path = os.path.join(scratch, "configs", f"default-{features}.yaml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = ["idp-cli", "config-create", "--features", features, "--output", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.dumps({
        "status": "success" if result.returncode == 0 else "failed",
        "output_path": output_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }, indent=2)


@tool
def validate_config(config_path: str) -> str:
    """Validate a config file for common issues that cause 0% accuracy.

    Checks for:
    - Missing x-aws-idp-document-type on classes (most common cause of 0% accuracy —
      evaluation silently skips classes without this attribute)
    - Missing $schema declaration
    - Missing type: object on class schemas
    - Nullable types (type: ["string", "null"]) which break evaluation matching
    - Missing data_type annotations on leaf fields
    - Assessment + granular enabled with array fields (causes timeouts)

    Args:
        config_path: Path to config YAML file.

    Returns:
        Validation result with errors and warnings.
    """
    from idpac import IDPConfig

    config = IDPConfig(config_path)
    result = config.validate()
    return str(result)


@tool
def auto_fix_config(
    config_path: str,
    fixes: Optional[list[str]] = None,
) -> str:
    """Apply automatic fixes to common config schema issues.

    Available fixes (default = all safe schema-only fixes):
    - add_document_type: Copies $id to x-aws-idp-document-type (fixes 0% accuracy)
    - add_schema: Adds $schema declaration
    - add_type_object: Adds type: object to class schemas
    - fix_nullable_types: Replaces type: ["string", "null"] with type: "string"
    - add_data_type: Adds data_type annotation to leaf fields based on type
    - disable_assessment: Sets assessment.enabled: false (NOT in default set — opt-in)
    - disable_summarization: Sets summarization.enabled: false (NOT in default set — opt-in)

    Only adds missing fields, never modifies existing values.

    Args:
        config_path: Path to input config YAML file.
        fixes: List of specific fixes to apply, or None for all safe fixes.

    Returns:
        Path where fixed config was saved, plus validation of the result.
    """
    from idpac import IDPConfig

    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_path = os.path.join(scratch, "configs", "fixed-" + os.path.basename(config_path))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    config = IDPConfig(config_path)
    fixed = config.auto_fix(fixes)
    saved = fixed.save(output_path)
    validation = fixed.validate()
    return f"Saved to: {saved}\n\nValidation:\n{validation}"


@tool
def compare_configs(path1: str, path2: str) -> str:
    """Compare two config files and show differences.

    Args:
        path1: Path to first config file.
        path2: Path to second config file.

    Returns:
        List of differences between the two configs.
    """
    from idpac import IDPConfig

    c1 = IDPConfig(path1)
    c2 = IDPConfig(path2)
    diffs = IDPConfig._compare(c1, c2, path1, path2)
    if not diffs:
        return "No differences found."
    lines = [f"Found {len(diffs)} differences:\n"]
    for d in diffs:
        lines.append(f"{d['setting']}:")
        for name, val in d["values"].items():
            display = val if val and len(val) < 120 else (val[:117] + "..." if val else "None")
            lines.append(f"  {name}: {display}")
    return "\n".join(lines)


# --- Evaluation Operations ---


@tool
def run_evaluation(test_set_id: str, context: str, config_version: str, n_files: int = 1) -> str:
    """Launch an evaluation run on a test set with a specific config version.

    IMPORTANT: Defaults to processing only 1 file as a validation check. After
    confirming the config works (evaluation produces valid output), re-run with
    n_files=0 to process all files.

    Args:
        test_set_id: Test set ID (e.g., 'cli-uploaded-test-set').
        context: Description of this run (e.g., 'v1 baseline run').
        config_version: Config version to evaluate (e.g., 'v1').
        n_files: Number of files to process. Default 1 (validation run).
                 Set to 0 to process all files in the test set.

    Returns:
        JSON with batch_id, status, stdout, stderr.
    """
    # Block new evaluations during finalizing status
    state = _get_optimization_state()
    if state:
        current = state.get_state()
        if current.get("status") == "finalizing":
            return json.dumps({"error": "Cannot launch evaluations during finalizing. Write your summary and call update_optimization_state(status='complete')."})

    if n_files == 0:
        print(f"Running evaluation on all files with config '{config_version}'")
        # Full evaluation = one iteration. Auto-increment.
        if state:
            iteration = int(current.get("iteration", 0)) + 1
            state.update_metrics(
                iteration=iteration,
                best_accuracy=float(current.get("best_accuracy", 0)),
                best_config_version=current.get("best_config_version", ""),
                current_config_version=config_version,
                best_cost_per_page_usd=float(current.get("best_cost_per_page_usd", 0)),
            )
    else:
        print(f"Running evaluation with {n_files} file(s) with config '{config_version}'")
    _auto_update_status("evaluating", f"Running evaluation {config_version}")
    client = _get_client()
    result = client.run_evaluation(test_set_id, context, config_version, n_files=n_files)
    return json.dumps(result, indent=2)


@tool
def get_evaluation_summary(batch_id: str, save_json: bool = False) -> str:
    """Get aggregated metrics for a completed evaluation run.

    Returns overall accuracy, per-file scores (top/bottom 3), classification
    metrics, and cost breakdown.

    Args:
        batch_id: Test run ID from run_evaluation.
        save_json: If true, saves full JSON results to scratch directory.

    Returns:
        Formatted evaluation summary.
    """
    global _eval_cost_usd
    from idpac.evaluations import EvaluationResult

    output_file = None
    if save_json:
        scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
        output_file = os.path.join(scratch, "eval-summaries", f"{batch_id}.json")
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

    client = _get_client()
    data = client.get_evaluation_summary(batch_id, output_file)

    # Accumulate eval pipeline cost (deduplicated by batch_id)
    total = data.get("totalCost", 0)
    if total and batch_id not in _eval_cost_seen_batches:
        _eval_cost_seen_batches.add(batch_id)
        _eval_cost_usd += float(total)

    er = EvaluationResult(data)

    import io
    import sys

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    er.print_aggregated_summary()
    sys.stdout = old_stdout
    return buf.getvalue()


@tool
def compare_evaluations(batch_ids: list[str]) -> str:
    """Compare two or more evaluation runs side by side.

    Args:
        batch_ids: List of test run IDs to compare.

    Returns:
        JSON comparison of metrics and config diffs.
    """
    client = _get_client()
    result = client.compare_evaluations(batch_ids, None)
    return json.dumps(result, indent=2, default=str)


@tool
def list_evaluations(time_period_hours: int = 168) -> str:
    """List recent evaluation runs (default: last 7 days).

    Args:
        time_period_hours: How far back to look.

    Returns:
        JSON list of evaluation run summaries.
    """
    client = _get_client()
    result = client.list_evaluations(time_period_hours)
    return json.dumps(result, indent=2, default=str)


@tool
def check_evaluation_status(test_run_id: str) -> str:
    """Check the status of a single evaluation run by its ID.

    Status values:
    - RUNNING: Still processing files (non-terminal — the only state meaning "in progress")
    - COMPLETE: All files processed successfully (terminal)
    - PARTIAL_COMPLETE: Run finished but some files failed; check failedFiles (terminal)
    - FAILED: Entire run failed (terminal)
    - EVALUATING: Evaluation scoring in progress after processing (non-terminal)

    Args:
        test_run_id: The test run ID (e.g. 'RealKIE-FCC-Verified-20260429-174653').

    Returns:
        JSON with status, filesCount, completedFiles, failedFiles, progress.
    """
    client = _get_client()
    result = client.check_evaluation_status(test_run_id)
    return json.dumps(result, indent=2, default=str)


@tool
def download_evaluation_results(batch_id: str) -> str:
    """Download per-document evaluation accuracy files for a completed test run.

    Downloads the accuracy comparison files that score extraction output against
    ground truth baselines. Use this to see which documents/fields scored well or
    poorly. For the raw extraction output itself, use download_raw_processing_results instead.

    Files are saved to the scratch directory automatically.

    Args:
        batch_id: Test run ID.

    Returns:
        JSON with download status, file count, and output_dir where files were saved.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_dir = os.path.join(scratch, "eval-results", batch_id)
    os.makedirs(output_dir, exist_ok=True)
    client = _get_client()
    result = client.download_evaluation_results(batch_id, output_dir)
    result["output_dir"] = output_dir
    result["files"] = _list_dir_files(output_dir)
    return json.dumps(result, indent=2)


# --- Inference (No Ground Truth) ---


@tool
def run_inference(
    documents_dir: str,
    config_version: str,
    file_pattern: str = "*.pdf",
    number_of_files: Optional[int] = None,
) -> str:
    """Run inference on documents without ground truth.

    Processes documents through the full IDP pipeline (OCR → classification →
    extraction) without needing baselines or test studio.

    Args:
        documents_dir: Local directory containing documents.
        config_version: Config version to use (e.g., 'v1').
        file_pattern: Glob pattern for documents (default: *.pdf).
        number_of_files: Limit number of files (None = all).

    Returns:
        JSON with batch_id, status, stdout, stderr.
    """
    _auto_update_status("evaluating", f"Running inference {config_version}")
    client = _get_client()
    result = client.run_inference(
        documents_dir, config_version, file_pattern=file_pattern,
        number_of_files=number_of_files,
    )
    return json.dumps(result, indent=2)


@tool
def download_raw_processing_results(
    batch_id: str,
    file_types: str = "sections",
) -> str:
    """Download raw processing output files (extraction JSON, OCR pages, etc.).

    Downloads the actual output produced by the IDP pipeline — what the model
    extracted from each document. Use this to inspect extraction results directly.
    For accuracy scores comparing against ground truth, use download_evaluation_results instead.

    Files are saved to the scratch directory automatically.

    Args:
        batch_id: Batch ID from run_inference or run_evaluation.
        file_types: What to download: 'sections', 'pages', 'summary', 'evaluation', or 'all'.

    Returns:
        JSON with status and output_dir where files were saved.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_dir = os.path.join(scratch, "raw-results", batch_id)
    os.makedirs(output_dir, exist_ok=True)
    client = _get_client()
    result = client.download_results(batch_id, output_dir, file_types)
    result["output_dir"] = output_dir
    result["files"] = _list_dir_files(output_dir)
    return json.dumps(result, indent=2)


# --- Dataset Analysis ---


@tool
def analyze_dataset(dataset_path: str) -> str:
    """Analyze a test dataset to determine its structure and class composition.

    Detects whether the dataset is single-class, multi-class, or packet-splitting.
    Lists all document classes, sample counts, and validates ground truth format.

    Args:
        dataset_path: Path to dataset directory containing input/ and baseline/.

    Returns:
        Dataset analysis summary including mode, classes, and any validation errors.
    """
    _auto_update_status("analyzing", "Analyzing dataset structure")
    from idpac import DatasetAnalyzer

    analyzer = DatasetAnalyzer(dataset_path)
    lines = []

    # Mode detection
    if analyzer.is_packet_splitting():
        mode = "packet-splitting"
        sections = analyzer.get_sections_per_document()
        total_sections = sum(len(s) for s in sections.values())
        lines.append(f"Mode: {mode} ({len(sections)} packets, {total_sections} total sections)")
    elif analyzer.is_multi_class():
        mode = "multi-class"
        lines.append(f"Mode: {mode}")
    else:
        mode = "single-class"
        lines.append(f"Mode: {mode}")

    # Classes
    classes = analyzer.get_class_names()
    lines.append(f"Classes ({len(classes)}): {', '.join(classes)}")

    # Samples per class
    samples = analyzer.get_samples_by_class(n=3)
    for cls, paths in samples.items():
        lines.append(f"  {cls}: {len(paths)} sample(s)")

    # Validation
    errors = analyzer.validate_ground_truth_format()
    if errors:
        lines.append(f"\nValidation errors ({len(errors)}):")
        for e in errors[:10]:
            lines.append(f"  - {e}")
        if len(errors) > 10:
            lines.append(f"  ... and {len(errors) - 10} more")
    else:
        lines.append("\nGround truth format: valid")

    # Field density (for single/multi class)
    if not analyzer.is_packet_splitting():
        for cls in classes[:3]:
            density = analyzer.get_field_density(cls)
            sparse = {k: v for k, v in density.items() if v < 0.1}
            if sparse:
                lines.append(f"\nSparse fields (<10% populated) for {cls}: {list(sparse.keys())}")

    return "\n".join(lines)


# --- Discovery ---


@tool
def run_discovery(
    document_path: str,
    ground_truth_path: Optional[str] = None,
) -> str:
    """Discover a document class schema from a sample document.

    Runs idp-cli discover in local mode (calls Bedrock directly, no stack needed).
    Saves discovered schema to scratch directory.

    Args:
        document_path: Path to a sample document (PDF or image).
        ground_truth_path: Optional path to ground truth JSON for better schema.

    Returns:
        The discovered JSON schema as a string.
    """
    _auto_update_status("discovering", "Running schema discovery")
    from idpac import Discovery

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    profile = os.environ.get("AWS_PROFILE") or None
    discovery = Discovery(region=region, profile=profile)

    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_path = os.path.join(scratch, "discovery", os.path.basename(document_path) + ".schema.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    schema = discovery.discover_and_save(document_path, output_path, ground_truth_path)
    return json.dumps(schema, indent=2)


@tool
def run_multi_class_discovery(dataset_path: str) -> str:
    """Discover schemas for all classes in a dataset and create a config.

    For packet-splitting datasets, extracts representative sections from packets.
    For multi-class datasets, uses one sample per class.
    Config is saved to the scratch directory.

    Args:
        dataset_path: Path to dataset with input/ and baseline/ dirs.

    Returns:
        Summary of discovered classes and path where config was saved.
    """
    _auto_update_status("discovering", "Running multi-class discovery")
    from idpac import DatasetAnalyzer, Discovery, PacketSplittingDiscovery

    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_config_path = os.path.join(scratch, "configs", "discovered-config.yaml")
    os.makedirs(os.path.dirname(output_config_path), exist_ok=True)

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    profile = os.environ.get("AWS_PROFILE") or None
    analyzer = DatasetAnalyzer(dataset_path)

    if analyzer.is_packet_splitting():
        psd = PacketSplittingDiscovery(dataset_path, region=region, profile=profile)
        config = psd.discover_and_create_config(output_config_path)
        classes = config.get_class_names()
        return f"Packet-splitting discovery complete. Classes: {classes}. Config saved to: {output_config_path}"

    # Multi-class or single-class
    samples = analyzer.get_samples_by_class(n=1)
    gt = analyzer.get_ground_truth_by_class(n=1)
    discovery = Discovery(region=region, profile=profile)
    schemas = discovery.discover_multi_class(samples, gt)

    from idpac import IDPConfig

    config = IDPConfig.from_defaults("pattern-2")
    config.data["classes"] = []
    for s in schemas:
        config.add_class(s)
    config.save(output_config_path)
    classes = config.get_class_names()
    return f"Discovery complete. Classes: {classes}. Config saved to: {output_config_path}"


# --- Optimization State ---


def _get_optimization_state():
    """Get or create the OptimizationState singleton from env vars."""
    global _optimization_state
    if _optimization_state is None:
        try:
            from optimization_state import OptimizationState
        except ImportError:
            from state import OptimizationState

        session_id = os.environ.get("AUTOTUNE_SESSION_ID", "")
        if not session_id:
            return None
        _optimization_state = OptimizationState(session_id=session_id)
    return _optimization_state


@tool
def update_optimization_state(
    status: str,
    status_detail: str = "",
    best_accuracy: Optional[float] = None,
    best_config_version: Optional[str] = None,
    best_cost_per_page_usd: Optional[float] = None,
    current_config_version: Optional[str] = None,
) -> str:
    """Update the optimization state in DynamoDB so the frontend can show progress.

    Call this to report progress not covered by built-in tool status updates
    (e.g., during manual analysis or when making decisions).

    IMPORTANT: Setting status='complete' immediately terminates the optimization loop.
    No further tool calls will execute after this. Always finish ALL other work first
    (writing to OPTIMIZATION-LOG.md, copying configs, etc.) BEFORE setting status to complete.

    Note: Iteration count is managed automatically (incremented on each full
    evaluation run with n_files=0). You do not need to track iterations.

    Args:
        status: Current status (e.g. "evaluating", "analyzing", "configuring", "discovering", "complete")
        status_detail: Human-readable detail (e.g. "Analyzing field-level accuracy...")
        best_accuracy: Best accuracy so far (if changed)
        best_config_version: Version name of best config (if changed)
        best_cost_per_page_usd: Cost per page in USD of the best config (e.g. 0.09 means $0.09/page)
        current_config_version: Version name of config being tested (if changed)
    """
    state = _get_optimization_state()
    if not state:
        return "No optimization state available (AUTOTUNE_SESSION_ID not set)"
    state.set_status(status, status_detail)
    if best_accuracy is not None and best_config_version is not None:
        current = state.get_state()
        state.update_metrics(
            iteration=int(current.get("iteration", 0)),
            best_accuracy=best_accuracy,
            best_config_version=best_config_version,
            current_config_version=current_config_version or "",
            best_cost_per_page_usd=best_cost_per_page_usd or 0.0,
        )
    return f"State updated: status={status}, detail={status_detail}"


@tool
def download_single_document_results(batch_id: str, filename: str) -> str:
    """Download all result files for a single document from an evaluation run.

    Downloads extraction output, evaluation scores, OCR pages, and other
    artifacts for one specific document. Use this to investigate why a
    particular document scored poorly.

    Args:
        batch_id: Test run ID from run_evaluation.
        filename: Document filename (e.g., 'invoice-001.pdf' or 'abc123.png').

    Returns:
        JSON with download status, file count, and output_dir.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_dir = os.path.join(scratch, "single-doc-results", batch_id, filename)
    os.makedirs(output_dir, exist_ok=True)
    client = _get_client()
    result = client.download_single_document_results(batch_id, filename, output_dir)
    result["output_dir"] = output_dir
    result["files"] = _list_dir_files(output_dir)
    return json.dumps(result, indent=2)


@tool
def list_test_set_files(test_set_id: str, max_files_to_return: int = 50) -> str:
    """List document filenames in a test set.

    Use this to discover what files exist before downloading ground truth
    or input documents.

    Args:
        test_set_id: Test set ID (e.g., 'davids-test-dataset').
        max_files_to_return: Max filenames to return (default 50).

    Returns:
        JSON with list of filenames, count returned, and total count.
    """
    client = _get_client()
    files = client.list_test_set_files(test_set_id)
    total = len(files)
    files = files[:max_files_to_return]
    return json.dumps({"test_set_id": test_set_id, "files": files, "count": len(files), "total": total}, indent=2)


@tool
def download_test_set(test_set_id: str) -> str:
    """Download an entire test set (input documents + ground truth baselines) locally.

    Creates the standard dataset layout required by analyze_dataset and
    run_multi_class_discovery:
        {output_dir}/input/{filename}
        {output_dir}/baseline/{filename}/sections/{N}/result.json

    Args:
        test_set_id: Test set ID (e.g., 'davids-test-dataset').

    Returns:
        JSON with output directory path and file counts.
    """
    _auto_update_status("downloading", f"Downloading test set {test_set_id}")
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_dir = os.path.join(scratch, "datasets", test_set_id)
    os.makedirs(output_dir, exist_ok=True)
    client = _get_client()
    result = client.download_test_set(test_set_id, output_dir)
    return json.dumps(result, indent=2)


@tool
def download_ground_truth(test_set_id: str, filename: str) -> str:
    """Download ground truth baseline for a single document.

    Use this to compare what the model extracted vs what the correct answer is.
    For packet-splitting datasets with multiple sections per document, this
    downloads all sections.

    NOTE: This requires an exact filename. To discover filenames in a test set,
    first run an evaluation (even with n_files=1) and use download_evaluation_results
    to see the list of files. Or use run_discovery which processes the test set
    directly without needing filenames.

    Args:
        test_set_id: Test set ID (e.g., 'davids-test-dataset').
        filename: Exact document filename (e.g., 'invoice-001.pdf'). Wildcards not supported.

    Returns:
        JSON with output path(s) where ground truth was saved.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    # Try all-sections first (works for both packet and single-class)
    output_dir = os.path.join(scratch, "ground-truth", test_set_id, filename)
    os.makedirs(output_dir, exist_ok=True)
    client = _get_client()
    try:
        result = client.download_ground_truth_all_sections(test_set_id, filename, output_dir)
        result["output_dir"] = output_dir
        result["files"] = _list_dir_files(output_dir)
        return json.dumps(result, indent=2)
    except Exception:
        # Fall back to single-file download
        output_path = os.path.join(output_dir, "result.json")
        client.download_ground_truth(test_set_id, filename, output_path)
        return json.dumps({"output_path": output_path, "files": [output_path]}, indent=2)


@tool
def parse_evaluation_results(results_path: str, result_type: str = "aggregated") -> str:
    """Parse and summarize evaluation results from a downloaded JSON file.

    Provides structured analysis of evaluation results including per-document
    scores, classification metrics, and packet-splitting metrics.

    Args:
        results_path: Path to evaluation JSON file (from get_evaluation_summary
            with save_json=True, or from download_evaluation_results).
        result_type: 'aggregated' for test set summary, 'individual' for single doc.

    Returns:
        Formatted summary with accuracy breakdown, top/bottom documents,
        classification metrics (multi-class), and split metrics (packet-splitting).
    """
    from idpac.evaluations import EvaluationResult
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    if result_type == "aggregated":
        result = EvaluationResult.from_aggregated_file(results_path)
        with redirect_stdout(buf):
            result.print_aggregated_summary(top_bottom_n=5)
            if result.get_classification_accuracy() is not None:
                result.print_classification_summary()
            if result.get_split_metrics() is not None:
                result.print_split_summary()
    else:
        result = EvaluationResult.from_individual_file(results_path)
        with redirect_stdout(buf):
            result.print_individual_summary(show_matched=False, max_value_len=120)
    return buf.getvalue()


@tool
def config_edit(config_path: str, operations: list[dict]) -> str:
    """Read, modify, and save IDP config files using dot-notation paths.

    Supports get, set, save, add_class, get_class_names, and delete operations
    on config YAML files. Multiple operations execute in order on the same
    config instance.

    Operations:
    - {"op": "get", "field": "extraction.model"} — Read a value
    - {"op": "set", "field": "extraction.model", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"} — Set a value
    - {"op": "add_class", "schema": {"$id": "INVOICE", ...}} — Add a document class
    - {"op": "get_class_names"} — List configured class names
    - {"op": "save"} — Save to original path
    - {"op": "save", "output_path": "path/to/new.yaml"} — Save to new path

    Dot notation supports array indices: 'classes.0.$id', 'classes.1.properties'.

    LOCKED FIELDS: You cannot modify x-aws-idp-evaluation-method,
    x-aws-idp-evaluation-threshold, or x-aws-idp-evaluation-weight attributes.
    These control how accuracy is measured and are locked to prevent inflating
    scores without improving extraction quality.

    Args:
        config_path: Path to config YAML file.
        operations: List of operation dicts to execute in order.

    Returns:
        JSON with results for each operation.
    """
    from idpac import IDPConfig

    LOCKED_PREFIXES = ("x-aws-idp-evaluation-method", "x-aws-idp-evaluation-threshold", "x-aws-idp-evaluation-weight")

    config = IDPConfig(config_path)
    results = []
    for op in operations:
        action = op.get("op", "")
        try:
            if action == "set":
                field = op.get("field", "")
                # Reject writes to evaluation metric attributes
                if any(locked in field for locked in LOCKED_PREFIXES):
                    results.append({"op": "set", "field": field, "error": "LOCKED: Evaluation metric attributes (x-aws-idp-evaluation-method/threshold/weight) cannot be modified. These define how accuracy is measured and must remain unchanged."})
                    continue
                config.set(field, op["value"])
                results.append({"op": "set", "field": field, "status": "ok"})
            elif action == "get":
                val = config.get(op["field"])
                results.append({"op": "get", "field": op["field"], "value": val})
            elif action == "save":
                path = op.get("output_path")
                saved = config.save(path)
                results.append({"op": "save", "path": saved})
            elif action == "add_class":
                # Check if the schema contains locked evaluation attributes
                schema = op.get("schema", {})
                schema_str = json.dumps(schema)
                if any(locked in schema_str for locked in LOCKED_PREFIXES):
                    results.append({"op": "add_class", "error": "LOCKED: Cannot add class schema containing x-aws-idp-evaluation-* attributes. Remove evaluation attributes from the schema and retry."})
                    continue
                config.add_class(schema)
                results.append({"op": "add_class", "status": "ok"})
            elif action == "get_class_names":
                results.append({"op": "get_class_names", "classes": config.get_class_names()})
            else:
                results.append({"op": action, "error": f"Unknown operation: {action}"})
        except Exception as e:
            results.append({"op": action, "error": str(e)})
    return json.dumps(results, indent=2, default=str)


@tool
def download_input_document(batch_id: str, filename: str) -> str:
    """Download a raw input document (PDF, PNG, etc.) from the IDP input bucket.

    Use this to visually inspect a source document — e.g., to understand why
    extraction failed, verify ground truth, or check document quality.

    IMPORTANT: Do NOT use file_read on image files — it does not support images
    and will crash the run. Use the image_reader tool instead for PNG/JPEG/etc.

    Args:
        batch_id: Test run ID (e.g., 'RealKIE-FCC-Verified-20260429-174653').
        filename: Document filename (e.g., 'invoice-001.pdf').

    Returns:
        JSON with the local file path and which tool to use for viewing.
    """
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    output_path = os.path.join(scratch, "input-documents", batch_id, filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    client = _get_client()
    document_id = f"{batch_id}/{filename}"
    client.download_input_document(document_id, output_path)

    ext = os.path.splitext(filename)[1].lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".tif", ".bmp"}
    viewer = "image_reader" if ext in image_exts else "file_read"

    # Resize large images to stay under Bedrock's 5MB inline limit
    if ext in image_exts and os.path.getsize(output_path) > 4 * 1024 * 1024:
        try:
            from PIL import Image
            img = Image.open(output_path)
            # Halve dimensions until under 4MB
            while os.path.getsize(output_path) > 4 * 1024 * 1024:
                img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
                save_fmt = "JPEG" if ext in {".jpg", ".jpeg"} else "PNG"
                img.save(output_path, format=save_fmt)
        except Exception as e:
            return json.dumps({
                "path": output_path,
                "warning": f"Image is too large for inline viewing ({os.path.getsize(output_path)} bytes) and resize failed: {e}. Inspect OCR output or ground truth instead.",
            })

    return json.dumps({
        "path": output_path,
        "view_with": viewer,
        "note": f"Use the {viewer} tool to view this file. Do NOT use file_read on images.",
    })


# --- Collect all tools for the agent ---

@tool
def list_files(directory: str = ".", max_depth: int = 2) -> str:
    """List files and directories at a given path.

    Use this to explore downloaded results, configs, or scratch directories.
    Returns a tree-like listing with file sizes.

    Args:
        directory: Path to list. Defaults to current working directory.
        max_depth: Maximum recursion depth (0 = just the directory itself, 1 = immediate children, 2 = one level of subdirs). Max 4.

    Returns:
        JSON with the file listing.
    """
    max_depth = min(max_depth, 4)
    if not os.path.exists(directory):
        return json.dumps({"error": f"Path does not exist: {directory}"})

    entries = []
    base_depth = directory.rstrip("/").count("/")

    for root, dirs, files in os.walk(directory):
        current_depth = root.rstrip("/").count("/") - base_depth
        if current_depth >= max_depth:
            dirs.clear()
            continue
        for name in sorted(dirs):
            entries.append({"path": os.path.join(root, name), "type": "dir"})
        for name in sorted(files):
            fpath = os.path.join(root, name)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = -1
            entries.append({"path": fpath, "type": "file", "size_bytes": size})

    return json.dumps({"directory": directory, "count": len(entries), "entries": entries[:500]}, indent=2)


@tool
def copy_config(source_name: str, dest_name: str) -> str:
    """Copy a config YAML file to a new name within the scratch configs directory.

    Use this to create a new config version from an existing one before editing.
    Both source and dest are relative names (e.g., 'v1.yaml', 'v2.yaml') — they
    are resolved within the scratch configs directory automatically.

    Args:
        source_name: Source config filename (e.g., 'v1.yaml').
        dest_name: Destination config filename (e.g., 'v2.yaml').

    Returns:
        JSON with the full path of the new copy.
    """
    import shutil
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    configs_dir = os.path.join(scratch, "configs")
    os.makedirs(configs_dir, exist_ok=True)

    src = os.path.join(configs_dir, source_name)
    dst = os.path.join(configs_dir, dest_name)

    if not os.path.exists(src):
        # Also check scratch root (download_config puts files there)
        alt_src = os.path.join(scratch, source_name)
        if os.path.exists(alt_src):
            src = alt_src
        else:
            return json.dumps({"error": f"Source not found: {src} (also checked {alt_src})"})

    shutil.copy2(src, dst)
    return json.dumps({"status": "ok", "source": src, "dest": dst})


@tool
def wait_seconds(seconds: int) -> str:
    """Wait for a specified number of seconds.

    Use this when waiting for evaluation runs to complete. Check status
    with check_evaluation_status after waiting.

    Args:
        seconds: Number of seconds to wait. Maximum 300 (5 minutes).

    Returns:
        JSON confirming the wait completed.
    """
    import time as _time
    seconds = min(max(seconds, 1), 300)
    _time.sleep(seconds)
    return json.dumps({"status": "ok", "waited_seconds": seconds})


@tool
def execute_python_analysis(code: str) -> str:
    """Execute Python code for data analysis in a sandboxed environment.

    Use this for:
    - Parsing and aggregating JSON evaluation results
    - Computing confusion matrices or accuracy breakdowns
    - Statistical analysis of extraction quality
    - Any data transformation or calculation

    The sandbox has access to standard Python libraries (json, collections,
    statistics, re, etc.) but NO filesystem access and NO AWS credentials.
    Pass data inline in the code string.

    Args:
        code: Python code to execute. Use print() for output.

    Returns:
        JSON with execution results (stdout/stderr).
    """
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    try:
        from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
        client = CodeInterpreter(region)
        client.start()
        try:
            response = client.invoke(
                "executeCode",
                {"code": code, "language": "python", "clearContext": False},
            )
            results = []
            for event in response.get("stream", []):
                if "result" in event:
                    results.append(event["result"])
            return json.dumps(results, indent=2) if results else json.dumps({"output": "No results returned"})
        finally:
            client.stop()
    except ImportError:
        # Fallback: run in-process with restricted builtins (local dev only)
        import io
        import contextlib
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exec(code, {"__builtins__": __builtins__})  # noqa: S102
            return json.dumps({"output": stdout.getvalue()})
        except Exception as e:
            return json.dumps({"error": str(e), "partial_output": stdout.getvalue()})


@tool
def write_optimization_log(operation: str, content: str = "", old_str: str = "", new_str: str = "") -> str:
    """Write to the OPTIMIZATION-LOG.md file in the session workspace.

    This is the ONLY way to write to the optimization log. Supports three operations:
    - create: Overwrite the entire file with new content
    - append: Append text to the end of the file (a timestamp line is prepended automatically)
    - str_replace: Find and replace a specific string in the file

    A timestamp is automatically added on each append operation.

    Args:
        operation: One of 'create', 'append', or 'str_replace'.
        content: Text content for 'create' or 'append' operations.
        old_str: String to find (for 'str_replace' only). Must match exactly.
        new_str: Replacement string (for 'str_replace' only).

    Returns:
        JSON with status and file path.
    """
    from datetime import datetime, timezone

    workspace = os.environ["AUTOTUNE_WORKSPACE_DIR"]
    log_path = os.path.join(workspace, "OPTIMIZATION-LOG.md")

    try:
        if operation == "create":
            with open(log_path, "w") as f:
                f.write(content)
        elif operation == "append":
            timestamp = datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M:%S UTC]")
            with open(log_path, "a") as f:
                f.write(f"\n\n{timestamp}\n{content}")
        elif operation == "str_replace":
            if not os.path.exists(log_path):
                return json.dumps({"error": "OPTIMIZATION-LOG.md does not exist. Use 'create' first."})
            with open(log_path, "r") as f:
                text = f.read()
            if old_str not in text:
                return json.dumps({"error": f"old_str not found in OPTIMIZATION-LOG.md. First 200 chars of file: {text[:200]}"})
            if text.count(old_str) > 1:
                return json.dumps({"error": "old_str matches multiple locations. Provide more context to make it unique."})
            text = text.replace(old_str, new_str, 1)
            with open(log_path, "w") as f:
                f.write(text)
        else:
            return json.dumps({"error": f"Unknown operation: {operation}. Use 'create', 'append', or 'str_replace'."})
        return json.dumps({"status": "ok", "path": log_path})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def list_files(directory: str = ".", max_depth: int = 2) -> str:
    """List files and directories at a given path.

    Use this to explore downloaded results, configs, or scratch directories.
    Returns a listing with file sizes.

    Args:
        directory: Path to list. Defaults to current working directory.
        max_depth: Maximum recursion depth (1 = immediate children, 2 = one level of subdirs). Max 4.

    Returns:
        JSON with the file listing.
    """
    max_depth = min(max(max_depth, 1), 4)
    if not os.path.exists(directory):
        return json.dumps({"error": f"Path does not exist: {directory}"})

    entries = []
    base_depth = directory.rstrip("/").count("/")

    for root, dirs, files in os.walk(directory):
        current_depth = root.rstrip("/").count("/") - base_depth
        if current_depth >= max_depth:
            dirs.clear()
            continue
        for name in sorted(dirs):
            entries.append({"path": os.path.join(root, name), "type": "dir"})
        for name in sorted(files):
            fpath = os.path.join(root, name)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = -1
            entries.append({"path": fpath, "type": "file", "size_bytes": size})

    return json.dumps({"directory": directory, "count": len(entries), "entries": entries[:500]}, indent=2)


@tool
def copy_config(source_name: str, dest_name: str) -> str:
    """Copy a config YAML file to a new name within the scratch configs directory.

    Use this to create a new config version from an existing one before editing.
    Both source and dest are relative names (e.g., 'v1.yaml', 'v2.yaml') — they
    are resolved within the scratch configs directory automatically.

    Args:
        source_name: Source config filename (e.g., 'v1.yaml').
        dest_name: Destination config filename (e.g., 'v2.yaml').

    Returns:
        JSON with the full path of the new copy.
    """
    import shutil
    scratch = os.environ["AUTOTUNE_SCRATCH_DIR"]
    configs_dir = os.path.join(scratch, "configs")
    os.makedirs(configs_dir, exist_ok=True)

    src = os.path.join(configs_dir, source_name)
    dst = os.path.join(configs_dir, dest_name)

    if not os.path.exists(src):
        # Also check scratch root (download_config puts files there)
        alt_src = os.path.join(scratch, source_name)
        if os.path.exists(alt_src):
            src = alt_src
        else:
            return json.dumps({"error": f"Source not found: {src} (also checked {alt_src})"})

    shutil.copy2(src, dst)
    return json.dumps({"status": "ok", "source": src, "dest": dst})


@tool
def wait_seconds(seconds: int) -> str:
    """Wait for a specified number of seconds.

    Use this when waiting for evaluation runs to complete. Check status
    with check_evaluation_status after waiting.

    Args:
        seconds: Number of seconds to wait. Maximum 300 (5 minutes).

    Returns:
        JSON confirming the wait completed.
    """
    import time as _time
    seconds = min(max(seconds, 1), 300)
    _time.sleep(seconds)
    return json.dumps({"status": "ok", "waited_seconds": seconds})


ALL_TOOLS = [
    deploy_stack,
    upload_test_set,
    upload_config,
    download_config,
    list_configs,
    create_default_config,
    validate_config,
    auto_fix_config,
    compare_configs,
    config_edit,
    run_evaluation,
    get_evaluation_summary,
    compare_evaluations,
    list_evaluations,
    check_evaluation_status,
    download_evaluation_results,
    download_single_document_results,
    download_ground_truth,
    download_input_document,
    list_test_set_files,
    download_test_set,
    parse_evaluation_results,
    run_inference,
    download_raw_processing_results,
    analyze_dataset,
    run_discovery,
    run_multi_class_discovery,
    update_optimization_state,
    write_optimization_log,
    list_files,
    copy_config,
    wait_seconds,
]
