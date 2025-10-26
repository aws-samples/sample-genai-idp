// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { useHistory } from 'react-router-dom';
import {
  Container,
  Header,
  SpaceBetween,
  FormField,
  Input,
  Button,
  Box,
  Alert,
  Spinner,
  ColumnLayout,
  StatusIndicator,
  ExpandableSection,
  Badge,
  Table,
} from '@awsui/components-react';
import { Logger } from 'aws-amplify';

import {
  checkDataCollectionHealth,
  lookupCompany,
  triggerBackgroundResearch,
  lookupOfficers,
  checkFilingHistory,
} from '../../services/dataCollection';
import useAppContext from '../../contexts/app';
import { DOCUMENTS_PATH } from '../../routes/constants';

import '@awsui/global-styles/index.css';

const logger = new Logger('CompanySelect');

const CompanySelect = () => {
  const history = useHistory();
  const { user } = useAppContext();

  const [companyNumber, setCompanyNumber] = useState('');
  const [companyData, setCompanyData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isResearching, setIsResearching] = useState(false);
  const [error, setError] = useState('');
  const [isDataCollectionAvailable, setIsDataCollectionAvailable] = useState(null);
  const [healthCheckComplete, setHealthCheckComplete] = useState(false);

  // Officers state
  const [officersData, setOfficersData] = useState(null);
  const [officersLoading, setOfficersLoading] = useState(false);
  const [officersError, setOfficersError] = useState(null);

  // Filing history state
  const [filingHistory, setFilingHistory] = useState(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [showFilingHistory, setShowFilingHistory] = useState(false);

  // Check if Data Collection Stack is available on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const available = await checkDataCollectionHealth();
        setIsDataCollectionAvailable(available);
        logger.debug('Data Collection availability:', available);
      } catch (err) {
        logger.warn('Health check failed:', err);
        setIsDataCollectionAvailable(false);
      } finally {
        setHealthCheckComplete(true);
      }
    };

    checkHealth();
  }, []);

  const handleCompanyNumberChange = (event) => {
    const { value } = event.detail;
    // Clean the input (remove spaces, ensure uppercase)
    const cleanValue = value.replace(/\s+/g, '').toUpperCase();
    // Remove any non-alphanumeric characters and limit to 8 characters
    const sanitized = cleanValue.replace(/[^A-Z0-9]/g, '').slice(0, 8);
    setCompanyNumber(sanitized);
    setCompanyData(null);
    setError('');
    setOfficersData(null);
    setFilingHistory(null);
  };

  const handleSearch = async () => {
    if (!companyNumber || companyNumber.length < 6) {
      setError('Please enter a valid company number (6-8 characters)');
      return;
    }

    setIsLoading(true);
    setError('');
    setCompanyData(null);
    setOfficersData(null);
    setFilingHistory(null);

    try {
      const data = await lookupCompany(companyNumber);
      logger.debug('Company data received:', data);
      setCompanyData(data);
    } catch (err) {
      logger.error('Error looking up company:', err);
      if (err.message.includes('404')) {
        setError('Company not found. Please check the company number and try again.');
      } else {
        setError('Failed to lookup company. Please try again later.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleCheckOfficers = async () => {
    if (!companyNumber) {
      setOfficersError('No company number available');
      return;
    }

    setOfficersLoading(true);
    setOfficersError(null);
    setOfficersData(null);

    try {
      const result = await lookupOfficers(companyNumber);
      logger.debug('Officers data:', result);

      if (result.total_officers !== undefined) {
        setOfficersData(result);
      } else {
        setOfficersError('Failed to fetch officers data');
      }
    } catch (err) {
      logger.error('Officers check failed:', err);

      if (err.message.includes('404')) {
        setOfficersError('No officers found for this company');
      } else {
        setOfficersError('Failed to check officers');
      }
    } finally {
      setOfficersLoading(false);
    }
  };

  const handleCheckFilingHistory = async () => {
    if (!companyNumber) {
      setError('No company number available');
      return;
    }

    // Validate company number format
    const cleanCompanyNumber = companyNumber.trim();
    if (cleanCompanyNumber.includes(' ') || !/^[A-Z0-9]+$/.test(cleanCompanyNumber)) {
      setError(`Invalid company number format: ${cleanCompanyNumber}. Expected alphanumeric ID.`);
      return;
    }

    setFilingLoading(true);
    setError(null);

    try {
      const response = await checkFilingHistory(cleanCompanyNumber);
      logger.debug('Filing history response:', response);
      setFilingHistory(response);
      setShowFilingHistory(true);
    } catch (err) {
      logger.error('Filing history check failed:', err);
      setError('Failed to fetch filing history');
    } finally {
      setFilingLoading(false);
    }
  };

  const handleConfirmAndResearch = async () => {
    if (!companyData) return;

    // Store company selection (would be saved to DynamoDB via API)
    // For now, we'll store in localStorage as temporary solution
    const companyContext = {
      company_number: companyData.company_number,
      company_name: companyData.company_name,
      selected_at: new Date().toISOString(),
      user_id: user?.username || 'unknown',
    };

    localStorage.setItem('active_company', JSON.stringify(companyContext));
    logger.debug('Company context saved:', companyContext);

    // If Data Collection Stack is available, trigger background research
    if (isDataCollectionAvailable) {
      setIsResearching(true);
      try {
        await triggerBackgroundResearch({
          company_number: companyData.company_number,
          company_name: companyData.company_name,
          user_id: user?.username || 'unknown',
          client_id: user?.username || 'unknown', // TODO: Replace with actual client_id
        });
        logger.debug('Background research initiated');
      } catch (err) {
        logger.warn('Failed to trigger background research:', err);
        // Non-blocking error - still proceed to documents
      }
    }

    // Redirect to documents page
    setTimeout(() => {
      history.push(DOCUMENTS_PATH);
    }, 1000);
  };

  const handleKeyPress = (event) => {
    if (event.detail.key === 'Enter') {
      handleSearch();
    }
  };

  const getRiskColor = (level) => {
    switch (level) {
      case 'HIGH':
        return 'red';
      case 'MEDIUM':
        return 'grey';
      case 'LOW':
        return 'green';
      default:
        return 'blue';
    }
  };

  const getScoreType = (score) => {
    if (score >= 8) return 'success';
    if (score >= 6) return 'warning';
    return 'error';
  };

  const renderRiskAnalysis = () => {
    if (!companyData?.risk_analysis) return null;

    const { risk_analysis: riskAnalysis } = companyData;

    return (
      <div style={{ borderTop: '1px solid #eee', paddingTop: '16px' }}>
        <Header variant="h3" description="Automated risk assessment based on Companies House data">
          🔍 Risk Analysis
        </Header>

        <SpaceBetween size="s">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Badge color={getRiskColor(riskAnalysis.risk_level)}>{riskAnalysis.risk_level} RISK</Badge>
            <Box>
              <Box variant="awsui-key-label">Risk Score</Box>
              <Box>{riskAnalysis.risk_score}/100</Box>
            </Box>
          </div>

          {riskAnalysis.risk_indicators && riskAnalysis.risk_indicators.length > 0 && (
            <Alert type="warning" header={`${riskAnalysis.risk_indicators.length} Risk Indicators Found`}>
              <ul style={{ margin: '0', paddingLeft: '20px' }}>
                {riskAnalysis.risk_indicators.map((indicator) => (
                  <li key={indicator}>{indicator}</li>
                ))}
              </ul>
            </Alert>
          )}

          {(!riskAnalysis.risk_indicators || riskAnalysis.risk_indicators.length === 0) && (
            <Alert type="success">No immediate risk factors detected from Companies House data.</Alert>
          )}

          {/* Enhanced Business Health Info */}
          {companyData.business_health && (
            <Box>
              <Box variant="awsui-key-label">Business Health Check</Box>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '14px' }}>
                <div>
                  <StatusIndicator type={companyData.business_health.has_insolvency_history ? 'error' : 'success'}>
                    {companyData.business_health.has_insolvency_history ? 'Has' : 'No'} insolvency history
                  </StatusIndicator>
                </div>
                <div>
                  <StatusIndicator type={companyData.business_health.has_charges ? 'warning' : 'success'}>
                    {companyData.business_health.has_charges ? 'Has' : 'No'} registered charges
                  </StatusIndicator>
                </div>
                <div>
                  <StatusIndicator type={companyData.business_health.has_been_liquidated ? 'error' : 'success'}>
                    {companyData.business_health.has_been_liquidated ? 'Has been' : 'Never'} liquidated
                  </StatusIndicator>
                </div>
                <div>
                  <StatusIndicator type={companyData.business_health.can_file ? 'success' : 'error'}>
                    {companyData.business_health.can_file ? 'Can' : 'Cannot'} file returns
                  </StatusIndicator>
                </div>
              </div>
            </Box>
          )}

          {/* Compliance Status */}
          {companyData.accounts && (
            <Box>
              <Box variant="awsui-key-label">Compliance Status</Box>
              <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                {companyData.accounts.overdue ? (
                  <Badge color="red">Accounts Overdue</Badge>
                ) : (
                  <Badge color="green">Accounts Up to Date</Badge>
                )}

                {companyData.confirmation_statement?.overdue ? (
                  <Badge color="red">Confirmation Overdue</Badge>
                ) : (
                  <Badge color="green">Confirmation Up to Date</Badge>
                )}
              </div>

              {companyData.accounts.next_due && (
                <div style={{ fontSize: '13px', color: '#666', marginTop: '4px' }}>
                  Next accounts due: {new Date(companyData.accounts.next_due).toLocaleDateString('en-GB')}
                </div>
              )}
            </Box>
          )}
        </SpaceBetween>
      </div>
    );
  };

  const renderOfficersAnalysis = () => {
    if (!officersData) return null;

    let alertType = 'success';
    if (officersData.risk_level === 'HIGH') {
      alertType = 'error';
    } else if (officersData.risk_level === 'MEDIUM') {
      alertType = 'warning';
    }

    return (
      <SpaceBetween size="m">
        <Alert type={alertType} header={`${officersData.risk_level} RISK (Score: ${officersData.risk_score})`}>
          <SpaceBetween size="xs">
            <div>
              <strong>Total Directors:</strong> {officersData.total_officers} ({officersData.active_officers} active)
            </div>

            {officersData.risk_indicators && officersData.risk_indicators.length > 0 && (
              <div>
                <strong>Risk Factors:</strong>
                <ul style={{ marginTop: '5px', marginBottom: '0', paddingLeft: '20px' }}>
                  {officersData.risk_indicators.map((indicator) => (
                    <li key={indicator}>{indicator}</li>
                  ))}
                </ul>
              </div>
            )}
          </SpaceBetween>
        </Alert>

        {officersData.officers && officersData.officers.length > 0 && (
          <ExpandableSection
            headerText={`Directors Details (${officersData.officers.length})`}
            defaultExpanded={officersData.risk_level === 'HIGH'}
          >
            {/* eslint-disable react/no-unstable-nested-components */}
            <Table
              columnDefinitions={[
                {
                  id: 'name',
                  header: 'Name',
                  cell: (officer) => (
                    <>
                      {officer.name}
                      {officer.risk_flag && <span style={{ color: '#d13212', marginLeft: '5px' }}>⚠️</span>}
                    </>
                  ),
                },
                {
                  id: 'role',
                  header: 'Role',
                  cell: (officer) => officer.officer_role,
                },
                {
                  id: 'appointed',
                  header: 'Appointed',
                  cell: (officer) => officer.appointed_on || '-',
                },
                {
                  id: 'status',
                  header: 'Status',
                  cell: (officer) => (
                    <StatusIndicator type={officer.is_active ? 'success' : 'stopped'}>
                      {officer.is_active ? 'Active' : 'Resigned'}
                    </StatusIndicator>
                  ),
                },
                {
                  id: 'nationality',
                  header: 'Nationality',
                  cell: (officer) => officer.nationality || '-',
                },
              ]}
              items={officersData.officers}
              loadingText="Loading officers..."
              sortingDisabled
              empty={
                <Box textAlign="center" color="inherit">
                  <b>No officers</b>
                </Box>
              }
            />
            {/* eslint-enable react/no-unstable-nested-components */}
          </ExpandableSection>
        )}
      </SpaceBetween>
    );
  };

  const renderFilingHistory = () => {
    if (!filingHistory) return null;

    return (
      <Container header={<Header variant="h3">Filing History Analysis</Header>}>
        <SpaceBetween size="m">
          <ColumnLayout columns={3}>
            <Box>
              <Box variant="awsui-key-label">Compliance Score</Box>
              <StatusIndicator type={getScoreType(filingHistory.compliance_score)}>
                {filingHistory.compliance_score}/10
              </StatusIndicator>
            </Box>
            <Box>
              <Box variant="awsui-key-label">Total Filings</Box>
              <div>{filingHistory.total_filings}</div>
            </Box>
            <Box>
              <Box variant="awsui-key-label">Overdue Filings</Box>
              <div>{filingHistory.overdue_filings}</div>
            </Box>
          </ColumnLayout>

          {filingHistory.risk_indicators?.length > 0 && (
            <Alert type="warning" header="Risk Indicators">
              <ul style={{ margin: 0, paddingLeft: '20px' }}>
                {filingHistory.risk_indicators.map((indicator) => (
                  <li key={indicator}>{indicator}</li>
                ))}
              </ul>
            </Alert>
          )}

          {filingHistory.recent_filings?.length > 0 && (
            /* eslint-disable react/no-unstable-nested-components */
            <Table
              columnDefinitions={[
                {
                  id: 'filing_type',
                  header: 'Filing Type',
                  cell: (item) => item.filing_type || 'N/A',
                },
                {
                  id: 'filing_date',
                  header: 'Filed Date',
                  cell: (item) => item.filing_date || 'N/A',
                },
                {
                  id: 'status',
                  header: 'Status',
                  cell: (item) => item.status || 'Filed',
                },
              ]}
              items={filingHistory.recent_filings}
              loadingText="Loading filings..."
              sortingDisabled
              empty={
                <Box textAlign="center" color="inherit">
                  <b>No filings</b>
                  <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                    No filing history available for this company.
                  </Box>
                </Box>
              }
            />
            /* eslint-enable react/no-unstable-nested-components */
          )}

          {filingHistory.next_due_date && (
            <Box>
              <Box variant="awsui-key-label">Next Filing Due</Box>
              <div>{new Date(filingHistory.next_due_date).toLocaleDateString('en-GB')}</div>
            </Box>
          )}
        </SpaceBetween>
      </Container>
    );
  };

  // Admin bypass function
  const handleAdminBypass = () => {
    logger.info('Admin bypass: Skipping company selection');
    // Store a placeholder company to maintain localStorage expectations
    localStorage.setItem(
      'selectedCompany',
      JSON.stringify({
        company_number: 'BYPASS',
        company_name: 'Admin Bypass - Direct Access',
        company_status: 'active',
        bypassed: true,
      }),
    );
    history.push(DOCUMENTS_PATH);
  };

  return (
    <Box padding={{ top: 'xxxl' }}>
      <SpaceBetween size="l">
        <Container
          header={
            <Header
              variant="h1"
              description="Enter a UK Companies House number to get started"
              actions={
                <Button variant="link" iconName="arrow-right" onClick={handleAdminBypass}>
                  Skip to Documents (Admin)
                </Button>
              }
            >
              Select Your Company
            </Header>
          }
        >
          <SpaceBetween size="l">
            {/* Health Check Status */}
            {healthCheckComplete && (
              <Alert
                type={isDataCollectionAvailable ? 'success' : 'info'}
                statusIconAriaLabel={isDataCollectionAvailable ? 'Success' : 'Info'}
                header={isDataCollectionAvailable ? 'Deep research available' : 'Basic search available'}
              >
                {isDataCollectionAvailable
                  ? 'Background company research is enabled. You will receive a notification when complete.'
                  : 'Background research is unavailable. You can still select your company and access documents.'}
              </Alert>
            )}

            {/* Search Form */}
            <FormField
              label="Company Number"
              description="Enter the 8-digit UK Companies House registration number"
              errorText={error}
            >
              <SpaceBetween size="xs" direction="horizontal">
                <Input
                  value={companyNumber}
                  onChange={handleCompanyNumberChange}
                  onKeyDown={handleKeyPress}
                  placeholder="12345678"
                  disabled={isLoading}
                  inputMode="text"
                  maxLength={8}
                />
                <Button
                  onClick={handleSearch}
                  loading={isLoading}
                  disabled={!companyNumber || companyNumber.length < 6}
                  variant="primary"
                >
                  Search
                </Button>
              </SpaceBetween>
            </FormField>

            {/* Company Details */}
            {companyData && (
              <Container header={<Header variant="h2">Company Details</Header>}>
                <SpaceBetween size="m">
                  <ColumnLayout columns={2} variant="text-grid">
                    <div>
                      <Box variant="awsui-key-label">Company Name</Box>
                      <div>{companyData.company_name}</div>
                    </div>
                    <div>
                      <Box variant="awsui-key-label">Company Number</Box>
                      <div>{companyData.company_number}</div>
                    </div>
                    <div>
                      <Box variant="awsui-key-label">Status</Box>
                      <div>
                        <StatusIndicator type={companyData.company_status === 'active' ? 'success' : 'warning'}>
                          {companyData.company_status?.toUpperCase() || 'UNKNOWN'}
                        </StatusIndicator>
                      </div>
                    </div>
                    <div>
                      <Box variant="awsui-key-label">Incorporation Date</Box>
                      <div>{companyData.date_of_creation || 'N/A'}</div>
                    </div>
                  </ColumnLayout>

                  {companyData.registered_office_address && (
                    <div>
                      <Box variant="awsui-key-label">Registered Office</Box>
                      <Box variant="p">
                        {[
                          companyData.registered_office_address.address_line_1,
                          companyData.registered_office_address.address_line_2,
                          companyData.registered_office_address.locality,
                          companyData.registered_office_address.region,
                          companyData.registered_office_address.postal_code,
                        ]
                          .filter(Boolean)
                          .join(', ')}
                      </Box>
                    </div>
                  )}

                  {/* Risk Analysis Section */}
                  {renderRiskAnalysis()}

                  {/* Directors Risk Analysis Section */}
                  {isDataCollectionAvailable && (
                    <div style={{ borderTop: '1px solid #eee', paddingTop: '16px' }}>
                      <Header
                        variant="h3"
                        description="Check company directors and risk indicators"
                        actions={
                          <Button
                            variant="primary"
                            loading={officersLoading}
                            onClick={handleCheckOfficers}
                            disabled={officersLoading}
                            iconName="search"
                          >
                            {officersData ? 'Refresh Directors' : 'Check Directors'}
                          </Button>
                        }
                      >
                        Directors Risk Analysis
                      </Header>

                      {officersError && (
                        <Alert type="warning" header="Directors Check">
                          {officersError}
                        </Alert>
                      )}

                      {officersData && renderOfficersAnalysis()}
                    </div>
                  )}

                  {/* Filing History Section */}
                  {isDataCollectionAvailable && (
                    <div style={{ borderTop: '1px solid #eee', paddingTop: '16px' }}>
                      <SpaceBetween size="s">
                        <SpaceBetween direction="horizontal" size="s">
                          <Button
                            variant="normal"
                            loading={filingLoading}
                            onClick={handleCheckFilingHistory}
                            iconName="search"
                          >
                            {filingLoading ? 'Analyzing Filing History...' : 'Check Filing History'}
                          </Button>

                          {showFilingHistory && filingHistory && (
                            <Button variant="link" onClick={() => setShowFilingHistory(!showFilingHistory)}>
                              {showFilingHistory ? 'Hide' : 'Show'} Filing Analysis
                            </Button>
                          )}
                        </SpaceBetween>

                        {showFilingHistory && renderFilingHistory()}
                      </SpaceBetween>
                    </div>
                  )}

                  <Box textAlign="center" padding={{ top: 'm' }}>
                    <SpaceBetween size="xs" direction="vertical">
                      {isResearching ? (
                        <Box>
                          <Spinner size="large" />
                          <Box variant="p" padding={{ top: 's' }}>
                            Initiating background research...
                          </Box>
                        </Box>
                      ) : (
                        <>
                          <Button
                            onClick={handleConfirmAndResearch}
                            variant="primary"
                            iconAlign="right"
                            iconName="arrow-right"
                          >
                            {isDataCollectionAvailable
                              ? 'Confirm and research company background'
                              : 'Confirm and continue'}
                          </Button>
                          <Box variant="small" color="text-status-inactive">
                            By confirming, you agree this is the correct company
                          </Box>
                        </>
                      )}
                    </SpaceBetween>
                  </Box>
                </SpaceBetween>
              </Container>
            )}
          </SpaceBetween>
        </Container>

        {/* Help Section */}
        <Container header={<Header variant="h3">Need help finding your company number?</Header>}>
          <SpaceBetween size="xs">
            <Box variant="p">You can find your company number on:</Box>
            <ul>
              <li>Your certificate of incorporation</li>
              <li>Official company documents and correspondence</li>
              <li>
                The{' '}
                <a
                  href="https://find-and-update.company-information.service.gov.uk/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Companies House website
                </a>
              </li>
            </ul>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </Box>
  );
};

export default CompanySelect;
