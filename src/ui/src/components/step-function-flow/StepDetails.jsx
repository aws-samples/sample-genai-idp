// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Box, SpaceBetween, ExpandableSection, Button, Alert, Container } from '@awsui/components-react';
import './StepDetails.css';

const JsonDisplay = ({ data }) => {
  if (!data) return null;

  const formatJson = (jsonString) => {
    if (!jsonString) return 'No data available';

    // Handle different data types
    if (typeof jsonString === 'object') {
      try {
        return JSON.stringify(jsonString, null, 2);
      } catch {
        return String(jsonString);
      }
    }

    if (typeof jsonString === 'string') {
      try {
        // Try to parse as JSON first
        const parsed = JSON.parse(jsonString);
        return JSON.stringify(parsed, null, 2);
      } catch {
        // If not JSON, return as-is but formatted
        return jsonString;
      }
    }

    return String(jsonString);
  };

  const formattedData = formatJson(data);

  return (
    <Container>
      <Box>
        <pre className="json-display">{formattedData}</pre>
      </Box>
    </Container>
  );
};

JsonDisplay.propTypes = {
  data: PropTypes.oneOfType([PropTypes.string, PropTypes.object, PropTypes.array]),
};

JsonDisplay.defaultProps = {
  data: null,
};

// Helper function to check if a step is disabled based on configuration
const isStepDisabled = (stepName, config) => {
  if (!config) return false;

  const stepNameLower = stepName.toLowerCase();

  // Check if this is a summarization step
  if (stepNameLower.includes('summarization') || stepNameLower.includes('summary')) {
    return config.summarization?.enabled === false;
  }

  // Check if this is an assessment step
  if (stepNameLower.includes('assessment') || stepNameLower.includes('assess')) {
    return config.assessment?.enabled === false;
  }

  return false;
};

