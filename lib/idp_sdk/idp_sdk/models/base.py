# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Base models and enums for IDP SDK."""

from enum import Enum


class StackState(str, Enum):
    """CloudFormation stack state."""

    CREATE_IN_PROGRESS = "CREATE_IN_PROGRESS"
    CREATE_COMPLETE = "CREATE_COMPLETE"
    CREATE_FAILED = "CREATE_FAILED"
    UPDATE_IN_PROGRESS = "UPDATE_IN_PROGRESS"
    UPDATE_COMPLETE = "UPDATE_COMPLETE"
    UPDATE_FAILED = "UPDATE_FAILED"
    DELETE_IN_PROGRESS = "DELETE_IN_PROGRESS"
    DELETE_COMPLETE = "DELETE_COMPLETE"
    DELETE_FAILED = "DELETE_FAILED"
    ROLLBACK_IN_PROGRESS = "ROLLBACK_IN_PROGRESS"
    ROLLBACK_COMPLETE = "ROLLBACK_COMPLETE"
    UPDATE_ROLLBACK_IN_PROGRESS = "UPDATE_ROLLBACK_IN_PROGRESS"
    UPDATE_ROLLBACK_COMPLETE = "UPDATE_ROLLBACK_COMPLETE"


class DocumentState(str, Enum):
    """Document processing state."""

    QUEUED = "QUEUED"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    OCR = "OCR"
    CLASSIFYING = "CLASSIFYING"
    EXTRACTING = "EXTRACTING"
    ASSESSING = "ASSESSING"
    SUMMARIZING = "SUMMARIZING"
    EVALUATING = "EVALUATING"
    POSTPROCESSING = "POSTPROCESSING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


class Pattern(str, Enum):
    """IDP processing patterns."""

    PATTERN_1 = "pattern-1"
    PATTERN_2 = "pattern-2"
    PATTERN_3 = "pattern-3"


class RerunStep(str, Enum):
    """Pipeline steps for rerun operations."""

    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
