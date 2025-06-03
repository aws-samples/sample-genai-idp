#!/usr/bin/env python

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


from setuptools import find_packages, setup

# Core dependencies required for all installations
install_requires = [
    "boto3>=1.37.29",  # Core dependency for AWS services
]

# Optional dependencies by component
extras_require = {
    # Core utilities only - minimal dependencies
    "core": [],
    # Image handling dependencies
    "image": [
        "Pillow>=11.1.0",
    ],
    # OCR module dependencies
    "ocr": [
        "Pillow>=11.1.0",
        "PyMuPDF>=1.25.5",
        "amazon-textract-textractor[pandas]>=1.9.2",
    ],
    # Classification module dependencies
    "classification": [
        "Pillow>=11.1.0",  # For image handling
    ],
    # Extraction module dependencies
    "extraction": [
        "Pillow>=11.1.0",  # For image handling
    ],
    # Appsync module dependencies
    "appsync": [
        "requests>=2.32.3",
    ],
    # Full package with all dependencies
    "all": [
        "Pillow>=11.1.0",
        "PyMuPDF>=1.25.5",
        "amazon-textract-textractor[pandas]>=1.9.2",
        "requests>=2.32.3",
    ],
}

setup(
    name="idp_common",
    version="0.3.1",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=install_requires,
    extras_require=extras_require,
)
