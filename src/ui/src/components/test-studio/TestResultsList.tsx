// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { Table, Button, SpaceBetween, ButtonDropdown, Pagination, Box, TextFilter, Flashbar } from '@cloudscape-design/components';
import type { IconProps } from '@cloudscape-design/components';
import { useCollection } from '@cloudscape-design/collection-hooks';
import { generateClient } from 'aws-amplify/api';
import GET_TEST_RUNS from '../../graphql/queries/getTestRuns';
import DELETE_TESTS from '../../graphql/queries/deleteTests';
import DeleteTestModal from './DeleteTestModal';
import DateRangeModal from '../common/DateRangeModal';
import { paginationLabels } from '../common/labels';
import TestRunnerStatus from './TestRunnerStatus';
import { TableHeader } from '../common/table';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { formatConfigVersionLink, formatConfigVersionText } from './utils/configVersionUtils';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GqlResult = { data: Record<string, any> };

const client = generateClient();

const TIME_PERIOD_OPTIONS = [
  { id: 'refresh-2h', hours: 2, text: '2 hrs' },
  { id: 'refresh-4h', hours: 4, text: '4 hrs' },
  { id: 'refresh-8h', hours: 8, text: '8 hrs' },
  { id: 'refresh-1d', hours: 24, text: '1 day' },
  { id: 'refresh-2d', hours: 48, text: '2 days' },
  { id: 'refresh-1w', hours: 168, text: '1 week' },
  { id: 'refresh-2w', hours: 336, text: '2 weeks' },
  { id: 'refresh-1m', hours: 720, text: '30 days' },
  { id: 'custom-range', hours: -1, text: 'Custom range...' },
].map((option) => ({ ...option, text: option.text }));

interface TestRunItem {
  testRunId: string;
  testSetName: string;
  status: string;
  isActive?: boolean;
  progress?: number;
  filesCount: number;
  createdAt: string;
  completedAt: string | null;
  context: string;
  configVersion?: string | null;
}

interface ActiveTestRun {
  testRunId: string;
  testSetName: string;
  startTime: Date;
  filesCount?: number;
  context?: string;
  configVersion?: string;
}

interface DateRange {
  startDateTime: string;
  endDateTime: string;
}

interface TestResultsListProps {
  timePeriodHours: number;
  setTimePeriodHours: (hours: number) => void;
  selectedItems: TestRunItem[];
  setSelectedItems: (items: TestRunItem[]) => void;
  preSelectedTestRunId?: string | null;
  activeTestRuns?: ActiveTestRun[];
  onTestComplete: (testRunId: string) => void;
}

const TestRunIdCell = ({ item, onSelect }: { item: TestRunItem; onSelect: (testRunId: string) => void }): React.JSX.Element => (
  <button
    type="button"
    style={{
      cursor: 'pointer',
      color: '#0073bb',
      textDecoration: 'underline',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      display: 'block',
      maxWidth: '100%',
      background: 'none',
      border: 'none',
      padding: 0,
      font: 'inherit',
      textAlign: 'left',
    }}
    title={item.testRunId}
    onClick={() => onSelect(item.testRunId)}
  >
    {item.testRunId}
  </button>
);

const TextCell = ({ text }: { text: string }): React.JSX.Element => (
  <span
    style={{
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      display: 'block',
      maxWidth: '100%',
    }}
    title={text}
  >
    {text}
  </span>
);

const TIME_PERIOD_STORAGE_KEY = 'testResultsTimePeriodHours';

