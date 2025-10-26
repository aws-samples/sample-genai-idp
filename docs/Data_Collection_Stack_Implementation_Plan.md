# FiscalShield Data Collection Stack - Implementation Plan

**Project**: FiscalShield Data Collection Stack (Independent Stack Architecture)  
**Stack Name**: `fiscalshield-dc`  
**Status**: Planning Phase  
**Date**: October 25, 2025  
**Stack Dependencies**: None (fully independent)

---

## 🎯 EXECUTIVE SUMMARY

The Data Collection Stack is responsible for fetching, caching, and managing external data sources (Companies House, HMRC, future APIs). This stack operates independently from other FiscalShield stacks and is called on-demand from the Core Stack frontend.

### Key Principles
- **Independence**: No dependencies on other stacks (except convention-based DynamoDB access)
- **Predictable Naming**: Convention-based resource names (`fiscalshield-dc-{environment}-{ResourceName}`) for cross-stack access
- **Smart Caching**: Minimize API costs through intelligent caching strategies
- **Multi-Tenant**: Client-aware data isolation from the ground up
- **Cost Optimization**: Pay-per-use model with aggressive caching
- **Graceful Degradation**: Core Stack functions even if Data Collection Stack is not deployed

### Architecture Highlights

#### **Hybrid Approach: Direct Lambda + Step Functions**

1. **Synchronous Path (Company Lookup)**
   - User inputs company number in Core Stack landing page
   - Direct API call: `GET /company/{number}` → Lambda → Companies House
   - Response time: <3s (cache miss), <500ms (cache hit)
   - User confirms company selection

2. **Asynchronous Path (Background Research)**
   - User clicks "Confirm and research company background"
   - Core Stack checks: `GET /health` (is Data Collection available?)
   - If available: `POST /research/company` → Step Functions workflow
   - Parallel execution: Filing History + Officers + PSC + Sanctions (5-8s)
   - User receives notification when complete

3. **Health Check Integration**
   - Core Stack detects if Data Collection Stack is deployed
   - Shows appropriate UI: "Research available" or "Research unavailable"
   - No hard dependency - graceful degradation

### Cost Summary
- **Monthly Cost (1000 clients):** ~$11.64/month
- **Per Research Execution:** ~$0.00087
- **Step Functions Overhead:** $0.38/month (worth it for UX and reliability)

---

## 📋 STACK SCOPE AND BOUNDARIES

### What This Stack Owns
✅ External API integrations (Companies House, HMRC, Banking APIs)  
✅ API secrets and credentials  
✅ Data caching layer (DynamoDB tables)  
✅ Lambda functions for data collection  
✅ API Gateway routes for data collection endpoints  
✅ Step Functions workflows for background research orchestration  
✅ Cache refresh logic and TTL policies  
✅ Health check endpoint for Core Stack integration  

### What This Stack Does NOT Own
❌ Core infrastructure (S3, Auth, base tables)  
❌ Document processing (Ingestion Stack)  
❌ Data analysis and categorization (Analytics Stack)  
❌ Frontend hosting (Core Stack)  
❌ User company selection landing page (Core Stack)  
❌ Monitoring dashboards (Evaluation Stack)  

### Integration with Core Stack
The Data Collection Stack provides a **public API** that Core Stack calls during user registration:

```
Core Stack Landing Page → GET /health (check availability)
                       → GET /company/{number} (display company info for confirmation)
                       → POST /research/company (trigger background research via Step Functions)
```

### Data Flow

#### 1. User-Initiated Company Lookup (Synchronous)
```
Core Stack Frontend → Data Collection API → CompanyLookup Lambda
                                          → Check cache
                                          → If miss: Companies House API
                                          → Return basic company info
                                          → Core Stack displays to user
```

#### 2. Background Research (Asynchronous - User Triggered)
```
User clicks "Confirm and research company background"
                       ↓
Core Stack → POST /research/company → Step Functions Workflow
                                    ↓
                    ┌───────────────┴───────────────┐
                    │  Parallel Data Collection     │
                    └───────────────┬───────────────┘
                    ┌───────┬───────┼───────┬───────┐
                    ↓       ↓       ↓       ↓       ↓
              Filing    Officers  PSC   Sanctions  News
              History   Lambda   Lambda  Lambda   Lambda
                    ↓       ↓       ↓       ↓       ↓
                    └───────┴───────┴───────┴───────┘
                                    ↓
                          Store in DynamoDB Cache
                                    ↓
                          Notify user (SNS/Email)
```

#### 3. Analytics Stack Access (Read-Only)
```
Analytics Stack → Reads enriched data from DynamoDB tables
               → Displays risk scores, compliance reports in UI
               → Convention-based table names (no imports needed)
```

---

## 🔐 SECRETS MANAGEMENT

### Secrets Owned by This Stack
Each secret is owned and managed within the Data Collection Stack to maintain independence.

#### 1. Companies House API Key
```yaml
Resource: CompaniesHouseApiKey
Type: AWS::SecretsManager::Secret
Name: fiscalshield-dc-{environment}-CompaniesHouseAPI
Rotation: Manual (annual key refresh)
Access: Data Collection Lambda functions only
```

**Secret Structure:**
```json
{
  "api_key": "your-companies-house-api-key",
  "base_url": "https://api.company-information.service.gov.uk",
  "rate_limit": 600,
  "rate_limit_window": 300
}
```

#### 2. HMRC API Credentials (Future)
```yaml
Resource: HMRCApiCredentials
Type: AWS::SecretsManager::Secret
Name: fiscalshield-dc-{environment}-HMRCAPI
Rotation: Automatic via HMRC OAuth refresh token
Access: HMRC Lambda functions only
```

**Secret Structure:**
```json
{
  "client_id": "your-hmrc-client-id",
  "client_secret": "your-hmrc-client-secret",
  "access_token": "oauth-access-token",
  "refresh_token": "oauth-refresh-token",
  "token_expiry": "2025-10-26T12:00:00Z",
  "base_url": "https://api.service.hmrc.gov.uk"
}
```

#### 3. Banking API Credentials (Future)
```yaml
Resource: BankingApiCredentials
Type: AWS::SecretsManager::Secret
Name: fiscalshield-dc-{environment}-BankingAPI
Access: Banking integration Lambda functions only
```

### Secret Access Pattern
```python
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

# In Lambda
environment = os.environ['ENVIRONMENT']
secret = get_secret(f'fiscalshield-dc-{environment}-CompaniesHouseAPI')
api_key = secret['api_key']
```

### Cost
- **Secrets Manager**: $0.40/secret/month + $0.05 per 10,000 API calls
- **Estimated Cost**: ~$2/month for 3 secrets with moderate rotation

---

## 🗄️ DYNAMODB TABLES

### Naming Convention
All tables follow: `fiscalshield-dc-{environment}-{ResourceName}`

**Examples:**
- `fiscalshield-dc-dev-FilingEvents`
- `fiscalshield-dc-dev-CompanyEvents`
- `fiscalshield-dc-prod-FilingEvents`

**Note:** No random suffix is used - this ensures predictable cross-stack access.

### Table 1: Companies House Filing Events Cache
```yaml
TableName: fiscalshield-dc-{environment}-FilingEvents
Purpose: Cache Companies House filing history data
Billing: PAY_PER_REQUEST

Schema:
  Partition Key: company_number (String)
  Sort Key: client_id (String)
  
Attributes:
  - company_number: UK company registration number (e.g., "12345678")
  - client_id: FiscalShield client identifier
  - last_updated: Unix timestamp of cache update
  - ttl: Expiry timestamp (24 hours from last_updated)
  - filing_count: Total number of filings
  - compliance_score: Integer 1-10
  - risk_level: String (LOW, MEDIUM, HIGH)
  - risk_indicators: List of detected issues
  - filings: JSON array of filing details
  - raw_data: Full API response for reference
  
GSI:
  client-index:
    Partition Key: client_id
    Sort Key: last_updated
    Purpose: Query all companies for a specific client
```

