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

    Args:
        config_path: Path to config YAML file.
        config_version: Version name (e.g., 'v1', 'v2').
        description: Description of what changed in this version.

    Returns:
        JSON with status, stdout, stderr.
    """
    client = _get_client()
    result = client.upload_config(config_path, config_version, description)
    return json.dumps(result, indent=2)


@tool
def download_config(output_path: str, config_version: str) -> str:
    """Download a config version from the deployed stack.

    Args:
        output_path: Local file path to save the config.
        config_version: Version to download (e.g., 'v1', 'Production').

    Returns:
        JSON with status and output path.
    """
    client = _get_client()
    result = client.config_download(output_path, config_version)
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
def create_default_config(output_path: str, features: str = "min") -> str:
    """Generate a config template from system defaults.

    Args:
        output_path: Where to save the generated config.
        features: Feature set - 'min', 'core', or 'all'.

    Returns:
        JSON with status and output path.
    """
    import subprocess

    cmd = ["idp-cli", "config-create", "--features", features, "--output", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.dumps({
        "status": "success" if result.returncode == 0 else "failed",
        "output": output_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }, indent=2)


@tool
def validate_config(config_path: str) -> str:
    """Validate a config file for common issues that cause 0% accuracy.

    Checks for missing x-aws-idp-document-type, nullable types, assessment
    settings, and other schema problems.

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
    output_path: str,
    fixes: Optional[list[str]] = None,
) -> str:
    """Apply automatic fixes to common config schema issues.

    Available fixes: add_document_type, add_schema, add_type_object,
    fix_nullable_types, add_data_type, disable_assessment, disable_summarization.
    If fixes is None, applies all safe schema-only fixes.

    Args:
        config_path: Path to input config YAML file.
        output_path: Path to save the fixed config.
        fixes: List of specific fixes to apply, or None for all safe fixes.

    Returns:
        Path where fixed config was saved, plus validation of the result.
    """
    from idpac import IDPConfig

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
def run_evaluation(test_set_id: str, context: str, config_version: str) -> str:
    """Launch an evaluation run on a test set with a specific config version.

    Monitors until completion. Can take several minutes depending on dataset size.

    Args:
        test_set_id: Test set ID (e.g., 'cli-uploaded-test-set').
        context: Description of this run (e.g., 'v1 baseline run').
        config_version: Config version to evaluate (e.g., 'v1').

    Returns:
        JSON with batch_id, status, stdout, stderr.
    """
    client = _get_client()
    result = client.run_evaluation(test_set_id, context, config_version)
    return json.dumps(result, indent=2)


@tool
def get_evaluation_summary(batch_id: str, output_file: Optional[str] = None) -> str:
    """Get aggregated metrics for a completed evaluation run.

    Returns overall accuracy, per-file scores (top/bottom 3), classification
    metrics, and cost breakdown.

    Args:
        batch_id: Test run ID from run_evaluation.
        output_file: Optional path to save full JSON results.

    Returns:
        Formatted evaluation summary.
    """
    from idpac.evaluations import EvaluationResult

    client = _get_client()
    data = client.get_evaluation_summary(batch_id, output_file)
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
def compare_evaluations(batch_ids: list[str], output_file: Optional[str] = None) -> str:
    """Compare two or more evaluation runs side by side.

    Args:
        batch_ids: List of test run IDs to compare.
        output_file: Optional path to save JSON comparison.

    Returns:
        JSON comparison of metrics and config diffs.
    """
    client = _get_client()
    result = client.compare_evaluations(batch_ids, output_file)
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
def download_evaluation_results(batch_id: str, output_dir: str) -> str:
    """Download individual evaluation files for a completed run.

    Args:
        batch_id: Test run ID.
        output_dir: Local directory to save results.

    Returns:
        JSON with download status and file count.
    """
    client = _get_client()
    result = client.download_evaluation_results(batch_id, output_dir)
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
    client = _get_client()
    result = client.run_inference(
        documents_dir, config_version, file_pattern=file_pattern,
        number_of_files=number_of_files,
    )
    return json.dumps(result, indent=2)


