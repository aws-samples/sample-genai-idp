# FiscalShield Data Collection Stack

**Stack Name:** `fiscalshield-dc`  
**Purpose:** Fetch, cache, and manage external data sources (Companies House, HMRC, Banking APIs)  
**Status:** Development Phase

## Architecture

This stack operates independently from other FiscalShield stacks and provides:

- **External API Integrations**: Companies House, HMRC, Banking APIs
- **Smart Caching**: DynamoDB-based caching with intelligent TTL strategies
- **REST APIs**: API Gateway endpoints for frontend consumption
- **Compliance Scoring**: Automated risk analysis for UK companies
- **Multi-Tenant**: Client-aware data isolation

## Directory Structure

```
stacks/data-collection/
├── template.yaml          # CloudFormation/SAM template
├── samconfig.toml         # SAM deployment configuration
├── parameters/            # Environment-specific parameters
│   ├── dev.json
│   ├── staging.json
│   └── prod.json
└── README.md             # This file
```

## Resources Created

### DynamoDB Tables
- `fiscalshield-dc-{env}-FilingEvents` - Companies House filing history cache
- `fiscalshield-dc-{env}-CompanyEvents` - Company information and officers cache
- `fiscalshield-dc-{env}-HMRCData` - HMRC VAT returns cache (future)

### Lambda Functions
- `fiscalshield-dc-{env}-CompanyLookup` - Fetch company profile
- `fiscalshield-dc-{env}-FilingHistory` - Fetch filing history with compliance scoring
- `fiscalshield-dc-{env}-Officers` - Fetch company officers with risk analysis
- `fiscalshield-dc-{env}-PSCLookup` - Fetch persons with significant control
- `fiscalshield-dc-{env}-VATObligations` - Fetch HMRC VAT obligations (future)
- `fiscalshield-dc-{env}-CacheMaintenance` - Scheduled cache cleanup and refresh

### Secrets
- `fiscalshield-dc-{env}-CompaniesHouseAPI` - Companies House API credentials
- `fiscalshield-dc-{env}-HMRCAPI` - HMRC API OAuth credentials (future)

### API Gateway
- `/companies-house/company/{company_number}` - Company lookup
- `/companies-house/filing-history/{company_number}` - Filing history
- `/companies-house/officers/{company_number}` - Company officers
- `/companies-house/psc/{company_number}` - PSC lookup
- `/hmrc/vat/{vrn}/obligations` - VAT obligations (future)

## Deployment

### Prerequisites
```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Configure AWS credentials
aws configure

# Set environment variables
export ENVIRONMENT=dev
```

### Deploy to Dev
```bash
cd stacks/data-collection
sam build
sam deploy --config-env dev --parameter-overrides ParameterKey=Environment,ParameterValue=dev
```

### Deploy to Staging
```bash
sam deploy --config-env staging --parameter-overrides ParameterKey=Environment,ParameterValue=staging
```

### Deploy to Production
```bash
sam deploy --config-env prod --parameter-overrides ParameterKey=Environment,ParameterValue=prod
```

## Configuration

### Environment Parameters

Create parameter files for each environment:

**parameters/dev.json**
```json
{
  "Environment": "dev",
  "CacheTTLHours": "24",
  "CompaniesHouseRateLimit": "600"
}
```

### Secrets Setup

Store Companies House API key in Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name fiscalshield-dc-dev-CompaniesHouseAPI \
  --secret-string '{
    "api_key": "your-api-key",
    "base_url": "https://api.company-information.service.gov.uk",
    "rate_limit": 600,
    "rate_limit_window": 300
  }'
```

## Testing

### Unit Tests
```bash
cd /home/josian/git/fiscalshield-idp-core
pytest tests/data_collection/unit/ -v
```

### Integration Tests
```bash
pytest tests/data_collection/integration/ -v --env=dev
```

### Load Tests
```bash
artillery run tests/data_collection/load/artillery-config.yml
```

## Monitoring

### CloudWatch Metrics
- `FiscalShield/DataCollection/CacheHitRate` - Cache efficiency
- `FiscalShield/DataCollection/ExternalAPICalls` - API usage tracking
- `FiscalShield/DataCollection/ComplianceScore` - Company risk metrics

### CloudWatch Alarms
- High error rate (>10 errors in 5 minutes)
- Low cache hit rate (<50%)
- High API latency (P95 >5 seconds)

## Cost Estimation

For 1,000 active clients:
- Lambda: ~$2/month
- DynamoDB: ~$1.50/month
- Secrets Manager: ~$1.50/month
- API Gateway: ~$3.50/month
- CloudWatch: ~$2.50/month

**Total: ~$11/month**

## Support

For issues or questions, contact the FiscalShield Backend Team.

## References

- [Implementation Plan](../../docs/Data_Collection_Stack_Implementation_Plan.md)
- [Companies House API Docs](https://developer.company-information.service.gov.uk/)
- [HMRC API Docs](https://developer.service.hmrc.gov.uk/)