const TestResultsList = ({
  timePeriodHours,
  setTimePeriodHours,
  selectedItems,
  setSelectedItems,
  activeTestRuns = [],
  onTestComplete,
}: TestResultsListProps): React.JSX.Element => {
  const { versions } = useConfigurationVersions();
  const [testRuns, setTestRuns] = useState<TestRunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isDeleteModalVisible, setIsDeleteModalVisible] = useState(false);
  const [isDateRangeModalVisible, setIsDateRangeModalVisible] = useState(false);
  const [customDateRange, setCustomDateRange] = useState<DateRange | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [pageSize, setPageSize] = useState(10);

  // Load saved time period from localStorage on mount
  useEffect(() => {
    const savedTimePeriod = localStorage.getItem(TIME_PERIOD_STORAGE_KEY);
    if (savedTimePeriod) {
      const parsedPeriod = JSON.parse(savedTimePeriod);
      if (parsedPeriod !== timePeriodHours) {
        setTimePeriodHours(parsedPeriod);
      }
    }
  }, []);

  const handleTimePeriodChange = ({ detail }: { detail: { id: string } }): void => {
    if (detail.id === 'custom-range') {
      setIsDateRangeModalVisible(true);
      return;
    }
    const selectedOption = TIME_PERIOD_OPTIONS.find((opt) => opt.id === detail.id);
    if (selectedOption) {
      setCustomDateRange(null); // Clear custom range when switching to relative
      setTimePeriodHours(selectedOption.hours);
      localStorage.setItem(TIME_PERIOD_STORAGE_KEY, JSON.stringify(selectedOption.hours));
    }
  };

  // Remove the URL effect since we're using props now
  // Use collection hook for pagination, filtering, and sorting
  const { items, collectionProps, paginationProps, filterProps } = useCollection(testRuns, {
    filtering: {
      empty: 'No test runs found',
      noMatch: 'No test runs match the filter',
    },
    pagination: { pageSize },
    sorting: { defaultState: { sortingColumn: { sortingField: 'createdAt' }, isDescending: true } },
  });

  const handleTestRunSelect = (testRunId: string): void => {
    window.location.hash = `#/test-studio?tab=results&testRunId=${testRunId}`;
  };

  const getTestRunIdCell = (item) => <TestRunIdCell item={item} onSelect={handleTestRunSelect} />;
  const getTestSetNameCell = (item) => <TextCell text={item.testSetName} />;
  const getContextCell = (item) => <TextCell text={item.context || 'N/A'} />;

  const getStatusCell = (item) => {
    if (item.isActive) {
      return <TestRunnerStatus testRunId={item.testRunId} onComplete={() => onTestComplete(item.testRunId)} />;
    }
    return item.status;
  };

  const fetchTestRuns = async () => {
    try {
      setLoading(true);
      const variables = customDateRange
        ? { startDateTime: customDateRange.startDateTime, endDateTime: customDateRange.endDateTime }
        : { timePeriodHours };
      console.log('Fetching test runs with variables:', variables);
      const result = (await client.graphql({
        query: GET_TEST_RUNS,
        variables,
      })) as GqlResult;
      console.log('Raw GraphQL result:', result);
      console.log('getTestRuns data:', result.data.getTestRuns);
      console.log('Number of test runs returned:', result.data.getTestRuns?.length || 0);

      const completedRuns = result.data.getTestRuns || [];

      // Add active test runs with progress
      const activeRunsWithProgress = activeTestRuns.map((run) => ({
        testRunId: run.testRunId,
        testSetName: run.testSetName,
        status: 'Running',
        isActive: true,
        progress: Math.min(90, Math.floor(((Date.now() - run.startTime.getTime()) / 1000 / 60) * 10)), // Simulate progress
        filesCount: run.filesCount || 0,
        createdAt: run.startTime.toISOString(),
        completedAt: null,
        context: run.context || 'N/A',
        configVersion: run.configVersion || null,
      }));

      // Filter out completed runs that match active run IDs to avoid duplicates
      const activeRunIds = new Set(activeTestRuns.map((run) => run.testRunId));
      const filteredCompletedRuns = completedRuns.filter((run) => !activeRunIds.has(run.testRunId));

      // Merge active and completed runs, active runs first
      const allRuns = [...activeRunsWithProgress, ...filteredCompletedRuns];
      setTestRuns(allRuns);
      setError(null);
    } catch (err) {
      console.error('Error fetching test runs:', err);
      const errorMessage = err.errors?.length > 0 ? err.errors.map((e) => e.message).join('; ') : 'Failed to load test runs';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTestRuns();
  }, [timePeriodHours, activeTestRuns, customDateRange]);

  const downloadToExcel = () => {
    // Convert test runs data to CSV format
    const headers = ['Test Run ID', 'Test Set', 'Context', 'Config Version', 'Status', 'Files Count', 'Created At', 'Completed At'];
    const csvData = testRuns.map((run) => [
      run.testRunId,
      run.testSetName || '',
      run.context || '',
      formatConfigVersionText(run.configVersion, versions),
      run.status,
      run.filesCount || 0,
      run.createdAt || '',
      run.completedAt || '',
    ]);

    const csvContent = [headers, ...csvData].map((row) => row.map((field) => `"${field}"`).join(',')).join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `test-results-${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleRefresh = () => {
    fetchTestRuns();
  };

  const handleCompare = () => {
    if (selectedItems.length > 1) {
      const testRunIds = selectedItems.map((item) => item.testRunId);
      const testIdsParam = testRunIds.join(',');
      window.location.hash = `#/test-studio?tab=comparison&testIds=${testIdsParam}&timePeriod=${timePeriodHours}`;
    }
  };

  const confirmDelete = async () => {
    try {
      setDeleteLoading(true);
      const testRunIds = selectedItems.map((item) => item.testRunId);
      console.log('Attempting to delete test runs:', testRunIds);

      const result = (await client.graphql({
        query: DELETE_TESTS,
        variables: { testRunIds },
      })) as GqlResult;
      console.log('Delete result:', result);

      const count = selectedItems.length;
      setSuccessMessage(`Successfully deleted ${count} test run${count > 1 ? 's' : ''}`);
      setSelectedItems([]);
      setIsDeleteModalVisible(false);
      fetchTestRuns(); // Refresh the list

      // Clear success message after 5 seconds
      setTimeout(() => setSuccessMessage(null), 5000);

      return result.data.deleteTests;
    } catch (err) {
      console.error('Error deleting test runs:', err);
      console.error('Error details:', err.errors);
      return false;
    } finally {
      setDeleteLoading(false);
    }
  };

  if (loading) return <div>Loading test runs...</div>;
  if (error) return <div>Error loading test runs: {error}</div>;

  return (
    <SpaceBetween size="s">
      {successMessage && (
        <Flashbar
          items={[
            {
              type: 'success',
              content: successMessage,
              dismissible: true,
              onDismiss: () => setSuccessMessage(null),
            },
          ]}
        />
      )}
      <TableHeader
        title={`Test Results (${testRuns.length})`}
        actionButtons={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown loading={loading} onItemClick={handleTimePeriodChange} items={TIME_PERIOD_OPTIONS}>
              {customDateRange
                ? (() => {
                    const s = new Date(customDateRange.startDateTime);
                    const e = new Date(customDateRange.endDateTime);
                    const fmt = (d: Date) =>
                      `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
                    return `Load: ${fmt(s)} → ${fmt(e)}`;
                  })()
                : `Load: ${TIME_PERIOD_OPTIONS.find((opt) => opt.hours === timePeriodHours)?.text || ''}`}
            </ButtonDropdown>
            <Button iconName="refresh" variant="normal" loading={loading} onClick={handleRefresh} />
            <Button iconName="download" variant="normal" loading={loading} onClick={downloadToExcel} />
            <Button
              iconName="remove"
              variant="normal"
              onClick={() => setIsDeleteModalVisible(true)}
              disabled={selectedItems.length === 0}
              loading={deleteLoading}
            />
            {selectedItems.length > 1 && (
              <Button iconName={'compare' as unknown as IconProps.Name} variant="normal" onClick={handleCompare}>
                Test Comparison ({selectedItems.length})
              </Button>
            )}
          </SpaceBetween>
        }
      />
      <Table
        resizableColumns
        items={items}
        selectedItems={selectedItems}
        onSelectionChange={({ detail }) => setSelectedItems(detail.selectedItems)}
        trackBy="testRunId"
        sortingColumn={collectionProps.sortingColumn}
        sortingDescending={collectionProps.sortingDescending}
        onSortingChange={collectionProps.onSortingChange}
        wrapLines={false}
        columnDefinitions={[
          {
            id: 'testRunId',
            header: 'Test Run ID',
            cell: getTestRunIdCell,
            sortingField: 'testRunId',
            width: 300,
          },
          {
            id: 'testSetName',
            header: 'Test Set Name',
            cell: getTestSetNameCell,
            sortingField: 'testSetName',
            width: 150,
          },
          {
            id: 'filesCount',
            header: 'Files Count',
            cell: (item) => item.filesCount,
            sortingField: 'filesCount',
            width: 100,
          },
          {
            id: 'configVersion',
            header: 'Config Version',
            cell: (item) => formatConfigVersionLink(item.configVersion, versions),
            sortingField: 'configVersion',
            width: 150,
          },
          {
            id: 'status',
            header: 'Status',
            cell: getStatusCell,
            sortingField: 'status',
            width: 200,
          },
          {
            id: 'context',
            header: 'Context',
            cell: getContextCell,
            sortingField: 'context',
            width: 200,
          },
          {
            id: 'createdAt',
            header: 'Created At',
            cell: (item) => new Date(item.createdAt).toLocaleString(),
            sortingField: 'createdAt',
          },
          {
            id: 'completedAt',
            header: 'Completed At',
            cell: (item) => (item.completedAt ? new Date(item.completedAt).toLocaleString() : 'N/A'),
            sortingField: 'completedAt',
          },
        ]}
        selectionType="multi"
        filter={
          <TextFilter
            filteringText={filterProps.filteringText}
            onChange={filterProps.onChange}
            filteringAriaLabel="Filter test runs"
            filteringPlaceholder="Find test runs"
          />
        }
        empty={
          <Box textAlign="center" color="inherit">
            <b>No test runs found</b>
            <Box variant="p" color="inherit">
              No test runs available for the selected time period.
            </Box>
          </Box>
        }
        loading={loading}
        stickyHeader
        pagination={
          <Pagination
            currentPageIndex={paginationProps.currentPageIndex}
            pagesCount={paginationProps.pagesCount}
            onChange={paginationProps.onChange}
            ariaLabels={paginationLabels}
          />
        }
        preferences={
          <Button
            variant="icon"
            iconName="settings"
            ariaLabel="Page size settings"
            onClick={() => {
              if (pageSize === 10) setPageSize(20);
              else if (pageSize === 20) setPageSize(50);
              else setPageSize(10);
            }}
          />
        }
      />

      <DeleteTestModal
        visible={isDeleteModalVisible}
        onDismiss={() => setIsDeleteModalVisible(false)}
        onConfirm={confirmDelete}
        selectedItems={selectedItems}
        itemType="test run"
        loading={deleteLoading}
      />

      <DateRangeModal
        visible={isDateRangeModalVisible}
        onDismiss={() => setIsDateRangeModalVisible(false)}
        onApply={(dateRange) => {
          setIsDateRangeModalVisible(false);
          setCustomDateRange(dateRange);
        }}
      />
    </SpaceBetween>
  );
};

export default TestResultsList;
