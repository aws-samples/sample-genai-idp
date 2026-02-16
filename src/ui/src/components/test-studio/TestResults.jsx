// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect, useMemo } from 'react';
import PropTypes from 'prop-types';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  ColumnLayout,
  ProgressBar,
  Badge,
  Alert,
  Table,
  Button,
  Modal,
  Textarea,
  FormField,
  Input,
  Select,
  CollectionPreferences,
  ExpandableSection,
  RadioGroup,
  Link,
} from '@cloudscape-design/components';
// eslint-disable-next-line import/no-extraneous-dependencies
import yaml from 'js-yaml';
import { generateClient } from 'aws-amplify/api';
import GET_TEST_RUN from '../../graphql/queries/getTestResults';
import START_TEST_RUN from '../../graphql/queries/startTestRun';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import GET_TEST_SETS from '../../graphql/queries/getTestSets';
import TestStudioHeader from './TestStudioHeader';
import useAppContext from '../../contexts/app';
import { formatConfigVersionLink } from './utils/configVersionUtils';

const client = generateClient();

/* eslint-disable react/prop-types */
const ComprehensiveBreakdown = ({
  costBreakdown,
  accuracyBreakdown,
  splitClassificationMetrics,
  averageWeightedScore,
  preferences,
  setPreferences,
}) => {
  if (!costBreakdown && !accuracyBreakdown && !splitClassificationMetrics) {
    return <Box>No breakdown data available</Box>;
  }

  return (
    <SpaceBetween direction="vertical" size="l">
      {/* Combined Accuracy and Split Classification Metrics */}
      {(accuracyBreakdown || splitClassificationMetrics) && (
        <Container
          header={<Header variant="h3">Average Accuracy and Split Metrics</Header>}
          preferences={<TestResultsPreferences preferences={preferences} setPreferences={setPreferences} />}
        >
          <SpaceBetween direction="vertical" size="m">
            {/* Main metrics */}
            <Table
              resizableColumns
              wrapLines={preferences.wrapLines}
              preferences={<TestResultsPreferences preferences={preferences} setPreferences={setPreferences} />}
              items={(() => {
                const mainItems = [];

                // Add Weighted Overall Score
                if (averageWeightedScore !== null) {
                  mainItems.push({
                    metric: (
                      <>
                        <span style={{ color: '#687078' }}>Extraction:</span> Weighted Overall Score
                      </>
                    ),
                    value: averageWeightedScore.toFixed(3),
                  });
                }

                // Add Page and Split with Order Accuracy
                if (splitClassificationMetrics) {
                  if (splitClassificationMetrics.page_level_accuracy !== undefined) {
                    mainItems.push({
                      metric: (
                        <>
                          <span style={{ color: '#687078' }}>Classification:</span> Page Level Accuracy
                        </>
                      ),
                      value:
                        typeof splitClassificationMetrics.page_level_accuracy === 'number'
                          ? splitClassificationMetrics.page_level_accuracy.toFixed(3)
                          : splitClassificationMetrics.page_level_accuracy?.toString() || '0',
                    });
                  }

                  if (splitClassificationMetrics.split_accuracy_with_order !== undefined) {
                    mainItems.push({
                      metric: (
                        <>
                          <span style={{ color: '#687078' }}>Classification:</span> Split Accuracy With Order
                        </>
                      ),
                      value:
                        typeof splitClassificationMetrics.split_accuracy_with_order === 'number'
                          ? splitClassificationMetrics.split_accuracy_with_order.toFixed(3)
                          : splitClassificationMetrics.split_accuracy_with_order?.toString() || '0',
                    });
                  }
                }

                return mainItems;
              })()}
              columnDefinitions={[
                { id: 'metric', header: 'Metric', cell: (item) => item.metric, width: 400 },
                { id: 'value', header: 'Value', cell: (item) => item.value, width: 200 },
              ]}
              variant="embedded"
            />

            {/* Details in collapsible section */}
            <ExpandableSection headerText="Additional Metrics">
              <Container>
                <Table
                  resizableColumns
                  wrapLines={preferences.wrapLines}
                  preferences={<div />}
                  items={[
                    // All accuracy breakdown metrics
                    ...(accuracyBreakdown
                      ? Object.entries(accuracyBreakdown).map(([key, value]) => ({
                          metric: (
                            <>
                              <span style={{ color: '#687078' }}>Extraction:</span>{' '}
                              {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                            </>
                          ),
                          value: value !== null && value !== undefined ? value.toFixed(3) : '0.000',
                        }))
                      : []),
                    // Remaining split classification metrics
                    ...(splitClassificationMetrics
                      ? Object.entries(splitClassificationMetrics)
                          .filter(([key]) => key !== 'page_level_accuracy' && key !== 'split_accuracy_with_order')
                          .map(([key, value]) => ({
                            metric: (
                              <>
                                <span style={{ color: '#687078' }}>Classification:</span>{' '}
                                {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                              </>
                            ),
                            value:
                              typeof value === 'number' && key.includes('accuracy')
                                ? value.toFixed(3)
                                : value !== null && value !== undefined
                                ? value.toString()
                                : '0',
                          }))
                      : []),
                  ]}
                  columnDefinitions={[
                    { id: 'metric', header: 'Metric', cell: (item) => item.metric, width: 400 },
                    { id: 'value', header: 'Value', cell: (item) => item.value, width: 200 },
                  ]}
                  variant="embedded"
                />
              </Container>
            </ExpandableSection>
          </SpaceBetween>
        </Container>
      )}

      {/* Cost breakdown */}
      {costBreakdown && (
        <Container header={<Header variant="h3">Estimated Cost</Header>}>
          <Table
            resizableColumns
            wrapLines={preferences.wrapLines}
            items={(() => {
              const costItems = [];
              let totalCost = 0;
              const contextTotals = {};

              // First pass: collect all items and calculate context totals
              Object.entries(costBreakdown).forEach(([context, services]) => {
                let contextSubtotal = 0;

                Object.entries(services).forEach(([serviceUnit, details]) => {
                  // Parse service/api_unit format: find last underscore to separate unit
                  const lastUnderscoreIndex = serviceUnit.lastIndexOf('_');
                  const serviceApi = serviceUnit.substring(0, lastUnderscoreIndex);
                  const unit = serviceUnit.substring(lastUnderscoreIndex + 1);
                  const [service, api] = serviceApi.split('/');

                  const cost = details.estimated_cost || 0;
                  contextSubtotal += cost;

                  costItems.push({
                    context,
                    serviceApi: `${service}/${api}`,
                    unit: details.unit || unit,
                    value: details.value || 'N/A',
                    unitCost: details.unit_cost ? `$${details.unit_cost}` : 'None',
                    estimatedCost: cost > 0 ? `$${cost.toFixed(4)}` : 'N/A',
                    sortOrder: 0, // Regular items
                  });
                });

                contextTotals[context] = contextSubtotal;
                totalCost += contextSubtotal;
              });

              // Sort items by context first, then by service/api
              costItems.sort((a, b) => {
                if (a.context !== b.context) {
                  return a.context.localeCompare(b.context);
                }
                return a.serviceApi.localeCompare(b.serviceApi);
              });

              // Second pass: insert subtotal rows after each context group
              const finalItems = [];
              let currentContext = null;

              costItems.forEach((item, index) => {
                // Add the regular item
                finalItems.push(item);

                // Check if this is the last item for this context
                const nextItem = costItems[index + 1];
                const isLastInContext = !nextItem || nextItem.context !== item.context;

                if (isLastInContext) {
                  // Add subtotal row for every context
                  finalItems.push({
                    context: '',
                    serviceApi: `${item.context} Subtotal`,
                    unit: '',
                    value: '',
                    unitCost: '',
                    estimatedCost: `$${contextTotals[item.context].toFixed(4)}`,
                    isSubtotal: true,
                    sortOrder: 1, // Subtotal items
                  });
                }
              });

              // Add total row
              if (totalCost > 0) {
                finalItems.push({
                  context: '',
                  serviceApi: 'Total',
                  unit: '',
                  value: '',
                  unitCost: '',
                  estimatedCost: `$${totalCost.toFixed(4)}`,
                  isTotal: true,
                  sortOrder: 2, // Total item
                });
              }

              return finalItems;
            })()}
            columnDefinitions={[
              {
                id: 'context',
                header: 'Context',
                cell: (item) => (item.isSubtotal || item.isTotal ? '' : item.context),
              },
              {
                id: 'serviceApi',
                header: 'Service/Api',
                cell: (item) => (
                  <span
                    style={{
                      fontWeight: item.isSubtotal || item.isTotal ? 'bold' : 'normal',
                      color: item.isTotal ? '#0073bb' : 'inherit',
                    }}
                  >
                    {item.serviceApi}
                  </span>
                ),
              },
              {
                id: 'unit',
                header: 'Unit',
                cell: (item) => (item.isSubtotal || item.isTotal ? '' : item.unit),
              },
              {
                id: 'value',
                header: 'Value',
                cell: (item) => {
                  if (item.isSubtotal || item.isTotal) return '';
                  const value = item.value;
                  if (value === 'N/A' || !value) return 'N/A';
                  const numValue = parseFloat(value.toString().replace(/,/g, ''));
                  return isNaN(numValue) ? value : numValue.toLocaleString();
                },
              },
              {
                id: 'unitCost',
                header: 'Unit Cost',
                cell: (item) => (item.isSubtotal || item.isTotal ? '' : item.unitCost),
              },
              {
                id: 'estimatedCost',
                header: 'Estimated Cost',
                cell: (item) => {
                  if (item.isSubtotal || item.isTotal) {
                    return <span style={{ fontWeight: 'bold', color: item.isTotal ? '#0073bb' : 'inherit' }}>{item.estimatedCost}</span>;
                  }
                  const cost = item.estimatedCost;
                  if (cost === 'N/A' || !cost) return 'N/A';
                  const numValue = parseFloat(cost.toString().replace('$', ''));
                  return isNaN(numValue) ? cost : `$${numValue.toFixed(4)}`;
                },
              },
            ]}
            variant="embedded"
          />
        </Container>
      )}
    </SpaceBetween>
  );
};

// Preferences component
const TestResultsPreferences = ({ preferences, setPreferences }) => (
  <CollectionPreferences
    title="Preferences"
    confirmLabel="Confirm"
    cancelLabel="Cancel"
    preferences={preferences}
    onConfirm={({ detail }) => setPreferences(detail)}
    wrapLinesPreference={{
      label: 'Wrap lines',
      description: 'Check to see all the text and wrap the lines',
    }}
  />
);

TestResultsPreferences.propTypes = {
  preferences: PropTypes.object.isRequired,
  setPreferences: PropTypes.func.isRequired,
};

const TestResults = ({ testRunId, setSelectedTestRunId }) => {
  const { addTestRun } = useAppContext();
  const { versions } = useConfigurationVersions();
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentAttempt, setCurrentAttempt] = useState(1);
  const [reRunLoading, setReRunLoading] = useState(false);
  const [showReRunModal, setShowReRunModal] = useState(false);
  const [reRunContext, setReRunContext] = useState('');
  const [reRunNumberOfFiles, setReRunNumberOfFiles] = useState('');
  const [testSetFileCount, setTestSetFileCount] = useState(null);
  const [testSetStatus, setTestSetStatus] = useState(null);
  const [testSetFilePattern, setTestSetFilePattern] = useState(null);
  const [chartType, setChartType] = useState({ label: 'Bar Chart', value: 'bar' });
  const [retryMessage, setRetryMessage] = useState('');
  const [preferences, setPreferences] = useState({ wrapLines: false });
  const [showDocumentsModal, setShowDocumentsModal] = useState(false);
  const [selectedRangeData, setSelectedRangeData] = useState(null);
  const [lowestScoreCount, setLowestScoreCount] = useState({ label: '5', value: 5 });

  // Config export modal state
  const [showConfigExportModal, setShowConfigExportModal] = useState(false);
  const [configExportFormat, setConfigExportFormat] = useState('json');
  const [configExportFileName, setConfigExportFileName] = useState('');

  const getProgressMessage = (progressLevel) => {
    if (progressLevel <= 1) return 'Initializing test results...';
    if (progressLevel <= 2) return 'Processing evaluation data...';
    if (progressLevel <= 3) return 'Calculating accuracy metrics...';
    if (progressLevel <= 4) return 'Generating cost analysis...';
    return 'Finalizing results...';
  };

  const checkTestSetStatus = async () => {
    if (!results?.testSetId) return;

    try {
      const testSetsResult = await client.graphql({
        query: GET_TEST_SETS,
      });

      const testSets = testSetsResult.data.getTestSets || [];
      const testSet = testSets.find((ts) => ts.id === results.testSetId);

      if (testSet) {
        setTestSetStatus(testSet.status);
        setTestSetFileCount(testSet.fileCount);
        setTestSetFilePattern(testSet.filePattern);
      } else {
        setTestSetStatus('NOT_FOUND');
        setTestSetFileCount(0);
        setTestSetFilePattern(null);
      }
    } catch (err) {
      console.error('Failed to check test set status:', err);
      setTestSetStatus('ERROR');
      setTestSetFileCount(0);
    }
  };

  useEffect(() => {
    let isCancelled = false;
    const timeouts = []; // Track all timeouts to clear them

    const fetchResults = async () => {
      if (isCancelled) return;

      // Clear any existing timeouts
      const clearAllTimeouts = () => {
        timeouts.forEach(clearTimeout);
        timeouts.length = 0;
      };

      try {
        let result;
        let attempt = 1;
        const maxRetries = 5;

        while (attempt <= maxRetries && !isCancelled) {
          try {
            console.log(`GET_TEST_RUN attempt ${attempt} starting...`);
            if (attempt === 1) {
              setCurrentAttempt(1);
              setRetryMessage('Getting results from cache...');

              // Show cache miss progression after 1 second for first attempt
              timeouts.push(
                setTimeout(() => {
                  if (!isCancelled) {
                    setRetryMessage('No cache found, generating results...');
                    setCurrentAttempt(2);
                  }
                }, 1000),
              );

              timeouts.push(
                setTimeout(() => {
                  if (!isCancelled) {
                    setRetryMessage(getProgressMessage(2));
                    setCurrentAttempt(3);
                  }
                }, 2000),
              );

              timeouts.push(
                setTimeout(() => {
                  if (!isCancelled) {
                    setRetryMessage(getProgressMessage(3));
                    setCurrentAttempt(4);
                  }
                }, 4000),
              );
            }

            if (isCancelled) return;

            result = await client.graphql({
              query: GET_TEST_RUN,
              variables: { testRunId },
            });

            if (isCancelled) return;

            console.log('GET_TEST_RUN result:', result);
            clearAllTimeouts(); // Clear timeouts on success
            setCurrentAttempt(10); // Set to 100% before completing
            await new Promise((resolve) => setTimeout(resolve, 500)); // Brief pause to show 100%
            break;
          } catch (retryError) {
            if (isCancelled) return;

            console.log('GET_TEST_RUN error caught:', {
              message: retryError.message,
              code: retryError.code,
              name: retryError.name,
              error: retryError,
            });
            const isTimeout =
              retryError.message?.toLowerCase().includes('timeout') ||
              retryError.code === 'TIMEOUT' ||
              retryError.message?.includes('Request failed with status code 504') ||
              retryError.name === 'TimeoutError' ||
              retryError.code === 'NetworkError' ||
              retryError.errors?.some(
                (err) => err.errorType === 'Lambda:ExecutionTimeoutException' || err.message?.toLowerCase().includes('timeout'),
              );
            if (isTimeout && attempt < maxRetries) {
              console.log(`GET_TEST_RUN attempt ${attempt} failed, retrying...`, retryError.message);

              clearAllTimeouts(); // Clear any running timeouts

              // Always move progress forward, never backwards
              setCurrentAttempt((currentProgress) => {
                const targetProgress = Math.min(currentProgress + 1, 9); // Move forward by 1 step, cap at 90%
                return Math.max(currentProgress, targetProgress);
              });

              attempt++;
              const waitTime = Math.max(2000, 5000 - attempt * 1000); // 5s, 4s, 3s, 2s min

              setRetryMessage(getProgressMessage(Math.min(attempt + 1, 5)));

              await new Promise((resolve) => setTimeout(resolve, waitTime));
              continue;
            }
            throw retryError;
          }
        }

        if (!isCancelled) {
          const testRun = result.data.getTestRun;
          console.log('Test results:', testRun);
          setResults(testRun);
        }
      } catch (err) {
        if (!isCancelled) {
          setError(err.message);
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    };

    fetchResults();

    // Cleanup function
    return () => {
      isCancelled = true;
      timeouts.forEach(clearTimeout);
    };
  }, [testRunId]);

  useEffect(() => {
    if (results?.testSetId) {
      checkTestSetStatus();
    }
  }, [results]);

  if (loading) return <ProgressBar status="in-progress" label={retryMessage || 'Loading test results...'} value={currentAttempt * 10} />;
  if (error) return <Box>Error loading test results: {error}</Box>;
  if (!results) {
    const handleBackClick = () => {
      if (setSelectedTestRunId) {
        setSelectedTestRunId(null);
      } else {
        window.location.replace('#/test-studio?tab=executions');
      }
    };

    return (
      <Container header={<TestStudioHeader title={`Test Results: ${testRunId}`} onBackClick={handleBackClick} />}>
        <Box>No test results found</Box>
      </Container>
    );
  }

  const getStatusColor = (status) => {
    if (status === 'COMPLETE') return 'green';
    if (status === 'RUNNING') return 'blue';
    return 'red';
  };

  const hasAccuracyData = results.overallAccuracy !== null && results.overallAccuracy !== undefined;

  // Calculate average weighted overall score
  const averageWeightedScore = (() => {
    if (!results.weightedOverallScores) return null;
    const scores =
      typeof results.weightedOverallScores === 'string' ? JSON.parse(results.weightedOverallScores) : results.weightedOverallScores;
    const values = Object.values(scores);
    return values.length > 0 ? values.reduce((sum, score) => sum + score, 0) / values.length : null;
  })();

  let costBreakdown = null;
  let accuracyBreakdown = null;
  let splitClassificationMetrics = null;

  try {
    if (results.costBreakdown) {
      costBreakdown = typeof results.costBreakdown === 'string' ? JSON.parse(results.costBreakdown) : results.costBreakdown;
    }
    if (results.accuracyBreakdown) {
      accuracyBreakdown = typeof results.accuracyBreakdown === 'string' ? JSON.parse(results.accuracyBreakdown) : results.accuracyBreakdown;
    }
    if (results.splitClassificationMetrics) {
      splitClassificationMetrics =
        typeof results.splitClassificationMetrics === 'string'
          ? JSON.parse(results.splitClassificationMetrics)
          : results.splitClassificationMetrics;
    }
  } catch (e) {
    console.error('Error parsing breakdown data:', e);
  }

  // Helper function to get merged config from results.config
  // The config may be stored as a JSON string (possibly double-stringified) with {Default: {...}, Custom: {...}} or already merged
  const getMergedConfig = (config) => {
    if (!config) return null;

    // Parse if it's a string (may be double-stringified)
    let parsedConfig = config;
    while (typeof parsedConfig === 'string') {
      try {
        parsedConfig = JSON.parse(parsedConfig);
      } catch (e) {
        console.error('Failed to parse config string:', e);
        return null;
      }
    }

    // If config is wrapped in a "Config" object, extract it
    if (parsedConfig && parsedConfig.Config && typeof parsedConfig.Config === 'object') {
      parsedConfig = parsedConfig.Config;
    }

    // Deep merge helper function
    const deepMerge = (target, source) => {
      const output = { ...target };
      if (source && typeof source === 'object' && !Array.isArray(source)) {
        Object.keys(source).forEach((key) => {
          if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
            if (target[key] && typeof target[key] === 'object' && !Array.isArray(target[key])) {
              output[key] = deepMerge(target[key], source[key]);
            } else {
              output[key] = { ...source[key] };
            }
          } else {
            output[key] = source[key];
          }
        });
      }
      return output;
    };

    // If config has Default and Custom properties, merge them
    if (parsedConfig && parsedConfig.Default && typeof parsedConfig.Default === 'object') {
      const defaultConfig = parsedConfig.Default;
      const customConfig = parsedConfig.Custom || {};

      console.log('Merging Default and Custom configs');
      return deepMerge(defaultConfig, customConfig);
    }

    // Config is already in merged format
    console.log('Config already in merged format or no Default/Custom found');
    return parsedConfig;
  };

  // Open config export modal
  const openConfigExportModal = () => {
    if (!results?.config) {
      console.error('No config data available');
      return;
    }
    // Set default filename based on testRunId
    setConfigExportFileName(`test-run-${results.testRunId}-config`);
    setConfigExportFormat('json');
    setShowConfigExportModal(true);
  };

  // Handle config export
  const handleConfigExport = () => {
    try {
      const mergedConfig = getMergedConfig(results.config);
      if (!mergedConfig) {
        console.error('No config data available');
        return;
      }

      let content;
      let mimeType;
      let fileExtension;

      if (configExportFormat === 'yaml') {
        content = yaml.dump(mergedConfig);
        mimeType = 'text/yaml';
        fileExtension = 'yaml';
      } else {
        content = JSON.stringify(mergedConfig, null, 2);
        mimeType = 'application/json';
        fileExtension = 'json';
      }

      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${configExportFileName}.${fileExtension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setShowConfigExportModal(false);
    } catch (err) {
      console.error('Export failed:', err);
    }
  };

  const handleReRun = async () => {
    console.log('=== handleReRun START ===');
    console.log('results.testSetId:', results?.testSetId);
    console.log('results.testSetName:', results?.testSetName);

    const testSetId = results?.testSetId;
    console.log('Using testSetId:', testSetId);

    if (!testSetId) {
      console.error('No testSetId found in results. Cannot re-run without testSetId.');
      return;
    }

    // Validate numberOfFiles if provided
    if (reRunNumberOfFiles.trim()) {
      const numFiles = parseInt(reRunNumberOfFiles.trim(), 10);
      if (isNaN(numFiles) || numFiles <= 0) {
        console.error('Invalid numberOfFiles value');
        return;
      }
      if (numFiles > testSetFileCount) {
        console.error(`numberOfFiles (${numFiles}) exceeds test set file count (${testSetFileCount})`);
        return;
      }
    }

    setReRunLoading(true);

    try {
      const input = {
        testSetId: testSetId,
        ...(reRunContext && { context: reRunContext }),
        ...(reRunNumberOfFiles.trim() && { numberOfFiles: parseInt(reRunNumberOfFiles.trim(), 10) }),
      };

      console.log('About to call GraphQL with input:', input);

      const result = await client.graphql({
        query: START_TEST_RUN,
        variables: { input },
      });

      console.log('GraphQL call completed, result:', result);

      if (result?.data?.startTestRun) {
        console.log('Success! Closing modal and redirecting...');
        const newTestRun = result.data.startTestRun;
        // Add to active test runs
        addTestRun(newTestRun.testRunId, newTestRun.testSetName, reRunContext, newTestRun.filesCount);
        setShowReRunModal(false);
        setReRunContext('');
        setReRunNumberOfFiles('');
        // Navigate to test executions tab
        window.location.hash = '#/test-studio?tab=executions';
      } else {
        console.error('No startTestRun data in result');
      }
    } catch (err) {
      console.error('GraphQL call failed:', err);
      if (err.errors) {
        err.errors.forEach((errorItem, index) => {
          console.error(`Error ${index}:`, errorItem.message);
        });
      }
    } finally {
      setReRunLoading(false);
    }
    console.log('=== handleReRun END ===');
  };

  const reRunButton = results?.testSetId ? (
    <Button
      onClick={() => {
        setShowReRunModal(true);
      }}
      iconName="arrow-right"
      disabled={!testSetFileCount || testSetFileCount === 0}
    >
      Re-Run
    </Button>
  ) : null;

  const configButton = (
    <Button onClick={openConfigExportModal} iconName="download">
      Config
    </Button>
  );

  const contextDescription = results.context ? (
    <Box variant="p" color="text-body-secondary" margin={{ top: 'xs' }}>
      Context: {results.context}
    </Box>
  ) : null;

  const handleBackClick = () => {
    if (setSelectedTestRunId) {
      setSelectedTestRunId(null);
    } else {
      window.location.replace('#/test-studio?tab=executions');
    }
  };

  return (
    <Container
      header={
        <TestStudioHeader
          title={`Test Results: ${results.testRunId} (${results.testSetName})`}
          description={contextDescription}
          showPrintButton={true}
          additionalActions={[configButton, reRunButton].filter(Boolean)}
          onBackClick={handleBackClick}
        />
      }
    >
      <SpaceBetween direction="vertical" size="l">
        {/* Overall Status */}
        <Box>
          <Badge color={getStatusColor(results.status)}>{results.status}</Badge>
          <Box margin={{ left: 's' }} display="inline">
            {results.completedFiles}/{results.filesCount} files processed
          </Box>
        </Box>

        {/* Test Results Alert */}
        {hasAccuracyData && (
          <Alert type="success" header="Test Results Available">
            Test run completed with accuracy and performance metrics
          </Alert>
        )}

        {!hasAccuracyData && results.status === 'COMPLETE' && (
          <Alert type="warning" header="No Accuracy Data">
            Test run completed but accuracy metrics are not available
          </Alert>
        )}

        {/* Key Metrics */}
        <ColumnLayout columns={6} variant="text-grid">
          <Box>
            <Box variant="awsui-key-label">Total Cost</Box>
            <Box fontSize="heading-l">
              {results.totalCost !== null && results.totalCost !== undefined ? `$${results.totalCost.toFixed(4)}` : 'N/A'}
            </Box>
          </Box>
          <Box>
            <Box variant="awsui-key-label">Avg Confidence</Box>
            <Box fontSize="heading-l">
              {results.averageConfidence !== null && results.averageConfidence !== undefined
                ? `${(results.averageConfidence * 100).toFixed(1)}%`
                : 'N/A'}
            </Box>
          </Box>
          <Box>
            <Box variant="awsui-key-label">Avg Accuracy</Box>
            <Box fontSize="heading-l">
              {results.overallAccuracy !== null && results.overallAccuracy !== undefined ? results.overallAccuracy.toFixed(3) : 'N/A'}
            </Box>
          </Box>
          <Box>
            <Box variant="awsui-key-label">Avg Weighted Score</Box>
            <Box fontSize="heading-l">{averageWeightedScore !== null ? averageWeightedScore.toFixed(3) : 'N/A'}</Box>
          </Box>
          <Box>
            <Box variant="awsui-key-label">Duration</Box>
            <Box fontSize="heading-l">
              {results.createdAt && results.completedAt
                ? (() => {
                    const duration = new Date(results.completedAt) - new Date(results.createdAt);
                    const minutes = Math.floor(duration / 60000);
                    const seconds = Math.floor((duration % 60000) / 1000);
                    return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
                  })()
                : 'N/A'}
            </Box>
          </Box>
          {results.configVersion && (
            <Box>
              <Box variant="awsui-key-label">Config Version</Box>
              <Box fontSize="heading-l">{formatConfigVersionLink(results.configVersion, versions)}</Box>
            </Box>
          )}
        </ColumnLayout>

        {/* Weighted Overall Scores Distribution Chart */}
        {results.weightedOverallScores && Object.keys(results.weightedOverallScores).length > 1 && (
          <Container
            header={
              <Header
                variant="h3"
                actions={
                  <Select
                    selectedOption={chartType}
                    onChange={({ detail }) => setChartType(detail.selectedOption)}
                    options={[
                      { label: 'Bar Chart', value: 'bar' },
                      { label: 'Line Chart', value: 'line' },
                    ]}
                    placeholder="Select chart type"
                  />
                }
              >
                Weighted Overall Score Distribution ({results.testRunId})
              </Header>
            }
          >
            {(() => {
              const generateChartData = () => {
                const scores =
                  typeof results.weightedOverallScores === 'string'
                    ? JSON.parse(results.weightedOverallScores)
                    : results.weightedOverallScores;

                // Create score range buckets
                const buckets = {
                  '0.0-0.1': { count: 0, docs: [] },
                  '0.1-0.2': { count: 0, docs: [] },
                  '0.2-0.3': { count: 0, docs: [] },
                  '0.3-0.4': { count: 0, docs: [] },
                  '0.4-0.5': { count: 0, docs: [] },
                  '0.5-0.6': { count: 0, docs: [] },
                  '0.6-0.7': { count: 0, docs: [] },
                  '0.7-0.8': { count: 0, docs: [] },
                  '0.8-0.9': { count: 0, docs: [] },
                  '0.9-1.0': { count: 0, docs: [] },
                };

                // Count documents and collect IDs in each bucket
                Object.entries(scores).forEach(([docId, score]) => {
                  let bucket;
                  if (score < 0.1) bucket = '0.0-0.1';
                  else if (score < 0.2) bucket = '0.1-0.2';
                  else if (score < 0.3) bucket = '0.2-0.3';
                  else if (score < 0.4) bucket = '0.3-0.4';
                  else if (score < 0.5) bucket = '0.4-0.5';
                  else if (score < 0.6) bucket = '0.5-0.6';
                  else if (score < 0.7) bucket = '0.6-0.7';
                  else if (score < 0.8) bucket = '0.7-0.8';
                  else if (score < 0.9) bucket = '0.8-0.9';
                  else bucket = '0.9-1.0';

                  buckets[bucket].count++;
                  buckets[bucket].docs.push({ docId, score });
                });

                let maxCount = 0;
                const mappedData = Object.entries(buckets).map(([range, data]) => {
                  if (data.count > maxCount) {
                    maxCount = data.count;
                  }

                  const sortedDocs = data.docs.sort((a, b) => b.score - a.score);
                  const topDocs = sortedDocs.slice(0, 3);

                  let tooltip = `${data.count} documents in range ${range}\n\n`;
                  topDocs.forEach((doc) => {
                    tooltip += `• ${doc.docId} (${doc.score?.toFixed(3)})\n`;
                  });
                  if (data.docs.length > 3) {
                    tooltip += `\n...and ${data.docs.length - 3} more documents`;
                  }

                  return {
                    x: range,
                    y: data.count,
                    tooltip: tooltip,
                  };
                });

                return { mappedData, maxCount, buckets };
              };

              const { mappedData, maxCount, buckets } = generateChartData();

              const chartData = mappedData.map((item) => ({
                range: item.x,
                count: item.y,
                tooltip: item.tooltip,
              }));

              return (
                <ResponsiveContainer width="100%" height={320}>
                  {chartType.value === 'bar' ? (
                    <BarChart data={chartData} margin={{ top: 20, right: 20, left: 20, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="range"
                        angle={-45}
                        textAnchor="end"
                        height={55}
                        interval={0}
                        label={{ value: 'Weighted Overall Score Range', position: 'insideBottom', offset: -8 }}
                      />
                      <YAxis
                        label={{ value: 'Number of Documents', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
                      />
                      <Tooltip
                        formatter={(value, name) => [value, 'Number of Documents']}
                        labelFormatter={(label) => `Score Range: ${label}`}
                      />
                      <Bar
                        dataKey="count"
                        fill="#0073bb"
                        onClick={(data) => {
                          const range = data.range;
                          if (range && buckets[range] && buckets[range].docs.length > 0) {
                            const docs = buckets[range].docs.sort((a, b) => b.score - a.score);
                            setSelectedRangeData({ range, docs });
                            setTimeout(() => {
                              setShowDocumentsModal(true);
                            }, 0);
                          }
                        }}
                      />
                    </BarChart>
                  ) : (
                    <LineChart data={chartData} margin={{ top: 20, right: 20, left: 20, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="range"
                        angle={-45}
                        textAnchor="end"
                        height={55}
                        interval={0}
                        label={{ value: 'Weighted Overall Score Range', position: 'insideBottom', offset: -8 }}
                      />
                      <YAxis
                        label={{ value: 'Number of Documents', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
                      />
                      <Tooltip
                        formatter={(value, name) => [value, 'Number of Documents']}
                        labelFormatter={(label) => `Score Range: ${label}`}
                      />
                      <Line
                        type="monotone"
                        dataKey="count"
                        stroke="#0073bb"
                        strokeWidth={2}
                        dot={{ fill: '#0073bb', strokeWidth: 2, r: 4, cursor: 'pointer' }}
                        activeDot={{
                          r: 6,
                          cursor: 'pointer',
                          onClick: (data) => {
                            const range = data.payload.range;
                            if (range && buckets[range] && buckets[range].docs.length > 0) {
                              const docs = buckets[range].docs.sort((a, b) => b.score - a.score);
                              setSelectedRangeData({ range, docs });
                              setTimeout(() => {
                                setShowDocumentsModal(true);
                              }, 0);
                            }
                          },
                        }}
                      />
                    </LineChart>
                  )}
                </ResponsiveContainer>
              );
            })()}
          </Container>
        )}

        {/* Lowest Scoring Documents Table */}
        {results?.weightedOverallScores && (
          <Container
            header={
              <Header
                actions={
                  <Select
                    selectedOption={lowestScoreCount}
                    onChange={({ detail }) => setLowestScoreCount(detail.selectedOption)}
                    options={[
                      { label: '5', value: 5 },
                      { label: '10', value: 10 },
                      { label: '20', value: 20 },
                      { label: '50', value: 50 },
                    ]}
                    placeholder="Select count"
                  />
                }
              >
                Documents with Lowest Weighted Overall Scores
              </Header>
            }
          >
            {(() => {
              const scores =
                typeof results.weightedOverallScores === 'string'
                  ? JSON.parse(results.weightedOverallScores)
                  : results.weightedOverallScores;

              const sortedDocs = Object.entries(scores)
                .map(([docId, score]) => ({ docId, score }))
                .sort((a, b) => a.score - b.score)
                .slice(0, lowestScoreCount.value);

              return (
                <Table
                  resizableColumns
                  wrapLines={preferences.wrapLines}
                  items={sortedDocs}
                  columnDefinitions={[
                    {
                      id: 'docId',
                      header: 'Document ID',
                      cell: (item) => (
                        <Button
                          variant="link"
                          onClick={() => {
                            const urlPath = item.docId.replace(/\//g, '%252F');
                            window.open(`#/documents/${urlPath}`, '_blank');
                          }}
                        >
                          {item.docId}
                        </Button>
                      ),
                    },
                    {
                      id: 'score',
                      header: 'Weighted Overall Score',
                      cell: (item) => item.score.toFixed(3),
                    },
                  ]}
                  variant="embedded"
                  contentDensity="compact"
                />
              );
            })()}
          </Container>
        )}

        {/* Breakdown Tables */}
        {(costBreakdown || accuracyBreakdown || splitClassificationMetrics) && (
          <ComprehensiveBreakdown
            costBreakdown={costBreakdown}
            accuracyBreakdown={accuracyBreakdown}
            splitClassificationMetrics={splitClassificationMetrics}
            averageWeightedScore={averageWeightedScore}
            preferences={preferences}
            setPreferences={setPreferences}
          />
        )}
      </SpaceBetween>

      <Modal
        visible={showReRunModal}
        onDismiss={() => {
          setShowReRunModal(false);
          setReRunContext('');
          setReRunNumberOfFiles('');
        }}
        header="Re-Run Test"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowReRunModal(false);
                  setReRunContext('');
                  setReRunNumberOfFiles('');
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" onClick={handleReRun} loading={reRunLoading}>
                Re-Run Test
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            <strong>Test Set:</strong> {results?.testSetName || 'N/A'}
            <br />
            <strong>Pattern:</strong> {testSetStatus === 'NOT_FOUND' ? 'Test set not found' : testSetFilePattern || 'Uploaded files'}
            <br />
            <strong>Files:</strong>{' '}
            {testSetStatus === 'NOT_FOUND' ? 'Test set deleted' : testSetFileCount !== null ? `${testSetFileCount} files` : 'Loading...'}
          </Box>
          <FormField label="Number of Files" description={`Optional: Limit the number of files to process (max: ${testSetFileCount || 0})`}>
            <Input
              value={reRunNumberOfFiles}
              onChange={({ detail }) => {
                const value = detail.value;

                // Allow empty value
                if (value === '') {
                  setReRunNumberOfFiles('');
                  return;
                }

                // Only allow digits (reject any non-digit characters)
                if (!/^\d+$/.test(value)) {
                  return; // Don't update state if invalid characters
                }

                // Check range
                const num = parseInt(value, 10);
                if (num > 0 && num <= (testSetFileCount || 0)) {
                  setReRunNumberOfFiles(value);
                }
                // If number is too large, don't update the state (prevents typing)
              }}
              placeholder={`Enter 1-${testSetFileCount || 0}`}
              type="text"
              inputMode="numeric"
            />
          </FormField>
          <FormField label="Context" description="Optional context information for this test run">
            <Textarea
              value={reRunContext}
              onChange={({ detail }) => setReRunContext(detail.value)}
              placeholder="Enter context information..."
              rows={3}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showDocumentsModal}
        onDismiss={() => setShowDocumentsModal(false)}
        header={`Documents in Range ${selectedRangeData?.range || ''}`}
        size="medium"
      >
        <Box>
          {selectedRangeData?.docs?.length > 0 ? (
            <Table
              resizableColumns
              wrapLines={preferences.wrapLines}
              items={selectedRangeData.docs}
              columnDefinitions={[
                {
                  id: 'docId',
                  header: 'Document ID',
                  cell: (item) => (
                    <Button
                      variant="link"
                      onClick={() => {
                        const urlPath = item.docId.replace(/\//g, '%252F');
                        window.open(`#/documents/${urlPath}`, '_blank');
                      }}
                    >
                      {item.docId}
                    </Button>
                  ),
                },
                {
                  id: 'score',
                  header: 'Score',
                  cell: (item) => item.score.toFixed(3),
                },
              ]}
              variant="embedded"
              contentDensity="compact"
            />
          ) : (
            <Box>No documents found in this range</Box>
          )}
        </Box>
      </Modal>

      <Modal
        visible={showConfigExportModal}
        onDismiss={() => setShowConfigExportModal(false)}
        header="Export Configuration"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowConfigExportModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleConfigExport}>
                Export
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="l">
          <FormField label="File format">
            <RadioGroup
              value={configExportFormat}
              onChange={({ detail }) => setConfigExportFormat(detail.value)}
              items={[
                { value: 'json', label: 'JSON' },
                { value: 'yaml', label: 'YAML' },
              ]}
            />
          </FormField>
          <FormField label="File name">
            <Input
              value={configExportFileName}
              onChange={({ detail }) => setConfigExportFileName(detail.value)}
              placeholder="configuration"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </Container>
  );
};

TestResults.propTypes = {
  testRunId: PropTypes.string.isRequired,
};

export default TestResults;