const StepDetails = ({ step, formatDuration, getStepIcon, mergedConfig }) => {
  const [inputExpanded, setInputExpanded] = useState(false);
  const [outputExpanded, setOutputExpanded] = useState(false);
  const [errorExpanded, setErrorExpanded] = useState(true); // Default to expanded for errors

  const stepDisabled = isStepDisabled(step.name, mergedConfig);

  const formatJson = (jsonString) => {
    if (!jsonString) return '';
    try {
      return JSON.stringify(JSON.parse(jsonString), null, 2);
    } catch {
      return jsonString;
    }
  };

  const copyToClipboard = (text) => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
      } else {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
    } catch (error) {
      console.warn('Failed to copy to clipboard:', error);
    }
  };

  return (
    <div className="step-details">
      <SpaceBetween size="l">
        {/* Step Header */}
        <Box>
          <SpaceBetween direction="horizontal" size="m" alignItems="center">
            <div className="step-details-icon">{getStepIcon(step.name, step.type, step.status)}</div>
            <div>
              <Box variant="h3">{step.name}</Box>
              <Box variant="small" color="text-status-inactive">
                Type: {step.type}
              </Box>
            </div>
          </SpaceBetween>
        </Box>

        {/* Configuration Disabled Notice */}
        {stepDisabled && (
          <Alert type="info" header="Step Disabled in Configuration">
            This step was disabled in the configuration (<strong>enabled: false</strong>) and performed no processing.
            While the step function executed this step, the Lambda function detected the disabled state and skipped all
            processing logic.
          </Alert>
        )}

        {/* Step Metadata */}
        <div className="step-metadata">
          <SpaceBetween direction="horizontal" size="l">
            <Box>
              <Box variant="awsui-key-label">Status</Box>
              <Box className={`step-status step-status-${step.status.toLowerCase()}`}>{step.status}</Box>
            </Box>
            <Box>
              <Box variant="awsui-key-label">Duration</Box>
              <Box>{formatDuration(step.startDate, step.stopDate)}</Box>
            </Box>
            <Box>
              <Box variant="awsui-key-label">Started</Box>
              <Box>{step.startDate ? new Date(step.startDate).toLocaleString() : 'N/A'}</Box>
            </Box>
            {step.stopDate && (
              <Box>
                <Box variant="awsui-key-label">Completed</Box>
                <Box>{new Date(step.stopDate).toLocaleString()}</Box>
              </Box>
            )}
          </SpaceBetween>
        </div>

        {/* Error Information */}
        {step.error && (
          <ExpandableSection
            headerText="Step Error"
            variant="error"
            expanded={errorExpanded}
            onChange={({ detail }) => setErrorExpanded(detail.expanded)}
            headerActions={
              <Button
                variant="inline-icon"
                iconName="copy"
                onClick={() => copyToClipboard(step.error)}
                ariaLabel="Copy error message"
              />
            }
          >
            <Alert type="error" header="Error Details">
              <Box>
                <pre className="error-message">{step.error}</pre>
              </Box>
            </Alert>
          </ExpandableSection>
        )}

        {/* Input Data */}
        {step.input ? (
          <ExpandableSection
            headerText="Input Data"
            expanded={inputExpanded}
            onChange={({ detail }) => setInputExpanded(detail.expanded)}
            headerActions={
              <Button
                variant="inline-icon"
                iconName="copy"
                onClick={() => copyToClipboard(formatJson(step.input))}
                ariaLabel="Copy input data"
              />
            }
          >
            <JsonDisplay data={step.input} />
          </ExpandableSection>
        ) : (
          <Box variant="p" color="text-status-inactive">
            No input data available for this step.
          </Box>
        )}

        {/* Map Iterations */}
        {step.type === 'Map' && step.mapIterationDetails && step.mapIterationDetails.length > 0 && (
          <ExpandableSection headerText={`Map Iterations (${step.mapIterationDetails.length})`} expanded={false}>
            <SpaceBetween size="m">
              {step.mapIterationDetails.map((iteration, index) => (
                <Container key={`iteration-${iteration.name}-${iteration.startDate || index}`} header={iteration.name}>
                  <SpaceBetween size="s">
                    <div className="iteration-metadata">
                      <SpaceBetween direction="horizontal" size="m">
                        <Box>
                          <Box variant="awsui-key-label">Status</Box>
                          <Box className={`step-status step-status-${iteration.status.toLowerCase()}`}>
                            {iteration.status}
                          </Box>
                        </Box>
                        <Box>
                          <Box variant="awsui-key-label">Duration</Box>
                          <Box>{formatDuration(iteration.startDate, iteration.stopDate)}</Box>
                        </Box>
                        <Box>
                          <Box variant="awsui-key-label">Started</Box>
                          <Box>{iteration.startDate ? new Date(iteration.startDate).toLocaleString() : 'N/A'}</Box>
                        </Box>
                        {iteration.stopDate && (
                          <Box>
                            <Box variant="awsui-key-label">Completed</Box>
                            <Box>{new Date(iteration.stopDate).toLocaleString()}</Box>
                          </Box>
                        )}
                      </SpaceBetween>
                    </div>
                    {iteration.error && (
                      <Alert type="error" header="Iteration Error">
                        <pre className="error-message">{iteration.error}</pre>
                      </Alert>
                    )}
                  </SpaceBetween>
                </Container>
              ))}
            </SpaceBetween>
          </ExpandableSection>
        )}

        {/* Output Data */}
        {step.output ? (
          <ExpandableSection
            headerText="Output Data"
            expanded={outputExpanded}
            onChange={({ detail }) => setOutputExpanded(detail.expanded)}
            headerActions={
              <Button
                variant="inline-icon"
                iconName="copy"
                onClick={() => copyToClipboard(formatJson(step.output))}
                ariaLabel="Copy output data"
              />
            }
          >
            <JsonDisplay data={step.output} />
          </ExpandableSection>
        ) : (
          <Box variant="p" color="text-status-inactive">
            No output data available for this step.
          </Box>
        )}
      </SpaceBetween>
    </div>
  );
};

StepDetails.propTypes = {
  step: PropTypes.shape({
    name: PropTypes.string.isRequired,
    type: PropTypes.string.isRequired,
    status: PropTypes.string.isRequired,
    startDate: PropTypes.string,
    stopDate: PropTypes.string,
    input: PropTypes.string,
    output: PropTypes.string,
    error: PropTypes.string,
    mapIterations: PropTypes.number,
    mapIterationDetails: PropTypes.arrayOf(
      PropTypes.shape({
        name: PropTypes.string.isRequired,
        type: PropTypes.string.isRequired,
        status: PropTypes.string.isRequired,
        startDate: PropTypes.string,
        stopDate: PropTypes.string,
        error: PropTypes.string,
      }),
    ),
  }).isRequired,
  formatDuration: PropTypes.func.isRequired,
  getStepIcon: PropTypes.func.isRequired,
  mergedConfig: PropTypes.shape({
    summarization: PropTypes.shape({
      enabled: PropTypes.bool,
    }),
    assessment: PropTypes.shape({
      enabled: PropTypes.bool,
    }),
  }),
};

StepDetails.defaultProps = {
  mergedConfig: null,
};

export default StepDetails;
