/**
 * IDPMonitor — TypeScript Type Definitions
 *
 * Mirrors the Python models in:
 *   lib/idp_common_pkg/idp_common/monitoring/models.py
 *
 * These types describe the parsed AWSJSON payloads returned by each
 * dashboard section in the getMonitoringDashboard query response.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Subscription
// ─────────────────────────────────────────────────────────────────────────────

export type SubscriptionStatus = 'active' | 'inactive' | 'unknown' | 'not_deployed' | 'loading';
export type SubscriptionTier = 'standard' | 'premium';

// ─────────────────────────────────────────────────────────────────────────────
// Volume Section  (section key: "volume")
// ─────────────────────────────────────────────────────────────────────────────

export interface DocumentVolumeMetrics {
  totalDocuments: number;
  completedDocuments: number;
  failedDocuments: number;
  inProgressDocuments: number;
  successRate: number;          // 0.0 – 100.0
  throughputPerHour: number;
  totalPages: number;
  timeRange: string;
  startTime: string;            // ISO 8601
  endTime: string;              // ISO 8601
  statusBreakdown: StatusBreakdown;
  timeSeries: VolumeTimeSeriesPoint[];
}

export interface StatusBreakdown {
  completed: number;
  failed: number;
  inProgress: number;
  queued: number;
}

export interface VolumeTimeSeriesPoint {
  timestamp: string;            // ISO 8601 bucket start
  completed: number;
  failed: number;
  total: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Cost Section  (section key: "cost")
// ─────────────────────────────────────────────────────────────────────────────

export interface CostMetrics {
  totalInputTokens: number;
  totalOutputTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  perModelBreakdown: ModelCostBreakdown[];
  historicalTrend?: CostTrendPoint[];   // Athena — nullable if < 2d range
  dataSource: 'dynamodb' | 'athena';
}

export interface ModelCostBreakdown {
  modelId: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  documentCount: number;
}

export interface CostTrendPoint {
  date: string;                 // YYYY-MM-DD
  estimatedCostUsd: number;
  totalTokens: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Latency Section  (section key: "latency")
// ─────────────────────────────────────────────────────────────────────────────

export interface LatencyMetrics {
  p50Ms: number;
  p90Ms: number;
  p99Ms: number;
  sampleCount: number;
  xRayEnabled: boolean;
  perStage?: StageLatency[];
}

export interface StageLatency {
  stageName: string;            // "ocr" | "classification" | "extraction" | "assessment"
  p50Ms: number;
  p90Ms: number;
  p99Ms: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Failures Section  (section key: "failures")
// ─────────────────────────────────────────────────────────────────────────────

export interface FailureMetrics {
  totalFailures: number;
  recentFailures: FailedDocument[];
  hasMore: boolean;
  nextToken?: string;
}

export interface FailedDocument {
  documentId: string;
  batchId?: string;
  documentClass?: string;
  pageCount?: number;
  failedAt: string;             // ISO 8601
  errorMessage?: string;
  errorCode?: string;
  stage?: string;               // pipeline stage where failure occurred
}

// ─────────────────────────────────────────────────────────────────────────────
// Throttles Section  (section key: "throttles")
// ─────────────────────────────────────────────────────────────────────────────

export interface ThrottleMetrics {
  overallSeverity: 'ok' | 'warning' | 'critical';
  lambdaThrottles: ThrottleMetric;
  bedrockThrottles: ThrottleMetric;
  textractThrottles: ThrottleMetric;
  dynamodbThrottles?: ThrottleMetric;
  sqsMessageAge: ThrottleMetric;
}

export interface ThrottleMetric {
  count: number;
  severity: 'ok' | 'warning' | 'critical';
  threshold: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Distribution Section  (section key: "distribution")
// ─────────────────────────────────────────────────────────────────────────────

export interface DocumentTypeDistribution {
  classes: DocumentClassCount[];
  totalDocuments: number;
  classificationLevel: 'section' | 'page';   // section preferred; page fallback
}

export interface DocumentClassCount {
  className: string;
  count: number;
  percentage: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Config Section  (section key: "config")
// ─────────────────────────────────────────────────────────────────────────────

export interface ConfigContext {
  activeVersion: string;
  documentClassCount: number;
  documentClasses: string[];
  versionHistory: ConfigVersion[];
}

export interface ConfigVersion {
  version: string;
  createdAt: string;            // ISO 8601
  isActive: boolean;
  documentCount?: number;       // documents processed during this version
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard Root
// ─────────────────────────────────────────────────────────────────────────────

export interface MonitoringDashboardData {
  subscriptionStatus: SubscriptionStatus;
  subscriptionTier?: SubscriptionTier;
  volume?: DocumentVolumeMetrics;
  cost?: CostMetrics;
  latency?: LatencyMetrics;
  failures?: FailureMetrics;
  throttles?: ThrottleMetrics;
  distribution?: DocumentTypeDistribution;
  config?: ConfigContext;
  timeRange?: string;
  startTime?: string;
  endTime?: string;
  generatedAt: string;
  errors: SectionError[];
}

export interface SectionError {
  section: string;
  message: string;
  code?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook / Component Props helpers
// ─────────────────────────────────────────────────────────────────────────────

export type TimeRangePreset = '1h' | '6h' | '24h' | '7d' | '30d' | 'custom';
export type DashboardSection = 'volume' | 'cost' | 'latency' | 'failures' | 'throttles' | 'distribution' | 'config';
