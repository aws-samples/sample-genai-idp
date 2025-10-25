"""
Constants for Data Collection Stack

Convention-based naming ensures predictable cross-stack access.
All resources follow: fiscalshield-dc-{environment}-{ResourceName}
"""

import os

# Environment
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

# DynamoDB Table Names (convention-based)
FILING_EVENTS_TABLE = f"fiscalshield-dc-{ENVIRONMENT}-FilingEvents"
COMPANY_EVENTS_TABLE = f"fiscalshield-dc-{ENVIRONMENT}-CompanyEvents"
HMRC_DATA_TABLE = f"fiscalshield-dc-{ENVIRONMENT}-HMRCData"

# Secrets Manager Secret Names
COMPANIES_HOUSE_SECRET = f"fiscalshield-dc-{ENVIRONMENT}-CompaniesHouseAPI"
HMRC_SECRET = f"fiscalshield-dc-{ENVIRONMENT}-HMRCAPI"
BANKING_SECRET = f"fiscalshield-dc-{ENVIRONMENT}-BankingAPI"

# Lambda Function Names
COMPANY_LOOKUP_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-CompanyLookup"
FILING_HISTORY_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-FilingHistory"
OFFICERS_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-Officers"
PSC_LOOKUP_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-PSCLookup"
VAT_OBLIGATIONS_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-VATObligations"
CACHE_MAINTENANCE_FUNCTION = f"fiscalshield-dc-{ENVIRONMENT}-CacheMaintenance"

# Cache TTL (in hours)
CACHE_TTL_COMPANY_PROFILE = 24
CACHE_TTL_FILING_HISTORY = 24
CACHE_TTL_OFFICERS = 24
CACHE_TTL_PSC = 168  # 7 days
CACHE_TTL_VAT_OBLIGATIONS = 1
CACHE_TTL_VAT_RETURNS = 720  # 30 days

# API Rate Limits
COMPANIES_HOUSE_RATE_LIMIT = 600  # requests per 5 minutes
COMPANIES_HOUSE_RATE_WINDOW = 300  # seconds

# Risk Levels
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"

# Compliance Score Range
MIN_COMPLIANCE_SCORE = 1
MAX_COMPLIANCE_SCORE = 10
