#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Example usage of the Granular Assessment Service.

This script demonstrates how to use the granular assessment approach
for improved accuracy and scalability when assessing document extraction confidence.
"""

import json
import logging
from typing import Any, Dict

import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def example_granular_assessment():
    """Example of using granular assessment service."""

    # Load configuration with granular assessment enabled
    config = {
        "assessment": {
            "default_confidence_threshold": 0.9,
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "system_prompt": "You are a document analysis assessment expert...",
            "task_prompt": """
            <background>
            You are an expert document analysis assessment system...
            </background>
            
            <<CACHEPOINT>>
            
            <extraction-results>
            {EXTRACTION_RESULTS}
            </extraction-results>
            
            <final-instructions>
            Analyze and provide confidence assessments...
            </final-instructions>
            """,
            # Granular assessment configuration
            "granular": {
                "enabled": True,
                "max_workers": 20,
                "simple_batch_size": 3,
                "list_batch_size": 1,
            },
        },
        "classes": [
            {
                "name": "Bank Statement",
                "attributes": [
                    {
                        "name": "Account Number",
                        "attributeType": "simple",
                        "confidence_threshold": 0.95,
                    },
                    {
                        "name": "Statement Period",
                        "attributeType": "simple",
                        "confidence_threshold": 0.85,
                    },
                    {
                        "name": "Account Holder Address",
                        "attributeType": "group",
                        "groupAttributes": [
                            {"name": "Street Number", "confidence_threshold": 0.95},
                            {"name": "Street Name", "confidence_threshold": 0.85},
                            {"name": "City", "confidence_threshold": 0.9},
                            {"name": "State", "confidence_threshold": 0.95},
                            {"name": "ZIP Code", "confidence_threshold": 0.95},
                        ],
                    },
                    {
                        "name": "Transactions",
                        "attributeType": "list",
                        "listItemTemplate": {
                            "itemAttributes": [
                                {"name": "Date", "confidence_threshold": 0.9},
                                {"name": "Description", "confidence_threshold": 0.75},
                                {"name": "Amount", "confidence_threshold": 0.95},
                            ]
                        },
                    },
                ],
            }
        ],
    }

    # Import the assessment module
    from idp_common.assessment import create_assessment_service

    # Create assessment service using factory function
    assessment_service = create_assessment_service(region="us-west-2", config=config)

    logger.info(f"Created assessment service: {type(assessment_service).__name__}")

    # Example extraction results that would be assessed
    example_extraction_results = {
        "Account Number": "123456789",
        "Statement Period": "January 2024",
        "Account Holder Address": {
            "Street Number": "123",
            "Street Name": "Main Street",
            "City": "Anytown",
            "State": "CA",
            "ZIP Code": "12345",
        },
        "Transactions": [
            {
                "Date": "01/15/2024",
                "Description": "GROCERY STORE PURCHASE",
                "Amount": "-45.67",
            },
            {
                "Date": "01/16/2024",
                "Description": "SALARY DEPOSIT",
                "Amount": "2500.00",
            },
            {
                "Date": "01/17/2024",
                "Description": "UTILITY PAYMENT",
                "Amount": "-125.30",
            },
        ],
    }

    logger.info("Example extraction results:")
    logger.info(json.dumps(example_extraction_results, indent=2))

    # Demonstrate task creation (this would normally be done internally)
    if hasattr(assessment_service, "_create_assessment_tasks"):
        attributes = assessment_service._get_class_attributes("Bank Statement")
        tasks = assessment_service._create_assessment_tasks(
            example_extraction_results, attributes, 0.9
        )

        logger.info(f"\nCreated {len(tasks)} assessment tasks:")
        for task in tasks:
            logger.info(f"  - {task.task_id}: {task.task_type} for {task.attributes}")

    return assessment_service, config


def compare_approaches():
    """Compare original vs granular assessment approaches."""

    logger.info("=== Comparison: Original vs Granular Assessment ===")

    # Configuration for original approach
    original_config = {"assessment": {"granular": {"enabled": False}}}

    # Configuration for granular approach
    granular_config = {
        "assessment": {
            "granular": {
                "enabled": True,
                "max_workers": 4,
                "simple_batch_size": 3,
                "list_batch_size": 1,
            }
        }
    }

    from idp_common.assessment import create_assessment_service

    # Create both services
    original_service = create_assessment_service(config=original_config)
    granular_service = create_assessment_service(config=granular_config)

    logger.info(f"Original service: {type(original_service).__name__}")
    logger.info(f"Granular service: {type(granular_service).__name__}")

    # Show the differences
    logger.info("\nKey Differences:")
    logger.info("Original Approach:")
    logger.info("  - Single inference for all attributes")
    logger.info("  - Simple implementation")
    logger.info("  - May struggle with complex documents")

    logger.info("\nGranular Approach:")
    logger.info("  - Multiple focused inferences")
    logger.info("  - Prompt caching for cost optimization")
    logger.info("  - Parallel processing for speed")
    logger.info("  - Better handling of complex documents")


def demonstrate_configuration_options():
    """Demonstrate different configuration options for granular assessment."""

    logger.info("=== Configuration Options ===")

    # Conservative configuration (good for starting)
    conservative_config = {
        "assessment": {
            "granular": {
                "enabled": True,
                "max_workers": 2,
                "simple_batch_size": 2,
                "list_batch_size": 1,
            }
        }
    }

    # Aggressive configuration (for high-throughput)
    aggressive_config = {
        "assessment": {
            "granular": {
                "enabled": True,
                "max_workers": 8,
                "simple_batch_size": 5,
                "list_batch_size": 2,
            }
        }
    }

    # Balanced configuration (recommended)
    balanced_config = {
        "assessment": {
            "granular": {
                "enabled": True,
                "max_workers": 4,
                "simple_batch_size": 3,
                "list_batch_size": 1,
            }
        }
    }

    configs = {
        "Conservative": conservative_config,
        "Aggressive": aggressive_config,
        "Balanced": balanced_config,
    }

    for name, config in configs.items():
        logger.info(f"\n{name} Configuration:")
        granular_settings = config["assessment"]["granular"]
        for key, value in granular_settings.items():
            logger.info(f"  {key}: {value}")


def main():
    """Main example function."""

    logger.info("=== Granular Assessment Service Examples ===")

    try:
        # Example 1: Basic usage
        logger.info("\n1. Basic Usage Example")
        service, config = example_granular_assessment()

        # Example 2: Compare approaches
        logger.info("\n2. Approach Comparison")
        compare_approaches()

        # Example 3: Configuration options
        logger.info("\n3. Configuration Options")
        demonstrate_configuration_options()

        logger.info("\n=== Examples Complete ===")
        logger.info("To use granular assessment in your application:")
        logger.info("1. Add granular configuration to your config file")
        logger.info("2. Use create_assessment_service() factory function")
        logger.info("3. Process documents with the same interface")
        logger.info("4. Monitor performance and tune parameters")

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure idp_common package is installed and available")
    except Exception as e:
        logger.error(f"Error running examples: {e}")
        raise


if __name__ == "__main__":
    main()
