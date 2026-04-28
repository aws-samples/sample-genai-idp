// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringFilters — filter state types for the IDP Monitoring dashboard.
 *
 * This file defines the shared filter state shape used by the open-source
 * hook (useMonitoringDashboard) and the premium UI filter components.
 * Keeping the type here ensures the OSS build typechecks correctly without
 * requiring @idp-accelerator/idp-monitor-ui to be installed.
 */

// Supported time range presets
export type TimeRangePreset = '1h' | '6h' | '24h' | '7d' | '30d';

/**
 * The filter state object passed into useMonitoringDashboard.
 * Additional filter fields (docType, status, etc.) can be added here
 * as the premium UI exposes more filter controls.
 */
export interface MonitoringFiltersState {
  /** Time range preset controlling the dashboard query window. */
  timeRange: TimeRangePreset;
}

/** Default filter values used on initial render. */
export const DEFAULT_MONITORING_FILTERS: MonitoringFiltersState = {
  timeRange: '24h',
};
