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
  DatePicker,
  TimeInput,
} from '@cloudscape-design/components';
import { generateClient } from '../../api/client-shim';
import {
  addTestSet,
  addTestSetFromUpload,
  addDocumentsToTestSet,
  addDocumentsToTestSetFromUpload,
  deleteTestSets,
  getTestSets,
  listBucketFiles,
  validateTestFileName,
  updateTestSet,
} from '../../graphql/generated';
import type { DocumentClassType } from '../../graphql/generated/schema-types';
import { getErrorMessage } from '../../utils/errorUtils';
import useSyntheticDataGenerator from '../../hooks/use-synthetic-data-generator';
import GenerateSyntheticDataModal from './GenerateSyntheticDataModal';

const client = generateClient();

// Constants
const MAX_ZIP_SIZE_BYTES = 1073741824; // 1 GB

const BUCKET_OPTIONS: SelectProps.Option[] = [
  { label: 'Input Bucket', value: 'input' },
  { label: 'Test Set Bucket', value: 'testset' },
];

const TIME_FILTER_OPTIONS: SelectProps.Option[] = [
  { label: 'No filter', value: '' },
  { label: 'Last 1 hour', value: '1' },
  { label: 'Last 4 hours', value: '4' },
  { label: 'Last 24 hours', value: '24' },
  { label: 'Last 7 days', value: '168' },
  { label: 'Last 30 days', value: '720' },
  { label: 'Custom date/time', value: 'custom' },
];

const DOCUMENT_CLASS_TYPE_OPTIONS: SelectProps.Option[] = [
  { label: 'Unspecified', value: '' },
  { label: 'Single Class', value: 'SINGLE_CLASS' },
  { label: 'Multi Class', value: 'MULTI_CLASS' },
  { label: 'Packet Splitting', value: 'PACKET_SPLITTING' },
];

