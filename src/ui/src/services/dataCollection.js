// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { Auth, Logger } from 'aws-amplify';
import { SSMClient, GetParameterCommand } from '@aws-sdk/client-ssm';
import awsExports from '../aws-exports';

const logger = new Logger('dataCollectionService');

// Configuration
const DATA_COLLECTION_API_PARAM = '/fiscalshield/data-collection/dev/api-url';
const DATA_COLLECTION_API_FALLBACK =
  process.env.REACT_APP_DATA_COLLECTION_API ||
  'https://your-data-collection-api.execute-api.eu-central-1.amazonaws.com/dev';

// API URL cache
let cachedApiUrl = null;
let apiUrlFetchAttempted = false;

// Health check cache
const HEALTH_CHECK_CACHE_TTL = 5 * 60 * 1000; // 5 minutes
let healthCheckCache = null;
let lastHealthCheck = 0;

/**
 * Fetch Data Collection API URL from Parameter Store
 * Cached after first successful fetch
 */
const getDataCollectionApiUrl = async () => {
  // Return cached URL if available
  if (cachedApiUrl) {
    return cachedApiUrl;
  }

  // Don't retry if we already failed once in this session
  if (apiUrlFetchAttempted) {
    logger.debug('Using fallback URL after previous fetch failure');
    return DATA_COLLECTION_API_FALLBACK;
  }

  try {
    apiUrlFetchAttempted = true;

    // Get AWS credentials from Amplify
    const credentials = await Auth.currentUserCredentials();

    if (!credentials) {
      logger.warn('No credentials available, using fallback URL');
      return DATA_COLLECTION_API_FALLBACK;
    }

    // Create SSM client
    const ssmClient = new SSMClient({
      credentials,
      region: awsExports.aws_project_region,
    });

    // Fetch parameter
    const command = new GetParameterCommand({ Name: DATA_COLLECTION_API_PARAM });
    const response = await ssmClient.send(command);

    if (response.Parameter?.Value) {
      cachedApiUrl = response.Parameter.Value;
      logger.info('Data Collection API URL loaded from Parameter Store:', cachedApiUrl);
      return cachedApiUrl;
    }

    logger.warn('Parameter exists but has no value, using fallback');
    return DATA_COLLECTION_API_FALLBACK;
  } catch (error) {
    // Parameter not found or access denied - Data Collection Stack not deployed
    if (error.name === 'ParameterNotFound' || error.code === 'ParameterNotFound') {
      logger.info('Data Collection Stack not deployed yet (parameter not found)');
    } else if (error.name === 'AccessDeniedException') {
      logger.warn('No permission to read Data Collection API URL parameter');
    } else {
      logger.error('Error fetching Data Collection API URL:', error);
    }

    return DATA_COLLECTION_API_FALLBACK;
  }
};

/**
 * Check if Data Collection Stack is available
 * Cached for 5 minutes to avoid excessive health checks
 */
export const checkDataCollectionHealth = async () => {
  const now = Date.now();

  // Return cached result if still valid
  if (healthCheckCache !== null && now - lastHealthCheck < HEALTH_CHECK_CACHE_TTL) {
    logger.debug('Returning cached health check result:', healthCheckCache);
    return healthCheckCache;
  }

  try {
    // Get API URL dynamically
    const apiUrl = await getDataCollectionApiUrl();

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000); // 2 second timeout

    const response = await fetch(`${apiUrl}/health`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      logger.warn('Health check failed with status:', response.status);
      healthCheckCache = false;
      lastHealthCheck = now;
      return false;
    }

    const data = await response.json();
    logger.debug('Health check response:', data);

    // Check if both companies_house and step_functions are operational
    const isAvailable =
      data.status === 'available' &&
      data.services?.companies_house === 'operational' &&
      data.services?.step_functions === 'available';

    healthCheckCache = isAvailable;
    lastHealthCheck = now;

    return isAvailable;
  } catch (error) {
    if (error.name === 'AbortError') {
      logger.warn('Health check timed out');
    } else {
      logger.warn('Health check failed:', error.message);
    }
    healthCheckCache = false;
    lastHealthCheck = now;
    return false;
  }
};

/**
 * Lookup company information from Companies House
 * @param {string} companyNumber - 6-8 character UK company number
 * @returns {Promise<Object>} Company data
 */
