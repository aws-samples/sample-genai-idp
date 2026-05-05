# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Code interpreter tools for AutoTune agent.

Provides sandboxed Python execution via AgentCore CodeInterpreter.
No filesystem access to the host, no AWS credentials — safe for arbitrary
agent-generated code. The agent can load local files into the sandbox
before execution via the `files` parameter.
"""

import json
import logging
import os

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
from strands import tool

logger = logging.getLogger(__name__)

_code_client = None


def _get_code_interpreter_client():
    """Get or create the singleton code interpreter client."""
    global _code_client
    if _code_client is None:
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        _code_client = CodeInterpreter(region)
        _code_client.start()
        logger.info(f"Started code interpreter client in region {region}")
    return _code_client


def _invoke_code_interpreter_tool(tool_name: str, arguments: dict) -> dict:
    """Invoke a code interpreter tool and return the result."""
    client = _get_code_interpreter_client()
    response = client.invoke(tool_name, arguments)
    for event in response["stream"]:
        return json.loads(json.dumps(event["result"], indent=2))
    return {}


def _collect_files(paths: list[str], max_total_bytes: int = 10 * 1024 * 1024) -> list[dict]:
    """Collect files from local paths into writeFiles format.

    Files are written to the sandbox's working directory using their basename.
    Directories are written preserving their internal structure under the
    directory's basename.
    """
    files_to_write = []
    total_bytes = 0

    def _add_file(local_path: str, sandbox_path: str):
        nonlocal total_bytes
        try:
            size = os.path.getsize(local_path)
            if total_bytes + size > max_total_bytes:
                logger.warning(f"Skipping {local_path}: would exceed {max_total_bytes} byte budget")
                return
            with open(local_path, "r") as f:
                content = f.read()
            files_to_write.append({"path": sandbox_path, "text": content})
            total_bytes += size
        except (UnicodeDecodeError, OSError) as e:
            logger.warning(f"Skipping {local_path}: {e}")

    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            _add_file(path, os.path.basename(path))
        elif os.path.isdir(path):
            dir_name = os.path.basename(path.rstrip("/"))
            for root, _, filenames in os.walk(path):
                for fname in sorted(filenames):
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, path)
                    _add_file(full, os.path.join(dir_name, rel))
        else:
            logger.warning(f"Path does not exist: {path}")

    return files_to_write


def cleanup():
    """Clean up the code interpreter session."""
    global _code_client
    if _code_client:
        logger.info("Cleaning up code interpreter session...")
        _code_client.stop()
        _code_client = None


@tool
def execute_python_analysis(code: str, description: str = "", files: list[str] = None) -> str:
    """Execute Python code in a secure AgentCore CodeInterpreter sandbox.

    Use this for data analysis tasks:
    - Parsing and aggregating JSON evaluation results
    - Computing confusion matrices or accuracy breakdowns
    - Statistical analysis of extraction quality
    - Any data transformation or calculation

    The sandbox has standard Python libraries (json, collections, statistics,
    re, math, pandas, etc.) but NO access to the host filesystem or AWS
    credentials.

    To get data into the sandbox, pass file/directory paths via the `files`
    parameter. Files appear in the sandbox's working directory:
    - Single files: available as their basename (e.g., "results.json")
    - Directories: available as dirname/relative_path (e.g., "eval-results/doc1/results.json")

    IMPORTANT: In your code, use ONLY the directory basename as the root path.
    Example: if you pass files=["/tmp/autotune-data/abc123/ground-truth/my-dataset"],
    the files will be at "my-dataset/..." in the sandbox — NOT at the original
    absolute path. The response will confirm the exact sandbox root paths to use.

    Args:
        code: Python code to execute. Use print() for output.
        description: Optional description of what the code does.
        files: Optional list of local file paths or directories to copy into
               the sandbox before execution. Max 10MB total. Text files only
               (JSON, CSV, YAML, TXT, MD). Binary files are skipped.

    Returns:
        JSON with execution results including list of files loaded into sandbox.
    """
    try:
        _get_code_interpreter_client()

        loaded_files = []
        if files:
            files_to_write = _collect_files(files)
            if files_to_write:
                _invoke_code_interpreter_tool("writeFiles", {"content": files_to_write})
                loaded_files = [f["path"] for f in files_to_write]
                logger.info(f"Wrote {len(files_to_write)} files into sandbox")

        if description:
            code = f"# {description}\n{code}"

        result = _invoke_code_interpreter_tool(
            "executeCode",
            {"code": code, "language": "python", "clearContext": False},
        )

        output = {"result": result}
        if loaded_files:
            # Show the sandbox root paths the agent should use in code
            roots = sorted(set(f.split("/")[0] for f in loaded_files))
            output["sandbox_paths"] = roots
            output["sandbox_paths_note"] = (
                "Use these as your base paths in code. "
                "Files are at: <root>/<relative_path>. "
                "Do NOT use the original absolute paths — they don't exist in the sandbox."
            )
            output["sandbox_file_count"] = len(loaded_files)
        return json.dumps(output, indent=2)
    except Exception as e:
        logger.error(f"Code execution failed: {e}")
        return json.dumps({"error": f"Code execution failed: {str(e)}"})
