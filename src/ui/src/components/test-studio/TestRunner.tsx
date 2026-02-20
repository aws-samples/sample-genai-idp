// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import type { SelectProps, IconProps } from '@cloudscape-design/components';
import { Container, Header, SpaceBetween, Button, FormField, Select, Alert, Textarea, Input } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import START_TEST_RUN from '../../graphql/queries/startTestRun';
import GET_TEST_SETS from '../../graphql/queries/getTestSets';
import handlePrint from './PrintUtils';
import useConfigurationVersions from '../../hooks/use-configuration-versions';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GqlResult = { data: Record<string, any> };

const client = generateClient();
const logger = new ConsoleLogger('TestRunner');

interface ActiveTestRun {
  testRunId: string;
  testSetName: string;
  startTime: Date;
}

interface TestSetData {
  id: string;
  name: string;
  filePattern?: string;
  fileCount: number;
  status: string;
}

interface TestRunnerProps {
  onTestStart: (testRunId: string, testSetName: string, context: string, filesCount: number, configVersion?: string) => void;
  onTestComplete: (testRunId: string) => void;
  activeTestRuns: ActiveTestRun[];
}

const TestRunner = ({
  onTestStart,
  onTestComplete: _onTestComplete,
  activeTestRuns: _activeTestRuns,
}: TestRunnerProps): React.JSX.Element => {
  const [testSets, setTestSets] = useState<TestSetData[]>([]);
  const [selectedTestSet, setSelectedTestSet] = useState<SelectProps.Option | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<SelectProps.Option | null>(null);
  const [numberOfFiles, setNumberOfFiles] = useState('');
  const [context, setContext] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { versions, loading: _versionsLoading, getVersionOptions } = useConfigurationVersions();

  // Set default to active version when versions are loaded
  React.useEffect(() => {
    if (versions.length > 0 && !selectedVersion) {
      const activeVersion = versions.find((v) => v.isActive);
      if (activeVersion) {
        // Use the same logic as getVersionOptions to ensure consistency
        const versionOptions = getVersionOptions();
        const activeVersionOption = versionOptions.find((option) => option.value === activeVersion.versionName);
        if (activeVersionOption) {
          setSelectedVersion(activeVersionOption);
        }
      }
    }
  }, [versions, selectedVersion, getVersionOptions]);

  // Set default context when test set, version, or numberOfFiles changes
  React.useEffect(() => {
    if (selectedTestSet && selectedVersion) {
      const testSetName = selectedTestSet.label.split(' - ')[0]; // Extract name without file count
      const versionName = selectedVersion.value; // Use value instead of label to avoid "(Active)"
      const testSetData = testSets.find((ts) => ts.id === selectedTestSet.value);
      const totalFiles = testSetData?.fileCount || 0;
      const filesToProcess = numberOfFiles.trim() ? parseInt(numberOfFiles.trim(), 10) : totalFiles;
      const defaultContext = `Test set: ${testSetName} using version (${versionName}) with ${filesToProcess} files`;
      setContext(defaultContext);
    }
  }, [selectedTestSet, selectedVersion, testSets, numberOfFiles]);

  const loadTestSets = async () => {
    try {
      console.log('TestRunner: Loading test sets...');
      const result = (await client.graphql({ query: GET_TEST_SETS })) as GqlResult;
      console.log('TestRunner: GraphQL result:', result);
      const testSetsData = result.data.getTestSets || [];
      console.log('TestRunner: Test sets data:', testSetsData);
      setTestSets(testSetsData);
    } catch (err) {
      console.error('TestRunner: Failed to load test sets:', err);
      setError(`Failed to load test sets: ${err.message}`);
    }
  };

  React.useEffect(() => {
    loadTestSets();
  }, []);

  const handleRunTest = async () => {
    if (!selectedTestSet) {
      setError('Please select a test set');
      return;
    }

    // Get the selected test set data to validate numberOfFiles
    const testSetData = testSets.find((ts) => ts.id === selectedTestSet.value);
    const maxFiles = testSetData?.fileCount || 0;

    let _filesToProcess = maxFiles;
    if (numberOfFiles.trim()) {
      const numFiles = parseInt(numberOfFiles.trim(), 10);
      if (isNaN(numFiles) || numFiles <= 0) {
        setError('Number of files must be a positive integer');
        return;
      }
      if (numFiles > maxFiles) {
        setError(`Number of files cannot exceed ${maxFiles} (total files in test set)`);
        return;
      }
      _filesToProcess = numFiles;
    }

    setLoading(true);
    try {
      const input = {
        testSetId: selectedTestSet.value,
        ...(context && { context }),
        ...(numberOfFiles.trim() && { numberOfFiles: parseInt(numberOfFiles.trim(), 10) }),
        ...(selectedVersion && { configVersion: selectedVersion.value }),
      };
      console.log('TestRunner: Starting test run with input:', input);

      const result = (await client.graphql({
        query: START_TEST_RUN,
        variables: { input },
      })) as GqlResult;

      console.log('TestRunner: GraphQL result:', result);

      if (!result?.data?.startTestRun) {
        throw new Error('No response data from startTestRun mutation');
      }

      logger.info('Test run started:', result.data.startTestRun);
      onTestStart(
        result.data.startTestRun.testRunId,
        result.data.startTestRun.testSetName,
        context,
        result.data.startTestRun.filesCount,
        selectedVersion?.value,
      );
      setError('');
    } catch (err) {
      logger.error('Failed to start test run:', err);
      console.error('TestRunner: Error details:', {
        message: err.message,
        errors: err.errors,
        networkError: err.networkError,
        graphQLErrors: err.graphQLErrors,
      });

      let errorMessage = 'Failed to start test run';
      if (err.errors && err.errors.length > 0) {
        errorMessage = err.errors.map((e) => e.message).join('; ');
      } else if (err.message) {
        errorMessage = err.message;
      }
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const testSetOptions = testSets
    .filter((testSet) => testSet.status === 'COMPLETED')
    .map((testSet) => ({
      label: `${testSet.name}${testSet.filePattern ? ` (${testSet.filePattern})` : ''} - ${testSet.fileCount} ${
        testSet.fileCount === 1 ? 'file' : 'files'
      }`,
      value: testSet.id,
      description: testSet.filePattern ? `Pattern: ${testSet.filePattern}` : 'Uploaded test set',
    }));

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Select a test set and execute test runs for document processing"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" onClick={handleRunTest} loading={loading} disabled={!selectedTestSet}>
                Run Test
              </Button>
              <Button onClick={handlePrint} iconName={'print' as unknown as IconProps.Name}>
                Print
              </Button>
            </SpaceBetween>
          }
        >
          Run Test Set
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}

        <FormField label="Select Test Set" description="Choose an existing test set to run">
          <Select
            selectedOption={selectedTestSet}
            onChange={({ detail }) => {
              setSelectedTestSet(detail.selectedOption);
              setNumberOfFiles(''); // Reset numberOfFiles when test set changes
            }}
            options={testSetOptions}
            placeholder="Choose a test set..."
            empty="No test sets available"
          />
        </FormField>

        <FormField
          label="Configuration Version"
          description="Select which configuration version to use for processing these test documents"
        >
          <Select
            selectedOption={selectedVersion}
            onChange={({ detail }) => setSelectedVersion(detail.selectedOption)}
            options={getVersionOptions()}
            placeholder={versions.length === 0 ? 'Loading versions...' : 'Select configuration version'}
            disabled={loading || versions.length === 0}
            loadingText="Loading versions..."
          />
        </FormField>

        <FormField
          label="Number of Files"
          description={`Optional: Limit the number of files to process (max: ${
            selectedTestSet ? testSets.find((ts) => ts.id === selectedTestSet.value)?.fileCount || 0 : 0
          })`}
        >
          <Input
            value={numberOfFiles}
            onChange={({ detail }) => {
              const value = detail.value;
              const maxFiles = selectedTestSet ? testSets.find((ts) => ts.id === selectedTestSet.value)?.fileCount || 0 : 0;

              // Allow empty value
              if (value === '') {
                setNumberOfFiles('');
                return;
              }

              // Only allow digits (reject any non-digit characters)
              if (!/^\d+$/.test(value)) {
                return; // Don't update state if invalid characters
              }

              // Check range
              const num = parseInt(value, 10);
              if (num > 0 && num <= maxFiles) {
                setNumberOfFiles(value);
              }
              // If number is too large, don't update the state (prevents typing)
            }}
            placeholder={
              selectedTestSet
                ? `Enter 1-${testSets.find((ts) => ts.id === selectedTestSet.value)?.fileCount || 0}`
                : 'Select a test set first'
            }
            disabled={!selectedTestSet}
            type="text"
            inputMode="numeric"
          />
        </FormField>

        <FormField
          label="Context"
          description="Optional context information for this test run"
          errorText={context && context.length > 500 ? 'Context cannot exceed 500 characters' : ''}
        >
          <Textarea
            value={context}
            onChange={({ detail }) => setContext(detail.value)}
            placeholder="Enter context information..."
            rows={2}
            invalid={context && context.length > 500}
          />
        </FormField>
      </SpaceBetween>
    </Container>
  );
};

export default TestRunner;
