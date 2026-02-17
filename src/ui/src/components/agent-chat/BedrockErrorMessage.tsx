// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useState } from 'react';
import { Alert, Box, ExpandableSection, SpaceBetween } from '@cloudscape-design/components';

interface BedrockErrorInfo {
  errorType: string;
  message: string;
  technicalDetails?: string;
  actionRecommendations?: string[];
  retryAttempts?: number;
}

interface BedrockErrorMessageProps {
  errorInfo: BedrockErrorInfo;
  className?: string;
}

const BedrockErrorMessage = ({ errorInfo, className = '' }: BedrockErrorMessageProps): React.JSX.Element => {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  // Map error types to appropriate alert types and status indicators
  const getErrorDisplayInfo = (errorType: string) => {
    switch (errorType) {
      case 'service_unavailable':
        return {
          alertType: 'warning' as const,
          statusType: 'warning',
          icon: 'warning',
          title: 'Service Temporarily Unavailable',
        };
      case 'rate_limit':
      case 'model_throttling':
      case 'too_many_requests':
        return {
          alertType: 'warning' as const,
          statusType: 'warning',
          icon: 'warning',
          title: 'Rate Limit Exceeded',
        };
      case 'quota_exceeded':
        return {
          alertType: 'error' as const,
          statusType: 'error',
          icon: 'error',
          title: 'Usage Quota Exceeded',
        };
      case 'validation_error':
        return {
          alertType: 'error' as const,
          statusType: 'error',
          icon: 'error',
          title: 'Request Validation Error',
        };
      case 'access_denied':
        return {
          alertType: 'error' as const,
          statusType: 'error',
          icon: 'error',
          title: 'Access Denied',
        };
      case 'model_unavailable':
        return {
          alertType: 'warning' as const,
          statusType: 'warning',
          icon: 'warning',
          title: 'AI Model Unavailable',
        };
      case 'timeout':
        return {
          alertType: 'warning' as const,
          statusType: 'warning',
          icon: 'warning',
          title: 'Request Timeout',
        };
      default:
        return {
          alertType: 'error' as const,
          statusType: 'error',
          icon: 'error',
          title: 'Service Error',
        };
    }
  };

  const displayInfo = getErrorDisplayInfo(errorInfo.errorType);

  return (
    <div className={`bedrock-error-message ${className}`}>
      <Alert
        type={displayInfo.alertType}
        header={
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            <span>{displayInfo.title}</span>
            {errorInfo.retryAttempts > 0 && (
              <Box fontSize="body-s" color="text-status-inactive">
                (After {errorInfo.retryAttempts} retry attempt{errorInfo.retryAttempts > 1 ? 's' : ''})
              </Box>
            )}
          </SpaceBetween>
        }
      >
        <SpaceBetween size="m">
          {/* Main error message */}
          <Box>{errorInfo.message}</Box>

          {/* Action recommendations */}
          {errorInfo.actionRecommendations && errorInfo.actionRecommendations.length > 0 && (
            <Box>
              <Box fontWeight="bold" fontSize="body-s" color="text-label">
                What you can do:
              </Box>
              <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                {errorInfo.actionRecommendations.map((recommendation) => (
                  <li key={recommendation} style={{ marginBottom: '4px' }}>
                    <Box fontSize="body-s">{recommendation}</Box>
                  </li>
                ))}
              </ul>
            </Box>
          )}

          {/* Technical details (expandable) */}
          {errorInfo.technicalDetails && (
            <ExpandableSection
              headerText="Technical Details"
              variant="footer"
              expanded={showTechnicalDetails}
              onChange={({ detail }) => setShowTechnicalDetails(detail.expanded)}
            >
              <Box
                padding="s"
                fontSize="body-s"
                {...({ backgroundColor: 'background-container-content', fontFamily: 'monospace' } as Record<string, unknown>)}
              >
                <Box color="text-body-secondary">Error Type: {errorInfo.errorType}</Box>
                <Box color="text-body-secondary" margin={{ top: 'xs' }}>
                  Details: {errorInfo.technicalDetails}
                </Box>
                {errorInfo.retryAttempts > 0 && (
                  <Box color="text-body-secondary" margin={{ top: 'xs' }}>
                    Retry Attempts: {errorInfo.retryAttempts}
                  </Box>
                )}
              </Box>
            </ExpandableSection>
          )}
        </SpaceBetween>
      </Alert>
    </div>
  );
};

export default BedrockErrorMessage;
