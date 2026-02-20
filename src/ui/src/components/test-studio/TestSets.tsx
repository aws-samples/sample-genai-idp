// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import type { SelectProps } from '@cloudscape-design/components';
import {
  Container,
  Header,
  SpaceBetween,
  Button,
  ButtonDropdown,
  Table,
  Box,
  Modal,
  FormField,
  Input,
  Alert,
  Badge,
  ExpandableSection,
  Select,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import ADD_TEST_SET from '../../graphql/queries/addTestSet';
import ADD_TEST_SET_FROM_UPLOAD from '../../graphql/queries/addTestSetFromUpload';
import DELETE_TEST_SETS from '../../graphql/queries/deleteTestSets';
import GET_TEST_SETS from '../../graphql/queries/getTestSets';
import LIST_BUCKET_FILES from '../../graphql/queries/listBucketFiles';
import VALIDATE_TEST_FILE_NAME from '../../graphql/queries/checkTestSetFiles';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GqlResult = { data: Record<string, any> };

const client = generateClient();

// Constants
const MAX_ZIP_SIZE_BYTES = 1073741824; // 1 GB

const BUCKET_OPTIONS: SelectProps.Option[] = [
  { label: 'Input Bucket', value: 'input' },
  { label: 'Test Set Bucket', value: 'testset' },
];

interface TestSetItem {
  id: string;
  name: string;
  description?: string;
  filePattern?: string | null;
  fileCount: number | null;
  status: string;
  createdAt: string;
  error?: string;
}

const TestSets = (): React.JSX.Element => {
  const [testSets, setTestSets] = useState<TestSetItem[]>([]);
  const [selectedItems, setSelectedItems] = useState<TestSetItem[]>([]);
  const [showAddPatternModal, setShowAddPatternModal] = useState(false);
  const [showAddUploadModal, setShowAddUploadModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [newTestSetName, setNewTestSetName] = useState('');
  const [newTestSetDescription, setNewTestSetDescription] = useState('');
  const [filePattern, setFilePattern] = useState('');
  const [selectedBucket, setSelectedBucket] = useState(BUCKET_OPTIONS[0]);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [matchingFiles, setMatchingFiles] = useState<string[]>([]);
  const [fileCount, setFileCount] = useState(0);
  const [showFilesModal, setShowFilesModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showBucketHelp, setShowBucketHelp] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [warningMessage, setWarningMessage] = useState('');
  const [confirmReplacement, setConfirmReplacement] = useState(false);
  const [showFileStructure, setShowFileStructure] = useState(() => {
    return localStorage.getItem('testset-show-file-structure') !== 'false';
  });
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const loadTestSets = async () => {
    try {
      console.log('TestSets: Loading test sets...');
      const result = (await client.graphql({ query: GET_TEST_SETS })) as GqlResult;
      console.log('TestSets: GraphQL result:', result);
      const backendTestSets = result.data.getTestSets || [];

      // Upsert: merge backend data with existing UI state, deduplicating by id
      setTestSets((prevTestSets) => {
        const backendIds = new Set(backendTestSets.map((ts) => ts.id));

        // Keep UI test sets that don't exist in backend (active processing)
        const uiOnlyTestSets = prevTestSets.filter((ts) => !backendIds.has(ts.id) && ts.status !== 'COMPLETED' && ts.status !== 'FAILED');

        // Combine backend test sets (always win) with UI-only active test sets
        return [...backendTestSets, ...uiOnlyTestSets];
      });
    } catch (err) {
      console.error('TestSets: Failed to load test sets:', err);
      setError(`Failed to load test sets: ${err.message || 'Unknown error'}`);
    }
  };

  // Preserve selections when testSets array changes
  React.useEffect(() => {
    if (selectedItems.length > 0) {
      const selectedIds = new Set(selectedItems.map((item) => item.id));
      const updatedSelections = testSets.filter((ts) => selectedIds.has(ts.id));
      if (updatedSelections.length !== selectedItems.length || !updatedSelections.every((item, index) => item === selectedItems[index])) {
        setSelectedItems(updatedSelections);
      }
    }
  }, [testSets]);

  React.useEffect(() => {
    loadTestSets();
  }, []);

  // Simple polling for active test sets
  React.useEffect(() => {
    const hasActiveTestSets = testSets.some((testSet) => testSet.status !== 'COMPLETED' && testSet.status !== 'FAILED');

    if (!hasActiveTestSets) {
      console.log('No active test sets, no polling needed');
      return;
    }

    console.log('Starting polling for active test sets');
    const interval = setInterval(() => {
      console.log('Polling refresh...');
      loadTestSets();
    }, 3000);

    return () => {
      console.log('Cleaning up polling');
      clearInterval(interval);
    };
  }, [testSets]);

  // Separate discovery polling for new test sets (less frequent)
  React.useEffect(() => {
    console.log('Starting discovery polling for new test sets');
    const discoveryInterval = setInterval(() => {
      console.log('Discovery polling...');
      loadTestSets();
    }, 60000); // Every 60 seconds (1 minute)

    return () => {
      console.log('Cleaning up discovery polling');
      clearInterval(discoveryInterval);
    };
  }, []); // No dependencies - always runs

  // Cleanup polling on unmount
  const handleCheckFiles = async () => {
    if (!filePattern.trim()) return;

    setLoading(true);
    try {
      const result = (await client.graphql({
        query: LIST_BUCKET_FILES,
        variables: {
          bucketType: selectedBucket.value,
          filePattern: filePattern.trim(),
        },
      })) as GqlResult;

      const files = result.data.listBucketFiles || [];
      setMatchingFiles(files);
      setFileCount(files.length);
      setShowFilesModal(true);
    } catch (err) {
      const errorMessage = err.message || err.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to check files: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const validateTestSetName = (name: string): boolean => {
    const validPattern = /^[a-zA-Z0-9\s-_]+$/;
    return validPattern.test(name) && name.length <= 50;
  };

  const validateDescription = (desc: string): boolean => {
    return desc.length <= 200;
  };

  const handleAddTestSet = async () => {
    if (!newTestSetName.trim() || !filePattern.trim()) {
      setError('Both test set name and file pattern are required');
      return;
    }

    // 1. UI validation using existing validateTestSetName
    if (!validateTestSetName(newTestSetName.trim())) {
      setError('Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)');
      return;
    }

    // Validate description
    if (newTestSetDescription && !validateDescription(newTestSetDescription.trim())) {
      setError('Description cannot exceed 200 characters');
      return;
    }

    // 2. Backend validation using VALIDATE_TEST_FILE_NAME
    try {
      const validationResult = (await client.graphql({
        query: VALIDATE_TEST_FILE_NAME,
        variables: { fileName: newTestSetName.trim() },
      })) as GqlResult;

      const validation = validationResult.data.validateTestFileName;
      if (validation && validation.exists) {
        if (!confirmReplacement) {
          setWarningMessage(
            `Test set ID "${validation.testSetId}" already exists and will be replaced. Click "Add Test Set" again to confirm.`,
          );
          setConfirmReplacement(true);
          return;
        }
        setWarningMessage('');
      } else {
        setWarningMessage('');
        setConfirmReplacement(false);
      }
    } catch (err) {
      console.error('Error validating test set name:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to validate test set name: ${errorMessage}`);
      return;
    }

    setLoading(true);
    try {
      const result = (await client.graphql({
        query: ADD_TEST_SET,
        variables: {
          name: newTestSetName.trim(),
          description: newTestSetDescription.trim(),
          filePattern: filePattern.trim(),
          bucketType: selectedBucket.value,
          fileCount,
        },
      })) as GqlResult;

      console.log('GraphQL result:', result);
      const newTestSet = result.data.addTestSet;
      console.log('New test set data:', newTestSet);

      if (newTestSet) {
        // Immediate UI update for responsive feedback - use upsert to prevent duplicates
        setTestSets((prev) => {
          const existingIndex = prev.findIndex((ts) => ts.id === newTestSet.id);
          if (existingIndex >= 0) {
            // Replace existing test set
            const updated = [...prev];
            updated[existingIndex] = newTestSet;
            return updated;
          } else {
            // Add new test set
            return [...prev, newTestSet];
          }
        });
        setNewTestSetName('');
        setNewTestSetDescription('');
        setFilePattern('');
        setSelectedBucket(BUCKET_OPTIONS[0]);
        setFileCount(0);
        setShowAddPatternModal(false);
        setError('');
        setWarningMessage('');
        setSuccessMessage(`Successfully created test set "${newTestSet.name}"`);
      } else {
        setError('Failed to create test set - no data returned');
      }
    } catch (err) {
      console.error('Error adding test set:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to add test set: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAddUploadTestSet = async () => {
    if (!newTestSetName.trim()) {
      setError('Test set name is required');
      return;
    }

    if (!validateTestSetName(newTestSetName.trim())) {
      setError('Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)');
      return;
    }

    // Validate description
    if (newTestSetDescription && !validateDescription(newTestSetDescription.trim())) {
      setError('Description cannot exceed 200 characters');
      return;
    }

    try {
      const validationResult = (await client.graphql({
        query: VALIDATE_TEST_FILE_NAME,
        variables: { fileName: newTestSetName.trim() },
      })) as GqlResult;

      const validation = validationResult.data.validateTestFileName;
      if (validation && validation.exists) {
        if (!confirmReplacement) {
          setWarningMessage(
            `Test set ID "${validation.testSetId}" already exists and will be replaced. Click "Create Test Set" again to confirm.`,
          );
          setConfirmReplacement(true);
          return;
        }
        setWarningMessage('');
      } else {
        setWarningMessage('');
        setConfirmReplacement(false);
      }
    } catch (err) {
      console.error('Error validating test set name:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to validate test set name: ${errorMessage}`);
      return;
    }

    if (!zipFile) {
      setError('Zip file is required');
      return;
    }

    setLoading(true);
    try {
      const result = (await client.graphql({
        query: ADD_TEST_SET_FROM_UPLOAD,
        variables: {
          input: {
            fileName: zipFile.name,
            fileSize: zipFile.size,
            description: newTestSetDescription.trim(),
          },
        },
      })) as GqlResult;

      const response = result.data.addTestSetFromUpload;

      if (!response || !response.presignedUrl) {
        throw new Error('Failed to get upload URL from server');
      }

      const presignedPostData = JSON.parse(response.presignedUrl);
      const formData = new FormData();

      Object.entries(presignedPostData.fields).forEach(([key, value]) => {
        formData.append(key, value as string);
      });
      formData.append('file', zipFile);

      const uploadResponse = await fetch(presignedPostData.url, {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        throw new Error(`Upload failed: ${uploadResponse.status} ${uploadResponse.statusText}`);
      }

      const newTestSet = {
        id: response.testSetId,
        name: newTestSetName.trim(),
        description: newTestSetDescription.trim(),
        status: 'QUEUED',
        fileCount: null,
        createdAt: new Date().toISOString(),
        filePattern: null,
      };

      // Immediate UI update for responsive feedback - use upsert to prevent duplicates
      setTestSets((prev) => {
        const existingIndex = prev.findIndex((ts) => ts.id === newTestSet.id);
        if (existingIndex >= 0) {
          // Replace existing test set
          const updated = [...prev];
          updated[existingIndex] = newTestSet;
          return updated;
        } else {
          // Add new test set
          return [...prev, newTestSet];
        }
      });

      setSuccessMessage(`Test set "${newTestSetName}" created successfully. Zip file is being processed.`);
      setError('');
      setShowAddUploadModal(false);
      setNewTestSetName('');
      setNewTestSetDescription('');
      setZipFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err) {
      console.error('Error creating test set:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to create test set: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setError('');
    setWarningMessage('');
    setSuccessMessage('');
    try {
      const result = (await client.graphql({ query: GET_TEST_SETS })) as GqlResult;
      setTestSets(result.data.getTestSets || []);
    } catch (err) {
      console.error('Error refreshing test sets:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to refresh test sets: ${errorMessage}`);
    } finally {
      setRefreshing(false);
    }
  };

  const handleDeleteTestSets = async () => {
    const testSetIds = selectedItems.map((item) => item.id);
    const deleteCount = testSetIds.length;

    setLoading(true);
    try {
      await client.graphql({
        query: DELETE_TEST_SETS,
        variables: { testSetIds },
      });
      setTestSets(testSets.filter((testSet) => !testSetIds.includes(testSet.id)));
      setSelectedItems([]);
      setSuccessMessage(`Successfully deleted ${deleteCount} test set${deleteCount > 1 ? 's' : ''}`);
      setError('');
    } catch (err) {
      console.error('Error deleting test sets:', err);
      const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
      setError(`Failed to delete test sets: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const filteredTestSets = testSets
    .filter((item) => item != null)
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  console.log('Filtered testSets for Table:', filteredTestSets);

  const columnDefinitions = [
    {
      id: 'name',
      header: 'Test Set Name',
      cell: (item) => item.name,
      sortingField: 'name',
    },
    {
      id: 'id',
      header: 'Test Set ID',
      cell: (item) => item.id,
      sortingField: 'id',
    },
    {
      id: 'description',
      header: 'Description',
      cell: (item) => item.description || '-',
      width: 200,
      minWidth: 120,
    },
    {
      id: 'filePattern',
      header: 'File Pattern',
      cell: (item) => item.filePattern,
    },
    {
      id: 'fileCount',
      header: 'Files',
      cell: (item) => item.fileCount,
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item) => {
        const status = item.status || '-';

        if (status === 'FAILED' && item.error) {
          const truncatedError = item.error.length > 15 ? `${item.error.substring(0, 15)}...` : item.error;

          return (
            <div>
              <div style={{ color: '#d13212', fontWeight: 'bold' }}>FAILED</div>
              <div
                style={{
                  fontSize: '0.9em',
                  color: '#666',
                  marginTop: '2px',
                  cursor: 'help',
                  maxWidth: '200px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={item.error}
              >
                {truncatedError}
              </div>
            </div>
          );
        }

        return status;
      },
    },
    {
      id: 'createdAt',
      header: 'Created',
      cell: (item) => new Date(item.createdAt).toLocaleDateString(),
      sortingField: 'createdAt',
    },
  ];

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Manage test sets for document processing"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" loading={refreshing} onClick={handleRefresh}>
                Refresh
              </Button>
              <Button iconName="remove" disabled={selectedItems.length === 0 || loading} onClick={() => setShowDeleteModal(true)} />
              <ButtonDropdown
                variant="primary"
                items={[
                  { id: 'pattern', text: 'Existing Files' },
                  { id: 'upload', text: 'New Upload' },
                ]}
                onItemClick={({ detail }) => {
                  if (detail.id === 'pattern') {
                    setShowAddPatternModal(true);
                  } else if (detail.id === 'upload') {
                    setShowAddUploadModal(true);
                  }
                }}
              >
                Add Test Set
              </ButtonDropdown>
            </SpaceBetween>
          }
        >
          Test Sets ({filteredTestSets.length})
        </Header>
      }
    >
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}

      {successMessage && (
        <Alert type="success" dismissible onDismiss={() => setSuccessMessage('')}>
          {successMessage}
        </Alert>
      )}

      <Table
        resizableColumns
        wrapLines
        columnDefinitions={columnDefinitions}
        items={filteredTestSets}
        selectedItems={selectedItems}
        onSelectionChange={({ detail }) => setSelectedItems(detail.selectedItems)}
        selectionType="multi"
        isItemDisabled={(item) => item.status !== 'COMPLETED' && item.status !== 'FAILED'}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No test sets</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              No test sets to display.
            </Box>
          </Box>
        }
      />

      <Modal
        visible={showAddPatternModal}
        onDismiss={() => {
          setShowAddPatternModal(false);
          setConfirmReplacement(false);
          setWarningMessage('');
          setSelectedBucket(BUCKET_OPTIONS[0]);
          setNewTestSetDescription('');
        }}
        header="Add Test Set from Pattern"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowAddPatternModal(false);
                  setConfirmReplacement(false);
                  setWarningMessage('');
                  setSelectedBucket(BUCKET_OPTIONS[0]);
                  setNewTestSetDescription('');
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={loading} onClick={handleAddTestSet} disabled={fileCount === 0}>
                Add Test Set
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}
          {warningMessage && <Alert type="warning">{warningMessage}</Alert>}

          <FormField
            label="Test Set Name"
            errorText={
              newTestSetName && !validateTestSetName(newTestSetName)
                ? 'Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)'
                : ''
            }
          >
            <Input
              value={newTestSetName}
              onChange={({ detail }) => {
                setNewTestSetName(detail.value);
                setConfirmReplacement(false);
                setWarningMessage('');
              }}
              placeholder="e.g., lending-package-v1"
              invalid={newTestSetName && !validateTestSetName(newTestSetName)}
            />
          </FormField>

          <FormField
            label="Description"
            description="Optional description for this test set"
            errorText={
              newTestSetDescription && !validateDescription(newTestSetDescription) ? 'Description cannot exceed 200 characters' : ''
            }
          >
            <Input
              value={newTestSetDescription}
              onChange={({ detail }) => setNewTestSetDescription(detail.value)}
              placeholder="Test set description"
              invalid={newTestSetDescription && !validateDescription(newTestSetDescription)}
            />
          </FormField>

          <FormField label="Source Bucket" description="Select the bucket to search for files">
            <SpaceBetween direction="vertical" size="xs">
              <Select
                selectedOption={selectedBucket}
                onChange={({ detail }) => {
                  setSelectedBucket(detail.selectedOption);
                  setFileCount(0);
                }}
                options={BUCKET_OPTIONS}
              />
              <ExpandableSection
                headerText="Bucket Structure Help"
                variant="footer"
                expanded={showBucketHelp}
                onChange={({ detail }) => setShowBucketHelp(detail.expanded)}
              >
                {selectedBucket.value === 'input' ? (
                  <Box>
                    <strong>Input Bucket Structure:</strong>
                    <Box variant="code" padding="xs" margin={{ top: 'xs' }}>
                      bucket/
                      <br />
                      ├── document1.pdf
                      <br />
                      ├── document2.pdf
                      <br />
                      ├── folder1/
                      <br />
                      │&nbsp;&nbsp;&nbsp;├── document1.pdf
                      <br />
                      │&nbsp;&nbsp;&nbsp;└── document2.pdf
                      <br />
                      └── folder2/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;└── document1.pdf
                    </Box>
                  </Box>
                ) : (
                  <Box>
                    <strong>Test Set Bucket Structure:</strong>
                    <Box variant="code" padding="xs" margin={{ top: 'xs' }}>
                      bucket/
                      <br />
                      └── my-test-set/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├── input/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;└── document1.pdf
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└── baseline/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└── document1.pdf/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└── sections/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├──{' '}
                      1/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;└──{' '}
                      result.json
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└──{' '}
                      2/
                      <br />
                      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└──{' '}
                      result.json
                    </Box>
                  </Box>
                )}
              </ExpandableSection>
            </SpaceBetween>
          </FormField>

          <FormField
            label="File Pattern"
            description={
              selectedBucket.value === 'testset'
                ? 'Use * for wildcards. Examples: test-set-name/input/*, test-set-prefix*/input/file-prefix*'
                : 'Use * for wildcards. Examples: prefix*, folder-name/*, folder-name/prefix*, folder-prefix*/file-prefix*'
            }
          >
            <SpaceBetween direction="horizontal" size="xs">
              <Input
                value={filePattern}
                onChange={({ detail }) => {
                  setFilePattern(detail.value);
                  setFileCount(0);
                }}
                placeholder={selectedBucket.value === 'testset' ? 'test-set-prefix*/input/*' : 'prefix*/*'}
              />
              <Button disabled={!filePattern.trim()} loading={loading} onClick={handleCheckFiles}>
                Check Files
              </Button>
            </SpaceBetween>
          </FormField>

          {fileCount > 0 && (
            <Box>
              <Badge color="green">
                {fileCount} {fileCount === 1 ? 'file' : 'files'} found
              </Badge>
            </Box>
          )}
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showAddUploadModal}
        onDismiss={() => {
          setShowAddUploadModal(false);
          setConfirmReplacement(false);
          setWarningMessage('');
          setError('');
          setZipFile(null);
          setNewTestSetName('');
          setNewTestSetDescription('');
          if (fileInputRef.current) {
            fileInputRef.current.value = '';
          }
        }}
        header="Add Test Set from Upload"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowAddUploadModal(false);
                  setConfirmReplacement(false);
                  setWarningMessage('');
                  setError('');
                  setZipFile(null);
                  setNewTestSetName('');
                  setNewTestSetDescription('');
                  if (fileInputRef.current) {
                    fileInputRef.current.value = '';
                  }
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={loading} onClick={handleAddUploadTestSet} disabled={!zipFile}>
                Upload and Create Test Set
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}
          {warningMessage && <Alert type="warning">{warningMessage}</Alert>}

          <FormField
            label="Description"
            description="Optional description for this test set"
            errorText={
              newTestSetDescription && !validateDescription(newTestSetDescription) ? 'Description cannot exceed 200 characters' : ''
            }
          >
            <Input
              value={newTestSetDescription}
              onChange={({ detail }) => setNewTestSetDescription(detail.value)}
              placeholder="Test set description"
              invalid={newTestSetDescription && !validateDescription(newTestSetDescription)}
            />
          </FormField>

          <FormField label="Test Set Zip File" description="Select a zip file containing your test set structure">
            <ExpandableSection
              headerText="View required file structure"
              variant="footer"
              expanded={showFileStructure}
              onChange={({ detail }) => {
                setShowFileStructure(detail.expanded);
                localStorage.setItem('testset-show-file-structure', detail.expanded.toString());
              }}
            >
              <Box margin={{ bottom: 's' }}>
                <pre
                  style={{
                    backgroundColor: '#f8f9fa',
                    padding: '12px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    overflow: 'auto',
                  }}
                >
                  {`my-test-set.zip
└── my-test-set/
    ├── input/
    │   ├── document1.pdf
    │   └── document2.pdf
    └── baseline/
        ├── document1.pdf/
        │   └── sections/
        │       ├── 1/
        │       │   └── result.json
        │       └── 2/
        │           └── result.json
        └── document2.pdf/
            └── sections/
                ├── 1/
                │   └── result.json
                └── 2/
                    └── result.json`}
                </pre>
              </Box>
              <Alert type="info">Each input file must have a corresponding baseline folder with the same name.</Alert>
            </ExpandableSection>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              onChange={async (e) => {
                const file = e.target.files[0];
                if (file) {
                  setZipFile(file);

                  // Check file size
                  if (file.size > MAX_ZIP_SIZE_BYTES) {
                    setError(`Zip file size (${(file.size / 1024 / 1024 / 1024).toFixed(2)} GB) exceeds maximum limit of 1 GB`);
                    setNewTestSetName('');
                    return;
                  }

                  // Extract test set name from zip filename (remove all extensions)
                  const fileName = file.name.replace(/\.[^.]*$/g, '').replace(/\.[^.]*$/g, '');

                  // Validate the filename
                  if (!validateTestSetName(fileName)) {
                    setError('Zip filename can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)');
                    setNewTestSetName('');
                    return;
                  }

                  // Check if test set already exists
                  try {
                    const validationResult = (await client.graphql({
                      query: VALIDATE_TEST_FILE_NAME,
                      variables: { fileName },
                    })) as GqlResult;

                    const validation = validationResult.data.validateTestFileName;
                    if (validation && validation.exists) {
                      setWarningMessage(`Test set ID "${validation.testSetId}" already exists and will be replaced.`);
                    } else {
                      setWarningMessage('');
                    }
                  } catch (err) {
                    console.error('Error validating test set name:', err);
                    const errorMessage = err?.message || err?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
                    setError(`Failed to validate test set name: ${errorMessage}`);
                    setNewTestSetName('');
                    return;
                  }

                  setNewTestSetName(fileName);
                  setError('');
                } else {
                  setZipFile(null);
                  setNewTestSetName('');
                  setWarningMessage('');
                }
              }}
              style={{ width: '100%', padding: '8px' }}
            />
            {zipFile && (
              <Box margin={{ top: 'xs' }}>
                <Badge color="blue">Test Set Name: {zipFile.name.replace(/\.[^.]*$/g, '').replace(/\.[^.]*$/g, '')}</Badge>
              </Box>
            )}
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showFilesModal}
        onDismiss={() => setShowFilesModal(false)}
        header={`Matching Files (${matchingFiles.length})`}
        footer={
          <Box float="right">
            <Button onClick={() => setShowFilesModal(false)}>Close</Button>
          </Box>
        }
      >
        <Box>
          {matchingFiles.length > 0 ? (
            <ul style={{ fontSize: '12px' }}>
              {matchingFiles.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          ) : (
            <Box textAlign="center">No matching files found</Box>
          )}
        </Box>
      </Modal>

      <Modal
        visible={showDeleteModal}
        onDismiss={() => setShowDeleteModal(false)}
        header="Confirm Delete"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowDeleteModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={loading}
                onClick={() => {
                  handleDeleteTestSets();
                  setShowDeleteModal(false);
                }}
              >
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box>
          <div>Are you sure you want to delete the following test set{selectedItems.length > 1 ? 's' : ''}?</div>
          <ul style={{ marginTop: '10px' }}>
            {selectedItems.map((item) => (
              <li key={item.id}>
                <strong>{item.name}</strong>
                {item.filePattern && ` (${item.filePattern})`}
              </li>
            ))}
          </ul>
        </Box>
      </Modal>
    </Container>
  );
};

export default TestSets;