export const lookupCompany = async (companyNumber) => {
  if (!companyNumber || companyNumber.length < 6) {
    throw new Error('Invalid company number. Must be 6-8 characters.');
  }

  logger.debug('Looking up company:', companyNumber);

  try {
    const apiUrl = await getDataCollectionApiUrl();

    const response = await fetch(`${apiUrl}/company/${companyNumber}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Company not found (404)');
      }
      throw new Error(`Failed to lookup company: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    logger.debug('Company data:', data);

    return data;
  } catch (error) {
    logger.error('Error looking up company:', error);
    throw error;
  }
};

/**
 * Lookup company officers from Companies House
 * @param {string} companyNumber - 6-8 character UK company number
 * @returns {Promise<Object>} Officers data with risk analysis
 */
export const lookupOfficers = async (companyNumber) => {
  if (!companyNumber || companyNumber.length < 6) {
    throw new Error('Invalid company number. Must be 6-8 characters.');
  }

  logger.debug('Looking up officers for company:', companyNumber);

  try {
    const apiUrl = await getDataCollectionApiUrl();

    const response = await fetch(`${apiUrl}/officers/${companyNumber}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Officers not found (404)');
      }
      throw new Error(`Failed to lookup officers: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    logger.debug('Officers data:', data);

    return data;
  } catch (error) {
    logger.error('Error looking up officers:', error);
    throw error;
  }
};

/**
 * Check company filing history from Companies House
 * @param {string} companyNumber - 6-8 character UK company number
 * @returns {Promise<Object>} Filing history with compliance analysis
 */
export const checkFilingHistory = async (companyNumber) => {
  if (!companyNumber || companyNumber.length < 6) {
    throw new Error('Invalid company number. Must be 6-8 characters.');
  }

  logger.debug('Checking filing history for company:', companyNumber);

  try {
    const apiUrl = await getDataCollectionApiUrl();

    const response = await fetch(`${apiUrl}/filing-history/${companyNumber}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Filing history not found (404)');
      }
      throw new Error(`Failed to check filing history: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    logger.debug('Filing history data:', data);

    return data;
  } catch (error) {
    logger.error('Error checking filing history:', error);
    throw error;
  }
};

/**
 * Trigger background research for a company
 * @param {Object} params - Research parameters
 * @param {string} params.company_number - Company number
 * @param {string} params.company_name - Company name
 * @param {string} params.user_id - User ID
 * @param {string} params.client_id - Client ID
 * @returns {Promise<Object>} Research execution details
 */
/* eslint-disable camelcase */
export const triggerBackgroundResearch = async ({ company_number, company_name, user_id, client_id }) => {
  logger.debug('Triggering background research:', { company_number, company_name, user_id, client_id });

  try {
    const apiUrl = await getDataCollectionApiUrl();

    const response = await fetch(`${apiUrl}/research/company`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        company_number,
        company_name,
        user_id,
        client_id,
        requested_at: new Date().toISOString(),
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to trigger research: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    logger.debug('Research triggered:', data);

    return data;
  } catch (error) {
    logger.error('Error triggering background research:', error);
    throw error;
  }
};
/* eslint-enable camelcase */

/**
 * Check the status of a background research execution
 * @param {string} executionArn - Step Functions execution ARN
 * @returns {Promise<Object>} Execution status
 */
export const checkResearchStatus = async (executionArn) => {
  logger.debug('Checking research status:', executionArn);

  try {
    const apiUrl = await getDataCollectionApiUrl();

    const encodedArn = encodeURIComponent(executionArn);
    const response = await fetch(`${apiUrl}/research/status/${encodedArn}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to check status: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    logger.debug('Research status:', data);

    return data;
  } catch (error) {
    logger.error('Error checking research status:', error);
    throw error;
  }
};

/**
 * Get the active company context from localStorage
 * @returns {Object|null} Company context or null if not set
 */
export const getActiveCompany = () => {
  try {
    const companyContext = localStorage.getItem('active_company');
    return companyContext ? JSON.parse(companyContext) : null;
  } catch (error) {
    logger.error('Error reading active company:', error);
    return null;
  }
};

/**
 * Clear the active company context
 */
export const clearActiveCompany = () => {
  try {
    localStorage.removeItem('active_company');
    logger.debug('Active company cleared');
  } catch (error) {
    logger.error('Error clearing active company:', error);
  }
};

/**
 * Check if a company is selected
 * @returns {boolean} True if company is selected
 */
export const hasActiveCompany = () => {
  return getActiveCompany() !== null;
};
