/**
 * IDPMonitor — AppSync GraphQL Query Definitions
 *
 * Apollo Client query documents for the IDPMonitor AppSync API.
 * These queries target IDPMonitor's own AppSync endpoint (separate from
 * the Accelerator's main AppSync API).
 *
 * Usage:
 *   import { GET_MONITORING_DASHBOARD, GET_MONITORING_STATUS } from './graphql/queries';
 *   const { data } = useQuery(GET_MONITORING_DASHBOARD, {
 *     variables: { input: { timeRange: '24h' } },
 *   });
 */

// gql is inlined as a tagged template function to avoid requiring @apollo/client
// as a hard peer dep in the library build. Host apps that use Apollo can pass
// the same string through their own gql tag.

// ─────────────────────────────────────────────────────────────────────────────
// GET_MONITORING_DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

export const GET_MONITORING_DASHBOARD = `
  query GetMonitoringDashboard($input: MonitoringQueryInput!) {
    getMonitoringDashboard(input: $input) {
      subscriptionStatus
      subscriptionTier
      volume
      cost
      latency
      failures
      throttles
      distribution
      config
      timeRange
      startTime
      endTime
      generatedAt
      errors {
        section
        message
        code
      }
    }
  }
`;

// ─────────────────────────────────────────────────────────────────────────────
// GET_MONITORING_STATUS
// ─────────────────────────────────────────────────────────────────────────────

export const GET_MONITORING_STATUS = `
  query GetMonitoringStatus {
    getMonitoringStatus {
      subscriptionStatus
      stackName
      acceleratorStackName
    }
  }
`;

// Re-export as named constants for consumers that use Apollo gql tag:
//
//   import gql from 'graphql-tag';
//   import { GET_MONITORING_DASHBOARD } from '@idp-accelerator/idp-monitor-ui';
//   const QUERY = gql(GET_MONITORING_DASHBOARD);