**Access Pattern:**
```python
# Data Collection Lambda writes
table.put_item(Item={
    'company_number': '12345678',
    'client_id': 'client-abc',
    'last_updated': 1729872000,
    'ttl': 1729958400,  # 24 hours later
    'compliance_score': 9,
    'risk_level': 'LOW',
    'filings': [...]
})

# Analytics Stack reads (no import needed!)
table_name = f'fiscalshield-dc-{environment}-FilingEvents'
response = table.query(
    KeyConditionExpression='company_number = :num',
    ExpressionAttributeValues={':num': '12345678'}
)
```

### Table 2: Companies House Company Events Cache
```yaml
TableName: fiscalshield-dc-{environment}-CompanyEvents
Purpose: Cache company information and officer data
Billing: PAY_PER_REQUEST

Schema:
  Partition Key: company_number (String)
  Sort Key: event_type#timestamp (String)
  
Attributes:
  - company_number: UK company registration number
  - event_type: Type of data (OFFICERS, COMPANY_INFO, PSC)
  - timestamp: When data was fetched
  - client_id: FiscalShield client identifier
  - ttl: Expiry timestamp (24 hours)
  - data: JSON payload of the event
  - total_officers: Count for officers data
  - active_officers: Count of active officers
  - risk_score: Calculated risk score
  
GSI:
  client-event-index:
    Partition Key: client_id
    Sort Key: event_type#timestamp
    Purpose: Query all events for a client
```

**Usage:**
- Officers data: `event_type = "OFFICERS#2025-10-25T12:00:00"`
- Company info: `event_type = "COMPANY_INFO#2025-10-25T12:00:00"`
- PSC data: `event_type = "PSC#2025-10-25T12:00:00"`

### Table 3: HMRC Data Cache (Future)
```yaml
TableName: fiscalshield-dc-{environment}-HMRCData
Purpose: Cache HMRC VAT returns and tax data
Billing: PAY_PER_REQUEST

Schema:
  Partition Key: vat_number (String)
  Sort Key: period_key (String)  # e.g., "2025-Q3"
  
Attributes:
  - vat_number: UK VAT registration number
  - period_key: Tax period identifier
  - client_id: FiscalShield client identifier
  - last_updated: Timestamp
  - ttl: Expiry timestamp (7 days for tax data)
  - vat_return_data: JSON of VAT return
  - submission_date: When return was submitted to HMRC
  - status: SUBMITTED, OUTSTANDING, OVERDUE
```

### Storage Cost Estimation
- **Filing Events**: ~50KB per company × 1,000 companies = 50MB
- **Company Events**: ~100KB per company × 1,000 companies = 100MB
- **HMRC Data**: ~20KB per return × 4 quarters × 1,000 clients = 80MB
- **Total**: ~230MB = **$0.06/month** (first 25GB free)
- **Requests**: With 80% cache hit rate, ~$0.50/month for 1M requests

---

## 🌐 API INTEGRATIONS

### 1. Companies House API

**Base URL:** `https://api.company-information.service.gov.uk`

**Authentication:** Basic Auth with API key as username

**Rate Limits:**
- 600 requests per 5 minutes
- No monthly limit
- Free tier available

#### Endpoint A: Company Profile
```http
GET /company/{company_number}

Response:
{
  "company_number": "12345678",
  "company_name": "ACME LTD",
  "company_status": "active",
  "type": "ltd",
  "date_of_creation": "2020-01-15",
  "registered_office_address": {...},
  "sic_codes": ["62012"],
  "accounts": {
    "next_due": "2025-12-31",
    "last_made_up_to": "2024-12-31"
  }
}

Caching Strategy:
- TTL: 24 hours (company info changes infrequently)
- Force refresh: When user explicitly requests
- Cost per call: Free
```

#### Endpoint B: Filing History
```http
GET /company/{company_number}/filing-history

Parameters:
  - items_per_page: 100
  - start_index: 0

Response:
{
  "total_count": 245,
  "items": [
    {
      "date": "2025-09-15",
      "type": "AA",
      "description": "Annual accounts",
      "category": "accounts"
    },
    ...
  ]
}

Caching Strategy:
- TTL: 24 hours
- Smart caching: Already implemented ✅
- Compliance scoring: Calculate on fetch
- Risk indicators: Pattern analysis
- Cost per call: Free
```

#### Endpoint C: Officers
```http
GET /company/{company_number}/officers

Response:
{
  "active_count": 2,
  "items": [
    {
      "name": "SMITH, John",
      "officer_role": "director",
      "appointed_on": "2020-01-15",
      "nationality": "British",
      "occupation": "Company Director"
    }
  ]
}

Caching Strategy:
- TTL: 24 hours
- Cross-check against disqualified directors list
- Multiple directorships risk flag
- Cost per call: Free
```

#### Endpoint D: Persons with Significant Control (PSC)
```http
GET /company/{company_number}/persons-with-significant-control

Response:
{
  "items": [
    {
      "name": "John Smith",
      "nature_of_control": ["ownership-of-shares-75-to-100-percent"],
      "notified_on": "2020-02-01"
    }
  ]
}

Caching Strategy:
- TTL: 7 days (changes rarely)
- Ownership structure analysis
- Beneficial owner identification
- Cost per call: Free
```

### 2. HMRC API (Future Implementation)

**Base URL:** `https://api.service.hmrc.gov.uk`

**Authentication:** OAuth 2.0 with refresh tokens

**Rate Limits:**
- Varies by endpoint
- Production rate limits after approval

#### Endpoint A: VAT Obligations
```http
GET /organisations/vat/{vrn}/obligations

Response:
{
  "obligations": [
    {
      "periodKey": "25A1",
      "start": "2025-01-01",
      "end": "2025-03-31",
      "due": "2025-05-07",
      "status": "O" // Open or F for Fulfilled
    }
  ]
}

Caching Strategy:
- TTL: 1 hour (status can change)
- Alert on overdue obligations
- Cost: Free (sandbox), production requires approval
```

#### Endpoint B: VAT Returns
```http
GET /organisations/vat/{vrn}/returns

Response:
{
  "periodKey": "25A1",
  "vatDueSales": 10500.00,
  "vatDueAcquisitions": 0.00,
  "totalVatDue": 10500.00,
  "vatReclaimedCurrPeriod": 3200.00,
  "netVatDue": 7300.00
}

Caching Strategy:
- TTL: 7 days (returns rarely change after submission)
- Compare against calculated VAT from invoices
- Discrepancy alerts
```

### 3. Open Banking API (Future)

**Purpose:** Bank statement transaction retrieval

**Standard:** Open Banking UK API Standard

**Implementation:** TBD based on banking partner selection

---

## 🔄 STEP FUNCTIONS WORKFLOW

### Overview
Step Functions orchestrates the background research process, triggered when users click "Confirm and research company background" in Core Stack.

### Workflow: CompanyBackgroundResearch

**State Machine Name:** `fiscalshield-dc-{environment}-CompanyResearch`

**Trigger:** API Gateway POST `/research/company`

**Input:**
```json
{
  "company_number": "12345678",
  "company_name": "ACME LTD",
  "user_id": "user-123",
  "client_id": "client-abc",
  "requested_at": "2025-10-26T10:30:00Z"
}
```

