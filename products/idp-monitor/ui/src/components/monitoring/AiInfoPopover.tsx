// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * AiInfoPopover — AI-Powered Info Icon for Widget Headers
 *
 * A drop-in replacement for the static Popover info icons used in widget headers.
 * When clicked, generates an AI insight summary of the widget's data using Bedrock
 * via the useWidgetInsight hook, with results cached in AnalyticsCacheService.
 *
 * Usage:
 *   <Header
 *     variant="h2"
 *     info={
 *       <AiInfoPopover
 *         widgetName="Processing Speed"
 *         cacheKey="latency-insight"
 *         data={latencyMetrics}
 *         header="Processing Speed"
 *         apiUrl={apiUrl}
 *         apiKey={apiKey}
 *       />
 *     }
 *   >
 *     Processing Speed
 *   </Header>
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { useEffect, useRef } from 'react';

import { useWidgetInsight } from '../../hooks/useWidgetInsight';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface AiInfoPopoverProps {
  /** Human-readable widget name (e.g. "Processing Speed") */
  widgetName: string;
  /** Cache key for storing the result (e.g. "latency-insight") */
  cacheKey: string;
  /** The widget's data to summarize */
  data: unknown;
  /** Popover header text (defaults to widgetName) */
  header?: string;
  /** Max characters for the AI response (default: 256) */
  maxChars?: number;
  /** AppSync API URL */
  apiUrl?: string;
  /** AppSync API key */
  apiKey?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function AiInfoPopover({
  widgetName,
  cacheKey,
  data,
  header,
  maxChars = 256,
  apiUrl,
  apiKey,
}: AiInfoPopoverProps): JSX.Element {
  const { insight, loading, error, generate } = useWidgetInsight({
    widgetName,
    cacheKey,
    data,
    maxChars,
    apiUrl,
    apiKey,
  });

  // Track if popover has been opened (to trigger generation on first open)
  const hasTriggeredRef = useRef(false);

  // Generate insight when the popover trigger is clicked
  const handleTriggerClick = () => {
    if (!hasTriggeredRef.current || (!insight && !loading && !error)) {
      hasTriggeredRef.current = true;
      generate();
    }
  };

  // If data changes and we had previously generated, reset the trigger
  useEffect(() => {
    hasTriggeredRef.current = false;
  }, [data]);

  // ── Popover content ──────────────────────────────────────────────────────
  const renderContent = () => {
    if (loading) {
      return (
        <SpaceBetween size="xs" direction="horizontal" alignItems="center">
          <Spinner size="normal" />
          <Box color="text-body-secondary" fontSize="body-s">
            Generating insight…
          </Box>
        </SpaceBetween>
      );
    }

    if (error) {
      return (
        <SpaceBetween size="xs">
          <StatusIndicator type="warning">{error}</StatusIndicator>
          <Button variant="link" iconName="refresh" onClick={generate}>
            Retry
          </Button>
        </SpaceBetween>
      );
    }

    if (insight) {
      return (
        <Box fontSize="body-s" color="text-body-secondary">
          {insight}
        </Box>
      );
    }

    return (
      <Box fontSize="body-s" color="text-body-secondary">
        Click to generate AI insight for this widget.
      </Box>
    );
  };

  return (
    <Popover
      header={header ?? widgetName}
      content={renderContent()}
      triggerType="custom"
      size="medium"
    >
      <span onClick={handleTriggerClick} style={{ cursor: 'pointer' }}>
        <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
          <Icon name="status-info" variant="link" />
        </Box>
      </span>
    </Popover>
  );
}
