// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Widget visibility types for the Monitoring Dashboard.
 * Ported from the IDP Accelerator reference implementation.
 */

export type WidgetId =
  | 'summary'
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
    id: 'summary',
    label: 'AI Insights',
    description: 'AI-generated summary of dashboard metrics and interactive chat for analytics queries',
    defaultVisible: true,
  },
  {
    id: 'kpiCards',
    label: 'Status',
    description: 'Total documents, pages, tokens, estimated cost, and success rate',
    defaultVisible: true,
  },
  {
    id: 'volumeChart',
    label: 'Document Volume',
    description: 'Processing volume over time with success/failure breakdown',
    defaultVisible: true,
  },
  {
    id: 'docTypes',
    label: 'Document Types',
    description: 'Distribution of processed documents by classification type',
    defaultVisible: true,
  },
  {
    id: 'configPanel',
    label: 'Active Configuration',
    description: 'Current config version, document classes, and deployment history',
    defaultVisible: true,
  },
  {
    id: 'latencyChart',
    label: 'Processing Speed',
    description: 'Average processing time and health status per pipeline step',
    defaultVisible: true,
  },
  {
    id: 'failuresTable',
    label: 'Recent Failures',
    description: 'Failed documents with error details and investigate action',
    defaultVisible: true,
  },
  {
    id: 'throttleEvents',
    label: 'Service Performance',
    description: 'Throttling and rate-limit status for Lambda, Bedrock, Textract, DynamoDB, and SQS',
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
