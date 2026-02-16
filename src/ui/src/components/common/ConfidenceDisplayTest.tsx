// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import { Box, SpaceBetween } from '@cloudscape-design/components';
import ConfidenceDisplay from './ConfidenceDisplay';

/**
 * Test component to verify ConfidenceDisplay color coding functionality
 * This component can be temporarily added to any page to test the confidence display
 */
const ConfidenceDisplayTest = (): React.JSX.Element => {
  // Test scenarios
  const testScenarios = [
    {
      name: 'High Confidence (Above Threshold)',
      confidenceInfo: {
        hasConfidenceInfo: true,
        confidence: 0.95,
        confidenceThreshold: 0.8,
        isAboveThreshold: true,
        displayMode: 'with-threshold',
      },
    },
    {
      name: 'Low Confidence (Below Threshold)',
      confidenceInfo: {
        hasConfidenceInfo: true,
        confidence: 0.65,
        confidenceThreshold: 0.8,
        isAboveThreshold: false,
        displayMode: 'with-threshold',
      },
    },
    {
      name: 'Confidence Only (No Threshold)',
      confidenceInfo: {
        hasConfidenceInfo: true,
        confidence: 0.75,
        confidenceThreshold: undefined,
        isAboveThreshold: undefined,
        displayMode: 'confidence-only',
      },
    },
    {
      name: 'No Confidence Info',
      confidenceInfo: {
        hasConfidenceInfo: false,
      },
    },
  ];

  return (
    <Box padding="m">
      <h3>Confidence Display Test</h3>
      <SpaceBetween size="m">
        {testScenarios.map((scenario) => (
          <Box
            key={scenario.name}
            padding="s"
            {...({ style: { border: '1px solid #ccc', borderRadius: '4px' } } as Record<string, unknown>)}
          >
            <Box fontWeight="bold" margin={{ bottom: 'xs' }}>
              {scenario.name}
            </Box>
            <Box>
              Field Name: <ConfidenceDisplay confidenceInfo={scenario.confidenceInfo} variant="detailed" showThreshold />
            </Box>
            <Box margin={{ top: 'xs' }}>
              Inline: <ConfidenceDisplay confidenceInfo={scenario.confidenceInfo} variant="inline" showThreshold />
            </Box>
            <Box margin={{ top: 'xs' }}>
              Badge: <ConfidenceDisplay confidenceInfo={scenario.confidenceInfo} variant="badge" showThreshold />
            </Box>
          </Box>
        ))}
      </SpaceBetween>
    </Box>
  );
};

export default ConfidenceDisplayTest;
