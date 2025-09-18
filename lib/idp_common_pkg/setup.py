#!/usr/bin/env python

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from setuptools import find_packages, setup

# Core dependencies required for all installations
install_requires = [
    "boto3==1.39.4",  # Core dependency for AWS services
]

# Optional dependencies by component
extras_require = {
    # Core utilities only - minimal dependencies
    "core": [],
    # Analytics agent dependencies
    "analytics": [
        "strands-agents>=1.0.0",
        "pandas>=2.0.0",
    ],
    # Image handling dependencies
    "image": [
        "Pillow==11.2.1",
    ],
    # OCR module dependencies
    "ocr": [
        "Pillow==11.2.1",
        "PyMuPDF==1.25.5",
        "amazon-textract-textractor[pandas]==1.9.2",
        "numpy==1.26.4",
        "pandas==2.2.3",
        "openpyxl==3.1.5",
        "python-docx==1.2.0",
    ],
    # Classification module dependencies
    "classification": [
        "Pillow==11.2.1",  # For image handling
    ],
    # Extraction module dependencies
    "extraction": [
        "Pillow==11.2.1",  # For image handling
    ],
    # Assessment module dependencies
    "assessment": [
        "Pillow==11.2.1",  # For image handling
    ],
    # Evaluation module dependencies
    "evaluation": [
        "munkres>=1.1.4",  # For Hungarian algorithm
        "numpy==1.26.4",  # For numeric operations
    ],
    # Reporting module dependencies
    "reporting": [
        "pyarrow==20.0.0",  # For Parquet conversion
    ],
    # Appsync module dependencies
    "appsync": [
        "requests==2.32.4",
    ],
    # Document service factory dependencies (includes both appsync and dynamodb support)
    "docs_service": [
        "requests==2.32.4",
    ],
    # Testing dependencies
    "test": [
        "pytest>=7.4.0",
        "pytest-cov>=4.1.0",
        "pytest-xdist>=3.3.1",  # For parallel test execution
        "requests>=2.32.3,<3.0.0",
        "pyarrow==20.0.0",
        "PyYAML==6.0.2",
        "openpyxl==3.1.5",
        "python-docx==1.2.0",
    ],
    # Development dependencies
    "dev": [
        "python-dotenv>=1.1.0,<2.0.0",
        "ipykernel>=6.29.5,<7.0.0",
        "jupyter>=1.1.1,<2.0.0",
    ],
    # Agents module dependencies
    "agents": [
        "strands-agents>=1.0.0",
        "strands-agents-tools>=0.2.2",
        "bedrock-agentcore>=0.1.1",  # Specifically for the code interpreter tool
        "regex>=2024.0.0,<2026.0.0",  # Pin regex version to avoid conflicts
    ],
    # Full package with all dependencies
    "all": [
        "Pillow==11.2.1",
        "PyMuPDF==1.25.5",
        "amazon-textract-textractor[pandas]==1.9.2",
        "munkres>=1.1.4",
        "numpy==1.26.4",
        "pandas==2.2.3",
        "requests==2.32.4",
        "pyarrow==20.0.0",
        "openpyxl==3.1.5",
        "python-docx==1.2.0",
        "strands-agents>=1.0.0",
        "strands-agents-tools>=0.2.2",
        "bedrock-agentcore>=0.1.1",
        "regex>=2024.0.0,<2026.0.0",
    ],
}

setup(
    name="idp_common",
    version="0.3.13",
    packages=find_packages(
        exclude=[
            "build",
            "build.*",
            "*build",
            "*build.*",
            "*.build",
            "*.build.*",
            "**build**",
        ]
    ),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=install_requires,
    extras_require=extras_require,
)
