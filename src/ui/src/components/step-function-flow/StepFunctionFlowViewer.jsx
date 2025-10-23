/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: MIT-0
 */
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { API, graphqlOperation, Logger } from 'aws-amplify';
import { Container, Header, SpaceBetween, Box, Alert, Spinner, Button, Modal, Badge } from '@awsui/components-react';
import {
  FaPlay,
  FaCheck,
  FaTimes,
  FaClock,
  FaRobot,
  FaFileAlt,
  FaEye,
  FaChartBar,
  FaMap,
  FaList,
  FaExclamationTriangle,
} from 'react-icons/fa';
import getStepFunctionExecution from '../../graphql/queries/getStepFunctionExecution';
import FlowDiagram from './FlowDiagram';
import StepDetails from './StepDetails';
import './StepFunctionFlowViewer.css';

const logger = new Logger('StepFunctionFlowViewer');

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

const StepFunctionFlowViewer = ({ executionArn, visible, onDismiss, mergedConfig }) => {
  const [selectedStep, setSelectedStep] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(false);
  const [lastRefreshTime, setLastRefreshTime] = useState(null);
  const autoRefreshIntervalRef = useRef(null);
  const AUTO_REFRESH_INTERVAL = 10000; // 10 seconds
  const [processedSteps, setProcessedSteps] = useState([]);

  // Function to process Step Function steps for better visualization
  const processStepFunctionStepsData = (steps) => {
    if (!steps || !Array.isArray(steps)) return [];

    // Create a flattened list of all steps including Map iterations
    const allSteps = [];

    steps.forEach((step) => {
      // Add the main step
      allSteps.push({
        ...step,
        isMainStep: true,
      });

      // If this is a Map state with iterations, add them as separate steps
      if (step.type === 'Map' && step.mapIterationDetails && step.mapIterationDetails.length > 0) {
        step.mapIterationDetails.forEach((iteration, index) => {
          allSteps.push({
            ...iteration,
            isMapIteration: true,
            parentMapName: step.name,
            iterationIndex: index,
          });
        });
      }
    });

    // Sort by start date to maintain chronological order
    return allSteps.sort((a, b) => {
      if (!a.startDate) return 1;
      if (!b.startDate) return -1;
      return new Date(a.startDate) - new Date(b.startDate);
    });
  };

  const fetchStepFunctionExecution = async () => {
    if (!executionArn || !visible) return;

    setLoading(true);
    setError(null);

    try {
      // Add detailed logging for debugging
      logger.info('Fetching Step Function execution with ARN:', executionArn);
      console.log('Fetching Step Function execution with ARN:', executionArn);

      const result = await API.graphql(graphqlOperation(getStepFunctionExecution, { executionArn }));
      logger.info('GraphQL response received:', result);
      console.log('GraphQL response received:', result);

      setData(result.data);
      setLastRefreshTime(new Date());
      logger.debug('Step Functions execution data:', result.data);

      // Process the steps to handle Map state visualization
      if (result.data?.getStepFunctionExecution?.steps) {
        const enhancedSteps = processStepFunctionStepsData(result.data.getStepFunctionExecution.steps);
        setProcessedSteps(enhancedSteps);

        // If there's a failed step and no step is currently selected, select the first failed step
        if (!selectedStep) {
          const failedStep = enhancedSteps.find((step) => step.status === 'FAILED');
          if (failedStep) {
            setSelectedStep(failedStep);
            logger.info('Auto-selected failed step:', failedStep.name);
          }
        }
      }
    } catch (err) {
      logger.error('Error fetching Step Functions execution:', err);
      console.error('Error fetching Step Functions execution:', err);

      // Enhanced error details for debugging
      if (err.errors) {
        err.errors.forEach((errorItem, index) => {
          logger.error(`GraphQL Error ${index + 1}:`, errorItem);
          console.error(`GraphQL Error ${index + 1}:`, errorItem);
        });
      }

      setError(err);
    } finally {
      setLoading(false);
    }
  };

  // Set up auto-refresh functionality
  const setupAutoRefresh = () => {
    if (autoRefreshEnabled) {
      // Clear any existing interval
      if (autoRefreshIntervalRef.current) {
        clearInterval(autoRefreshIntervalRef.current);
      }

      // Set up new interval
      autoRefreshIntervalRef.current = setInterval(() => {
        logger.debug('Auto-refreshing Step Functions execution data');
        fetchStepFunctionExecution();
      }, AUTO_REFRESH_INTERVAL);

      logger.info('Auto-refresh enabled for execution:', executionArn);
    } else if (autoRefreshIntervalRef.current) {
      // Disable auto-refresh by clearing the interval
      clearInterval(autoRefreshIntervalRef.current);
      autoRefreshIntervalRef.current = null;
      logger.info('Auto-refresh disabled for execution:', executionArn);
    }
  };

  // Toggle auto-refresh
  const toggleAutoRefresh = () => {
    const newState = !autoRefreshEnabled;
    setAutoRefreshEnabled(newState);
  };

  // Helper function to get status indicator
  const getStatusIndicator = () => {
    if (autoRefreshEnabled) {
      return (
        <Box variant="small" color="text-status-success">
          🔄 Auto-Refresh On
        </Box>
      );
    }
    return (
      <Box variant="small" color="text-status-inactive">
        ⏸️ Auto-Refresh Off
      </Box>
    );
  };

  // Initial fetch and auto-refresh setup
  useEffect(() => {
    if (visible && executionArn) {
      fetchStepFunctionExecution();
    }

    return () => {
      // Clean up interval on unmount
      if (autoRefreshIntervalRef.current) {
        clearInterval(autoRefreshIntervalRef.current);
        autoRefreshIntervalRef.current = null;
      }
    };
  }, [executionArn, visible]);

  // Update auto-refresh when the toggle changes
  useEffect(() => {
    setupAutoRefresh();
  }, [autoRefreshEnabled]);

  // Disable auto-refresh when execution completes
  useEffect(() => {
    const execution = data?.getStepFunctionExecution;
    if (
      execution &&
      (execution.status === 'SUCCEEDED' || execution.status === 'FAILED' || execution.status === 'ABORTED')
    ) {
      // If execution is complete, disable auto-refresh
      if (autoRefreshEnabled) {
        logger.info('Execution complete, disabling auto-refresh');
        setAutoRefreshEnabled(false);
      }
    }
  }, [data]);

  const getStepIcon = (stepName, stepType, status) => {
    const iconProps = { size: 24, className: `step-icon step-icon-${status.toLowerCase()}` };

    if (stepName.toLowerCase().includes('upload') || stepName.toLowerCase().includes('input')) {
      return <FaFileAlt size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('bda') || stepName.toLowerCase().includes('bedrock')) {
      return <FaRobot size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('review') || stepName.toLowerCase().includes('hitl')) {
      return <FaEye size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('result') || stepName.toLowerCase().includes('process')) {
      return <FaChartBar size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('map') || stepName.toLowerCase().includes('sections')) {
      return <FaMap size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('iterator')) {
      return <FaList size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('ocr')) {
      return <FaFileAlt size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('classification')) {
      return <FaRobot size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('extraction')) {
      return <FaRobot size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('assessment')) {
      return <FaEye size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('summarization')) {
      return <FaChartBar size={iconProps.size} className={iconProps.className} />;
    }
    if (stepName.toLowerCase().includes('workflow')) {
      return <FaCheck size={iconProps.size} className={iconProps.className} />;
    }

    // Default icons based on status
    switch (status) {
      case 'SUCCEEDED':
        return <FaCheck size={iconProps.size} className={iconProps.className} />;
      case 'FAILED':
        return <FaTimes size={iconProps.size} className={iconProps.className} />;
      case 'RUNNING':
        return <FaClock size={iconProps.size} className={iconProps.className} />;
      default:
        return <FaPlay size={iconProps.size} className={iconProps.className} />;
    }
  };

  const formatDuration = (startDate, stopDate) => {
    if (!startDate) return 'N/A';
    const start = new Date(startDate);
    const end = stopDate ? new Date(stopDate) : new Date();
    const duration = Math.floor((end - start) / 1000);

    const minutes = Math.floor(duration / 60);
    const seconds = duration % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  if (loading && !data) {
    return (
      <Modal visible={visible} onDismiss={onDismiss} header="Document Processing Flow" size="max">
        <Box textAlign="center" padding="xxl">
          <Spinner size="large" />
          <Box variant="p" margin={{ top: 'm' }}>
            Loading processing flow...
          </Box>
        </Box>
      </Modal>
    );
  }

  if (error) {
    return (
      <Modal visible={visible} onDismiss={onDismiss} header="Document Processing Flow" size="max">
        <Alert type="error" header="Error loading processing flow">
          {error.message || 'An error occurred while loading the processing flow.'}
        </Alert>
      </Modal>
    );
  }

  const execution = data?.getStepFunctionExecution;
  if (!execution) {
    return (
      <Modal visible={visible} onDismiss={onDismiss} header="Document Processing Flow" size="max">
        <Alert type="info" header="No processing flow found">
          No Step Functions execution found for this document.
        </Alert>
      </Modal>
    );
  }

  // Check if execution has a top-level error
  const hasExecutionError = execution.status === 'FAILED' && execution.error;

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={
        <Header
          variant="h2"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              {getStatusIndicator()}
              <Button
                variant={autoRefreshEnabled ? 'primary' : 'normal'}
                onClick={toggleAutoRefresh}
                iconName={autoRefreshEnabled ? 'refresh' : 'settings'}
              >
                {autoRefreshEnabled ? 'Disable' : 'Enable'} Auto-Refresh
              </Button>
              <Button onClick={() => fetchStepFunctionExecution()} iconName="refresh" loading={loading}>
                Refresh Now
              </Button>
              {lastRefreshTime && (
                <Box variant="small" color="text-body-secondary">
                  Last updated: {lastRefreshTime.toLocaleTimeString()}
                </Box>
              )}
            </SpaceBetween>
          }
        >
          Document Processing Flow
        </Header>
      }
      size="max"
    >
      <SpaceBetween size="l">
        {/* Execution Overview */}
        <Container header={<Header variant="h3">Execution Overview</Header>}>
          <SpaceBetween size="l">
            <SpaceBetween direction="horizontal" size="l">
              <Box>
                <Box variant="awsui-key-label">Status</Box>
                <Box className={`execution-status execution-status-${execution.status.toLowerCase()}`}>
                  {execution.status}
                </Box>
              </Box>
              <Box>
                <Box variant="awsui-key-label">Duration</Box>
                <Box>{formatDuration(execution.startDate, execution.stopDate)}</Box>
              </Box>
              <Box>
                <Box variant="awsui-key-label">Started</Box>
                <Box>{execution.startDate ? new Date(execution.startDate).toLocaleString() : 'N/A'}</Box>
              </Box>
              {execution.stopDate && (
                <Box>
                  <Box variant="awsui-key-label">Completed</Box>
                  <Box>{new Date(execution.stopDate).toLocaleString()}</Box>
                </Box>
              )}
            </SpaceBetween>

            {/* Display execution-level error if present */}
            {hasExecutionError && (
              <Alert type="error" header="Execution Failed">
                <SpaceBetween size="s">
                  <Box>
                    <FaExclamationTriangle size={20} style={{ marginRight: '8px', color: '#d13212' }} />
                    <strong>Error:</strong> {execution.error}
                  </Box>
                </SpaceBetween>
              </Alert>
            )}
          </SpaceBetween>
        </Container>

        {/* Flow Diagram */}
        <Container header={<Header variant="h3">Processing Flow</Header>}>
          <FlowDiagram
            steps={processedSteps.length > 0 ? processedSteps : execution.steps || []}
            onStepClick={setSelectedStep}
            selectedStep={selectedStep}
            getStepIcon={getStepIcon}
            mergedConfig={mergedConfig}
          />
        </Container>

        {/* Step Details */}
        {selectedStep && (
          <Container header={<Header variant="h3">Step Details</Header>}>
            <StepDetails
              step={selectedStep}
              formatDuration={formatDuration}
              getStepIcon={getStepIcon}
              mergedConfig={mergedConfig}
            />
          </Container>
        )}

        {/* Steps Timeline */}
        <Container header={<Header variant="h3">Steps Timeline</Header>}>
          <div className="steps-timeline">
            {(processedSteps.length > 0 ? processedSteps : execution.steps)?.map((step, index) => {
              const stepDisabled = isStepDisabled(step.name, mergedConfig);
              return (
                <div
                  key={`timeline-${step.name}-${step.type}-${step.status}-${step.startDate || index}`}
                  className={`timeline-step ${step.status.toLowerCase()} ${
                    selectedStep?.name === step.name ? 'selected' : ''
                  } ${step.isMapIteration ? 'map-iteration-step' : ''} ${stepDisabled ? 'step-disabled' : ''}`}
                  onClick={() => setSelectedStep(step)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      setSelectedStep(step);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  title={stepDisabled ? 'This step was disabled in configuration and performed no processing' : ''}
                >
                  <div className="timeline-step-icon">{getStepIcon(step.name, step.type, step.status)}</div>
                  <div className="timeline-step-content">
                    <div className="timeline-step-name">
                      {step.name}
                      {stepDisabled && <Badge color="grey">NOT ENABLED</Badge>}
                      {step.isMapIteration && <Badge color="green">Map Iteration</Badge>}
                      {step.type === 'Map' && step.mapIterations && (
                        <Badge color="blue">{step.mapIterations} iterations</Badge>
                      )}
                    </div>
                    <div className="timeline-step-meta">
                      <span className={`timeline-step-status status-${step.status.toLowerCase()}`}>{step.status}</span>
                      <span className="timeline-step-duration">{formatDuration(step.startDate, step.stopDate)}</span>
                    </div>
                    {step.error && (
                      <div className="timeline-step-error">
                        <FaExclamationTriangle size={14} style={{ marginRight: '4px', color: '#d13212' }} />
                        <strong>Error:</strong>{' '}
                        {step.error.length > 100 ? `${step.error.substring(0, 100)}...` : step.error}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Container>
      </SpaceBetween>
    </Modal>
  );
};

StepFunctionFlowViewer.propTypes = {
  executionArn: PropTypes.string.isRequired,
  visible: PropTypes.bool.isRequired,
  onDismiss: PropTypes.func.isRequired,
  mergedConfig: PropTypes.shape({
    summarization: PropTypes.shape({
      enabled: PropTypes.bool,
    }),
    assessment: PropTypes.shape({
      enabled: PropTypes.bool,
    }),
  }),
};

StepFunctionFlowViewer.defaultProps = {
  mergedConfig: null,
};

export default StepFunctionFlowViewer;
