// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import PropTypes from 'prop-types';
import { Box, Badge } from '@awsui/components-react';
import './FlowDiagram.css';

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

const FlowDiagram = ({ steps, onStepClick, selectedStep, getStepIcon, mergedConfig }) => {
  if (!steps || steps.length === 0) {
    return (
      <Box textAlign="center" padding="xl">
        <Box variant="p" color="text-status-inactive">
          No steps available
        </Box>
      </Box>
    );
  }

  // Separate main steps from Map iterations
  const mainSteps = steps.filter((step) => !step.isMapIteration);
  const mapIterations = steps.filter((step) => step.isMapIteration);

  const getStepStatus = (step) => {
    return step.status.toLowerCase();
  };

  const getProgressPercentage = (step) => {
    if (step.status === 'SUCCEEDED') return 100;
    if (step.status === 'FAILED') return 100;
    if (step.status === 'RUNNING') return 75; // Assume 75% for running steps
    return 0;
  };

  const getProgressBarStyle = (step) => {
    const width = `${getProgressPercentage(step)}%`;

    // Add specific styling for failed steps
    if (step.status === 'FAILED') {
      return {
        width,
        backgroundColor: '#dc3545', // Red color for failed steps
      };
    }

    return { width };
  };

  // Group Map iterations by their parent Map state
  const mapIterationsByParent = mapIterations.reduce((acc, iteration) => {
    const parentName = iteration.parentMapName || 'Unknown';
    if (!acc[parentName]) {
      acc[parentName] = [];
    }
    acc[parentName].push(iteration);
    return acc;
  }, {});

  return (
    <div className="flow-diagram">
      <div className="flow-container">
        {mainSteps.map((step, index) => {
          // Check if this is a Map state
          const isMapState = step.type === 'Map';
          const mapIterationsForThisStep = mapIterationsByParent[step.name] || [];
          const stepDisabled = isStepDisabled(step.name, mergedConfig);

          return (
            <React.Fragment key={`main-step-${step.name}-${step.type}-${step.startDate || index}`}>
              {/* Step Node */}
              <div
                className={`flow-step ${getStepStatus(step)} ${selectedStep?.name === step.name ? 'selected' : ''} ${
                  isMapState ? 'map-step' : ''
                } ${stepDisabled ? 'step-disabled' : ''}`}
                onClick={() => onStepClick(step)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    onStepClick(step);
                  }
                }}
                role="button"
                tabIndex={0}
                title={stepDisabled ? 'This step was disabled in configuration and performed no processing' : ''}
              >
                <div className="step-icon-container">
                  {getStepIcon(step.name, step.type, step.status)}
                  {step.status === 'RUNNING' && <div className="step-pulse-ring" />}
                </div>
                <div className="step-label">
                  <div className="step-name">
                    {step.name}
                    {stepDisabled && <Badge color="grey">NOT ENABLED</Badge>}
                    {isMapState && step.mapIterations && <Badge color="blue">{step.mapIterations} iterations</Badge>}
                  </div>
                  <div className={`step-status-text status-text-${step.status.toLowerCase()}`}>{step.status}</div>
                  {step.error && (
                    <div className="step-error-indicator">
                      <span className="error-icon">⚠️</span>
                    </div>
                  )}
                </div>
                <div className="step-progress">
                  <div className={`step-progress-bar ${step.status.toLowerCase()}`} style={getProgressBarStyle(step)} />
                </div>
              </div>

              {/* Show Map iterations inline if this is a Map state */}
              {isMapState && mapIterationsForThisStep.length > 0 && (
                <div className="map-iterations-inline">
                  <div className="map-iterations-header">
                    <h5>Map Iterations ({mapIterationsForThisStep.length})</h5>
                  </div>
                  <div className="map-iterations-grid">
                    {mapIterationsForThisStep.slice(0, 6).map((iteration, iterIndex) => (
                      <div
                        key={`iteration-${iteration.name}-${iteration.startDate || iterIndex}`}
                        className={`iteration-step ${getStepStatus(iteration)} ${
                          selectedStep?.name === iteration.name ? 'selected' : ''
                        }`}
                        onClick={() => onStepClick(iteration)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            onStepClick(iteration);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="iteration-icon">
                          {getStepIcon(iteration.name, iteration.type, iteration.status)}
                        </div>
                        <div className="iteration-label">
                          <div className="iteration-name">{iteration.name}</div>
                          <div className={`iteration-status status-text-${iteration.status.toLowerCase()}`}>
                            {iteration.status}
                          </div>
                        </div>
                      </div>
                    ))}
                    {mapIterationsForThisStep.length > 6 && (
                      <div className="more-iterations">
                        <span>+{mapIterationsForThisStep.length - 6} more</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Flow Arrow */}
              {index < mainSteps.length - 1 && (
                <div className="flow-arrow">
                  <div className="arrow-line">
                    <div className="arrow-animation" />
                  </div>
                  <div className="arrow-head" />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Complete Flow Section */}
      <div className="flow-legend">
        <div className="legend-item">
          <div className="legend-icon succeeded" />
          <span>Completed</span>
        </div>
        <div className="legend-item">
          <div className="legend-icon running" />
          <span>Running</span>
        </div>
        <div className="legend-item">
          <div className="legend-icon failed" />
          <span>Failed</span>
        </div>
        <div className="legend-item">
          <div className="legend-icon pending" />
          <span>Pending</span>
        </div>
      </div>
    </div>
  );
};

FlowDiagram.propTypes = {
  steps: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string.isRequired,
      type: PropTypes.string.isRequired,
      status: PropTypes.string.isRequired,
      startDate: PropTypes.string,
      stopDate: PropTypes.string,
      error: PropTypes.string,
      isMapIteration: PropTypes.bool,
      parentMapName: PropTypes.string,
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
    }),
  ),
  onStepClick: PropTypes.func.isRequired,
  selectedStep: PropTypes.shape({
    name: PropTypes.string,
  }),
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

FlowDiagram.defaultProps = {
  steps: [],
  selectedStep: null,
  mergedConfig: null,
};

export default FlowDiagram;
