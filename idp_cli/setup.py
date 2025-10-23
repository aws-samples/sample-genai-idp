# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Setup script for IDP CLI package
"""

from setuptools import find_packages, setup

with open("requirements.txt") as f:
    requirements = [
        line.strip() for line in f if line.strip() and not line.startswith("#")
    ]

setup(
    name="idp-cli",
    version="1.0.0",
    description="Command-line interface for IDP Accelerator batch document processing",
    author="AWS",
    license="MIT-0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=requirements,
    extras_require={
        "test": [
            "pytest>=7.4.0",
            "pytest-mock>=3.11.0",
            "moto>=4.2.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "idp-cli=idp_cli.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