**Workflow Definition:**
```json
{
  "Comment": "Company Background Research Workflow",
  "StartAt": "CheckRecentResearch",
  "States": {
    "CheckRecentResearch": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-CheckCache",
      "Parameters": {
        "company_number.$": "$.company_number",
        "client_id.$": "$.client_id"
      },
      "ResultPath": "$.cache_result",
      "Next": "IsResearchFresh",
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.error",
        "Next": "ParallelDataCollection"
      }],
      "TimeoutSeconds": 10
    },
    
    "IsResearchFresh": {
      "Type": "Choice",
      "Choices": [{
        "Variable": "$.cache_result.age_hours",
        "NumericLessThan": 24,
        "Next": "ReturnCachedResults"
      }],
      "Default": "ParallelDataCollection"
    },
    
    "ParallelDataCollection": {
      "Type": "Parallel",
      "ResultPath": "$.research_results",
      "Branches": [
        {
          "StartAt": "FetchFilingHistory",
          "States": {
            "FetchFilingHistory": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-FilingHistory",
              "Parameters": {
                "company_number.$": "$.company_number",
                "client_id.$": "$.client_id"
              },
              "Retry": [{
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
              }],
              "Catch": [{
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.filing_error",
                "Next": "FilingHistoryFailed"
              }],
              "TimeoutSeconds": 60,
              "End": true
            },
            "FilingHistoryFailed": {
              "Type": "Pass",
              "Result": {
                "status": "failed",
                "service": "filing_history"
              },
              "End": true
            }
          }
        },
        {
          "StartAt": "FetchOfficers",
          "States": {
            "FetchOfficers": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-Officers",
              "Parameters": {
                "company_number.$": "$.company_number",
                "client_id.$": "$.client_id"
              },
              "Retry": [{
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
              }],
              "Catch": [{
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.officers_error",
                "Next": "OfficersFailed"
              }],
              "TimeoutSeconds": 30,
              "End": true
            },
            "OfficersFailed": {
              "Type": "Pass",
              "Result": {
                "status": "failed",
                "service": "officers"
              },
              "End": true
            }
          }
        },
        {
          "StartAt": "FetchPSC",
          "States": {
            "FetchPSC": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-PSCLookup",
              "Parameters": {
                "company_number.$": "$.company_number",
                "client_id.$": "$.client_id"
              },
              "Retry": [{
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
              }],
              "Catch": [{
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.psc_error",
                "Next": "PSCFailed"
              }],
              "TimeoutSeconds": 30,
              "End": true
            },
            "PSCFailed": {
              "Type": "Pass",
              "Result": {
                "status": "failed",
                "service": "psc"
              },
              "End": true
            }
          }
        },
        {
          "StartAt": "CheckSanctions",
          "States": {
            "CheckSanctions": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-SanctionsCheck",
              "Parameters": {
                "company_number.$": "$.company_number",
                "client_id.$": "$.client_id"
              },
              "Retry": [{
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 2,
                "BackoffRate": 2.0
              }],
              "Catch": [{
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.sanctions_error",
                "Next": "SanctionsFailed"
              }],
              "TimeoutSeconds": 30,
              "End": true
            },
            "SanctionsFailed": {
              "Type": "Pass",
              "Result": {
                "status": "failed",
                "service": "sanctions"
              },
              "End": true
            }
          }
        }
      ],
      "Next": "AggregateResults"
    },
    
    "AggregateResults": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-AggregateResults",
      "Parameters": {
        "company_number.$": "$.company_number",
        "client_id.$": "$.client_id",
        "research_results.$": "$.research_results",
        "requested_at.$": "$.requested_at"
      },
      "ResultPath": "$.aggregated",
      "TimeoutSeconds": 15,
      "Next": "StoreResults"
    },
    
    "StoreResults": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:fiscalshield-dc-${Environment}-StoreResults",
      "Parameters": {
        "company_number.$": "$.company_number",
        "client_id.$": "$.client_id",
        "aggregated_data.$": "$.aggregated"
      },
      "TimeoutSeconds": 10,
      "Next": "NotifyUser"
    },
    
    "NotifyUser": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:${AWS::Region}:${AWS::AccountId}:fiscalshield-dc-${Environment}-ResearchComplete",
        "Message": {
          "company_name.$": "$.company_name",
          "company_number.$": "$.company_number",
          "risk_level.$": "$.aggregated.risk_level",
          "compliance_score.$": "$.aggregated.compliance_score",
          "user_id.$": "$.user_id"
        }
      },
      "End": true
    },
    
    "ReturnCachedResults": {
      "Type": "Pass",
      "Result": {
        "status": "cached",
        "message": "Using recent research results"
      },
      "End": true
    }
  }
}
```

### Execution Time
- **Best Case (cached):** <2 seconds (skip to ReturnCachedResults)
- **Typical Case:** 5-8 seconds (parallel execution)
- **Worst Case:** 12-15 seconds (some retries)

### Cost per Execution
- Step Functions: $0.000375 (15 state transitions)
- Lambda executions: ~$0.0005
- **Total:** ~$0.00087 per research

For 1000 companies researched: **$0.87/month**

### Error Handling
- Each branch retries independently (exponential backoff)
- Failed services don't block other services
- Partial results still returned to user
- Failed services marked in result with error details

### Monitoring
CloudWatch metrics tracked:
- ExecutionsStarted
- ExecutionsSucceeded
- ExecutionsFailed
- ExecutionTime (P50, P95, P99)
- Per-service success rate

---

## 🏥 HEALTH CHECK ENDPOINT

### Purpose
Allows Core Stack to detect if Data Collection Stack is deployed and operational before attempting to trigger background research.

### Endpoint

```http
GET /health
```

### Response (Stack Available)

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

**Status Code:** 200 OK

### Response (Partial Availability)

```json
{
  "status": "degraded",
  "version": "1.0.0",
  "services": {
    "companies_house": "operational",
    "step_functions": "unavailable",
    "dynamodb": "operational"
  },
  "region": "eu-central-1",
  "environment": "dev"
}
```

**Status Code:** 200 OK (still returns 200, but Core Stack should show warning)

### Lambda Implementation

```python
# src/data_collection/health/handler.py
import json
import boto3
import os

def lambda_handler(event, context):
    """
    Health check endpoint for Data Collection Stack
    Returns availability status of all services
    """
    environment = os.environ.get('ENVIRONMENT', 'dev')
    region = os.environ.get('AWS_REGION', 'eu-central-1')
    
    services = {
        'companies_house': check_companies_house_api(),
        'step_functions': check_step_functions(),
        'dynamodb': check_dynamodb()
    }
    
    # Determine overall status
    all_operational = all(status == 'operational' for status in services.values())
    status = 'available' if all_operational else 'degraded'
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'  # CORS for Core Stack frontend
        },
        'body': json.dumps({
            'status': status,
            'version': '1.0.0',
            'services': services,
            'region': region,
            'environment': environment
        })
    }

def check_companies_house_api():
    """Verify Companies House API credentials exist"""
    try:
        secrets = boto3.client('secretsmanager')
        secrets.get_secret_value(
            SecretId=f'fiscalshield-dc-{os.environ["ENVIRONMENT"]}-CompaniesHouseAPI'
        )
        return 'operational'
    except Exception:
        return 'unavailable'

def check_step_functions():
    """Verify Step Functions state machine exists"""
    try:
        sfn = boto3.client('stepfunctions')
        state_machine_arn = f'arn:aws:states:{os.environ["AWS_REGION"]}:{context.invoked_function_arn.split(":")[4]}:stateMachine:fiscalshield-dc-{os.environ["ENVIRONMENT"]}-CompanyResearch'
        sfn.describe_state_machine(stateMachineArn=state_machine_arn)
        return 'available'
    except Exception:
        return 'unavailable'

def check_dynamodb():
    """Verify DynamoDB tables exist"""
    try:
        dynamodb = boto3.client('dynamodb')
        dynamodb.describe_table(
            TableName=f'fiscalshield-dc-{os.environ["ENVIRONMENT"]}-FilingEvents'
        )
        return 'operational'
    except Exception:
        return 'unavailable'
```

### Core Stack Usage

```javascript
// In Core Stack frontend
async function isBackgroundResearchAvailable() {
  try {
    const response = await fetch(
      `${process.env.REACT_APP_DATA_COLLECTION_API}/health`,
      {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(2000) // 2 second timeout
      }
    );
    
    if (!response.ok) return false;
    
    const data = await response.json();
    
    // Check if both companies_house and step_functions are operational
    return (
      data.status === 'available' &&
      data.services.companies_house === 'operational' &&
      data.services.step_functions === 'available'
    );
  } catch (error) {
    console.warn('Data Collection Stack unavailable:', error);
    return false;
  }
}
```

### Caching Health Check Results

To avoid hitting the health endpoint on every page load:

```javascript
// Cache health check result for 5 minutes
const HEALTH_CHECK_CACHE_TTL = 5 * 60 * 1000;
let healthCheckCache = null;
let lastHealthCheck = 0;

async function isBackgroundResearchAvailable() {
  const now = Date.now();
  
  if (healthCheckCache !== null && (now - lastHealthCheck) < HEALTH_CHECK_CACHE_TTL) {
    return healthCheckCache;
  }
  
  try {
    const response = await fetch(...);
    const data = await response.json();
    
    healthCheckCache = (
      data.status === 'available' &&
      data.services.companies_house === 'operational' &&
      data.services.step_functions === 'available'
    );
    lastHealthCheck = now;
    
    return healthCheckCache;
  } catch (error) {
    healthCheckCache = false;
    lastHealthCheck = now;
    return false;
  }
}
```

