// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { Logger } from 'aws-amplify';

const logger = new Logger('dataCollectionService');

// Configuration
const DATA_COLLECTION_API =
  process.env.REACT_APP_DATA_COLLECTION_API ||
  'https://your-data-collection-api.execute-api.eu-central-1.amazonaws.com/dev';

// Health check cache
const HEALTH_CHECK_CACHE_TTL = 5 * 60 * 1000; // 5 minutes
let healthCheckCache = null;
let lastHealthCheck = 0;

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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000); // 2 second timeout

    const response = await fetch(`${DATA_COLLECTION_API}/health`, {
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
    const response = await fetch(`${DATA_COLLECTION_API}/company/${companyNumber}`, {
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
    const response = await fetch(`${DATA_COLLECTION_API}/officers/${companyNumber}`, {
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
    const response = await fetch(`${DATA_COLLECTION_API}/filing-history/${companyNumber}`, {
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
    const response = await fetch(`${DATA_COLLECTION_API}/research/company`, {
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
    const encodedArn = encodeURIComponent(executionArn);
    const response = await fetch(`${DATA_COLLECTION_API}/research/status/${encodedArn}`, {
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
