// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * AnalyticsCacheService — Shared In-Memory Cache for AI Analytics Results
 *
 * Provides a simple key-value cache for AI-generated content such as:
 *   - Widget insight summaries (from info icon popovers)
 *   - Root cause analysis for failed documents (future)
 *   - Any derived AI analytics content
 *
 * The cache is context-aware: it automatically clears all entries when the
 * dashboard time range changes (since the underlying data has changed and
 * cached insights are no longer valid).
 *
 * Usage:
 *   import { analyticsCache } from '../services/analyticsCacheService';
 *   analyticsCache.set('latency-insight', 'Processing is healthy...');
 *   analyticsCache.get('latency-insight'); // → 'Processing is healthy...'
 *   analyticsCache.clearAll(); // on time range change
 */

// ─────────────────────────────────────────────────────────────────────────────
// Service Class
// ─────────────────────────────────────────────────────────────────────────────

class AnalyticsCacheService {
  private cache: Map<string, string> = new Map();
  private currentTimeRange: string = '';

  /**
   * Update the current time range context.
   * If it differs from the stored range, all cached entries are cleared.
   */
  setTimeRange(timeRange: string): void {
    if (timeRange !== this.currentTimeRange) {
      this.currentTimeRange = timeRange;
      this.clearAll();
    }
  }

  /**
   * Retrieve a cached value by key.
   * Returns null if not found.
   */
  get(key: string): string | null {
    return this.cache.get(key) ?? null;
  }

  /**
   * Store a value in the cache.
   */
  set(key: string, value: string): void {
    this.cache.set(key, value);
  }

  /**
   * Remove a specific entry from the cache.
   */
  invalidate(key: string): void {
    this.cache.delete(key);
  }

  /**
   * Clear all cached entries.
   * Called automatically when time range changes, or can be called manually.
   */
  clearAll(): void {
    this.cache.clear();
  }

  /**
   * Check if a key exists in the cache.
   */
  has(key: string): boolean {
    return this.cache.has(key);
  }

  /**
   * Get the current number of cached entries (useful for debugging).
   */
  get size(): number {
    return this.cache.size;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Singleton Export
// ─────────────────────────────────────────────────────────────────────────────

export const analyticsCache = new AnalyticsCacheService();