---

## ⚙️ LAMBDA FUNCTIONS

### Naming Convention
`fiscalshield-dc-{environment}-{FunctionName}`

**Examples:**
- `fiscalshield-dc-dev-CompanyLookup`
- `fiscalshield-dc-dev-FilingHistory`
- `fiscalshield-dc-prod-CompanyLookup`

### Lambda 1: Companies House Company Lookup
```yaml
Function: fiscalshield-dc-{environment}-CompanyLookup
Trigger: API Gateway GET /companies-house/company/{company_number}
Runtime: Python 3.11
Memory: 256MB
Timeout: 30 seconds

Purpose:
  - Fetch company profile from Companies House
  - Cache result in DynamoDB
  - Return company information to frontend

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - TABLE_NAME: fiscalshield-dc-{environment}-CompanyEvents
  - SECRET_NAME: fiscalshield-dc-{environment}-CompaniesHouseAPI
  - CACHE_TTL_HOURS: 24

Logic Flow:
  1. Extract company_number from path
  2. Check DynamoDB cache for fresh data (<24 hours)
  3. If cache hit: return cached data
  4. If cache miss: 
     - Fetch from Companies House API
     - Store in cache with TTL
     - Return fresh data
  5. Handle errors gracefully

IAM Permissions:
  - DynamoDB: PutItem, GetItem, Query on CompanyEvents table
  - Secrets Manager: GetSecretValue for API key
  - CloudWatch: Logs
```

### Lambda 2: Companies House Filing History
```yaml
Function: fiscalshield-dc-{environment}-FilingHistory
Trigger: API Gateway GET /companies-house/filing-history/{company_number}
Runtime: Python 3.11
Memory: 512MB (handles large filing histories)
Timeout: 60 seconds

Purpose:
  - Fetch filing history from Companies House
  - Analyze filing patterns for compliance
  - Calculate compliance score (1-10)
  - Identify risk indicators
  - Cache result in DynamoDB

Status: ✅ Smart caching already implemented

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - TABLE_NAME: fiscalshield-dc-{environment}-FilingEvents
  - SECRET_NAME: fiscalshield-dc-{environment}-CompaniesHouseAPI
  - CACHE_TTL_HOURS: 24
  - MAX_FILINGS: 100

Logic Flow:
  1. Check cache for company_number + client_id
  2. If fresh data exists (<24 hours): return cache
  3. If stale or missing:
     - Fetch from Companies House API (paginated)
     - Analyze filing patterns:
       * Check for late filings
       * Missing accounts
       * Compliance score calculation
       * Risk indicator detection
     - Store in DynamoDB with TTL
     - Return analyzed data
  4. Support force refresh with ?refresh=true

Risk Indicators Detected:
  - Late filing history (>2 late filings = HIGH risk)
  - Missing annual accounts
  - Recent address changes
  - Director resignations
  - Dormant to active transitions

Compliance Score Algorithm:
  Start: 10 points
  Deduct 2 points per late filing
  Deduct 3 points for missing accounts
  Deduct 1 point per director resignation
  Minimum: 1 point
```

### Lambda 3: Companies House Officers
```yaml
Function: fiscalshield-dc-{environment}-Officers
Trigger: API Gateway GET /companies-house/officers/{company_number}
Runtime: Python 3.11
Memory: 256MB
Timeout: 30 seconds

Purpose:
  - Fetch company officers from Companies House
  - Check against disqualified directors database
  - Analyze officer risk factors
  - Cache result in DynamoDB

Status: 🔄 Needs smart caching implementation

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - TABLE_NAME: fiscalshield-dc-{environment}-CompanyEvents
  - SECRET_NAME: fiscalshield-dc-{environment}-CompaniesHouseAPI
  - CACHE_TTL_HOURS: 24

Logic Flow:
  1. Check cache (event_type = "OFFICERS")
  2. If fresh: return cached officers
  3. If stale/missing:
     - Fetch officers from Companies House
     - Cross-reference with disqualified directors API
     - Calculate risk score based on:
       * Number of active directorships
       * Recent appointments/resignations
       * Disqualification status
     - Store in cache
     - Return officer data

Risk Factors:
  - Director holds >10 active directorships (HIGH)
  - Director appointed <6 months ago (MEDIUM)
  - Director resigned from multiple companies recently (HIGH)
  - Disqualified director detected (CRITICAL)
```

### Lambda 4: Companies House PSC Lookup
```yaml
Function: fiscalshield-dc-{environment}-PSCLookup
Trigger: API Gateway GET /companies-house/psc/{company_number}
Runtime: Python 3.11
Memory: 256MB
Timeout: 30 seconds

Purpose:
  - Fetch Persons with Significant Control
  - Identify beneficial owners
  - Cache result in DynamoDB

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - TABLE_NAME: fiscalshield-dc-{environment}-CompanyEvents
  - SECRET_NAME: fiscalshield-dc-{environment}-CompaniesHouseAPI
  - CACHE_TTL_HOURS: 168  # 7 days (changes rarely)

Logic Flow:
  1. Check cache (event_type = "PSC")
  2. If fresh (<7 days): return cached PSC data
  3. If stale/missing:
     - Fetch PSC from Companies House
     - Parse ownership structure
     - Identify ultimate beneficial owners
     - Store in cache with longer TTL
     - Return PSC data
```

### Lambda 5: HMRC VAT Obligations (Future)
```yaml
Function: fiscalshield-dc-{environment}-VATObligations
Trigger: API Gateway GET /hmrc/vat/{vrn}/obligations
Runtime: Python 3.11
Memory: 256MB
Timeout: 30 seconds

Purpose:
  - Fetch VAT obligations from HMRC
  - Identify overdue returns
  - Cache result in DynamoDB

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - TABLE_NAME: fiscalshield-dc-{environment}-HMRCData
  - SECRET_NAME: fiscalshield-dc-{environment}-HMRCAPI
  - CACHE_TTL_HOURS: 1  # Refresh hourly

Logic Flow:
  1. Check cache for VRN
  2. If fresh (<1 hour): return cached obligations
  3. If stale/missing:
     - Authenticate with HMRC OAuth
     - Fetch obligations
     - Identify overdue periods
     - Store in cache
     - Return obligations + alerts
```

### Lambda 6: Cache Maintenance (Scheduled)
```yaml
Function: fiscalshield-dc-{environment}-CacheMaintenance
Trigger: EventBridge Rule (daily at 2 AM UTC)
Runtime: Python 3.11
Memory: 256MB
Timeout: 900 seconds (15 minutes)

Purpose:
  - Clean up expired cache entries
  - Proactively refresh popular companies
  - Generate cache hit ratio metrics

Logic Flow:
  1. Scan tables for expired TTL entries
  2. Delete expired items (DynamoDB auto-deletes, this is backup)
  3. Identify top 50 most-accessed companies
  4. Proactively refresh their data
  5. Send metrics to CloudWatch:
     - Cache hit ratio
     - Average response time
     - API call count
     - Cost savings estimate
```

### Lambda 7: Health Check
```yaml
Function: fiscalshield-dc-{environment}-HealthCheck
Trigger: API Gateway GET /health
Runtime: Python 3.11
Memory: 128MB (minimal)
Timeout: 5 seconds

Purpose:
  - Provide health status for Core Stack integration
  - Verify all services are operational
  - Enable graceful degradation

Environment Variables:
  - ENVIRONMENT: dev/staging/prod

Logic Flow:
  1. Check Companies House API credentials exist
  2. Verify Step Functions state machine exists
  3. Verify DynamoDB tables accessible
  4. Return status JSON with service availability

Response:
  {
    "status": "available",
    "services": {
      "companies_house": "operational",
      "step_functions": "available",
      "dynamodb": "operational"
    }
  }

IAM Permissions:
  - Secrets Manager: DescribeSecret
  - Step Functions: DescribeStateMachine
  - DynamoDB: DescribeTable
```

