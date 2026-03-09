# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
GraphQL mutations and queries for AppSync operations.

This module contains the GraphQL mutation and query strings used by the AppSync client
for document operations.
"""

# Mutation to create a new document
CREATE_DOCUMENT = """
mutation CreateDocument($input: CreateDocumentInput!) {
    createDocument(input: $input) {
        ObjectKey
    }
}
"""

# Mutation to update an existing document
UPDATE_DOCUMENT = """
mutation UpdateDocument($input: UpdateDocumentInput!) {
    updateDocument(input: $input) {
        ObjectKey
        ObjectStatus
        InitialEventTime
        QueuedTime
        WorkflowStartTime
        CompletionTime
        WorkflowExecutionArn
        WorkflowStatus
        PageCount
        Sections {
            Id
            PageIds
            Class
            OutputJSONUri
            ConfidenceThresholdAlerts {
                attributeName
                confidence
                confidenceThreshold
            }
        }
        Pages {
            Id
            Class
            ImageUri
            TextUri
            TextConfidenceUri
        }
        Metering
        EvaluationReportUri
        EvaluationStatus
        SummaryReportUri
        ExpiresAfter
        HITLStatus
        HITLReviewURL
        ConfidenceAlertCount
        TraceId
    }
}
"""

# Query to get a document by ObjectKey
GET_DOCUMENT = """
query GetDocument($objectKey: ID!) {
    getDocument(ObjectKey: $objectKey) {
        PK
        SK
        ObjectKey
        ObjectStatus
        InitialEventTime
        QueuedTime
        WorkflowStartTime
        CompletionTime
        WorkflowExecutionArn
        WorkflowStatus
        PageCount
        Sections {
            Id
            PageIds
            Class
            OutputJSONUri
            ConfidenceThresholdAlerts {
                attributeName
                confidence
                confidenceThreshold
            }
        }
        Pages {
            Id
            Class
            ImageUri
            TextUri
            TextConfidenceUri
        }
        Metering
        EvaluationReportUri
        EvaluationStatus
        SummaryReportUri
        ExpiresAfter
        HITLStatus
        HITLReviewURL
        ConfigVersion
        TraceId
    }
}
"""

# Lightweight status-only update mutation for minimal DynamoDB WCU usage
# Use this during parallel Map operations to update status without touching Sections array
UPDATE_DOCUMENT_STATUS = """
mutation UpdateDocumentStatus($input: UpdateDocumentStatusInput!) {
    updateDocumentStatus(input: $input) {
        ObjectKey
        ObjectStatus
        WorkflowExecutionArn
        WorkflowStatus
    }
}
"""

# Atomic section-level update mutation for parallel Map operations
# Uses SET Sections[index] = :value for efficient single-section updates
UPDATE_DOCUMENT_SECTION = """
mutation UpdateDocumentSection($input: UpdateDocumentSectionInput!) {
    updateDocumentSection(input: $input) {
        ObjectKey
        ObjectStatus
        Sections {
            Id
            PageIds
            Class
            OutputJSONUri
            ConfidenceThresholdAlerts {
                attributeName
                confidence
                confidenceThreshold
            }
        }
    }
}
"""