@tool
def download_results(
    batch_id: str,
    output_dir: str,
    file_types: str = "sections",
) -> str:
    """Download processing results (extraction output, OCR pages, etc.).

    Args:
        batch_id: Batch ID from run_inference or run_evaluation.
        output_dir: Local directory to save results.
        file_types: What to download: 'sections', 'pages', 'summary', 'evaluation', or 'all'.

    Returns:
        JSON with status and output directory.
    """
    client = _get_client()
    result = client.download_results(batch_id, output_dir, file_types)
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
    output_path: Optional[str] = None,
) -> str:
    """Discover a document class schema from a sample document.

    Runs idp-cli discover in local mode (calls Bedrock directly, no stack needed).

    Args:
        document_path: Path to a sample document (PDF or image).
        ground_truth_path: Optional path to ground truth JSON for better schema.
        output_path: Optional path to save the discovered schema JSON.

    Returns:
        The discovered JSON schema as a string.
    """
    from idpac import Discovery

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    profile = os.environ.get("AWS_PROFILE") or None
    discovery = Discovery(region=region, profile=profile)

    if output_path:
        schema = discovery.discover_and_save(document_path, output_path, ground_truth_path)
    else:
        schema = discovery.discover(document_path, ground_truth_path)
    return json.dumps(schema, indent=2)


@tool
def run_multi_class_discovery(dataset_path: str, output_config_path: str) -> str:
    """Discover schemas for all classes in a dataset and create a config.

    For packet-splitting datasets, extracts representative sections from packets.
    For multi-class datasets, uses one sample per class.

    Args:
        dataset_path: Path to dataset with input/ and baseline/ dirs.
        output_config_path: Where to save the generated config YAML.

    Returns:
        Summary of discovered classes and config path.
    """
    from idpac import DatasetAnalyzer, Discovery, PacketSplittingDiscovery

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    profile = os.environ.get("AWS_PROFILE") or None
    analyzer = DatasetAnalyzer(dataset_path)

    if analyzer.is_packet_splitting():
        psd = PacketSplittingDiscovery(dataset_path, region=region, profile=profile)
        config = psd.discover_and_create_config(output_config_path)
        classes = config.get_class_names()
        return f"Packet-splitting discovery complete. Classes: {classes}. Config: {output_config_path}"

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
    return f"Discovery complete. Classes: {classes}. Config: {output_config_path}"


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
    phase: str,
    phase_detail: str = "",
    iteration: Optional[int] = None,
    best_accuracy: Optional[float] = None,
    best_config_version: Optional[str] = None,
    current_config_version: Optional[str] = None,
) -> str:
    """Update the optimization state in DynamoDB so the frontend can show progress.

    Call this before and after long operations (evaluations, inference, discovery)
    to keep the status display current.

    Args:
        phase: Current phase (e.g. "evaluating", "analyzing", "configuring", "discovering")
        phase_detail: Human-readable detail (e.g. "Running evaluation v3...")
        iteration: Current iteration number (if changed)
        best_accuracy: Best accuracy so far (if changed)
        best_config_version: Version name of best config (if changed)
        current_config_version: Version name of config being tested (if changed)
    """
    state = _get_optimization_state()
    if not state:
        return "No optimization state available (AUTOTUNE_SESSION_ID not set)"
    state.update_phase(phase, phase_detail)
    if iteration is not None and best_accuracy is not None and best_config_version is not None:
        state.update_metrics(
            iteration=iteration,
            best_accuracy=best_accuracy,
            best_config_version=best_config_version,
            current_config_version=current_config_version or "",
        )
    return f"State updated: phase={phase}, detail={phase_detail}"


# --- Collect all tools for the agent ---

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
    run_evaluation,
    get_evaluation_summary,
    compare_evaluations,
    list_evaluations,
    download_evaluation_results,
    run_inference,
    download_results,
    analyze_dataset,
    run_discovery,
    run_multi_class_discovery,
    update_optimization_state,
]