### Lambda 8: Trigger Research (Step Functions Initiator)
```yaml
Function: fiscalshield-dc-{environment}-TriggerResearch
Trigger: API Gateway POST /research/company
Runtime: Python 3.11
Memory: 128MB
Timeout: 10 seconds

Purpose:
  - Receive research request from Core Stack
  - Validate input
  - Start Step Functions workflow
  - Return execution ARN for tracking

Environment Variables:
  - ENVIRONMENT: dev/staging/prod
  - STATE_MACHINE_ARN: arn:aws:states:...CompanyResearch

Input:
  {
    "company_number": "12345678",
    "company_name": "ACME LTD",
    "user_id": "user-123",
    "client_id": "client-abc"
  }

Logic Flow:
  1. Validate company_number format
  2. Start Step Functions execution
  3. Return execution ARN + estimated completion time
  4. Log research request

Response:
  {
    "execution_arn": "arn:aws:states:...:execution:...",
    "status": "started",
    "estimated_completion_seconds": 10,
    "message": "Background research initiated"
  }

IAM Permissions:
  - Step Functions: StartExecution
  - CloudWatch: PutMetricData
```

### Lambda 9: Check Cache (Step Functions Task)
```yaml
Function: fiscalshield-dc-{environment}-CheckCache
Trigger: Step Functions workflow
Runtime: Python 3.11
Memory: 128MB
Timeout: 10 seconds

Purpose:
  - Check if recent research exists (< 24 hours)
  - Decide if fresh research needed
  - Used by Step Functions to skip unnecessary work

Logic Flow:
  1. Query FilingEvents table for company + client
  2. Check last_updated timestamp
  3. If < 24 hours old: return cached data
  4. If stale or missing: signal fresh research needed

Response:
  {
    "cache_status": "fresh" | "stale" | "missing",
    "age_hours": 12,
    "cached_data": {...} (if fresh)
  }
```

### Lambda 10: Aggregate Results (Step Functions Task)
```yaml
Function: fiscalshield-dc-{environment}-AggregateResults
Trigger: Step Functions workflow
Runtime: Python 3.11
Memory: 256MB
Timeout: 15 seconds

Purpose:
  - Combine results from parallel Lambda executions
  - Calculate overall risk score
  - Generate compliance summary
  - Handle partial failures gracefully

Input (from Step Functions):
  {
    "company_number": "12345678",
    "research_results": [
      { "filing_history": {...}, "compliance_score": 9 },
      { "officers": {...}, "risk_score": 2 },
      { "psc": {...} },
      { "sanctions": {"status": "clear"} }
    ]
  }

Logic Flow:
  1. Parse results from all branches
  2. Identify failures (handle gracefully)
  3. Calculate overall risk level:
     - Aggregate compliance scores
     - Weight different risk factors
     - Consider sanctions findings
  4. Generate summary report
  5. Determine notification priority

Output:
  {
    "overall_risk_level": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
    "compliance_score": 9,
    "risk_indicators": ["late_filing", "recent_director_change"],
    "summary": "Company shows good compliance history...",
    "services_failed": ["sanctions"],  // Optional
    "data_completeness": 0.75  // 3 out of 4 services succeeded
  }
```

### Lambda 11: Store Results (Step Functions Task)
```yaml
Function: fiscalshield-dc-{environment}-StoreResults
Trigger: Step Functions workflow
Runtime: Python 3.11
Memory: 128MB
Timeout: 10 seconds

Purpose:
  - Store aggregated research results in DynamoDB
  - Update cache with latest data
  - Set appropriate TTL (24 hours)

Logic Flow:
  1. Format aggregated data for DynamoDB
  2. Calculate TTL (current time + 24 hours)
  3. Write to FilingEvents table
  4. Write to CompanyEvents table
  5. Update access metrics

IAM Permissions:
  - DynamoDB: PutItem, UpdateItem on all tables
```

### Lambda 12: Sanctions Check (Future)
```yaml
Function: fiscalshield-dc-{environment}-SanctionsCheck
Trigger: Step Functions workflow (parallel branch)
Runtime: Python 3.11
Memory: 256MB
Timeout: 30 seconds

Purpose:
  - Check company and directors against sanctions lists
  - Query UK HM Treasury list
  - Query OFAC list (US)
  - Query UN sanctions list

Status: 🔄 Future implementation

Logic Flow:
  1. Get company details from CompanyEvents cache
  2. Extract director names from officers data
  3. Check each against sanctions APIs
  4. Cache results (7 day TTL)
  5. Return findings

Response:
  {
    "company_sanctioned": false,
    "directors_sanctioned": [],
    "checks_performed": ["uk_hmt", "ofac", "un"],
    "last_checked": "2025-10-26T10:30:00Z"
  }
```

---

## 💰 COST OPTIMIZATION STRATEGIES

### Strategy 1: Aggressive Caching (Current Implementation)

**Smart Cache Decision Logic:**
```python
def should_fetch_fresh_data(cached_item, force_refresh=False):
    if force_refresh:
        return True
    
    if not cached_item:
        return True  # Cache miss
    
    # Check TTL
    ttl = cached_item.get('ttl', 0)
    current_time = int(time.time())
    
    if current_time > ttl:
        return True  # Expired
    
    # Check access pattern (hot data gets shorter TTL)
    access_count = cached_item.get('access_count', 0)
    if access_count > 100:
        # Popular company - refresh more frequently
        age_hours = (current_time - cached_item['last_updated']) / 3600
        return age_hours > 12  # 12 hour TTL for hot data
    
    return False  # Use cache
```

**Expected Savings:**
- Without caching: 1M Companies House calls/month = FREE (but slow)
- With 80% cache hit: 200K Companies House calls + DynamoDB
- Response time improvement: 3-5s → <500ms
- User experience: Dramatically better

### Strategy 2: Bulk Refresh During Off-Peak

```python
# Scheduled Lambda (daily at 2 AM)
def bulk_refresh_companies():
    """
    Proactively refresh all monitored companies during off-peak
    Users get instant responses during business hours
    """
    clients = dynamodb.scan(TableName='fiscalshield-dc-dev-Clients')
    
    for client in clients['Items']:
        company_number = client.get('company_number')
        if company_number:
            # Refresh filing history
            fetch_and_cache_filing_history(company_number)
            time.sleep(0.1)  # Rate limit compliance
```

**Benefits:**
- Business hours: 95%+ cache hit rate
- Faster user experience
- Predictable API usage

### Strategy 3: Tiered Cache TTL

Different data types have different change frequencies:

| Data Type | Change Frequency | Cache TTL |
|-----------|-----------------|-----------|
| Company profile | Weekly | 24 hours |
| Filing history | Monthly | 24 hours |
| Officers | Quarterly | 24 hours |
| PSC | Rarely | 7 days |
| VAT obligations | Daily | 1 hour |
| VAT returns | Never (once filed) | 30 days |

### Strategy 4: Conditional Requests (Future)

```python
# Store ETag from API response
cached_item['etag'] = response_headers.get('ETag')

# On next request
headers = {'If-None-Match': cached_item['etag']}
response = requests.get(url, headers=headers)

if response.status_code == 304:
    # Not Modified - use cache
    return cached_item['data']
else:
    # Data changed - update cache
    return response.json()
```

**Savings:** Reduces API response size when data unchanged

### Cost Projection (1,000 active clients)

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| Lambda (10M requests) | 256MB, avg 1s | $2.00 |
| DynamoDB (1M requests) | PAY_PER_REQUEST | $1.25 |
| DynamoDB storage (250MB) | Standard class | $0.06 |
| Secrets Manager (3 secrets) | + 500K API calls | $1.45 |
| API Gateway (1M requests) | REST API | $3.50 |
| Step Functions (1000 executions) | 15 state transitions each | $0.38 |
| SNS (1000 notifications) | Research complete alerts | $0.50 |
| CloudWatch Logs (5GB) | 7-day retention | $2.50 |
| **Total** | | **$11.64/month** |

**Without caching:** Same cost but 5x slower response times  
**With Step Functions:** Additional $0.38/month for orchestration, parallel execution, and better UX

---

## ⚡ STEP FUNCTIONS ARCHITECTURE DECISION

