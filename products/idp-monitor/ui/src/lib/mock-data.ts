/**
 * IDPMonitor — Client-side mock data for local development
 *
 * Mirrors the TypeScript types in ../types/monitoring.ts.
 * Used by useMonitoringDashboard when VITE_IDP_MONITOR_MOCK=true.
 *
 * To enable in your host app's .env.development:
 *   VITE_IDP_MONITOR_MOCK=true
 *
 * The data returned here matches what the Lambda resolver returns in
 * SUBSCRIPTION_VALIDATION_MODE=none, so the UI looks identical in both
 * local dev and a deployed dev environment.
 */

import type {
  MonitoringDashboardData,
  TimeRangePreset,
} from '../types/monitoring';

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

function isoOffset(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

function hoursAgo(h: number): string {
  return isoOffset(h * 3_600_000);
}

function daysAgo(d: number): string {
  return isoOffset(d * 86_400_000);
}

function daysAgoDate(d: number): string {
  return new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Build 24 hourly time series buckets
// ---------------------------------------------------------------------------

function buildTimeSeries(count = 24) {
  return Array.from({ length: count }, (_, i) => {
    const hoursBack = count - i;
    return {
      timestamp: hoursAgo(hoursBack),
      completed: 45 + (hoursBack % 7) * 3,
      failed: 1 + (hoursBack % 3),
      total: 47 + (hoursBack % 7) * 3,
    };
  });
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function buildMockDashboard(
  timeRange: TimeRangePreset | string = '24h'
): MonitoringDashboardData {
  return {
    subscriptionStatus: 'active',
    subscriptionTier: 'standard',
    timeRange,
    startTime: hoursAgo(24),
    endTime: new Date().toISOString(),
    generatedAt: new Date().toISOString(),
    errors: [],

    // ── Volume ──────────────────────────────────────────────────────────────
    volume: {
      totalDocuments: 1247,
      completedDocuments: 1198,
      failedDocuments: 23,
      inProgressDocuments: 26,
      successRate: 96.1,
      throughputPerHour: 52.0,
      totalPages: 8734,
      timeRange,
      startTime: hoursAgo(24),
      endTime: new Date().toISOString(),
      statusBreakdown: {
        completed: 1198,
        failed: 23,
        inProgress: 26,
        queued: 0,
      },
      timeSeries: buildTimeSeries(24),
    },

    // ── Cost ─────────────────────────────────────────────────────────────────
    cost: {
      totalInputTokens: 4_820_000,
      totalOutputTokens: 980_000,
      totalTokens: 5_800_000,
      estimatedCostUsd: 8.74,
      dataSource: 'dynamodb',
      perModelBreakdown: [
        {
          modelId: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
          inputTokens: 3_200_000,
          outputTokens: 650_000,
          totalTokens: 3_850_000,
          estimatedCostUsd: 5.93,
          documentCount: 812,
        },
        {
          modelId: 'amazon.nova-pro-v1:0',
          inputTokens: 1_620_000,
          outputTokens: 330_000,
          totalTokens: 1_950_000,
          estimatedCostUsd: 2.81,
          documentCount: 435,
        },
      ],
      historicalTrend: Array.from({ length: 7 }, (_, i) => ({
        date: daysAgoDate(7 - i),
        estimatedCostUsd: parseFloat((7.5 + i * 0.3 + (i % 3) * 0.5).toFixed(2)),
        totalTokens: 5_200_000 + i * 100_000,
      })),
    },

    // ── Latency ──────────────────────────────────────────────────────────────
    latency: {
      p50Ms: 1840,
      p90Ms: 4200,
      p99Ms: 8750,
      sampleCount: 1198,
      xRayEnabled: true,
      perStage: [
        { stageName: 'ocr',            p50Ms: 320,  p90Ms: 720,  p99Ms: 1200 },
        { stageName: 'classification', p50Ms: 480,  p90Ms: 980,  p99Ms: 1800 },
        { stageName: 'extraction',     p50Ms: 890,  p90Ms: 2100, p99Ms: 4900 },
        { stageName: 'assessment',     p50Ms: 150,  p90Ms: 400,  p99Ms: 850  },
      ],
    },

    // ── Failures ─────────────────────────────────────────────────────────────
    failures: {
      totalFailures: 23,
      hasMore: false,
      recentFailures: Array.from({ length: 5 }, (_, i) => ({
        documentId: `doc-${1000 + i}`,
        batchId: 'batch-20260427-001',
        documentClass: i % 2 === 0 ? 'W2' : 'Invoice',
        pageCount: 2 + (i % 4),
        failedAt: isoOffset((30 + i * 15) * 60_000),
        errorMessage:
          i % 3 === 0
            ? 'Bedrock throttling: rate limit exceeded'
            : 'Textract: document quality too low',
        errorCode: i % 3 === 0 ? 'ThrottlingException' : 'DocumentQualityError',
        stage: i % 3 === 0 ? 'extraction' : 'ocr',
      })),
    },

    // ── Throttles ────────────────────────────────────────────────────────────
    throttles: {
      overallSeverity: 'warning',
      lambdaThrottles:   { count: 3,  severity: 'warning', threshold: 5   },
      bedrockThrottles:  { count: 12, severity: 'warning', threshold: 10  },
      textractThrottles: { count: 0,  severity: 'ok',      threshold: 5   },
      sqsMessageAge:     { count: 45, severity: 'ok',      threshold: 300 },
    },

    // ── Distribution ─────────────────────────────────────────────────────────
    distribution: {
      totalDocuments: 1247,
      classificationLevel: 'section',
      classes: [
        { className: 'W2',           count: 523, percentage: 41.9 },
        { className: 'Invoice',      count: 312, percentage: 25.0 },
        { className: '1099-MISC',    count: 198, percentage: 15.9 },
        { className: 'BankStatement',count: 142, percentage: 11.4 },
        { className: 'Other',        count: 72,  percentage: 5.8  },
      ],
    },

    // ── Config ────────────────────────────────────────────────────────────────
    config: {
      activeVersion: 'v1.4.2',
      documentClassCount: 5,
      documentClasses: ['W2', 'Invoice', '1099-MISC', 'BankStatement', 'Other'],
      versionHistory: [
        { version: 'v1.4.2', createdAt: daysAgo(3),  isActive: true  },
        { version: 'v1.4.1', createdAt: daysAgo(14), isActive: false },
        { version: 'v1.4.0', createdAt: daysAgo(30), isActive: false },
      ],
    },
  };
}
