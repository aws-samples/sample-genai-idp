// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Table,
  Box,
  Button,
  ButtonDropdown,
  ProgressBar,
  Select,
  CollectionPreferences,
  ExpandableSection,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import COMPARE_TEST_RUNS from '../../graphql/queries/compareTestRuns';
import TestStudioHeader from './TestStudioHeader';
import useLocalStorage from '../common/local-storage';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { formatConfigVersionLink, formatConfigVersionText, type ConfigVersion as UtilsConfigVersion } from './utils/configVersionUtils';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GqlResult = { data: Record<string, any> };

const client = generateClient();

interface TestComparisonProps {
  preSelectedTestRunIds?: string[];
}

interface ComparisonData {
  metrics?: Record<string, Record<string, unknown>>;
  configs?: Array<{ setting: string; values: string | Record<string, string> }>;
  error?: string;
}

const TestComparison = ({ preSelectedTestRunIds = [] }: TestComparisonProps): React.JSX.Element => {
  const { versions } = useConfigurationVersions();
  const [comparisonData, setComparisonData] = useState<ComparisonData | null>(null);
  const [comparing, setComparing] = useState(false);
  const [currentAttempt, setCurrentAttempt] = useState(1);
  const [lowestScoreCount, setLowestScoreCount] = useState<Record<string, unknown>>({ label: '5', value: 5 });
  const [preferences, setPreferences] = useLocalStorage('test-comparison-preferences', { wrapLines: false });

  // Color grading functions
  const getCostColorGrade = (cost: unknown, allCosts: unknown[]): React.CSSProperties => {
    if (!cost || cost === 'N/A') return {};
    const numCost = typeof cost === 'string' ? parseFloat(cost.replace('$', '')) : cost;
    const validCosts = allCosts.filter((c) => c && c !== 'N/A').map((c) => (typeof c === 'string' ? parseFloat(c.replace('$', '')) : c));
    if (validCosts.length === 0) return {};

    const sortedCosts = [...validCosts].sort((a, b) => Number(a) - Number(b));
    const index = sortedCosts.indexOf(numCost);
    const ratio = validCosts.length === 1 ? 0 : index / (validCosts.length - 1);

    // Green → Yellow → Red gradient
    let r, g, b;
    if (ratio <= 0.5) {
      // Green to Yellow (first half)
      const t = ratio * 2;
      r = Math.round(34 + t * (255 - 34)); // 34 to 255
      g = Math.round(139 + t * (255 - 139)); // 139 to 255
      b = Math.round(34 + t * (0 - 34)); // 34 to 0
    } else {
      // Yellow to Red (second half)
      const t = (ratio - 0.5) * 2;
      r = 255; // Stay at 255
      g = Math.round(255 + t * (0 - 255)); // 255 to 0
      b = 0; // Stay at 0
    }

    // Use black text for light backgrounds (yellow range)
    const textColor = ratio > 0.3 && ratio < 0.7 ? 'black' : 'white';

    return { backgroundColor: `rgb(${r}, ${g}, ${b})`, color: textColor };
  };

  const getScoreColorGrade = (score: unknown, allScores: unknown[]): React.CSSProperties => {
    if (!score || score === 'N/A') return {};
    const numScore = typeof score === 'string' ? parseFloat(score) : score;
    const validScores = allScores.filter((s) => s && s !== 'N/A').map((s) => (typeof s === 'string' ? parseFloat(s) : s));
    if (validScores.length === 0) return {};

    const sortedScores = [...validScores].sort((a, b) => Number(b) - Number(a)); // Highest to lowest
    const index = sortedScores.indexOf(numScore);
    const ratio = validScores.length === 1 ? 0 : index / (validScores.length - 1);

    // Green → Yellow → Red gradient
    let r, g, b;
    if (ratio <= 0.5) {
      // Green to Yellow (first half)
      const t = ratio * 2;
      r = Math.round(34 + t * (255 - 34)); // 34 to 255
      g = Math.round(139 + t * (255 - 139)); // 139 to 255
      b = Math.round(34 + t * (0 - 34)); // 34 to 0
    } else {
      // Yellow to Red (second half)
      const t = (ratio - 0.5) * 2;
      r = 255; // Stay at 255
      g = Math.round(255 + t * (0 - 255)); // 255 to 0
      b = 0; // Stay at 0
    }

    // Use black text for light backgrounds (yellow range)
    const textColor = ratio > 0.3 && ratio < 0.7 ? 'black' : 'white';

    return { backgroundColor: `rgb(${r}, ${g}, ${b})`, color: textColor };
  };

  const TestComparisonPreferences = ({
    preferences: prefs,
    setPreferences: setPrefs,
  }: {
    preferences: { wrapLines: boolean };
    setPreferences: (prefs: { wrapLines: boolean }) => void;
  }): React.JSX.Element => (
    <CollectionPreferences
      title="Preferences"
      confirmLabel="Confirm"
      cancelLabel="Cancel"
      preferences={prefs}
      onConfirm={({ detail }) => setPrefs(detail as { wrapLines: boolean })}
      wrapLinesPreference={{
        label: 'Wrap lines',
        description: 'Check to see all the text and wrap the lines',
      }}
    />
  );

  useEffect(() => {
    const fetchComparison = async () => {
      if (preSelectedTestRunIds.length >= 2) {
        setComparing(true);
        console.log('=== STARTING COMPARISON ===');
        console.log('Selected test run IDs:', preSelectedTestRunIds);

        try {
          console.log('Making GraphQL request...');
          let result;
          let attempt = 1;
          const maxRetries = 5;

          while (attempt <= maxRetries) {
            try {
              setCurrentAttempt(attempt);
              result = (await client.graphql({
                query: COMPARE_TEST_RUNS,
                variables: { testRunIds: preSelectedTestRunIds },
              })) as GqlResult;
              setCurrentAttempt(5); // Set to 100% before completing
              await new Promise((resolve) => setTimeout(resolve, 500)); // Brief pause to show 100%
              break;
            } catch (error) {
              const isTimeout =
                error.message?.toLowerCase().includes('timeout') ||
                error.code === 'TIMEOUT' ||
                error.message?.includes('Request failed with status code 504') ||
                error.name === 'TimeoutError' ||
                error.code === 'NetworkError' ||
                error.errors?.some(
                  (err) => err.errorType === 'Lambda:ExecutionTimeoutException' || err.message?.toLowerCase().includes('timeout'),
                );
              if (isTimeout && attempt < maxRetries) {
                console.log(`COMPARE_TEST_RUNS attempt ${attempt} failed, retrying...`, error.message);
                attempt++;

                // Animate progress during 5-second wait
                const waitTime = 5000;
                const intervalTime = 100;
                const steps = waitTime / intervalTime;
                const startProgress = (attempt - 1) * 20;
                const endProgress = attempt * 20;
                const progressStep = (endProgress - startProgress) / steps;

                let currentProgress = startProgress;
                const progressInterval = setInterval(() => {
                  currentProgress += progressStep;
                  setCurrentAttempt(Math.min(currentProgress / 20, 5));
                }, intervalTime);

                await new Promise((resolve) =>
                  setTimeout(() => {
                    clearInterval(progressInterval);
                    setCurrentAttempt(attempt);
                    resolve(undefined as unknown as void);
                  }, waitTime),
                );

                continue;
              }
              throw error;
            }
          }

          const compareData = result.data.compareTestRuns;

          // Parse metrics if it's a JSON string
          if (typeof compareData.metrics === 'string') {
            compareData.metrics = JSON.parse(compareData.metrics);
          }

          setComparisonData(compareData);
        } catch (error) {
          console.error('Error comparing test runs:', error);

          const errorMessage =
            error.errors?.length > 0 ? error.errors.map((e) => e.message).join('; ') : error.message || 'Error comparing test runs';
          setComparisonData({ error: errorMessage });
        } finally {
          setComparing(false);
        }
      }
    };

    fetchComparison();
  }, [preSelectedTestRunIds]);

  // Helper function to create clickable test run ID headers
  const createTestRunHeader = (testRunId: string, truncate = false): React.JSX.Element => {
    const displayId = testRunId;
    const _testSetName = truncate ? completeTestRuns[testRunId]?.testSetName : null;

    if (truncate) {
      return (
        <span
          title={testRunId}
          style={{ cursor: 'pointer', color: '#0073bb' }}
          role="button"
          tabIndex={0}
          onClick={() => {
            window.location.hash = `#/test-studio?tab=results&testRunId=${testRunId}`;
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              window.location.hash = `#/test-studio?tab=results&testRunId=${testRunId}`;
            }
          }}
        >
          {displayId}
        </span>
      );
    }

    return (
      <Button
        variant="link"
        onClick={() => {
          window.location.hash = `#/test-studio?tab=results&testRunId=${testRunId}`;
        }}
        {...({ title: testRunId } as Record<string, unknown>)}
      >
        {displayId}
      </Button>
    );
  };

  const downloadToCsv = () => {
    if (!comparisonData || !comparisonData.metrics) return;

    const completeTestRuns = Object.fromEntries(
      Object.entries(comparisonData.metrics).filter(
        ([, testRun]) => testRun.status === 'COMPLETE' || testRun.status === 'PARTIAL_COMPLETE',
      ),
    );

    // Create headers
    const headers = ['Metric', ...Object.keys(completeTestRuns)];

    // Create rows for performance metrics
    const performanceRows = [
      ['Test Set', ...Object.values(completeTestRuns).map((run) => run.testSetName || 'N/A')],
      ['Context', ...Object.values(completeTestRuns).map((run) => run.context || 'N/A')],
      [
        'Config Version',
        ...Object.values(completeTestRuns).map((run) =>
          formatConfigVersionText(run.configVersion as string | undefined, versions as unknown as UtilsConfigVersion[]),
        ),
      ],
      ['Files Processed', ...Object.values(completeTestRuns).map((run) => run.filesCount || 'N/A')],
      ['Files Completed', ...Object.values(completeTestRuns).map((run) => run.completedFiles || 'N/A')],
      ['Files Failed', ...Object.values(completeTestRuns).map((run) => run.failedFiles || 'N/A')],
      [
        'Total Cost',
        ...Object.values(completeTestRuns).map((run) =>
          run.totalCost !== null && run.totalCost !== undefined ? `$${Number(run.totalCost).toFixed(4)}` : 'N/A',
        ),
      ],
      [
        'Average Accuracy',
        ...Object.values(completeTestRuns).map((run) =>
          run.overallAccuracy !== null && run.overallAccuracy !== undefined ? Number(run.overallAccuracy).toFixed(3) : 'N/A',
        ),
      ],
      [
        'Average Confidence',
        ...Object.values(completeTestRuns).map((run) =>
          run.averageConfidence !== null && run.averageConfidence !== undefined
            ? `${(Number(run.averageConfidence) * 100).toFixed(1)}%`
            : 'N/A',
        ),
      ],
      [
        'Average Weighted Overall Score',
        ...Object.values(completeTestRuns).map((run) => {
          if (run.weightedOverallScores) {
            const scores =
              typeof run.weightedOverallScores === 'string' ? JSON.parse(run.weightedOverallScores) : run.weightedOverallScores;
            const values = Object.values(scores) as number[];
            if (values.length > 0) {
              const avg = values.reduce((sum: number, score: unknown) => sum + Number(score), 0) / values.length;
              return avg.toFixed(3);
            }
          }
          return 'N/A';
        }),
      ],
      [
        'Duration',
        ...Object.values(completeTestRuns).map((run) => {
          if (run.createdAt && run.completedAt) {
            const duration = new Date(run.completedAt as string).getTime() - new Date(run.createdAt as string).getTime();
            const minutes = Math.floor(duration / 60000);
            const seconds = Math.floor((duration % 60000) / 1000);
            return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
          }
          return 'N/A';
        }),
      ],
    ];

    // Add cost breakdown rows
    const costRows: string[][] = [];
    const allCostItems = new Set();

    Object.values(completeTestRuns).forEach((testRun) => {
      if (testRun.costBreakdown) {
        Object.entries(testRun.costBreakdown).forEach(([context, services]) => {
          Object.keys(services).forEach((serviceUnit) => {
            // Parse service/api_unit format: find last underscore to separate unit
            const lastUnderscoreIndex = serviceUnit.lastIndexOf('_');
            const serviceApi = serviceUnit.substring(0, lastUnderscoreIndex);
            const unit = serviceUnit.substring(lastUnderscoreIndex + 1);
            const [service, api] = serviceApi.split('/');
            allCostItems.add(`${context}|${service}/${api}|${unit}`);
          });
        });
      }
    });

    // Add cost breakdown header
    costRows.push(['Context', 'Service/Api', 'Unit', ...Object.keys(completeTestRuns)]);

    const sortedCostItems = Array.from(allCostItems).sort();
    const contexts = [...new Set(sortedCostItems.map((item) => String(item).split('|')[0]))];

    contexts.forEach((context) => {
      const contextItems = sortedCostItems.filter((item) => String(item).startsWith(`${context}|`));

      // Add context items
      contextItems.forEach((itemKey) => {
        const [ctx, serviceApi, unit] = String(itemKey).split('|');
        const row = [ctx, serviceApi, unit];

        Object.entries(completeTestRuns).forEach(([_testRunId, testRun]) => {
          const services = testRun.costBreakdown?.[ctx] || {};
          const serviceKey = Object.keys(services).find((key) => {
            const lastUnderscoreIndex = key.lastIndexOf('_');
            const keyServiceApi = key.substring(0, lastUnderscoreIndex);
            const keyUnit = key.substring(lastUnderscoreIndex + 1);
            return keyServiceApi === serviceApi && keyUnit === unit;
          });

          const details = services[serviceKey] || {};
          const estimatedCost = details.estimated_cost || 0;
          row.push(estimatedCost > 0 ? `$${estimatedCost.toFixed(4)}` : 'N/A');
        });

        costRows.push(row);
      });

      // Add subtotal row
      const subtotalRow = ['', `${context} Subtotal`, ''];
      Object.keys(completeTestRuns).forEach((testRunId) => {
        const contextTotal = contextItems.reduce((sum, itemKey) => {
          const [ctx, serviceApi, unit] = String(itemKey).split('|');
          const services = completeTestRuns[testRunId].costBreakdown?.[ctx] || {};
          const serviceKey = Object.keys(services).find((key) => {
            const lastUnderscoreIndex = key.lastIndexOf('_');
            const keyServiceApi = key.substring(0, lastUnderscoreIndex);
            const keyUnit = key.substring(lastUnderscoreIndex + 1);
            return keyServiceApi === serviceApi && keyUnit === unit;
          });
          const details = services[serviceKey] || {};
          const estimatedCost = details.estimated_cost || 0;
          return sum + estimatedCost;
        }, 0);
        subtotalRow.push(`$${Number(contextTotal).toFixed(4)}`);
      });
      costRows.push(subtotalRow);
    });

    // Add total row
    const totalRow = ['', 'Total', ''];
    Object.keys(completeTestRuns).forEach((testRunId) => {
      const grandTotal = sortedCostItems.reduce((sum, itemKey) => {
        const [context, serviceApi, unit] = String(itemKey).split('|');
        const services = completeTestRuns[testRunId].costBreakdown?.[context] || {};
        const serviceKey = Object.keys(services).find((key) => {
          const lastUnderscoreIndex = key.lastIndexOf('_');
          const keyServiceApi = key.substring(0, lastUnderscoreIndex);
          const keyUnit = key.substring(lastUnderscoreIndex + 1);
          return keyServiceApi === serviceApi && keyUnit === unit;
        });
        const details = services[serviceKey] || {};
        const estimatedCost = details.estimated_cost || 0;
        return sum + estimatedCost;
      }, 0);
      totalRow.push(`$${Number(grandTotal).toFixed(4)}`);
    });
    costRows.push(totalRow);

    // Add usage breakdown rows
    const usageRows = [];
    usageRows.push(['Context', 'Service/Api', 'Unit', ...Object.keys(completeTestRuns)]);

    Array.from(allCostItems)
      .sort()
      .forEach((itemKey) => {
        const [context, serviceApi, unit] = String(itemKey).split('|');
        const row = [context, serviceApi, unit];

        Object.entries(completeTestRuns).forEach(([_testRunId, testRun]) => {
          const services = testRun.costBreakdown?.[context] || {};
          const serviceKey = Object.keys(services).find((key) => {
            const lastUnderscoreIndex = key.lastIndexOf('_');
            const keyServiceApi = key.substring(0, lastUnderscoreIndex);
            const keyUnit = key.substring(lastUnderscoreIndex + 1);
            return keyServiceApi === serviceApi && keyUnit === unit;
          });

          const details = services[serviceKey] || {};
          const value = details.value || 0;
          row.push(value > 0 ? value.toLocaleString() : 'N/A');
        });

        usageRows.push(row);
      });

    // Add accuracy breakdown rows
    const accuracyRows = [];
    const allAccuracyMetrics = new Set();
    Object.values(completeTestRuns).forEach((testRun) => {
      if (testRun.accuracyBreakdown) {
        Object.keys(testRun.accuracyBreakdown).forEach((metric) => {
          allAccuracyMetrics.add(metric);
        });
      }
    });

    // Add accuracy breakdown header
    accuracyRows.push(['Accuracy Metric', ...Object.keys(completeTestRuns)]);

    // Add accuracy breakdown metrics
    Array.from(allAccuracyMetrics).forEach((metricKey) => {
      const row = [
        String(metricKey)
          .replace(/_/g, ' ')
          .replace(/\b\w/g, (l) => l.toUpperCase()),
      ];
      Object.entries(completeTestRuns).forEach(([_testRunId, testRun]) => {
        const accuracyBreakdown = testRun.accuracyBreakdown || {};
        const value = accuracyBreakdown[metricKey as string];
        const displayValue = value !== null && value !== undefined ? Number(value).toFixed(3) : '0.000';
        row.push(displayValue);
      });
      accuracyRows.push(row);
    });

    // Add weighted overall score to accuracy breakdown
    const weightedRow = ['Weighted Overall Score'];
    Object.entries(completeTestRuns).forEach(([_testRunId, testRun]) => {
      if (testRun.weightedOverallScores) {
        const scores =
          typeof testRun.weightedOverallScores === 'string' ? JSON.parse(testRun.weightedOverallScores) : testRun.weightedOverallScores;
        const values = Object.values(scores) as number[];
        if (values.length > 0) {
          const avg = values.reduce((sum: number, score: unknown) => sum + Number(score), 0) / values.length;
          weightedRow.push(avg.toFixed(3));
        } else {
          weightedRow.push('N/A');
        }
      } else {
        weightedRow.push('N/A');
      }
    });
    accuracyRows.push(weightedRow);

    // Add config comparison rows
    const configRows = [];
    if (comparisonData.configs && comparisonData.configs.length > 0) {
      comparisonData.configs.forEach((config) => {
        const values = typeof config.values === 'string' ? JSON.parse(config.values) : config.values;
        const row = [config.setting, ...Object.keys(completeTestRuns).map((testRunId) => values[testRunId] || 'N/A')];
        configRows.push(row);
      });
    }

    // Combine all data
    const csvData = [
      headers,
      ['=== PERFORMANCE METRICS ==='],
      ...performanceRows,
      [''],
      ['=== CONFIGURATION COMPARISON ==='],
      ...configRows,
      [''],
      ['=== AVERAGE ACCURACY BREAKDOWN ==='],
      ...accuracyRows,
      [''],
      ['=== COST BREAKDOWN ==='],
      ...costRows,
      [''],
      ['=== USAGE BREAKDOWN ==='],
      ...usageRows,
    ];

    const csvContent = csvData.map((row) => row.map((field) => `"${String(field).replace(/"/g, '""')}"`).join(',')).join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    const now = new Date();
    const timestamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(
      2,
      '0',
    )}-${String(now.getHours()).padStart(2, '0')}-${String(now.getMinutes()).padStart(2, '0')}-${String(now.getSeconds()).padStart(
      2,
      '0',
    )}`;
    link.setAttribute('href', url);
    link.setAttribute('download', `test-comparison-${timestamp}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadToJson = () => {
    if (!comparisonData) return;

    const completeTestRuns = Object.fromEntries(
      Object.entries(comparisonData.metrics).filter(
        ([, testRun]) => testRun.status === 'COMPLETE' || testRun.status === 'PARTIAL_COMPLETE',
      ),
    );

    // Create JSON structure matching the UI sections
    const filteredData = {
      testRuns: Object.keys(completeTestRuns),
      performanceMetrics: Object.fromEntries(
        Object.entries(completeTestRuns).map(([testRunId, testRun]) => [
          testRunId,
          {
            testSetName: testRun.testSetName,
            context: testRun.context,
            configVersion: formatConfigVersionText(testRun.configVersion as string | undefined, versions),
            filesCount: testRun.filesCount,
            completedFiles: testRun.completedFiles,
            failedFiles: testRun.failedFiles,
            totalCost: testRun.totalCost,
            averageAccuracy: testRun.overallAccuracy,
            averageConfidence: testRun.averageConfidence,
            averageWeightedOverallScore: (() => {
              if (testRun.weightedOverallScores) {
                const scores =
                  typeof testRun.weightedOverallScores === 'string'
                    ? JSON.parse(testRun.weightedOverallScores)
                    : testRun.weightedOverallScores;
                const values = Object.values(scores) as number[];
                return values.length > 0 ? values.reduce((sum: number, score: unknown) => sum + Number(score), 0) / values.length : null;
              }
              return null;
            })(),
            duration:
              testRun.createdAt && testRun.completedAt
                ? (() => {
                    const duration = new Date(testRun.completedAt as string).getTime() - new Date(testRun.createdAt as string).getTime();
                    const minutes = Math.floor(duration / 60000);
                    const seconds = Math.floor((duration % 60000) / 1000);
                    return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
                  })()
                : 'N/A',
          },
        ]),
      ),
      configurationDifferences: comparisonData.configs || [],
      accuracyBreakdown: Object.fromEntries(
        Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
          const breakdown = { ...((testRun.accuracyBreakdown || {}) as Record<string, unknown>) };
          // Add weighted overall score to accuracy breakdown
          if (testRun.weightedOverallScores) {
            const scores =
              typeof testRun.weightedOverallScores === 'string' ? JSON.parse(testRun.weightedOverallScores) : testRun.weightedOverallScores;
            const values = Object.values(scores) as number[];
            if (values.length > 0) {
              breakdown.weightedOverallScore = values.reduce((sum: number, score: unknown) => sum + Number(score), 0) / values.length;
            }
          }
          return [testRunId, breakdown];
        }),
      ),
      costBreakdown: Object.fromEntries(
        Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.costBreakdown || {}]),
      ),
    };

    const jsonData = JSON.stringify(filteredData, null, 2);
    const blob = new Blob([jsonData], { type: 'application/json' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    const now = new Date();
    const timestamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(
      2,
      '0',
    )}-${String(now.getHours()).padStart(2, '0')}-${String(now.getMinutes()).padStart(2, '0')}-${String(now.getSeconds()).padStart(
      2,
      '0',
    )}`;
    link.setAttribute('href', url);
    link.setAttribute('download', `test-comparison-${timestamp}.json`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (comparing) {
    return <ProgressBar status="in-progress" label="Loading comparison..." value={currentAttempt * 20} />;
  }

  if (!comparisonData) {
    return (
      <Container header={<TestStudioHeader title="Compare Test Runs" />}>
        <Box>No comparison data available</Box>
      </Container>
    );
  }

  if (comparisonData.error) {
    return (
      <Container header={<TestStudioHeader title="Compare Test Runs" />}>
        <Box>Error: {comparisonData.error}</Box>
      </Container>
    );
  }

  // Debug logging
  console.log('Comparison data structure:', comparisonData);
  console.log('Metrics structure:', comparisonData.metrics);

  // Filter out incomplete test runs (include COMPLETE and PARTIAL_COMPLETE)
  const completeTestRuns = comparisonData.metrics
    ? Object.fromEntries(
        Object.entries(comparisonData.metrics).filter(
          ([, testRun]) => testRun.status === 'COMPLETE' || testRun.status === 'PARTIAL_COMPLETE',
        ),
      )
    : {};

  const hasIncompleteRuns = comparisonData.metrics
    ? Object.values(comparisonData.metrics).some((testRun) => testRun.status !== 'COMPLETE' && testRun.status !== 'PARTIAL_COMPLETE')
    : false;

  const downloadButton = (
    <ButtonDropdown
      variant="normal"
      {...({ iconName: 'download' } as Record<string, unknown>)}
      items={[
        { id: 'csv', text: 'CSV' },
        { id: 'json', text: 'JSON' },
      ]}
      onItemClick={({ detail }) => {
        if (detail.id === 'csv') {
          downloadToCsv();
        } else if (detail.id === 'json') {
          downloadToJson();
        }
      }}
    ></ButtonDropdown>
  );

  return (
    <Container
      header={
        <TestStudioHeader
          title={`Compare Test Runs (${Object.keys(completeTestRuns).length})`}
          showPrintButton={true}
          additionalActions={[downloadButton]}
        />
      }
    >
      <SpaceBetween direction="vertical" size="l">
        {/* Performance Metrics */}
        <Box>
          <Header variant="h3">Performance Metrics</Header>
          {hasIncompleteRuns && (
            <Box variant="awsui-key-label" color="text-status-warning" padding="s">
              Some test runs are not complete. Only showing results for completed test runs.
            </Box>
          )}
          {Object.keys(completeTestRuns).length > 0 ? (
            <Table
              resizableColumns
              contentDensity="compact"
              wrapLines={preferences.wrapLines}
              preferences={<TestComparisonPreferences preferences={preferences} setPreferences={setPreferences} />}
              items={[
                {
                  metric: 'Test Set',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.testSetName || 'N/A']),
                  ),
                },
                {
                  metric: 'Context',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.context || 'N/A']),
                  ),
                },
                {
                  metric: 'Config Version',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [
                      testRunId,
                      formatConfigVersionLink(testRun.configVersion as string | undefined, versions as unknown as UtilsConfigVersion[]),
                    ]),
                  ),
                },
                {
                  metric: 'Files Processed',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.filesCount || 'N/A']),
                  ),
                },
                {
                  metric: 'Files Completed',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.completedFiles || 'N/A']),
                  ),
                },
                {
                  metric: 'Files Failed',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [testRunId, testRun.failedFiles || 'N/A']),
                  ),
                },
                {
                  metric: 'Total Cost',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [
                      testRunId,
                      testRun.totalCost !== null && testRun.totalCost !== undefined ? `$${Number(testRun.totalCost).toFixed(4)}` : 'N/A',
                    ]),
                  ),
                },
                {
                  metric: 'Average Accuracy',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [
                      testRunId,
                      testRun.overallAccuracy !== null && testRun.overallAccuracy !== undefined
                        ? Number(testRun.overallAccuracy).toFixed(3)
                        : 'N/A',
                    ]),
                  ),
                },
                {
                  metric: 'Average Weighted Overall Score',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                      if (testRun.weightedOverallScores) {
                        const scores =
                          typeof testRun.weightedOverallScores === 'string'
                            ? JSON.parse(testRun.weightedOverallScores)
                            : testRun.weightedOverallScores;
                        const values = Object.values(scores) as number[];
                        if (values.length > 0) {
                          const avg = values.reduce((sum: number, score: unknown) => sum + Number(score), 0) / values.length;
                          return [testRunId, avg.toFixed(3)];
                        }
                      }
                      return [testRunId, 'N/A'];
                    }),
                  ),
                },
                {
                  metric: 'Average Confidence',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => [
                      testRunId,
                      testRun.averageConfidence !== null && testRun.averageConfidence !== undefined
                        ? `${(Number(testRun.averageConfidence) * 100).toFixed(1)}%`
                        : 'N/A',
                    ]),
                  ),
                },
                {
                  metric: 'Duration',
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                      if (testRun.createdAt && testRun.completedAt) {
                        const duration =
                          new Date(testRun.completedAt as string).getTime() - new Date(testRun.createdAt as string).getTime();
                        const minutes = Math.floor(duration / 60000);
                        const seconds = Math.floor((duration % 60000) / 1000);
                        return [testRunId, minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`];
                      }
                      return [testRunId, 'N/A'];
                    }),
                  ),
                },
              ]}
              columnDefinitions={[
                { id: 'metric', header: 'Metric', cell: (item) => item.metric, width: 250 },
                ...Object.keys(completeTestRuns).map((testRunId) => ({
                  id: testRunId,
                  header: createTestRunHeader(testRunId, true),
                  cell: (item) => {
                    const value = item[testRunId];
                    let style = {};

                    if (item.metric === 'Total Cost') {
                      const allCosts = Object.keys(completeTestRuns).map((id) => item[id]);
                      style = getCostColorGrade(value, allCosts);
                    } else if (item.metric === 'Average Weighted Overall Score') {
                      const allScores = Object.keys(completeTestRuns).map((id) => item[id]);
                      style = getScoreColorGrade(value, allScores);
                    }

                    return <span style={{ ...style, WebkitPrintColorAdjust: 'exact', colorAdjust: 'exact' }}>{value}</span>;
                  },
                })),
              ]}
              variant="embedded"
            />
          ) : (
            <Box>No completed test runs available</Box>
          )}
        </Box>

        {/* Lowest Scoring Documents Across Tests */}
        <Container
          header={
            <Header
              actions={
                <Select
                  selectedOption={lowestScoreCount}
                  onChange={({ detail }) => setLowestScoreCount(detail.selectedOption as Record<string, unknown>)}
                  options={[
                    { label: '5', value: '5' },
                    { label: '10', value: '10' },
                    { label: '20', value: '20' },
                    { label: '50', value: '50' },
                  ]}
                  placeholder="Select count"
                />
              }
            >
              Documents with Lowest Weighted Overall Scores Across Tests
            </Header>
          }
        >
          {(() => {
            const testRunIds = Object.keys(completeTestRuns);

            // Get lowest scoring documents from each test run
            const getLowestDocs = (testRun: Record<string, unknown>) => {
              if (!testRun?.weightedOverallScores) return [];

              const scores =
                typeof testRun.weightedOverallScores === 'string'
                  ? JSON.parse(testRun.weightedOverallScores)
                  : testRun.weightedOverallScores;

              return Object.entries(scores)
                .map(([docId, score]) => ({ docId, score }))
                .sort((a, b) => Number(a.score) - Number(b.score))
                .slice(0, Number(lowestScoreCount.value));
            };

            const allTestDocs = testRunIds.map((testRunId) => getLowestDocs(completeTestRuns[testRunId]));
            const maxRows = Math.max(...allTestDocs.map((docs) => docs.length));

            // Create table items with T1 and T2 columns
            const tableItems = Array.from({ length: maxRows }, (_, index) => {
              const item = { index };
              testRunIds.forEach((testRunId, testIndex) => {
                item[`t${testIndex + 1}Doc`] = allTestDocs[testIndex][index];
              });
              return item;
            });

            // Helper function to extract filename from document ID
            const getDocumentFilename = (docId: string): string => {
              return docId.split('/').pop().split('\\').pop(); // Handle both / and \ separators
            };

            // Create color mapping for matching document filenames
            const getDocumentColor = (docId: string): string => {
              const filename = getDocumentFilename(docId);

              // Count how many test runs have this filename
              let matchCount = 0;
              tableItems.forEach((item) => {
                testRunIds.forEach((_, testIndex) => {
                  if (item[`t${testIndex + 1}Doc`] && getDocumentFilename(item[`t${testIndex + 1}Doc`].docId) === filename) {
                    matchCount++;
                  }
                });
              });

              // Only color if document appears in multiple test runs
              if (matchCount <= 1) return 'transparent';

              const colors = ['#e3f2fd', '#f3e5f5', '#e8f5e8', '#fff3e0', '#fce4ec', '#e0f2f1', '#f1f8e9', '#fff8e1', '#e8eaf6', '#fafafa'];

              // Get all matching filenames
              const matchingFilenames = new Set();
              tableItems.forEach((item) => {
                testRunIds.forEach((_, testIndex) => {
                  if (item[`t${testIndex + 1}Doc`]) {
                    const fname = getDocumentFilename(item[`t${testIndex + 1}Doc`].docId);
                    // Count occurrences of this filename
                    let count = 0;
                    tableItems.forEach((innerItem) => {
                      testRunIds.forEach((__, innerTestIndex) => {
                        if (
                          innerItem[`t${innerTestIndex + 1}Doc`] &&
                          getDocumentFilename(innerItem[`t${innerTestIndex + 1}Doc`].docId) === fname
                        ) {
                          count++;
                        }
                      });
                    });
                    if (count > 1) matchingFilenames.add(fname);
                  }
                });
              });

              const filenameArray = Array.from(matchingFilenames).sort();
              const colorIndex = filenameArray.indexOf(filename) % colors.length;
              return colors[colorIndex];
            };

            return tableItems.length > 0 ? (
              <Table
                resizableColumns
                wrapLines={preferences.wrapLines}
                preferences={<div />}
                items={tableItems}
                columnDefinitions={testRunIds.map((testRunId, index) => ({
                  id: `t${index + 1}`,
                  header: createTestRunHeader(testRunId, true),
                  width: 400,
                  cell: (item) =>
                    item[`t${index + 1}Doc`] ? (
                      <div
                        style={{
                          textAlign: 'left',
                          backgroundColor: getDocumentColor(item[`t${index + 1}Doc`].docId),
                          padding: '8px',
                          borderRadius: '4px',
                          WebkitPrintColorAdjust: 'exact',
                          colorAdjust: 'exact',
                        }}
                      >
                        <Button
                          variant="link"
                          onClick={() => {
                            const urlPath = item[`t${index + 1}Doc`].docId.replace(/\//g, '%252F');
                            window.open(`#/documents/${urlPath}`, '_blank');
                          }}
                        >
                          {item[`t${index + 1}Doc`].docId}
                        </Button>
                        <div style={{ fontSize: '12px', color: '#666' }}>Score: {item[`t${index + 1}Doc`].score.toFixed(3)}</div>
                      </div>
                    ) : (
                      ''
                    ),
                }))}
                variant="embedded"
                contentDensity="compact"
              />
            ) : (
              <Box>No documents with weighted overall scores found</Box>
            );
          })()}
        </Container>

        {/* Breakdown Tables */}
        <SpaceBetween direction="vertical" size="l">
          {/* Configuration Comparison */}
          <Container header={<Header variant="h3">Configuration Comparison</Header>}>
            {(() => {
              if (!comparisonData.configs || comparisonData.configs.length === 0) {
                return <Box>No configuration differences found - all test runs use identical configurations</Box>;
              }

              return (
                <Table
                  resizableColumns
                  wrapLines={preferences.wrapLines}
                  preferences={<div />}
                  items={comparisonData.configs.map((config) => {
                    const values = typeof config.values === 'string' ? JSON.parse(config.values) : config.values;
                    return {
                      setting: config.setting,
                      ...values, // Spread the values object to create columns for each test run
                    };
                  })}
                  columnDefinitions={[
                    { id: 'setting', header: 'Config', cell: (item) => item.setting, width: 200 },
                    ...Object.keys(completeTestRuns).map((testRunId) => ({
                      id: testRunId,
                      header: createTestRunHeader(testRunId, true),
                      cell: (item) => item[testRunId] || 'N/A',
                    })),
                  ]}
                  variant="embedded"
                />
              );
            })()}
          </Container>

          {/* Average Accuracy and Split Metrics Comparison */}
          <Container header={<Header variant="h3">Average Accuracy and Split Metrics Comparison</Header>}>
            {(() => {
              const hasAccuracyData = Object.values(completeTestRuns).some((testRun) => testRun.accuracyBreakdown);
              const hasSplitData = Object.values(completeTestRuns).some((testRun) => testRun.splitClassificationMetrics);

              if (!hasAccuracyData && !hasSplitData) {
                return <Box>No accuracy or split metrics data available</Box>;
              }

              const mainItems = [];

              // Add weighted overall score
              mainItems.push({
                metric: (
                  <>
                    <span style={{ color: '#687078' }}>Extraction:</span> Weighted Overall Score
                  </>
                ),
                ...Object.fromEntries(
                  Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                    if (testRun.weightedOverallScores) {
                      const scores =
                        typeof testRun.weightedOverallScores === 'string'
                          ? JSON.parse(testRun.weightedOverallScores)
                          : testRun.weightedOverallScores;
                      const values = Object.values(scores) as number[];
                      if (values.length > 0) {
                        const avg = (values as number[]).reduce((sum, score) => sum + score, 0) / values.length;
                        return [testRunId, avg.toFixed(3)];
                      }
                    }
                    return [testRunId, 'N/A'];
                  }),
                ),
              });

              // Add Page Level Accuracy and Split Accuracy With Order
              if (hasSplitData) {
                mainItems.push({
                  metric: (
                    <>
                      <span style={{ color: '#687078' }}>Classification:</span> Page Level Accuracy
                    </>
                  ),
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                      const splitMetrics = testRun.splitClassificationMetrics || {};
                      const value = (splitMetrics as Record<string, unknown>).page_level_accuracy;
                      const displayValue = typeof value === 'number' ? value.toFixed(3) : value?.toString() || '0';
                      return [testRunId, displayValue];
                    }),
                  ),
                });

                mainItems.push({
                  metric: (
                    <>
                      <span style={{ color: '#687078' }}>Classification:</span> Split Accuracy With Order
                    </>
                  ),
                  ...Object.fromEntries(
                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                      const splitMetrics = testRun.splitClassificationMetrics || {};
                      const value = (splitMetrics as Record<string, unknown>).split_accuracy_with_order;
                      const displayValue = typeof value === 'number' ? value.toFixed(3) : value?.toString() || '0';
                      return [testRunId, displayValue];
                    }),
                  ),
                });
              }

              return (
                <>
                  <Table
                    resizableColumns
                    wrapLines={preferences.wrapLines}
                    preferences={<div />}
                    items={mainItems}
                    columnDefinitions={[
                      { id: 'metric', header: 'Metric', cell: (item) => item.metric, width: 400 },
                      ...Object.keys(completeTestRuns).map((testRunId) => ({
                        id: testRunId,
                        header: createTestRunHeader(testRunId, true),
                        cell: (item) => item[testRunId],
                        width: 200,
                      })),
                    ]}
                    variant="embedded"
                  />

                  {/* Additional Metrics in collapsible section */}
                  <ExpandableSection headerText="Additional Metrics">
                    <Container>
                      <Table
                        resizableColumns
                        wrapLines={preferences.wrapLines}
                        preferences={<div />}
                        items={[
                          // All accuracy breakdown metrics
                          ...(hasAccuracyData
                            ? (() => {
                                const allAccuracyMetrics = new Set();
                                Object.values(completeTestRuns).forEach((testRun) => {
                                  if (testRun.accuracyBreakdown) {
                                    Object.keys(testRun.accuracyBreakdown).forEach((metric) => {
                                      allAccuracyMetrics.add(metric);
                                    });
                                  }
                                });

                                return Array.from(allAccuracyMetrics).map((metricKey) => ({
                                  metric: (
                                    <>
                                      <span style={{ color: '#687078' }}>Extraction:</span>{' '}
                                      {String(metricKey)
                                        .replace(/_/g, ' ')
                                        .replace(/\b\w/g, (l) => l.toUpperCase())}
                                    </>
                                  ),
                                  ...Object.fromEntries(
                                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                                      const accuracyBreakdown = testRun.accuracyBreakdown || {};
                                      const value = accuracyBreakdown[metricKey as string];
                                      const displayValue = value !== null && value !== undefined ? value.toFixed(3) : '0.000';
                                      return [testRunId, displayValue];
                                    }),
                                  ),
                                }));
                              })()
                            : []),
                          // Remaining split classification metrics (excluding main ones)
                          ...(hasSplitData
                            ? (() => {
                                const allSplitMetrics = new Set();
                                Object.values(completeTestRuns).forEach((testRun) => {
                                  if (testRun.splitClassificationMetrics) {
                                    Object.keys(testRun.splitClassificationMetrics)
                                      .filter((key) => key !== 'page_level_accuracy' && key !== 'split_accuracy_with_order')
                                      .forEach((metric) => {
                                        allSplitMetrics.add(metric);
                                      });
                                  }
                                });

                                return Array.from(allSplitMetrics).map((metricKey) => ({
                                  metric: (
                                    <>
                                      <span style={{ color: '#687078' }}>Classification:</span>{' '}
                                      {String(metricKey)
                                        .replace(/_/g, ' ')
                                        .replace(/\b\w/g, (l) => l.toUpperCase())}
                                    </>
                                  ),
                                  ...Object.fromEntries(
                                    Object.entries(completeTestRuns).map(([testRunId, testRun]) => {
                                      const splitMetrics = testRun.splitClassificationMetrics || {};
                                      const value = (splitMetrics as Record<string, unknown>)[metricKey as string];
                                      const displayValue =
                                        typeof value === 'number' && String(metricKey).includes('accuracy')
                                          ? value.toFixed(3)
                                          : value !== null && value !== undefined
                                          ? value.toString()
                                          : '0';
                                      return [testRunId, displayValue];
                                    }),
                                  ),
                                }));
                              })()
                            : []),
                        ]}
                        columnDefinitions={[
                          { id: 'metric', header: 'Metric', cell: (item) => item.metric, width: 400 },
                          ...Object.keys(completeTestRuns).map((testRunId) => ({
                            id: testRunId,
                            header: createTestRunHeader(testRunId, true),
                            cell: (item) => item[testRunId],
                            width: 200,
                          })),
                        ]}
                        variant="embedded"
                      />
                    </Container>
                  </ExpandableSection>
                </>
              );
            })()}
          </Container>

          {/* Cost Comparison */}
          <Container header={<Header variant="h3">Cost Breakdown Comparison</Header>}>
            {(() => {
              const allCostItems = new Set();

              // Collect all unique cost items
              Object.values(completeTestRuns).forEach((testRun) => {
                if (testRun.costBreakdown) {
                  Object.entries(testRun.costBreakdown).forEach(([context, services]) => {
                    Object.keys(services).forEach((serviceUnit) => {
                      const lastUnderscoreIndex = serviceUnit.lastIndexOf('_');
                      const serviceApi = serviceUnit.substring(0, lastUnderscoreIndex);
                      const unit = serviceUnit.substring(lastUnderscoreIndex + 1);
                      const [service, api] = serviceApi.split('/');
                      allCostItems.add(`${context}|${service}/${api}|${unit}`);
                    });
                  });
                }
              });

              const tableItems = Array.from(allCostItems).map((itemKey) => {
                const [context, serviceApi, unit] = String(itemKey).split('|');
                const row = {
                  context,
                  serviceApi,
                  unit,
                };

                // Add cost for each test run
                Object.entries(completeTestRuns).forEach(([testRunId, testRun]) => {
                  const services = testRun.costBreakdown?.[context] || {};
                  const serviceKey = Object.keys(services).find((key) => {
                    const lastUnderscoreIndex = key.lastIndexOf('_');
                    const keyServiceApi = key.substring(0, lastUnderscoreIndex);
                    const keyUnit = key.substring(lastUnderscoreIndex + 1);
                    return keyServiceApi === serviceApi && keyUnit === unit;
                  });

                  const details = services[serviceKey] || {};
                  const estimatedCost = details.estimated_cost || 0;
                  row[testRunId] = estimatedCost > 0 ? `$${estimatedCost.toFixed(4)}` : 'N/A';
                });

                return row;
              });

              // Sort by context, then by service/api
              tableItems.sort((a, b) => {
                if (a.context !== b.context) return a.context.localeCompare(b.context);
                return a.serviceApi.localeCompare(b.serviceApi);
              });

              // Add context subtotals
              const finalItems = [];
              tableItems.forEach((item, index) => {
                finalItems.push(item);

                // Check if this is the last item for this context
                const nextItem = tableItems[index + 1];
                const isLastInContext = !nextItem || nextItem.context !== item.context;

                if (isLastInContext) {
                  // Calculate subtotal for this context
                  const contextItems = tableItems.filter((i) => i.context === item.context);
                  const subtotalRow = {
                    context: '',
                    serviceApi: `${item.context} Subtotal`,
                    unit: '',
                    isSubtotal: true,
                  };

                  Object.keys(completeTestRuns).forEach((testRunId) => {
                    const contextTotal = contextItems.reduce((sum, contextItem) => {
                      const value = contextItem[testRunId];
                      if (value === 'N/A' || !value) return sum;
                      const numValue = parseFloat(value.replace('$', ''));
                      return sum + (isNaN(numValue) ? 0 : numValue);
                    }, 0);
                    subtotalRow[testRunId] = `$${contextTotal.toFixed(4)}`;
                  });

                  finalItems.push(subtotalRow);
                }
              });

              // Add total row
              const totalRow = {
                context: '',
                serviceApi: 'Total',
                unit: '',
                isTotal: true,
              };

              Object.keys(completeTestRuns).forEach((testRunId) => {
                const grandTotal = tableItems.reduce((sum, item) => {
                  const value = item[testRunId];
                  if (value === 'N/A' || !value) return sum;
                  const numValue = parseFloat(value.replace('$', ''));
                  return sum + (isNaN(numValue) ? 0 : numValue);
                }, 0);
                totalRow[testRunId] = `$${grandTotal.toFixed(4)}`;
              });

              finalItems.push(totalRow);

              return finalItems.length > 0 ? (
                <Table
                  resizableColumns
                  wrapLines={preferences.wrapLines}
                  preferences={<div />}
                  items={finalItems}
                  columnDefinitions={[
                    { id: 'context', header: 'Context', cell: (item) => (item.isSubtotal || item.isTotal ? '' : item.context), width: 180 },
                    {
                      id: 'serviceApi',
                      header: 'Service/Api',
                      width: 300,
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
                    { id: 'unit', header: 'Unit', cell: (item) => (item.isSubtotal || item.isTotal ? '' : item.unit), width: 200 },
                    ...Object.keys(completeTestRuns).map((testRunId) => ({
                      id: testRunId,
                      header: createTestRunHeader(testRunId, true),
                      width: 100,
                      cell: (item) => (
                        <span
                          style={{
                            fontWeight: item.isSubtotal || item.isTotal ? 'bold' : 'normal',
                            color: item.isTotal ? '#0073bb' : 'inherit',
                          }}
                        >
                          {item[testRunId] || '$0.0000'}
                        </span>
                      ),
                    })),
                  ]}
                  variant="embedded"
                />
              ) : (
                <Box>No cost breakdown data available</Box>
              );
            })()}
          </Container>

          {/* Usage Comparison */}
          <Container header={<Header variant="h3">Usage Breakdown Comparison</Header>}>
            {(() => {
              const allUsageItems = new Set();

              // Collect all unique usage items
              Object.values(completeTestRuns).forEach((testRun) => {
                if (testRun.costBreakdown) {
                  Object.entries(testRun.costBreakdown).forEach(([context, services]) => {
                    Object.keys(services).forEach((serviceUnit) => {
                      const lastUnderscoreIndex = serviceUnit.lastIndexOf('_');
                      const serviceApi = serviceUnit.substring(0, lastUnderscoreIndex);
                      const unit = serviceUnit.substring(lastUnderscoreIndex + 1);
                      const [service, api] = serviceApi.split('/');
                      allUsageItems.add(`${context}|${service}/${api}|${unit}`);
                    });
                  });
                }
              });

              const tableItems = Array.from(allUsageItems).map((itemKey) => {
                const [context, serviceApi, unit] = String(itemKey).split('|');
                const row = {
                  context,
                  serviceApi,
                  unit,
                };

                // Add usage value for each test run
                Object.entries(completeTestRuns).forEach(([testRunId, testRun]) => {
                  const services = testRun.costBreakdown?.[context] || {};
                  const serviceKey = Object.keys(services).find((key) => {
                    const lastUnderscoreIndex = key.lastIndexOf('_');
                    const keyServiceApi = key.substring(0, lastUnderscoreIndex);
                    const keyUnit = key.substring(lastUnderscoreIndex + 1);
                    return keyServiceApi === serviceApi && keyUnit === unit;
                  });

                  const details = services[serviceKey] || {};
                  const value = details.value || 0;
                  row[testRunId] = value > 0 ? value.toLocaleString() : 'N/A';
                });

                return row;
              });

              // Sort by context, then by service/api
              tableItems.sort((a, b) => {
                if (a.context !== b.context) return a.context.localeCompare(b.context);
                return a.serviceApi.localeCompare(b.serviceApi);
              });

              return tableItems.length > 0 ? (
                <Table
                  resizableColumns
                  wrapLines={preferences.wrapLines}
                  preferences={<div />}
                  items={tableItems}
                  columnDefinitions={[
                    { id: 'context', header: 'Context', cell: (item) => item.context, width: 180 },
                    { id: 'serviceApi', header: 'Service/Api', cell: (item) => item.serviceApi, width: 300 },
                    { id: 'unit', header: 'Unit', cell: (item) => item.unit, width: 200 },
                    ...Object.keys(completeTestRuns).map((testRunId) => ({
                      id: testRunId,
                      header: createTestRunHeader(testRunId, true),
                      width: 150,
                      cell: (item) => item[testRunId] || '0',
                    })),
                  ]}
                  variant="embedded"
                />
              ) : (
                <Box>No usage breakdown data available</Box>
              );
            })()}
          </Container>
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );
};

export default TestComparison;