### Use Cases in This Stack

We use **two different patterns** for different purposes:

#### 1. **Direct Lambda** - Company Lookup (Synchronous)
```
Core Stack → GET /company/{number} → Lambda → Companies House → Response
```

**Purpose:** Immediate company info display for user confirmation  
**Latency:** <3s  
**Why:** User waits for result, needs fast response  

#### 2. **Step Functions** - Background Research (Asynchronous)
```
Core Stack → POST /research/company → Step Functions → Parallel Lambdas → Notification
```

**Purpose:** Deep background check with multiple API calls  
**Latency:** 5-15s (user doesn't wait)  
**Why:** Complex workflow, parallel execution, error handling  

### Comparison Matrix

| Criteria | Direct Lambda | Step Functions | SQS |
|----------|---------------|----------------|-----|
| **Company Lookup** | ✅ USED | ❌ Too slow | ❌ Too slow |
| **Background Research** | ❌ Sequential | ✅ USED | ⚠️ No orchestration |
| Latency | <1s | 5-15s | 5-30s |
| Cost (per execution) | $0.0002 | $0.00087 | $0.0003 |
| Complexity | Simple | High | Medium |
| Error handling | Basic | Advanced | Good |
| Parallel execution | ❌ No | ✅ Yes | ❌ No |
| Visual monitoring | Basic | ✅ Excellent | Limited |
| Progress tracking | ❌ No | ✅ Yes | ❌ No |

### Decision: Hybrid Approach ✅

**Why Step Functions for Background Research:**

1. **Parallel Execution**
   - Filing History + Officers + PSC + Sanctions run simultaneously
   - Total time: ~5-8s (vs 13-15s sequential)
   - Better user experience

2. **Built-in Retry Logic**
   - Each API call retries independently with exponential backoff
   - One service failure doesn't block others
   - Graceful degradation

3. **Visual Monitoring**
   - See exactly which step failed in AWS Console
   - Real-time execution tracking
   - Easy debugging

4. **User Experience**
   - Can show progress: "Checking filing history... ✓ Complete"
   - User knows system is working
   - Clear feedback on completion time

5. **Cost Justification**
   - User-initiated (not bulk operations)
   - Only ~1000 executions/month = $0.87
   - Worth it for better UX and reliability

**Why NOT Step Functions for Company Lookup:**
- User waits for response (latency critical)
- Single API call (no orchestration needed)
- Cost inefficient for simple operation

**Why NOT SQS:**
- No orchestration capabilities
- Can't run tasks in parallel
- No built-in retry per task
- Harder to track progress

### Implementation

**Synchronous Path (Fast Lookup):**
```
Core Stack Landing Page
  ↓
  User inputs company number
  ↓
  GET /company/12345678 → CompanyLookup Lambda → 2s response
  ↓
  Display company info
  ↓
  User clicks "Confirm and research company background"
```

**Asynchronous Path (Deep Research):**
```
POST /research/company → TriggerResearch Lambda
  ↓
  Start Step Functions workflow
  ↓
  Parallel branches (5-8s):
    ├─ Filing History Lambda
    ├─ Officers Lambda  
    ├─ PSC Lambda
    └─ Sanctions Lambda
  ↓
  Aggregate Results Lambda → Calculate risk score
  ↓
  Store Results Lambda → Save to DynamoDB
  ↓
  SNS Notification → User receives email/alert
```

---

## 🚀 DEPLOYMENT STRATEGY

### Phase 1: Core Companies House Integration + Health Check (Week 1)

**Goal:** Deploy basic Companies House lookup with caching + health endpoint for Core Stack

**Resources to Deploy:**
1. DynamoDB Tables:
   - `fiscalshield-dc-dev-FilingEvents`
   - `fiscalshield-dc-dev-CompanyEvents`

2. Secrets:
   - `fiscalshield-dc-dev-CompaniesHouseAPI`

3. Lambda Functions:
   - `fiscalshield-dc-dev-HealthCheck` ← NEW (enables Core Stack detection)
   - `fiscalshield-dc-dev-CompanyLookup`
   - `fiscalshield-dc-dev-FilingHistory`
   - `fiscalshield-dc-dev-Officers`

4. API Gateway:
   - `GET /health` ← NEW (for Core Stack)
   - `GET /company/{company_number}`
   - `GET /filing-history/{company_number}`
   - `GET /officers/{company_number}`

**Success Criteria:**
- API returns company data in <3s (cache miss)
- API returns company data in <500ms (cache hit)
- Health check returns 200 OK
- Core Stack can detect availability
- Cache hit ratio >70% after 24 hours

---

### Phase 2: Step Functions Workflow + Background Research (Week 2)

**Goal:** Add Step Functions orchestration for user-triggered deep research

**New Resources:**
1. Step Functions State Machine:
   - `fiscalshield-dc-dev-CompanyResearch`

2. Lambda Functions:
   - `fiscalshield-dc-dev-TriggerResearch` (starts workflow)
   - `fiscalshield-dc-dev-CheckCache` (Step Functions task)
   - `fiscalshield-dc-dev-AggregateResults` (Step Functions task)
   - `fiscalshield-dc-dev-StoreResults` (Step Functions task)
   - `fiscalshield-dc-dev-PSCLookup` (parallel branch)

3. SNS Topic:
   - `fiscalshield-dc-dev-ResearchComplete` (user notifications)

4. API Gateway:
   - `POST /research/company` (trigger background research)
   - `GET /research/status/{execution_arn}` (optional - check progress)

**Success Criteria:**
- Step Functions workflow executes successfully
- Parallel branches complete in 5-8 seconds
- Failed branches don't block other branches
- User receives notification when complete
- Aggregated risk score calculated correctly

---

### Phase 3: Enhanced Officers & PSC (Week 3)

**Goal:** Add sanctions check and enhanced risk analysis

**New Resources:**
1. Lambda Functions:
   - `fiscalshield-dc-dev-SanctionsCheck` (future - placeholder OK)
   - Enhanced officers risk scoring logic

2. Step Functions Update:
   - Add Sanctions branch to parallel execution

**Success Criteria:**
- Officer risk scores calculated correctly
- PSC data cached with 7-day TTL
- Disqualified director checks operational
- Sanctions check integrated (or gracefully skipped if not ready)

---

### Phase 4: HMRC Integration (Week 4-5)

**Goal:** Add HMRC VAT data collection

**New Resources:**
1. Lambda Functions:
   - `fiscalshield-dc-dev-PSCLookup`
   - Enhanced officers risk scoring

2. API Gateway:
   - `/companies-house/psc/{company_number}`

**Success Criteria:**
- Officer risk scores calculated correctly
- PSC data cached with 7-day TTL
- Disqualified director checks operational

### Phase 3: HMRC Integration (Week 3-4)

**Goal:** Add HMRC VAT data collection

**New Resources:**
1. DynamoDB Table:
   - `fiscalshield-dc-dev-HMRCData`

2. Secrets:
   - `fiscalshield-dc-dev-HMRCAPI`

3. Lambda Functions:
   - `fiscalshield-dc-dev-VATObligations`
   - `fiscalshield-dc-dev-VATReturns`
   - OAuth token refresh handler

4. API Gateway:
   - `/hmrc/vat/{vrn}/obligations`
   - `/hmrc/vat/{vrn}/returns`

**Success Criteria:**
- HMRC OAuth flow working
- VAT obligations fetched successfully
- Overdue obligations identified and alerted

### Phase 4: Optimization & Monitoring (Week 5)

**Goal:** Add cache maintenance and monitoring

**New Resources:**
1. Lambda Functions:
   - `fiscalshield-dc-dev-CacheMaintenance`

2. EventBridge Rules:
   - Daily cache cleanup (2 AM UTC)
   - Bulk company refresh (3 AM UTC)

3. CloudWatch Dashboards:
   - Cache hit ratio metrics
   - API latency tracking
   - Cost tracking per client

**Success Criteria:**
- Cache hit ratio >80%
- Average response time <500ms
- Monthly cost <$15 for 1,000 clients

### Phase 5: Production Deployment

**Staging Validation:**
```bash
# Deploy to staging
./scripts/deploy-data-collection-stack.sh -Environment staging

# Run integration tests
npm run test:integration:staging

# Load testing
artillery run load-test-data-collection.yml

# Validate costs
aws ce get-cost-and-usage --time-period Start=2025-10-01,End=2025-10-31
```

**Production Deployment:**
```bash
# Deploy to production
./scripts/deploy-data-collection-stack.sh -Environment prod

# Blue-green deployment pattern
aws apigatewayv2 update-stage --stage-name prod --deployment-id $NEW_DEPLOYMENT_ID

# Monitor for 24 hours
# Rollback if error rate >1%
```

---

## 🧪 TESTING STRATEGY

### Unit Tests (Lambda Functions)

```python
# test_companies_house_lambda.py
def test_cache_hit():
    """Test that cached data is returned without API call"""
    # Mock DynamoDB with fresh cache entry
    # Call Lambda
    # Assert no API call made
    # Assert cached data returned

def test_cache_miss():
    """Test that API is called when cache is empty"""
    # Mock DynamoDB with no cache entry
    # Mock Companies House API
    # Call Lambda
    # Assert API called once
    # Assert data cached

def test_expired_cache():
    """Test that expired cache triggers refresh"""
    # Mock DynamoDB with expired cache entry
    # Mock Companies House API
    # Call Lambda
    # Assert API called
    # Assert cache updated

def test_force_refresh():
    """Test ?refresh=true bypasses cache"""
    # Mock DynamoDB with fresh cache
    # Mock Companies House API
    # Call Lambda with refresh=true
    # Assert API called despite fresh cache
```

### Integration Tests (End-to-End)

```javascript
// test/integration/data-collection.test.js
describe('Data Collection Stack', () => {
  
  test('Company lookup flow', async () => {
    const companyNumber = '12345678';
    
    // First call - cache miss
    const response1 = await fetch(
      `${API_URL}/companies-house/company/${companyNumber}`
    );
    expect(response1.status).toBe(200);
    const data1 = await response1.json();
    expect(data1.cache_status).toBe('miss');
    
    // Second call - cache hit
    const response2 = await fetch(
      `${API_URL}/companies-house/company/${companyNumber}`
    );
    const data2 = await response2.json();
    expect(data2.cache_status).toBe('hit');
    expect(data2.company_number).toBe(companyNumber);
  });
  
  test('Filing history with compliance score', async () => {
    const response = await fetch(
      `${API_URL}/companies-house/filing-history/12345678`
    );
    const data = await response.json();
    
    expect(data.compliance_score).toBeGreaterThanOrEqual(1);
    expect(data.compliance_score).toBeLessThanOrEqual(10);
    expect(data.filings).toBeInstanceOf(Array);
    expect(data.risk_level).toMatch(/LOW|MEDIUM|HIGH/);
  });
  
  test('Cross-stack access from Analytics', async () => {
    // Simulate Analytics Stack reading cached data
    const tableName = `fiscalshield-dc-dev-FilingEvents`;
    const result = await dynamodb.getItem({
      TableName: tableName,
      Key: { company_number: '12345678' }
    });
    
    expect(result.Item).toBeDefined();
    expect(result.Item.compliance_score).toBeDefined();
  });
});
```

### Load Testing

```yaml
# load-test-data-collection.yml
config:
  target: "https://api.fiscalshield.com"
  phases:
    - duration: 60
      arrivalRate: 10  # 10 requests per second
    - duration: 120
      arrivalRate: 50  # Ramp to 50 req/s
  
scenarios:
  - name: "Company lookup"
    flow:
      - get:
          url: "/companies-house/company/12345678"
      - think: 2
      - get:
          url: "/companies-house/filing-history/12345678"
```

**Success Criteria:**
- P95 latency <2 seconds
- Error rate <0.1%
- Cache hit ratio >75%

---

## 📊 MONITORING & ALERTS

### CloudWatch Metrics

**Custom Metrics to Track:**
```python
# In Lambda code
cloudwatch.put_metric_data(
    Namespace='FiscalShield/DataCollection',
    MetricData=[
        {
            'MetricName': 'CacheHitRate',
            'Value': cache_hits / total_requests,
            'Unit': 'Percent',
            'Dimensions': [
                {'Name': 'Environment', 'Value': environment},
                {'Name': 'DataSource', 'Value': 'CompaniesHouse'}
            ]
        },
        {
            'MetricName': 'ExternalAPICalls',
            'Value': 1,
            'Unit': 'Count',
            'Dimensions': [
                {'Name': 'API', 'Value': 'CompaniesHouse'},
                {'Name': 'Endpoint', 'Value': 'filing-history'}
            ]
        }
    ]
)
```

### CloudWatch Dashboard

**Widgets:**
1. Cache Hit Ratio (last 24 hours)
2. API Latency (P50, P95, P99)
3. External API Call Count (per endpoint)
4. Error Rate (percentage)
5. Cost Projection (current spend × 30 days)
6. Top 10 Most Queried Companies

### Alerts

```yaml
# CloudWatch Alarms
Alarms:
  HighErrorRate:
    MetricName: Errors
    Threshold: 10
    Period: 300  # 5 minutes
    EvaluationPeriods: 2
    Statistic: Sum
    Action: SNS notification to ops team
    
  LowCacheHitRate:
    MetricName: CacheHitRate
    Threshold: 50  # Alert if <50%
    Period: 3600  # 1 hour
    ComparisonOperator: LessThanThreshold
    Action: SNS notification
    
  HighExternalAPICalls:
    MetricName: ExternalAPICalls
    Threshold: 1000
    Period: 3600  # Alert if >1000 calls/hour
    Action: SNS notification (possible cache failure)
    
  HighLatency:
    MetricName: Duration
    Threshold: 5000  # 5 seconds
    Statistic: p95
    Period: 300
    Action: SNS notification
```

---

## 🔒 SECURITY CONSIDERATIONS

### IAM Policies

**Lambda Execution Role:**
```yaml
DataCollectionLambdaRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    Policies:
      - PolicyName: DataCollectionPolicy
        PolicyDocument:
          Statement:
            # DynamoDB access - scoped to specific tables
            - Effect: Allow
              Action:
                - dynamodb:GetItem
                - dynamodb:PutItem
                - dynamodb:Query
                - dynamodb:UpdateItem
              Resource:
                - !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/fiscalshield-dc-${Environment}-FilingEvents"
                - !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/fiscalshield-dc-${Environment}-CompanyEvents"
            
            # Secrets Manager - scoped to data collection secrets only
            - Effect: Allow
              Action:
                - secretsmanager:GetSecretValue
              Resource:
                - !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:fiscalshield-dc-${Environment}-CompaniesHouseAPI-*"
                - !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:fiscalshield-dc-${Environment}-HMRCAPI-*"
            
            # CloudWatch metrics
            - Effect: Allow
              Action:
                - cloudwatch:PutMetricData
              Resource: "*"
              Condition:
                StringEquals:
                  cloudwatch:namespace: "FiscalShield/DataCollection"
```

### API Gateway Authentication

```yaml
# Cognito User Pool Authorizer
APIGatewayAuthorizer:
  Type: AWS::ApiGateway::Authorizer
  Properties:
    Name: CognitoAuthorizer
    Type: COGNITO_USER_POOLS
    IdentitySource: method.request.header.Authorization
    RestApiId: !Ref DataCollectionAPI
    ProviderARNs:
      - !GetAtt CognitoUserPool.Arn

# API Key for service-to-service calls (optional)
APIKey:
  Type: AWS::ApiGateway::ApiKey
  Properties:
    Name: !Sub "fiscalshield-dc-data-collection-${Environment}"
    Enabled: true
```

### Data Encryption

**At Rest:**
- DynamoDB: Encryption enabled by default (AWS managed keys)
- Secrets Manager: Encrypted with AWS KMS

**In Transit:**
- API Gateway: HTTPS only
- Companies House API: HTTPS only
- HMRC API: HTTPS only

### Client Isolation

**Critical:** All DynamoDB queries must include `client_id`

```python
# BAD - returns data across all clients
response = table.query(
    KeyConditionExpression='company_number = :num',
    ExpressionAttributeValues={':num': company_number}
)

# GOOD - client-isolated query
response = table.query(
    KeyConditionExpression='company_number = :num AND client_id = :client',
    ExpressionAttributeValues={
        ':num': company_number,
        ':client': client_id
    }
)
```

---

## 📦 ADDITIONAL CONSIDERATIONS

### Error Handling Best Practices

```python
def lambda_handler(event, context):
    try:
        # Extract parameters
        company_number = event['pathParameters']['company_number']
        client_id = get_client_id_from_token(event['headers'])
        
        # Validate inputs
        if not is_valid_company_number(company_number):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid company number format'})
            }
        
        # Business logic
        result = fetch_company_data(company_number, client_id)
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except ExternalAPIError as e:
        # External API failure - return 502 Bad Gateway
        logger.error(f"Companies House API failed: {e}")
        return {
            'statusCode': 502,
            'body': json.dumps({
                'error': 'External API unavailable',
                'message': 'Please try again later'
            })
        }
        
    except RateLimitError as e:
        # Rate limit hit - return 429
        return {
            'statusCode': 429,
            'body': json.dumps({
                'error': 'Rate limit exceeded',
                'retry_after': 60
            })
        }
        
    except Exception as e:
        # Unexpected error - return 500
        logger.exception("Unexpected error in lambda")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'request_id': context.request_id
            })
        }
```

### Logging Standards

```python
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log_event(event_type, data):
    """Structured logging for easy CloudWatch Insights queries"""
    log_entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'event_type': event_type,
        'environment': os.environ['ENVIRONMENT'],
        'data': data
    }
    logger.info(json.dumps(log_entry))

# Usage
log_event('CACHE_HIT', {
    'company_number': '12345678',
    'client_id': 'client-abc',
    'age_hours': 12
})

log_event('EXTERNAL_API_CALL', {
    'api': 'companies_house',
    'endpoint': 'filing_history',
    'company_number': '12345678',
    'duration_ms': 1234
})
```

### CloudWatch Insights Queries

```sql
-- Cache hit rate by hour
fields @timestamp, data.event_type
| filter data.event_type in ['CACHE_HIT', 'CACHE_MISS']
| stats count(*) as total, 
        sum(data.event_type = 'CACHE_HIT') as hits 
        by bin(@timestamp, 1h)
| eval hit_rate = (hits / total) * 100

-- Slowest API calls
fields @timestamp, data.duration_ms, data.company_number
| filter data.event_type = 'EXTERNAL_API_CALL'
| sort data.duration_ms desc
| limit 20

-- Error rate by client
fields @timestamp, data.client_id, data.error
| filter data.event_type = 'ERROR'
| stats count(*) as error_count by data.client_id
| sort error_count desc
```

### API Rate Limiting

```python
from functools import wraps
import time

class RateLimiter:
    """Token bucket rate limiter"""
    def __init__(self, rate=600, per=300):  # 600 requests per 5 minutes
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.time()
    
    def allow_request(self):
        current = time.time()
        time_passed = current - self.last_check
        self.last_check = current
        self.allowance += time_passed * (self.rate / self.per)
        
        if self.allowance > self.rate:
            self.allowance = self.rate
        
        if self.allowance < 1.0:
            return False
        
        self.allowance -= 1.0
        return True

rate_limiter = RateLimiter()

def with_rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not rate_limiter.allow_request():
            raise RateLimitError("API rate limit exceeded")
        return func(*args, **kwargs)
    return wrapper

@with_rate_limit
def call_companies_house_api(endpoint):
    # API call implementation
    pass
```

### Multi-Region Considerations

**Future Enhancement:** Deploy Data Collection Stack to multiple regions

```yaml
# US Region
fiscalshield-dc-prod-FilingEvents (us-east-1)
fiscalshield-dc-prod-CompanyEvents (us-east-1)

# EU Region
fiscalshield-dc-prod-FilingEvents (eu-west-1)
fiscalshield-dc-prod-CompanyEvents (eu-west-1)
```

**Benefits:**
- Lower latency for global users
- Disaster recovery capability
- Data residency compliance (GDPR)

**Implementation:**
```bash
# Deploy to multiple regions
AWS_REGION=eu-west-1 ./scripts/deploy-data-collection-stack.sh -Environment prod
AWS_REGION=us-east-1 ./scripts/deploy-data-collection-stack.sh -Environment prod

# Use Route 53 latency-based routing
aws route53 create-health-check --type HTTPS --resource-path /health
```

---

## ✅ SUCCESS CRITERIA

### Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Cache Hit Ratio | >80% | CloudWatch Metrics |
| P95 Response Time (cache hit) | <500ms | API Gateway metrics |
| P95 Response Time (cache miss) | <3s | API Gateway metrics |
| Error Rate | <0.1% | CloudWatch Alarms |
| External API Calls | <20% of total requests | Custom metric |
| Monthly Cost | <$15/1000 clients | AWS Cost Explorer |

### Business Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Data Freshness | <24 hours old | DynamoDB TTL tracking |
| Companies House Coverage | 100% of UK companies | API success rate |
| Risk Detection Accuracy | >90% | Manual validation |
| User Satisfaction | >4.5/5 | Frontend feedback |

### Deployment Success

| Criteria | Definition |
|----------|------------|
| Zero Downtime | No service interruption during deployment |
| Rollback Capability | Can revert to previous version in <5 minutes |
| Independent Operation | Stack functions without other stacks |
| Cross-Stack Access | Analytics can read cached data |

---

## 🚦 GO-LIVE CHECKLIST

### Pre-Deployment
- [ ] All Lambda functions tested locally
- [ ] Integration tests passing (100% coverage)
- [ ] Load testing completed (50 req/s sustained)
- [ ] Security review completed
- [ ] IAM policies follow least privilege
- [ ] Secrets rotated and stored in Secrets Manager
- [ ] Cost estimation validated (<$15/month for 1000 clients)

### Deployment
- [ ] Deploy to dev environment
- [ ] Validate dev deployment (smoke tests)
- [ ] Deploy to staging environment
- [ ] Run full integration test suite in staging
- [ ] Load test staging environment
- [ ] Deploy to production (blue-green deployment)
- [ ] Monitor production for 24 hours
- [ ] Validate cache behavior in production

### Post-Deployment
- [ ] CloudWatch alarms configured and tested
- [ ] Dashboard created for monitoring
- [ ] Runbook created for common issues
- [ ] On-call team trained on stack architecture
- [ ] Documentation updated
- [ ] Frontend team notified of API endpoints
- [ ] Analytics Stack team informed of table names

---

## 📞 SUPPORT & TROUBLESHOOTING

### Common Issues

**Issue: High API latency**
- Check: Cache hit ratio (should be >70%)
- Action: Verify DynamoDB table performance
- Action: Check Companies House API status
- Escalation: If >5s P95 latency, increase Lambda memory

**Issue: Low cache hit rate**
- Check: TTL configuration (should be 24 hours)
- Check: Cache maintenance Lambda running daily
- Action: Investigate if high client_id cardinality
- Action: Review force refresh usage

**Issue: External API errors**
- Check: Companies House API key validity
- Check: Rate limit status (600/5min)
- Action: Verify Secrets Manager permissions
- Escalation: Contact Companies House support

### Rollback Procedure

```bash
# Identify previous working deployment
aws cloudformation describe-stack-events \
  --stack-name fiscalshield-dc-prod

# Rollback stack
aws cloudformation update-stack \
  --stack-name fiscalshield-dc-prod \
  --use-previous-template \
  --parameters ParameterKey=DeploymentId,UsePreviousValue=true

# Monitor rollback
aws cloudformation wait stack-update-complete \
  --stack-name fiscalshield-dc-prod
```

---

## 📚 REFERENCES

### External Documentation
- [Companies House API Documentation](https://developer.company-information.service.gov.uk/)
- [HMRC API Documentation](https://developer.service.hmrc.gov.uk/)
- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [DynamoDB Caching Strategies](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html)

### Internal Documentation
- Core Stack Documentation
- Analytics Stack Documentation
- FiscalShield Architecture Overview
- Multi-Tenant Security Guidelines

---

**Document Version:** 1.1  
**Last Updated:** October 25, 2025  
**Next Review:** November 2025  
**Owner:** FiscalShield Backend Team
