Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Document Knowledge Base

The GenAI IDP solution includes an integrated Document Knowledge Base feature that enables you to interactively ask questions about your processed document collection using natural language. This feature leverages the processed data to create a searchable knowledge base with flexible backend options.

## Backend Options Overview

The solution provides **flexible knowledge base backend options**, allowing you to choose the storage and retrieval architecture that best fits your requirements:

- **OpenSearch**: Traditional knowledge base using Amazon OpenSearch Service with Bedrock Knowledge Base integration
- **S3 Vectors**: Serverless knowledge base using AWS S3 Vectors service with Bedrock Knowledge Base integration  
- **Disabled**: No knowledge base functionality (document processing only)

### Backend Comparison

| Feature | OpenSearch | S3 Vectors | Disabled |
|---------|------------|------------|----------|
| **Architecture** | Always-on OpenSearch cluster | Serverless S3 Vectors service | No knowledge base |
| **Query Processing** | Bedrock Knowledge Base APIs | Bedrock Knowledge Base APIs | N/A |
| **Query Performance** | Sub-second responses | 2-10 second responses | N/A |
| **Best For** | Real-time analytics, fast queries | Cost-effective large-scale processing | Processing-only workflows |

Both OpenSearch and S3 Vectors backends use **Amazon Bedrock Knowledge Base** for consistent query processing, document chunking, and response generation. The difference is in the underlying vector storage mechanism.

## How It Works

1. **Document Indexing**
   - Processed documents are automatically indexed in a vector database
   - Documents are chunked into semantic segments for efficient retrieval
   - Each chunk maintains reference to its source document

2. **Interactive Query Interface**
   - Access through the Web UI via the "Knowledge Base" section
   - Ask natural language questions about your document collection
   - View responses with citations to source documents
   - Follow-up with contextual questions in a chat-like interface

3. **AI-Powered Responses**
   - LLM generates responses based on relevant document chunks
   - Responses include citations to source documents
   - Links to original documents for reference
   - Context-aware for follow-up questions

## Query Features

- **Natural Language Understanding**: Ask questions in plain English rather than using keywords or query syntax
- **Document Citations**: Responses include references to the specific documents used to generate answers
- **Contextual Follow-ups**: Ask follow-up questions without repeating context
- **Direct Document Links**: Click on document references to view the original source
- **Markdown Formatting**: Responses support rich formatting for better readability
- **Real-time Processing**: Get answers in seconds, even across large document collections

## Configuration

### CloudFormation Parameters

Configure the knowledge base backend during stack deployment:

| Parameter | Values | Description |
|-----------|--------|-------------|
| `DocumentKnowledgeBase` | `OpenSearch` \| `S3 Vectors` \| `Disabled` | Selects knowledge base backend or disables it entirely |
| `KnowledgeBaseModelId` | Model ARN | Foundational model for knowledge base chat (e.g., `us.amazon.nova-pro-v1:0`) |

### S3 Vectors Specific Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VectorSimilarityMeasure` | `cosine` | Distance metric (`cosine` \| `euclidean`) |
| `KnowledgeBaseEmbeddingModelId` | `amazon.titan-embed-text-v2:0` | Embedding model for vectorization |

### Vector Similarity Measures

Choose the appropriate similarity measure for your use case:

- **Cosine Similarity** (Recommended): Measures angle between vectors, normalized for document length. Best for finding documents with similar topics regardless of length.
- **Euclidean Distance**: Measures absolute distance, sensitive to vector magnitude. Best when both content similarity and document characteristics matter.

When the knowledge base is enabled, the solution:
- Creates the selected backend infrastructure (OpenSearch cluster or S3 Vectors resources)
- Configures Bedrock Knowledge Base integration
- Sets up automatic document ingestion from processed documents
- Adds the query interface to the Web UI

## Using the Knowledge Base

### Accessing the Knowledge Base

1. Log in to the Web UI
2. Navigate to the "Knowledge Base" section in the main navigation
3. You'll see a chat-like interface for querying your document collection

### Asking Questions

1. Type your question in the input field at the bottom of the screen
2. Press Enter or click the send button
3. The system will process your question and return an answer
4. The answer will include:
   - A direct response to your question
   - Citations to the source documents
   - Links to view the original documents

### Exploring Document Context

1. Click on document citations to view the original source
2. The system will highlight the relevant sections in the document
3. You can navigate to other parts of the document to explore the full context

### Follow-up Questions

1. After receiving an answer, you can ask related follow-up questions
2. The system maintains context from previous questions
3. This allows for a natural conversation about your documents
4. You can start a new topic at any time by asking an unrelated question

## Choosing the Right Backend

### Choose OpenSearch When:
- You need fast, sub-second query responses
- You have consistent, predictable query patterns
- You require real-time analytics capabilities
- You have existing OpenSearch expertise
- Query performance is more important than cost optimization

### Choose S3 Vectors When:
- You prefer serverless, pay-per-use pricing
- You have variable or unpredictable query patterns
- Cost optimization is a primary concern
- You can accept 2-10 second query response times
- You want to minimize always-on infrastructure

### Choose Disabled When:
- You only need document processing capabilities
- Knowledge base querying is not required
- You want to minimize infrastructure costs
- You plan to integrate with external knowledge base systems

## Best Practices

### Query Best Practices
1. **Be specific**: Clearly state what information you're looking for
2. **Start broad, then narrow**: Begin with general questions before diving into specifics
3. **Use follow-ups**: Build on previous questions to explore topics in depth
4. **Check citations**: Verify information by consulting the source documents
5. **Refine questions**: If you don't get the expected answer, try rephrasing your question

### Configuration Best Practices
- Test both backends with your document corpus before deciding on production deployment
- Monitor resource utilization and costs after deployment
- Use appropriate embedding models for your content language and type
- Consider your query patterns when choosing between backends

## Performance Considerations

### OpenSearch Backend
- **Query Response Time**: Sub-second responses for most queries
- **Infrastructure**: Always-on cluster with consistent performance
- **Scaling**: Automatic scaling based on query load
- **Cost**: Fixed daily cost regardless of usage

### S3 Vectors Backend  
- **Query Response Time**: 2-10 seconds depending on document corpus size
- **Infrastructure**: Serverless, scales automatically
- **Scaling**: Pay-per-query model with automatic scaling
- **Cost**: Variable cost based on actual usage

### General Considerations
- **Document Collection Size**: Both backends handle large collections, but query times may vary
- **Query Complexity**: More complex queries may take longer to process
- **Document Types**: Some document types may be indexed more effectively than others
- **Model Selection**: Different Bedrock models offer different performance/accuracy tradeoffs

## Security Considerations

The Knowledge Base feature maintains the security controls of the overall solution:

- Access is restricted to authenticated users
- Document visibility respects user permissions
- Questions and answers are processed securely within your AWS account
- No data is sent to external services beyond the configured Bedrock models
