// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import { Box, Badge } from '@cloudscape-design/components';

interface ConfidenceInfo {
  hasConfidenceInfo: boolean;
  confidence?: number;
  confidenceThreshold?: number;
  isAboveThreshold?: boolean;
  displayMode?: string;
}

interface ConfidenceDisplayProps {
  confidenceInfo?: ConfidenceInfo | null;
  variant?: 'inline' | 'badge' | 'detailed';
  showThreshold?: boolean;
}

const ConfidenceDisplay = ({
  confidenceInfo = null,
  variant = 'detailed',
  showThreshold = true,
}: ConfidenceDisplayProps): React.JSX.Element | null => {
  if (!confidenceInfo || !confidenceInfo.hasConfidenceInfo) {
    return null;
  }

  const { confidence, confidenceThreshold, isAboveThreshold, displayMode } = confidenceInfo;

  // Format confidence as percentage
  const confidencePercent = (confidence * 100).toFixed(1);

  // Determine colors based on threshold comparison
  const getColors = () => {
    if (displayMode === 'with-threshold') {
      return {
        textColor: isAboveThreshold ? '#16794d' : '#d13313', // Green for good, red for poor
        badgeColor: isAboveThreshold ? 'green' : 'red',
        backgroundColor: isAboveThreshold ? '#f0f9f4' : '#fef2f2',
      };
    }
    // No threshold available - use neutral colors
    return {
      textColor: '#000000',
      badgeColor: 'blue',
      backgroundColor: '#f8f9fa',
    };
  };

  const colors = getColors();

  // Format threshold display
  const getThresholdText = () => {
    if (!showThreshold || displayMode !== 'with-threshold' || confidenceThreshold === undefined) {
      return '';
    }
    const thresholdPercent = (confidenceThreshold * 100).toFixed(1);
    return ` (Threshold: ${thresholdPercent}%)`;
  };

  const thresholdText = getThresholdText();

  // Render based on variant
  switch (variant) {
    case 'inline':
      return (
        <span style={{ color: colors.textColor, fontSize: '0.875rem' }}>
          {confidencePercent}%{thresholdText}
        </span>
      );

    case 'badge':
      return (
        <Badge color={colors.badgeColor as 'blue' | 'green' | 'grey' | 'red'}>
          {confidencePercent}%{thresholdText}
        </Badge>
      );

    case 'detailed':
    default:
      return (
        <Box
          fontSize="body-s"
          padding={{ top: 'xxxs' }}
          {...({
            style: {
              color: colors.textColor,
              backgroundColor: colors.backgroundColor,
              padding: '4px 8px',
              borderRadius: '4px',
              display: 'inline-block',
              marginTop: '2px',
            },
          } as Record<string, unknown>)}
        >
          Confidence: {confidencePercent}%{thresholdText}
        </Box>
      );
  }
};

export default ConfidenceDisplay;
