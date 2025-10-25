"""
FiscalShield Data Collection Stack

This module provides data collection services for external APIs including:
- Companies House (UK company data)
- HMRC (VAT and tax data)
- Banking APIs (future)

All data is cached in DynamoDB with intelligent TTL strategies.
"""

__version__ = "0.1.0"
