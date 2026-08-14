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

    # MUST stay a superset of idp_common.models.Status: this enum validates the
    # ObjectStatus read straight out of the tracking table, so any runtime status
    # missing here makes `idp-cli status` / `run-inference --monitor` die with a
    # pydantic ValidationError ("Input should be 'QUEUED', ...") rather than
    # reporting progress. Four were missing, and two of them are on ordinary
    # paths: PREPROCESSING is set for EVERY document whenever a preprocessing
    # hook is registered (so every PII Anonymization user hit it), and
    # RULE_VALIDATION_POLICY_CLASSIFICATION for every rule-validation document.
    PENDING_UPLOAD = "PENDING_UPLOAD"
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    PREPROCESSING = "PREPROCESSING"
    OCR = "OCR"
    CLASSIFYING = "CLASSIFYING"
    EXTRACTING = "EXTRACTING"
    ASSESSING = "ASSESSING"
    RULE_VALIDATION_POLICY_CLASSIFICATION = "RULE_VALIDATION_POLICY_CLASSIFICATION"
    RULE_VALIDATION = "RULE_VALIDATION"
    RULE_VALIDATION_ORCHESTRATOR = "RULE_VALIDATION_ORCHESTRATOR"
    SUMMARIZING = "SUMMARIZING"
    HITL_IN_PROGRESS = "HITL_IN_PROGRESS"
    EVALUATING = "EVALUATING"
    POSTPROCESSING = "POSTPROCESSING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    # Terminal: a preprocessing hook replaced this original with a redacted copy.
    # Listed in the monitor's terminal-state sets too, or monitoring would wait
    # forever for a document that will never reach COMPLETED.
    REDACTED_SUPERSEDED = "REDACTED_SUPERSEDED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class Pattern(str, Enum):
    """IDP processing patterns."""

    PATTERN_1 = "pattern-1"
    PATTERN_2 = "pattern-2"


class RerunStep(str, Enum):
    """Pipeline steps for rerun operations."""

    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
