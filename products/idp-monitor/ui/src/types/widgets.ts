// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Widget visibility types for the Monitoring Dashboard.
 * Ported from the IDP Accelerator reference implementation.
 */

export type WidgetId =
  | 'kpiCards'
  | 'volumeChart'
  | 'configPanel'
  | 'docTypes'
  | 'latencyChart'
  | 'failuresTable'
  | 'throttleEvents';

export type WidgetVisibilityMap = Record<WidgetId, boolean>;

export interface WidgetDefinition {
  id: WidgetId;
  label: string;
  description: string;
  defaultVisible: boolean;
}

export const WIDGET_DEFINITIONS: WidgetDefinition[] = [
  {
    id: 'kpiCards',
    label: 'Key Metrics',
    description: 'Documents, pages, tokens, cost, and failure rate at a glance',
    defaultVisible: true,
  },
  {
    id: 'volumeChart',
    label: 'Volume Over Time',
    description: 'Hourly or daily document processing volume (success vs failure)',
    defaultVisible: true,
  },
  {
    id: 'docTypes',
    label: 'Document Type Breakdown',
    description: 'Bar chart showing volume by document class',
    defaultVisible: true,
  },
  {
    id: 'configPanel',
    label: 'Active Configuration',
    description: 'Current config version, document classes, and version history',
    defaultVisible: true,
  },
  {
    id: 'latencyChart',
    label: 'Latency by Step',
    description: 'P50/P90/P99 latency for each pipeline step',
    defaultVisible: true,
  },
  {
    id: 'failuresTable',
    label: 'Recent Failures',
    description: 'Sortable table of failed documents with investigation links',
    defaultVisible: true,
  },
  {
    id: 'throttleEvents',
    label: 'Throttle Events',
    description: 'AWS service throttle counts with quota-increase recommendations',
    defaultVisible: true,
  },
];

export const DEFAULT_WIDGET_VISIBILITY: WidgetVisibilityMap = Object.fromEntries(
  WIDGET_DEFINITIONS.map((w) => [w.id, w.defaultVisible]),
) as WidgetVisibilityMap;

const STORAGE_KEY = 'idp-monitor-widget-visibility';

export const loadWidgetVisibility = (defaults: WidgetVisibilityMap): WidgetVisibilityMap => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<WidgetVisibilityMap>;
      // Merge with defaults to handle newly added widgets
      return { ...defaults, ...parsed } as WidgetVisibilityMap;
    }
  } catch {
    // ignore parse errors
  }
  return defaults;
};

export const saveWidgetVisibility = (visibility: WidgetVisibilityMap): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(visibility));
  } catch {
    // ignore storage errors
  }
};
