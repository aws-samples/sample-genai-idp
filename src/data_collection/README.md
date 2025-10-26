# Data Collection Lambda Functions

## Overview

This directory contains Lambda functions for the Data Collection Stack that integrate with external APIs (Companies House, HMRC, etc.).

## Lambda Functions

### 1. Company Lookup (`company_lookup/handler.py`)

**Purpose**: Fetch basic company information from Companies House API

**Trigger**: API Gateway `GET /company/{company_number}`

**Features**:
- ✅ Basic Auth with Companies House API
- ✅ DynamoDB caching (24-hour TTL)
- ✅ Company number validation and sanitization
- ✅ Error handling (404, 401, 500)
- ✅ CORS headers for frontend access

**Response Example**:
```json
{
  "success": true,
  "company_number": "12345678",
  "cached": false,
  "company_name": "ACME LTD",
  "company_status": "active",
  "company_type": "ltd",
  "date_of_creation": "2020-01-15",
  "registered_office_address": {
    "address_line_1": "123 High Street",
    "locality": "London",
    "postal_code": "SW1A 1AA"
  },
  "sic_codes": ["62012"],
  "last_updated": "2025-10-26T10:30:00"
}
```

**Environment Variables**:
- `ENVIRONMENT`: dev/staging/prod
- `SECRET_NAME`: Secrets Manager secret name (default: fiscalshield-dc-{env}-CompaniesHouseAPI)
- `CACHE_TABLE_NAME`: DynamoDB table for caching (default: fiscalshield-dc-{env}-CompanyEvents)

---

### 2. Health Check (`health/handler.py`)

**Purpose**: Verify Data Collection Stack availability for Core Stack integration

**Trigger**: API Gateway `GET /health`

**Features**:
- ✅ Check Companies House API credentials exist
- ✅ Check Step Functions state machine exists
- ✅ Check DynamoDB tables are accessible
- ✅ 5-minute cache header
- ✅ CORS enabled

**Response Example**:
```json
{
  "status": "available",
  "version": "1.0.0",
  "services": {
    "companies_house": "operational",
    "step_functions": "available",
    "dynamodb": "operational"
  },
  "region": "eu-central-1",
  "environment": "dev"
}
```

**Status Values**:
- `available`: All services operational
- `degraded`: Some services unavailable
- Service statuses: `operational`, `available`, `unavailable`, `degraded`

---

## Secrets Configuration

The Lambdas expect a secret in AWS Secrets Manager with the following structure:

**Secret Name**: `fiscalshield-dc-{environment}-CompaniesHouseAPI`

**Secret Value** (JSON):
```json
{
  "api_key": "your-companies-house-api-key",
  "base_url": "https://api.company-information.service.gov.uk",
  "rate_limit": 600,
  "rate_limit_window": 300
}
```

**Current Secret ARN**:
```
arn:aws:secretsmanager:eu-central-1:864899848062:secret:fiscalshield-dc-dev-CompaniesHouseAPI-J4N454
```

---

## DynamoDB Cache Structure

**Table**: `fiscalshield-dc-{environment}-CompanyEvents`

**Item Structure**:
```json
{
  "company_number": "12345678",
  "event_type": "COMPANY_INFO#2025-10-26",
  "timestamp": "2025-10-26T10:30:00",
  "last_updated": "2025-10-26T10:30:00",
  "ttl": 1729958400,
  "data": {
    "company_name": "ACME LTD",
    "company_status": "active",
    ...
  }
}
```

**Cache Logic**:
- TTL: 24 hours
- Automatic cleanup by DynamoDB TTL
- Date-based sort key for versioning
- Most recent entry returned on cache hit

---

## Testing Locally

### Test Company Lookup Lambda

```python
# test_event.json
{
  "pathParameters": {
    "company_number": "12345678"
  }
}
```

```bash
# Install dependencies
pip install boto3

# Set environment variables
export ENVIRONMENT=dev
export AWS_REGION=eu-central-1
export SECRET_NAME=fiscalshield-dc-dev-CompaniesHouseAPI
export CACHE_TABLE_NAME=fiscalshield-dc-dev-CompanyEvents

# Run locally (requires AWS credentials)
python -c "
from src.data_collection.companies_house.company_lookup.handler import lambda_handler
import json
event = json.load(open('test_event.json'))
result = lambda_handler(event, None)
print(json.dumps(result, indent=2))
"
```

### Test Health Check Lambda

```bash
export ENVIRONMENT=dev
export AWS_REGION=eu-central-1

python -c "
from src.data_collection.health.handler import lambda_handler
result = lambda_handler({}, None)
print(json.dumps(result, indent=2))
"
```

---

## Deployment

These Lambdas are deployed as part of the Data Collection Stack via SAM:

```bash
cd stacks/data-collection
sam build
sam deploy --config-env dev
```

See `stacks/data-collection/template.yaml` for Lambda resource definitions.

---

## Error Handling

### Company Lookup Errors

| Status | Reason | Response |
|--------|--------|----------|
| 400 | Invalid company number | `{"error": "Company number is required"}` |
| 404 | Company not found | `{"error": "Company not found"}` |
| 500 | API error / Internal | `{"error": "Internal server error during lookup"}` |

### Health Check

Always returns `200 OK`, but service statuses indicate availability.

---

## Monitoring

**CloudWatch Metrics**:
- Lambda invocations
- Duration (should be <3s for company lookup)
- Errors
- Throttles

**Custom Logs**:
```
Cache HIT for company: 12345678
Cache MISS for company: 12345678
Successfully looked up company: 12345678
HTTP error: code=404, reason=Not Found
```

**CloudWatch Insights Query** (Cache hit ratio):
```sql
fields @timestamp, @message
| filter @message like /Cache HIT/ or @message like /Cache MISS/
| stats count(*) as total, 
        sum(@message like /Cache HIT/) as hits 
        by bin(@timestamp, 1h)
| eval hit_rate = (hits / total) * 100
```

---

## Future Enhancements

- [ ] Add filing history Lambda
- [ ] Add officers lookup Lambda
- [ ] Add PSC lookup Lambda
- [ ] Add Step Functions workflow trigger Lambda
- [ ] Add aggregation Lambda for research results
- [ ] Add SIC code enhancement (from your old Lambda)
- [ ] Add rate limiting middleware
- [ ] Add request validation with schemas
- [ ] Add X-Ray tracing