interface TestSetItem {
  id: string;
  name: string;
  description?: string | null;
  filePattern?: string | null;
  fileCount?: number | null;
  status?: string | null;
  createdAt: string;
  error?: string | null;
  lastAddResult?: string | null;
  documentClassType?: string | null;
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
  const [initialLoading, setInitialLoading] = useState(true);
  const [showBucketHelp, setShowBucketHelp] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  // The synthetic-data generator is an optional extension; the button is only
  // shown when it's installed (available).
  const { available: generatorAvailable } = useSyntheticDataGenerator();
  const [warningMessage, setWarningMessage] = useState('');
  const [confirmReplacement, setConfirmReplacement] = useState(false);
  const [showFileStructure, setShowFileStructure] = useState(() => {
    return localStorage.getItem('testset-show-file-structure') !== 'false';
  });
  const [showAddDocsPatternModal, setShowAddDocsPatternModal] = useState(false);
  const [showAddDocsUploadModal, setShowAddDocsUploadModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editDescription, setEditDescription] = useState('');
  const [editDocumentClassType, setEditDocumentClassType] = useState(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
  const [selectedTimeFilter, setSelectedTimeFilter] = useState(TIME_FILTER_OPTIONS[0]);
  const [customDate, setCustomDate] = useState('');
  const [customTime, setCustomTime] = useState('00:00:00');
  const [addDocsZipFile, setAddDocsZipFile] = useState<File | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const addDocsFileInputRef = React.useRef<HTMLInputElement | null>(null);
  const [selectedDocumentClassType, setSelectedDocumentClassType] = useState(DOCUMENT_CLASS_TYPE_OPTIONS[0]);

  const loadTestSets = async () => {
    try {
      console.log('TestSets: Loading test sets...');
      const result = await client.graphql({ query: getTestSets });
      console.log('TestSets: GraphQL result:', result);
      const backendTestSets = result.data.getTestSets || [];

      // Upsert: merge backend data with existing UI state, deduplicating by id
      setTestSets((prevTestSets) => {
        const nonNullBackendTestSets = backendTestSets.filter((ts): ts is NonNullable<typeof ts> => ts !== null);
        const backendIds = new Set(nonNullBackendTestSets.map((ts) => ts.id));

        // Keep UI test sets that don't exist in backend (active processing)
        const uiOnlyTestSets = prevTestSets.filter((ts) => !backendIds.has(ts.id) && ts.status !== 'COMPLETED' && ts.status !== 'FAILED');

        // Combine backend test sets (always win) with UI-only active test sets
        return [...nonNullBackendTestSets, ...uiOnlyTestSets];
      });
    } catch (err) {
      console.error('TestSets: Failed to load test sets:', err);
      setError(`Failed to load test sets: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setInitialLoading(false);
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

  const getModifiedAfterTimestamp = (): string | undefined => {
    const filterValue = selectedTimeFilter.value;
    if (!filterValue) return undefined;
    if (filterValue === 'custom') {
      if (!customDate) return undefined;
      return `${customDate}T${customTime || '00:00:00'}.000Z`;
    }
    const date = new Date(Date.now() - parseInt(filterValue) * 60 * 60 * 1000);
    return date.toISOString();
  };

  // Cleanup polling on unmount
  const handleCheckFiles = async () => {
    if (!filePattern.trim()) return;

    setLoading(true);
    try {
      const result = await client.graphql({
        query: listBucketFiles,
        variables: {
          bucketType: selectedBucket.value ?? '',
          filePattern: filePattern.trim(),
          modifiedAfter: getModifiedAfterTimestamp(),
        },
      });

      const files = (result.data.listBucketFiles || []).filter((f): f is string => f !== null);
      setMatchingFiles(files);
      setFileCount(files.length);
      setShowFilesModal(true);
    } catch (err) {
      const errorMessage = getErrorMessage(err);
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
    return desc.length <= 500;
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
      setError('Description cannot exceed 500 characters');
      return;
    }

    // 2. Backend validation using validateTestFileName
    try {
      const validationResult = await client.graphql({
        query: validateTestFileName,
        variables: { fileName: newTestSetName.trim() },
      });

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
      const errorMessage = getErrorMessage(err);
      setError(`Failed to validate test set name: ${errorMessage}`);
      return;
    }

    setLoading(true);
    try {
      const variables: {
        name: string;
        description: string;
        filePattern: string;
        bucketType: string;
        fileCount: number;
        modifiedAfter: string | undefined;
        documentClassType?: DocumentClassType;
      } = {
        name: newTestSetName.trim(),
        description: newTestSetDescription.trim(),
        filePattern: filePattern.trim(),
        bucketType: selectedBucket.value ?? '',
        fileCount,
        modifiedAfter: getModifiedAfterTimestamp(),
      };

      // Add documentClassType if specified (not "Unspecified")
      if (selectedDocumentClassType.value) {
        variables.documentClassType = selectedDocumentClassType.value as DocumentClassType;
      }

      const result = await client.graphql({
        query: addTestSet,
        variables,
      });

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
        setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
        setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
        setCustomDate('');
        setCustomTime('00:00:00');
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
      const errorMessage = getErrorMessage(err);
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
      setError('Description cannot exceed 500 characters');
      return;
    }

    try {
      const validationResult = await client.graphql({
        query: validateTestFileName,
        variables: { fileName: newTestSetName.trim() },
      });

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
      const errorMessage = getErrorMessage(err);
      setError(`Failed to validate test set name: ${errorMessage}`);
      return;
    }

    if (!zipFile) {
      setError('Zip file is required');
      return;
    }

    setLoading(true);
    try {
      const input: {
        fileName: string;
        fileSize: number;
        description: string;
        documentClassType?: DocumentClassType;
      } = {
        fileName: zipFile.name,
        fileSize: zipFile.size,
        description: newTestSetDescription.trim(),
      };

      // Add documentClassType if specified (not "Unspecified")
      if (selectedDocumentClassType.value) {
        input.documentClassType = selectedDocumentClassType.value as DocumentClassType;
      }

      const result = await client.graphql({
        query: addTestSetFromUpload,
        variables: { input },
      });

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

      const newTestSet: TestSetItem = {
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
      setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
      setZipFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err) {
      console.error('Error creating test set:', err);
      const errorMessage = getErrorMessage(err);
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
      const result = await client.graphql({ query: getTestSets });
      setTestSets((result.data.getTestSets || []).filter((ts): ts is NonNullable<typeof ts> => ts !== null));
    } catch (err) {
      console.error('Error refreshing test sets:', err);
      const errorMessage = getErrorMessage(err);
      setError(`Failed to refresh test sets: ${errorMessage}`);
    } finally {
      setRefreshing(false);
    }
  };

  const handleEditTestSet = async () => {
    const selected = selectedItems[0];
    if (!selected) {
      setError('No test set selected');
      return;
    }

    // Validate description
    if (editDescription && !validateDescription(editDescription.trim())) {
      setError('Description cannot exceed 500 characters');
      return;
    }

    setLoading(true);
    try {
      const input: {
        id: string;
        description?: string;
        documentClassType?: DocumentClassType | null;
      } = {
        id: selected.id,
        description: editDescription.trim(),
      };

      // Add documentClassType if specified (not "Unspecified")
      if (editDocumentClassType.value) {
        input.documentClassType = editDocumentClassType.value as DocumentClassType;
      } else {
        input.documentClassType = null;
      }

      const result = await client.graphql({
        query: updateTestSet,
        variables: { input },
      });

      const updatedTestSet = result.data.updateTestSet;

      if (updatedTestSet) {
        // Update the test set in the list
        setTestSets((prev) => prev.map((ts) => (ts.id === updatedTestSet.id ? updatedTestSet : ts)));
        setSuccessMessage(`Successfully updated test set "${updatedTestSet.name}"`);
        setError('');
        setShowEditModal(false);
        setSelectedItems([updatedTestSet]);
      } else {
        setError('Failed to update test set - no data returned');
      }
    } catch (err) {
      console.error('Error updating test set:', err);
      const errorMessage = getErrorMessage(err);
      setError(`Failed to update test set: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteTestSets = async () => {
    const testSetIds = selectedItems.map((item) => item.id);
    const deleteCount = testSetIds.length;

    setLoading(true);
    try {
      await client.graphql({
        query: deleteTestSets,
        variables: { testSetIds },
      });
      setTestSets(testSets.filter((testSet) => !testSetIds.includes(testSet.id)));
      setSelectedItems([]);
      setSuccessMessage(`Successfully deleted ${deleteCount} test set${deleteCount > 1 ? 's' : ''}`);
      setError('');
    } catch (err) {
      console.error('Error deleting test sets:', err);
      const errorMessage = getErrorMessage(err);
      setError(`Failed to delete test sets: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAddDocuments = async () => {
    if (!filePattern.trim()) {
      setError('File pattern is required');
      return;
    }

    const targetTestSet = selectedItems[0];
    if (!targetTestSet) return;

    setLoading(true);
    try {
      const result = await client.graphql({
        query: addDocumentsToTestSet,
        variables: {
          testSetId: targetTestSet.id,
          filePattern: filePattern.trim(),
          bucketType: selectedBucket.value ?? '',
          fileCount,
          modifiedAfter: getModifiedAfterTimestamp(),
        },
      });

      const updatedTestSet = result.data.addDocumentsToTestSet;

      if (updatedTestSet) {
        setTestSets((prev) => {
          const idx = prev.findIndex((ts) => ts.id === updatedTestSet.id);
          if (idx >= 0) {
            const updated = [...prev];
            updated[idx] = updatedTestSet;
            return updated;
          }
          return prev;
        });
        setFilePattern('');
        setSelectedBucket(BUCKET_OPTIONS[0]);
        setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
        setCustomDate('');
        setCustomTime('00:00:00');
        setFileCount(0);
        setShowAddDocsPatternModal(false);
        setError('');
        setSuccessMessage(`Adding documents to test set "${targetTestSet.name}"...`);
      } else {
        setError('Failed to add documents - no data returned');
      }
    } catch (err) {
      console.error('Error adding documents to test set:', err);
      const errorMessage = getErrorMessage(err);
      setError(`Failed to add documents: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAddDocumentsUpload = async () => {
    const targetTestSet = selectedItems[0];
    if (!targetTestSet) return;

    if (!addDocsZipFile) {
      setError('Zip file is required');
      return;
    }

    setLoading(true);
    try {
      const result = await client.graphql({
        query: addDocumentsToTestSetFromUpload,
        variables: {
          input: {
            testSetId: targetTestSet.id,
            fileName: addDocsZipFile.name,
            fileSize: addDocsZipFile.size,
          },
        },
      });

      const response = result.data.addDocumentsToTestSetFromUpload;

      if (!response || !response.presignedUrl) {
        throw new Error('Failed to get upload URL from server');
      }

      const presignedPostData = JSON.parse(response.presignedUrl);
      const formData = new FormData();

      Object.entries(presignedPostData.fields).forEach(([key, value]) => {
        formData.append(key, value as string);
      });
      formData.append('file', addDocsZipFile);

      const uploadResponse = await fetch(presignedPostData.url, {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        throw new Error(`Upload failed: ${uploadResponse.status} ${uploadResponse.statusText}`);
      }

      // Update the test set status in UI
      setTestSets((prev) => {
        const idx = prev.findIndex((ts) => ts.id === targetTestSet.id);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = { ...updated[idx], status: 'UPDATING' };
          return updated;
        }
        return prev;
      });

      setSuccessMessage(`Uploading documents to test set "${targetTestSet.name}". Zip file is being processed.`);
      setError('');
      setShowAddDocsUploadModal(false);
      setAddDocsZipFile(null);
      if (addDocsFileInputRef.current) {
        addDocsFileInputRef.current.value = '';
      }
    } catch (err) {
      console.error('Error adding documents from upload:', err);
      const errorMessage = getErrorMessage(err);
      setError(`Failed to add documents: ${errorMessage}`);
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
      cell: (item: TestSetItem) => item.name,
      sortingField: 'name',
    },
    {
      id: 'id',
      header: 'Test Set ID',
      cell: (item: TestSetItem) => item.id,
      sortingField: 'id',
    },
    {
      id: 'description',
      header: 'Description',
      cell: (item: TestSetItem) => item.description || '-',
      width: 200,
      minWidth: 120,
    },
    {
      id: 'filePattern',
      header: 'File Pattern',
      cell: (item: TestSetItem) => item.filePattern,
    },
    {
      id: 'fileCount',
      header: 'Files',
      cell: (item: TestSetItem) => item.fileCount,
    },
    {
      id: 'documentClassType',
      header: 'Classification Type',
      cell: (item: TestSetItem) => {
        if (!item.documentClassType) {
          return '-';
        }
        const badges: Record<string, React.JSX.Element> = {
          SINGLE_CLASS: <Badge color="blue">Single Class</Badge>,
          MULTI_CLASS: <Badge color="green">Multi Class</Badge>,
          PACKET_SPLITTING: <Badge>Packet Splitting</Badge>,
        };
        return badges[item.documentClassType] || item.documentClassType;
      },
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: TestSetItem) => {
        const status = item.status || '-';

        if (status === 'UPDATING') {
          return <Badge color="blue">Updating...</Badge>;
        }

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
      cell: (item: TestSetItem) => new Date(item.createdAt).toLocaleDateString(),
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
              <Button
                iconName="edit"
                disabled={selectedItems.length !== 1 || loading}
                onClick={() => {
                  const selected = selectedItems[0];
                  if (selected) {
                    setEditDescription(selected.description || '');
                    const classTypeOption =
                      DOCUMENT_CLASS_TYPE_OPTIONS.find((opt) => opt.value === selected.documentClassType) || DOCUMENT_CLASS_TYPE_OPTIONS[0];
                    setEditDocumentClassType(classTypeOption);
                    setShowEditModal(true);
                  }
                }}
              >
                Edit
              </Button>
              <Button iconName="remove" disabled={selectedItems.length === 0 || loading} onClick={() => setShowDeleteModal(true)} />
              <ButtonDropdown
                items={[
                  { id: 'docs-pattern', text: 'From Existing Files' },
                  { id: 'docs-upload', text: 'From Upload' },
                ]}
                disabled={selectedItems.length !== 1 || selectedItems[0]?.status !== 'COMPLETED' || loading}
                onItemClick={({ detail }) => {
                  if (detail.id === 'docs-pattern') {
                    setFilePattern(selectedItems[0]?.filePattern || '');
                    setSelectedBucket(BUCKET_OPTIONS[0]);
                    setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
                    setCustomDate('');
                    setCustomTime('00:00:00');
                    setFileCount(0);
                    setError('');
                    setShowAddDocsPatternModal(true);
                  } else if (detail.id === 'docs-upload') {
                    setAddDocsZipFile(null);
                    setError('');
                    setShowAddDocsUploadModal(true);
                  }
                }}
              >
                Add Documents
              </ButtonDropdown>
              {generatorAvailable && (
                <Button iconName="gen-ai" disabled={loading} onClick={() => setShowGenerateModal(true)}>
                  Generate Synthetic Data
                </Button>
              )}
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

      {testSets
        .filter((ts) => ts.lastAddResult && ts.status === 'COMPLETED')
        .map((ts) => (
          <Alert
            key={ts.id}
            type="info"
            dismissible
            onDismiss={() => {
              setTestSets((prev) => prev.map((t) => (t.id === ts.id ? { ...t, lastAddResult: null } : t)));
            }}
          >
            <strong>{ts.name}:</strong> {ts.lastAddResult}
          </Alert>
        ))}

      <Table
        resizableColumns
        wrapLines
        columnDefinitions={columnDefinitions}
        items={filteredTestSets}
        selectedItems={selectedItems}
        onSelectionChange={({ detail }) => setSelectedItems(detail.selectedItems)}
        selectionType="multi"
        loading={initialLoading}
        loadingText="Loading test sets..."
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
          setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
          setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
          setCustomDate('');
          setCustomTime('00:00:00');
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
                  setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
                  setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
                  setCustomDate('');
                  setCustomTime('00:00:00');
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
              invalid={!!newTestSetName && !validateTestSetName(newTestSetName)}
            />
          </FormField>

          <FormField
            label="Description"
            description="Optional description for this test set"
            errorText={
              newTestSetDescription && !validateDescription(newTestSetDescription) ? 'Description cannot exceed 500 characters' : ''
            }
          >
            <Input
              value={newTestSetDescription}
              onChange={({ detail }) => setNewTestSetDescription(detail.value)}
              placeholder="Test set description"
              invalid={!!newTestSetDescription && !validateDescription(newTestSetDescription)}
            />
          </FormField>

          <FormField label="Document Classification Type" description="Optional: Specify the type of documents in this test set">
            <Select
              selectedOption={selectedDocumentClassType}
              onChange={({ detail }) => setSelectedDocumentClassType(detail.selectedOption)}
              options={DOCUMENT_CLASS_TYPE_OPTIONS}
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

          {selectedBucket.value === 'input' && (
            <FormField label="Modified after" description="Optional: only include files modified within this time period">
              <SpaceBetween size="xs">
                <Select
                  selectedOption={selectedTimeFilter}
                  onChange={({ detail }) => {
                    setSelectedTimeFilter(detail.selectedOption);
                    setFileCount(0);
                  }}
                  options={TIME_FILTER_OPTIONS}
                />
                {selectedTimeFilter.value === 'custom' && (
                  <SpaceBetween size="xs" direction="horizontal">
                    <DatePicker
                      value={customDate}
                      onChange={({ detail }) => {
                        setCustomDate(detail.value);
                        setFileCount(0);
                      }}
                      placeholder="YYYY/MM/DD"
                      openCalendarAriaLabel={(selectedDate) => `Choose date${selectedDate ? `, selected date is ${selectedDate}` : ''}`}
                    />
                    <TimeInput
                      value={customTime}
                      onChange={({ detail }) => {
                        setCustomTime(detail.value);
                        setFileCount(0);
                      }}
                      format="hh:mm:ss"
                      placeholder="HH:mm:ss"
                    />
                    <Box variant="small" padding={{ top: 'xs' }}>
                      UTC
                    </Box>
                  </SpaceBetween>
                )}
              </SpaceBetween>
            </FormField>
          )}

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
          setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
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
                  setSelectedDocumentClassType(DOCUMENT_CLASS_TYPE_OPTIONS[0]);
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
              newTestSetDescription && !validateDescription(newTestSetDescription) ? 'Description cannot exceed 500 characters' : ''
            }
          >
            <Input
              value={newTestSetDescription}
              onChange={({ detail }) => setNewTestSetDescription(detail.value)}
              placeholder="Test set description"
              invalid={!!newTestSetDescription && !validateDescription(newTestSetDescription)}
            />
          </FormField>

          <FormField label="Document Classification Type" description="Optional: Specify the type of documents in this test set">
            <Select
              selectedOption={selectedDocumentClassType}
              onChange={({ detail }) => setSelectedDocumentClassType(detail.selectedOption)}
              options={DOCUMENT_CLASS_TYPE_OPTIONS}
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
                const file = e.target.files?.[0];
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
                    const validationResult = await client.graphql({
                      query: validateTestFileName,
                      variables: { fileName },
                    });

                    const validation = validationResult.data.validateTestFileName;
                    if (validation && validation.exists) {
                      setWarningMessage(`Test set ID "${validation.testSetId}" already exists and will be replaced.`);
                    } else {
                      setWarningMessage('');
                    }
                  } catch (err) {
                    console.error('Error validating test set name:', err);
                    const errorMessage = getErrorMessage(err);
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
        visible={showAddDocsPatternModal}
        onDismiss={() => {
          setShowAddDocsPatternModal(false);
          setSelectedBucket(BUCKET_OPTIONS[0]);
          setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
          setCustomDate('');
          setCustomTime('00:00:00');
          setFileCount(0);
          setFilePattern('');
          setError('');
        }}
        header={`Add Documents to "${selectedItems[0]?.name ?? ''}"`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowAddDocsPatternModal(false);
                  setSelectedBucket(BUCKET_OPTIONS[0]);
                  setSelectedTimeFilter(TIME_FILTER_OPTIONS[0]);
                  setCustomDate('');
                  setCustomTime('00:00:00');
                  setFileCount(0);
                  setFilePattern('');
                  setError('');
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={loading} onClick={handleAddDocuments} disabled={fileCount === 0}>
                Add Documents
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}

          <FormField label="Source Bucket" description="Select the bucket to search for files">
            <Select
              selectedOption={selectedBucket}
              onChange={({ detail }) => {
                setSelectedBucket(detail.selectedOption);
                setFileCount(0);
              }}
              options={BUCKET_OPTIONS}
            />
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

          {selectedBucket.value === 'input' && (
            <FormField label="Modified after" description="Optional: only include files modified within this time period">
              <SpaceBetween size="xs">
                <Select
                  selectedOption={selectedTimeFilter}
                  onChange={({ detail }) => {
                    setSelectedTimeFilter(detail.selectedOption);
                    setFileCount(0);
                  }}
                  options={TIME_FILTER_OPTIONS}
                />
                {selectedTimeFilter.value === 'custom' && (
                  <SpaceBetween size="xs" direction="horizontal">
                    <DatePicker
                      value={customDate}
                      onChange={({ detail }) => {
                        setCustomDate(detail.value);
                        setFileCount(0);
                      }}
                      placeholder="YYYY/MM/DD"
                      openCalendarAriaLabel={(selectedDate) => `Choose date${selectedDate ? `, selected date is ${selectedDate}` : ''}`}
                    />
                    <TimeInput
                      value={customTime}
                      onChange={({ detail }) => {
                        setCustomTime(detail.value);
                        setFileCount(0);
                      }}
                      format="hh:mm:ss"
                      placeholder="HH:mm:ss"
                    />
                    <Box variant="small" padding={{ top: 'xs' }}>
                      UTC
                    </Box>
                  </SpaceBetween>
                )}
              </SpaceBetween>
            </FormField>
          )}

          {fileCount > 0 && (
            <Box>
              <Badge color="green">
                {fileCount} {fileCount === 1 ? 'file' : 'files'} found
              </Badge>
            </Box>
          )}

          {selectedBucket.value === 'input' && (
            <Alert type="info">Files without matching baseline data in the evaluation bucket will be automatically excluded.</Alert>
          )}
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showAddDocsUploadModal}
        onDismiss={() => {
          setShowAddDocsUploadModal(false);
          setAddDocsZipFile(null);
          setError('');
          if (addDocsFileInputRef.current) {
            addDocsFileInputRef.current.value = '';
          }
        }}
        header={`Add Documents to "${selectedItems[0]?.name ?? ''}" from Upload`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowAddDocsUploadModal(false);
                  setAddDocsZipFile(null);
                  setError('');
                  if (addDocsFileInputRef.current) {
                    addDocsFileInputRef.current.value = '';
                  }
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={loading} onClick={handleAddDocumentsUpload} disabled={!addDocsZipFile}>
                Upload and Add Documents
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}

          <FormField label="Zip File" description="Select a zip file containing documents and baseline data to add">
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
                  {`documents.zip
└── documents/
    ├── input/
    │   ├── document1.pdf
    │   └── document2.pdf
    └── baseline/
        ├── document1.pdf/
        │   └── sections/
        │       └── 1/
        │           └── result.json
        └── document2.pdf/
            └── sections/
                └── 1/
                    └── result.json`}
                </pre>
              </Box>
              <Alert type="info">Each input file must have a corresponding baseline folder with the same name.</Alert>
            </ExpandableSection>
            <input
              ref={addDocsFileInputRef}
              type="file"
              accept=".zip"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  if (file.size > MAX_ZIP_SIZE_BYTES) {
                    setError(`Zip file size (${(file.size / 1024 / 1024 / 1024).toFixed(2)} GB) exceeds maximum limit of 1 GB`);
                    setAddDocsZipFile(null);
                    return;
                  }
                  setAddDocsZipFile(file);
                  setError('');
                } else {
                  setAddDocsZipFile(null);
                }
              }}
              style={{ width: '100%', padding: '8px' }}
            />
            {addDocsZipFile && (
              <Box margin={{ top: 'xs' }}>
                <Badge color="blue">
                  {addDocsZipFile.name} ({(addDocsZipFile.size / 1024 / 1024).toFixed(1)} MB)
                </Badge>
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
        visible={showEditModal}
        onDismiss={() => {
          setShowEditModal(false);
          setError('');
        }}
        header="Edit Test Set"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowEditModal(false);
                  setError('');
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={loading} onClick={handleEditTestSet}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}

          <FormField label="Test Set Name">
            <Input value={selectedItems[0]?.name || ''} disabled />
          </FormField>

          <FormField
            label="Description"
            description="Optional description for this test set"
            errorText={editDescription && !validateDescription(editDescription) ? 'Description cannot exceed 500 characters' : ''}
          >
            <Input
              value={editDescription}
              onChange={({ detail }) => setEditDescription(detail.value)}
              placeholder="Test set description"
              invalid={!!editDescription && !validateDescription(editDescription)}
            />
          </FormField>

          <FormField label="Document Classification Type" description="Specify the type of documents in this test set">
            <Select
              selectedOption={editDocumentClassType}
              onChange={({ detail }) => setEditDocumentClassType(detail.selectedOption)}
              options={DOCUMENT_CLASS_TYPE_OPTIONS}
            />
          </FormField>
        </SpaceBetween>
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

      <GenerateSyntheticDataModal
        visible={showGenerateModal}
        onDismiss={() => setShowGenerateModal(false)}
        onStarted={(jobId) => {
          setShowGenerateModal(false);
          setSuccessMessage(
            `Synthetic data generation started (job ${jobId}). The test set will appear here when it completes; use Refresh to check.`,
          );
        }}
      />
    </Container>
  );
};

export default TestSets;
