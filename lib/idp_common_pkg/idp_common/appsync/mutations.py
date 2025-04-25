"""
GraphQL mutations for AppSync operations.

This module contains the GraphQL mutation strings used by the AppSync client
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
        }
        Pages {
            Id
            Class
            ImageUri
            TextUri
        }
        Metering
        EvaluationReportUri
        EvaluationStatus
        SummaryReportUri
        ExpiresAfter
    }
}
"""