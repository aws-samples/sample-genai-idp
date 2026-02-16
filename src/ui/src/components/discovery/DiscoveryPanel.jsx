// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable prettier/prettier */
/* eslint-disable react/no-array-index-key */

// src/components/discovery/DiscoveryPanel.jsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Container,
  Header,
  SpaceBetween,
  FormField,
  StatusIndicator,
  Alert,
  Input,
  Table,
  Box,
  TextContent,
  ColumnLayout,
  Select,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';

import uploadDiscoveryDocument from '../../graphql/queries/uploadDiscoveryDocument';
import listDiscoveryJobs from '../../graphql/queries/listDiscoveryJobs';
import onDiscoveryJobStatusChange from '../../graphql/subscriptions/onDiscoveryJobStatusChange';
import useSettingsContext from '../../contexts/settings';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { getJsonValidationError } from '../common/utilities';

const client = generateClient();

const DiscoveryPanel = () => {
  const { settings } = useSettingsContext();
  const { versions, loading: versionsLoading, getVersionOptions } = useConfigurationVersions();
  const [documentFile, setDocumentFile] = useState(null);
  const [groundTruthFile, setGroundTruthFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState([]);
  const [error, setError] = useState(null);
  const [prefix, setPrefix] = useState('');
  const [discoveryJobs, setDiscoveryJobs] = useState([]);
  const [isLoadingJobs, setIsLoadingJobs] = useState(false);
  const [isValidatingJson, setIsValidatingJson] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState(null);
  // Remove unused activeSubscriptions state since we manage subscriptions locally in useEffect

  // Set default active version when versions load
  useEffect(() => {
    if (versions.length > 0 && !selectedVersion) {
      const activeVersion = versions.find((version) => version.isActive);
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

  // Debounced status update to prevent rapid DOM changes
  const debouncedSetUploadStatus = useCallback((statusArray) => {
    setTimeout(() => {
      setUploadStatus([...statusArray]);
    }, 50);
  }, []);

  const loadDiscoveryJobs = async () => {
    setIsLoadingJobs(true);
    try {
      const response = await client.graphql({ query: listDiscoveryJobs });
      // Access the DiscoveryJobs array from the response
      console.log('loadDiscoveryJobs done');
      console.log(response);
      setDiscoveryJobs(response.data.listDiscoveryJobs?.DiscoveryJobs || []);
    } catch (err) {
      console.error(err);
      console.error('Error loading discovery jobs:', err);
      setError(`Failed to load discovery jobs: ${err.message}`);
    } finally {
      setIsLoadingJobs(false);
    }
  };

  // Suppress ResizeObserver errors
  useEffect(() => {
    const originalError = console.error;
    const originalWindowError = window.onerror;

    // Suppress console errors
    console.error = (...args) => {
      if (args[0]?.includes?.('ResizeObserver loop completed with undelivered notifications')) {
        return;
      }
      originalError.apply(console, args);
    };

    // Suppress window errors
    window.onerror = (message, source, lineno, colno, errorObj) => {
      if (message?.includes?.('ResizeObserver loop completed with undelivered notifications')) {
        return true; // Prevent default error handling
      }
      if (originalWindowError) {
        return originalWindowError(message, source, lineno, colno, errorObj);
      }
      return false;
    };

    // Also handle unhandled promise rejections
    const handleUnhandledRejection = (event) => {
      if (event.reason?.message?.includes?.('ResizeObserver loop completed with undelivered notifications')) {
        event.preventDefault();
      }
    };

    window.addEventListener('unhandledrejection', handleUnhandledRejection);

    return () => {
      console.error = originalError;
      window.onerror = originalWindowError;
      window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    };
  }, []);

  // Load discovery jobs on component mount
  useEffect(() => {
    loadDiscoveryJobs();
  }, []);

  // Set up a subscription for new discovery jobs (if such a subscription exists)
  // This would be similar to how documents subscribe to onCreateDocument
  // For now, we'll rely on the upload process to refresh the list

  // Update a specific job in the list
  const updateDiscoveryJob = useCallback((updatedJob) => {
    console.log('Updating discovery job status:', updatedJob);
    setDiscoveryJobs((currentJobs) => {
      const jobIndex = currentJobs.findIndex((job) => job.jobId === updatedJob.jobId);
      if (jobIndex >= 0) {
        const newJobs = [...currentJobs];
        const oldJob = newJobs[jobIndex];
        newJobs[jobIndex] = { ...oldJob, status: updatedJob.status };
        console.log(`Updated job ${updatedJob.jobId}: ${oldJob.status} -> ${updatedJob.status}`);
        return newJobs;
      }
      console.warn(`Job ${updatedJob.jobId} not found in current jobs list, adding it`);
      return [...currentJobs, updatedJob];
    });
  }, []);

  // Set up global subscription for all discovery job updates (similar to document updates)
  useEffect(() => {
    console.log('Setting up global discovery job subscription');

    // Note: This is a simplified approach. In a production system, you might want to
    // subscribe to all jobs or use a different pattern, but for now we'll subscribe
    // to individual jobs as they're created.

    // We'll set up subscriptions for active jobs, but with better lifecycle management
    const subscriptions = new Map();

    discoveryJobs.forEach((job) => {
      if (job.status === 'PENDING' || job.status === 'IN_PROGRESS') {
        console.log(`Setting up subscription for discovery job: ${job.jobId}`);

        const subscription = client
          .graphql({ query: onDiscoveryJobStatusChange, variables: { jobId: job.jobId } })
          .subscribe({
            next: (data) => {
              console.log('Discovery job status changed:', data);
              const updatedJob = data?.data?.onDiscoveryJobStatusChange;
              if (updatedJob) {
                // Directly update the specific job instead of refreshing entire list
                updateDiscoveryJob(updatedJob);
                return;
              }
              console.warn('Received subscription update but no job data, falling back to refresh');
              loadDiscoveryJobs();
            },
            error: (subscriptionError) => {
              console.error('Discovery job subscription error:', subscriptionError);
            },
          });

        subscriptions.set(job.jobId, subscription);
      }
    });

    // Subscriptions are managed locally in this effect

    // Cleanup function
    return () => {
      console.log('Cleaning up discovery job subscriptions');
      subscriptions.forEach((subscription) => {
        subscription.unsubscribe();
      });
    };
  }, [JSON.stringify(discoveryJobs.map((job) => ({ jobId: job.jobId, status: job.status }))), updateDiscoveryJob]);

  if (!settings.DiscoveryBucket) {
    return (
      <Container header={<Header variant="h2">Discovery</Header>}>
        <Alert type="error">Discovery bucket not configured</Alert>
      </Container>
    );
  }

  const handleDocumentFileChange = (e) => {
    const file = e.target.files[0];
    setDocumentFile(file);
    setUploadStatus([]);
    setError(null);
  };

  const handleGroundTruthFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) {
      setGroundTruthFile(null);
      setUploadStatus([]);
      setError(null);
      setIsValidatingJson(false);
      return;
    }

    if (!file.name.toLowerCase().endsWith('.json')) {
      setError('Ground truth file must be a JSON file');
      setIsValidatingJson(false);
      return;
    }

    // Start validation
    setIsValidatingJson(true);
    setError(null);

    // Validate JSON content
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const content = event.target.result;

        // Check if file is empty
        if (!content || content.trim().length === 0) {
          setError('Ground truth file is empty. Please select a valid JSON file.');
          setGroundTruthFile(null);
          setIsValidatingJson(false);
          e.target.value = '';
          return;
        }

        JSON.parse(content); // This will throw if invalid JSON

        // JSON is valid, set the file
        setGroundTruthFile(file);
        setUploadStatus([]);
        setError(null);
        setIsValidatingJson(false);
      } catch (jsonError) {
        const friendlyError = getJsonValidationError(jsonError);
        setError(`Invalid JSON format in ground truth file: ${friendlyError}`);
        setGroundTruthFile(null);
        setIsValidatingJson(false);
        // Clear the file input
        e.target.value = '';
      }
    };

    reader.onerror = () => {
      setError('Failed to read ground truth file');
      setGroundTruthFile(null);
      setIsValidatingJson(false);
      e.target.value = '';
    };

    reader.readAsText(file);
  };

  const handlePrefixChange = (e) => {
    setPrefix(e.detail.value);
  };

  const uploadFileToS3 = async (file, presignedUrl, objectKey, fileType, statusArray) => {
    try {
      const presignedPostData = JSON.parse(presignedUrl);
      console.log(`Parsed presigned POST data for ${fileType}:`, presignedPostData);

      const formData = new FormData();

      // Add all the fields from the presigned POST data to the form
      Object.entries(presignedPostData.fields).forEach(([key, value]) => {
        formData.append(key, value);
      });

      // Append the file last
      formData.append('file', file);

      // Post the form to S3
      const uploadResponse = await fetch(presignedPostData.url, {
        method: 'POST',
        body: formData,
      });

      console.log(`Upload response status for ${fileType}: ${uploadResponse.status}`);

      if (!uploadResponse.ok) {
        console.error(`Upload failed with status: ${uploadResponse.status}`);
        const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
        console.error(`Error details: ${errorText}`);
        throw new Error(`HTTP error! status: ${uploadResponse.status}`);
      }

      console.log(`Successfully uploaded ${fileType}: ${file.name}`);
      statusArray.push({
        file: file.name,
        type: fileType,
        status: 'success',
        objectKey,
      });
    } catch (err) {
      console.error(`Error uploading ${fileType} ${file.name}:`, err);
      statusArray.push({
        file: file.name,
        type: fileType,
        status: 'error',
        error: err.message,
      });
    }

    // Update status after each file with debounced update
    debouncedSetUploadStatus(statusArray);
  };

  const uploadFiles = async () => {
    if (!documentFile) {
      setError('Please select a document file to upload');
      return;
    }

    setIsUploading(true);
    setUploadStatus([]);
    setError(null);

    const newUploadStatus = [];

    try {
      // Upload document file
      console.log(`Getting upload credentials for document: ${documentFile.name}, ${documentFile.type}....`);
      console.log(`Uploading to discovery bucket: ${settings.DiscoveryBucket}...`);
      let groundTruthFileName = null;
      if (groundTruthFile) {
        groundTruthFileName = groundTruthFile.name;
      }

      const documentResponse = await client.graphql({
        query: uploadDiscoveryDocument,
        variables: {
          fileName: documentFile.name,
          contentType: documentFile.type,
          prefix: prefix || '',
          bucket: settings.DiscoveryBucket,
          groundTruthFileName: groundTruthFileName || '',
          version: selectedVersion?.value,
        },
      });

      const {
        presignedUrl: docPresignedUrl,
        objectKey: docObjectKey,
        usePostMethod: docUsePostMethod,
        groundTruthObjectKey: docGroundTruthObjectKey,
        groundTruthPresignedUrl: docGroundTruthPresignedUrl,
      } = documentResponse.data.uploadDiscoveryDocument;

      if (!docUsePostMethod) {
        throw new Error('Server returned PUT method which is not supported. Please update your backend code.');
      }
      // Upload document file to S3
      console.log(`Uploading document ${documentFile.name} to S3...`);
      await uploadFileToS3(documentFile, docPresignedUrl, docObjectKey, 'document', newUploadStatus);

      if (groundTruthFile) {
        // Upload ground truth file
        console.log(`Getting upload credentials for ground truth: ${groundTruthFile.name}...`);

        // Upload ground truth file to S3
        console.log(`Uploading ground truth ${groundTruthFile.name} to S3...`);
        await uploadFileToS3(
          groundTruthFile,
          docGroundTruthPresignedUrl,
          docGroundTruthObjectKey,
          'ground truth',
          newUploadStatus,
        );
      }
      // Refresh discovery jobs list
      await loadDiscoveryJobs();
    } catch (err) {
      console.error('Error in overall upload process:', err);
      setError(`Upload process failed: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };
  /*
  const formatTimestamp = (timestamp) => {
      console.log( 'Timestamp is: ');
      return timestamp;
  };
 */

  const getStatusIcon = (status) => {
    switch (status) {
      case 'COMPLETED':
        return <StatusIndicator type="success">Completed</StatusIndicator>;
      case 'FAILED':
        return <StatusIndicator type="error">Failed</StatusIndicator>;
      case 'IN_PROGRESS':
        return <StatusIndicator type="in-progress">In Progress</StatusIndicator>;
      case 'PENDING':
        return <StatusIndicator type="pending">Pending</StatusIndicator>;
      default:
        return <StatusIndicator type="info">{status}</StatusIndicator>;
    }
  };

  const discoveryJobsColumns = [
    {
      id: 'jobId',
      header: 'Job ID',
      cell: (item) => item.jobId || 'N/A',
      sortingField: 'jobId',
    },
    {
      id: 'documentKey',
      header: 'Document',
      cell: (item) => (item.documentKey ? item.documentKey.split('/').pop() : 'N/A'),
      sortingField: 'documentKey',
    },
    {
      id: 'groundTruthKey',
      header: 'Ground Truth',
      cell: (item) => (item.groundTruthKey ? item.groundTruthKey.split('/').pop() : 'N/A'),
      sortingField: 'groundTruthKey',
    },
    {
      id: 'version',
      header: 'Version',
      cell: (item) => item.version || 'N/A',
      sortingField: 'version',
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item) => getStatusIcon(item.status),
      sortingField: 'status',
    },
    {
      id: 'createdAt',
      header: 'Created At',
      cell: (item) => item.createdAt || 'N/A',
      sortingField: 'createdAt',
    },
    {
      id: 'updatedAt',
      header: 'Updated At',
      cell: (item) => item.updatedAt || 'N/A',
      sortingField: 'updatedAt',
    },
  ];

  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Discovery</Header>}>
        <Alert type="warning" header="Important Notice">
          Use this feature in non-production environments to discover documents and images. Fine-tune and test the
          generated custom class configuration before exporting it to production.
        </Alert>

        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <SpaceBetween size="l">
          <TextContent>
            <p>
              Upload a document and its corresponding ground truth data (JSON format) to start a discovery analysis. The
              system will process both files and compare the extracted data against the ground truth.
            </p>
          </TextContent>

          <FormField
            label="Configuration Version"
            description="Select which configuration version to save the discovered document schema to"
          >
            <Select
              selectedOption={selectedVersion}
              onChange={({ detail }) => setSelectedVersion(detail.selectedOption)}
              options={getVersionOptions()}
              placeholder={versions.length === 0 ? 'Loading versions...' : 'Select configuration version'}
              disabled={isUploading || versionsLoading || versions.length === 0}
              loadingText="Loading versions..."
            />
          </FormField>

          <ColumnLayout columns={2}>
            <FormField label="Document File" description="Select the document to analyze">
              <input
                type="file"
                onChange={handleDocumentFileChange}
                disabled={isUploading}
                accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
              />
              {documentFile && (
                <Box margin={{ top: 'xs' }}>
                  <StatusIndicator type="success">Selected: {documentFile.name}</StatusIndicator>
                </Box>
              )}
            </FormField>

            <FormField label="Ground Truth File" description="Select the JSON file with expected results">
              <input
                type="file"
                onChange={handleGroundTruthFileChange}
                disabled={isUploading || isValidatingJson}
                accept=".json"
              />
              {isValidatingJson && (
                <Box margin={{ top: 'xs' }}>
                  <StatusIndicator type="in-progress">Validating JSON format...</StatusIndicator>
                </Box>
              )}
              {groundTruthFile && !isValidatingJson && (
                <Box margin={{ top: 'xs' }}>
                  <StatusIndicator type="success">Selected: {groundTruthFile.name} (Valid JSON)</StatusIndicator>
                </Box>
              )}
            </FormField>
          </ColumnLayout>

          <FormField label="Optional folder prefix (e.g., experiments/batch1)">
            <Input
              value={prefix}
              onChange={handlePrefixChange}
              placeholder="Leave empty for root folder"
              disabled={isUploading}
            />
          </FormField>

          <Button
            variant="primary"
            onClick={uploadFiles}
            loading={isUploading}
            disabled={!documentFile || !selectedVersion || isUploading || isValidatingJson}
          >
            Start Discovery
          </Button>

          {uploadStatus.length > 0 && (
            <Container header={<Header variant="h3">Upload Results</Header>}>
              <SpaceBetween size="s">
                {uploadStatus.map((item, index) => (
                  <div key={`upload-status-${item.file}-${index}`}>
                    <StatusIndicator type={item.status === 'success' ? 'success' : 'error'}>
                      {item.type}: {item.file}{' '}
                      {item.status === 'success' ? 'Uploaded successfully' : `Failed - ${item.error}`}
                      {item.status === 'success' && (
                        <div>
                          <small>Object Key: {item.objectKey}</small>
                        </div>
                      )}
                    </StatusIndicator>
                  </div>
                ))}
              </SpaceBetween>
            </Container>
          )}
        </SpaceBetween>
      </Container>

      <Container header={<Header variant="h2">Discovery Jobs</Header>}>
        <Table
          columnDefinitions={discoveryJobsColumns}
          items={discoveryJobs}
          loading={isLoadingJobs}
          loadingText="Loading discovery jobs..."
          empty={
            <Box textAlign="center" color="inherit">
              <b>No discovery jobs found</b>
              <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                Upload documents to start discovery analysis.
              </Box>
            </Box>
          }
          header={
            <Header
              counter={`(${discoveryJobs.length})`}
              actions={
                <Button iconName="refresh" onClick={loadDiscoveryJobs} loading={isLoadingJobs}>
                  Refresh
                </Button>
              }
            >
              Discovery Jobs
            </Header>
          }
        />
      </Container>
    </SpaceBetween>
  );
};

export default DiscoveryPanel;
