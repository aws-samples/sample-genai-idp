// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared TypeScript types for the IDP Monitoring dashboard.
 *
 * These types are used by both the open-source hook (useMonitoringDashboard)
 * and the premium UI components (@idp-accelerator/idp-monitor-ui).
 * Keeping them here ensures the OSS build typechecks correctly without
 * requiring the premium package to be installed.
 */

// ─────────────────────────────────────────────────────────────────────────────
// KPI / Summary
// ─────────────────────────────────────────────────────────────────────────────

export interface KPIData {
  totalDocs: number;
  totalPages: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCost: number;
  avgCostPerDoc: number;
  failureRate: number;
  successRate: number;
  criticalErrors: number;
  throttleEvents: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Volume over time
// ─────────────────────────────────────────────────────────────────────────────

export interface VolumeDataPoint {
  timestamp: string;
  label: string;
  success: number;
  failure: number;
  pending: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Success / Failure breakdown
// ─────────────────────────────────────────────────────────────────────────────

export interface SuccessFailureData {
  successCount: number;
  failureCount: number;
  pendingCount: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Document type distribution
// ─────────────────────────────────────────────────────────────────────────────

export interface DocTypeBreakdown {
  docType: string;
  count: number;
  percentage: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Recent failures
// ─────────────────────────────────────────────────────────────────────────────

export interface FailureRecord {
  documentId: string;
  docType: string;
  stage: 'classification' | 'extraction' | 'validation' | 'unknown';
  errorCode: string;
  errorMessage: string;
  timestamp: string;
  retryCount: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Throttle report
// ─────────────────────────────────────────────────────────────────────────────

export interface ThrottleServiceEntry {
  service: string;
  eventCount: number;
  lastSeen: string;
}

export interface ThrottleData {
  services: ThrottleServiceEntry[];
  totalEvents: number;
  flaggedServices: string[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Latency by pipeline step
// ─────────────────────────────────────────────────────────────────────────────

export interface LatencyStepData {
  step: string;
  avgMs: number;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Config info
// ─────────────────────────────────────────────────────────────────────────────

export interface ConfigVersion {
  version: string;
  createdAt: string;
  active: boolean;
}

export interface ConfigInfoData {
  activeVersion: string | null;
  documentTypesCount: number;
  lastUpdatedAt: string | null;
  configVersions: ConfigVersion[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Top-level dashboard data shape
// ─────────────────────────────────────────────────────────────────────────────

export interface MonitoringDashboardData {
  summary: string | null;
  kpi: KPIData;
  volume: VolumeDataPoint[];
  successFailure: SuccessFailureData;
  docTypes: DocTypeBreakdown[];
  failures: FailureRecord[];
  throttle: ThrottleData;
  latencyByStep: LatencyStepData[];
  configInfo: ConfigInfoData;
}
