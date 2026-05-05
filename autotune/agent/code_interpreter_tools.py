# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Code interpreter tools for AutoTune agent.

Provides sandboxed Python execution via AgentCore CodeInterpreter.
No filesystem access to the host, no AWS credentials — safe for arbitrary
agent-generated code. The agent can load local files into the sandbox
before execution via the `files` parameter, preserving their original paths.
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
    """Collect files from local paths, preserving their full filesystem paths.

    Files are placed in the sandbox at the same absolute path they have on the
    host, so the agent can reference them with identical paths in its code.

    Supports individual files and directories (recursively collects all files).
    Skips binary files and files that exceed the size budget.

    Returns:
        List of {"path": <full_path>, "text": <content>} dicts.
    """
    files_to_write = []
    total_bytes = 0

    def _add_file(local_path: str):
        nonlocal total_bytes
        try:
            size = os.path.getsize(local_path)
            if total_bytes + size > max_total_bytes:
                logger.warning(f"Skipping {local_path}: would exceed {max_total_bytes} byte budget")
                return
            with open(local_path, "r") as f:
                content = f.read()
            files_to_write.append({"path": local_path, "text": content})
            total_bytes += size
        except (UnicodeDecodeError, OSError) as e:
            logger.warning(f"Skipping {local_path}: {e}")

    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            _add_file(path)
        elif os.path.isdir(path):
            for root, _, filenames in os.walk(path):
                for fname in sorted(filenames):
                    _add_file(os.path.join(root, fname))
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
    parameter. These are copied into the sandbox at their ORIGINAL paths,
    so you can use the same paths in your code that you see from other tools.

    Args:
        code: Python code to execute. Use print() for output.
        description: Optional description of what the code does.
        files: Optional list of local file paths or directories to copy into
               the sandbox before execution. Max 10MB total. Text files only
               (JSON, CSV, YAML, TXT, MD). Binary files are skipped.

    Returns:
        JSON with execution results.
    """
    try:
        client = _get_code_interpreter_client()

        # Load files into sandbox if provided
        if files:
            files_to_write = _collect_files(files)
            if files_to_write:
                _invoke_code_interpreter_tool("writeFiles", {"content": files_to_write})
                logger.info(f"Wrote {len(files_to_write)} files into sandbox")

        if description:
            code = f"# {description}\n{code}"

        result = _invoke_code_interpreter_tool(
            "executeCode",
            {"code": code, "language": "python", "clearContext": False},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Code execution failed: {e}")
        return json.dumps({"error": f"Code execution failed: {str(e)}"})
