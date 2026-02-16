// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// src/components/upload-document/UploadDocumentPanel.jsx
import React, { useState, useEffect } from 'react';
import {
  Button,
  Container,
  Header,
  SpaceBetween,
  FormField,
  StatusIndicator,
  Alert,
  Input,
  FileUpload,
  Select,
} from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';

import uploadDocument from '../../graphql/queries/uploadDocument';

import useConfigurationVersions from '../../hooks/use-configuration-versions';

import useSettingsContext from '../../contexts/settings';

const client = generateClient();

interface UploadStatusItem {
  file: string;
  status: 'success' | 'error';
  objectKey?: string;
  error?: string;
}

const UploadDocumentPanel = (): React.JSX.Element => {
  const { settings } = useSettingsContext();
  const { versions, getVersionOptions } = useConfigurationVersions();
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<UploadStatusItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [prefix, setPrefix] = useState('');
  const [selectedVersion, setSelectedVersion] = useState<SelectProps.Option | null>(null);

  // Set default to active version when versions are loaded
  useEffect(() => {
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

  if (!(settings as Record<string, unknown>).InputBucket) {
    return (
      <Container header={<Header variant="h2">Upload Documents</Header>}>
        <Alert type="error">Input bucket not configured</Alert>
      </Container>
    );
  }

  const handleFileChange = (files: File[]): void => {
    setSelectedFiles(files);
    setUploadStatus([]);
    setError(null);
  };

  const handlePrefixChange = ({ detail }: { detail: { value: string } }): void => {
    setPrefix(detail.value);
  };

  const uploadFiles = async () => {
    if (selectedFiles.length === 0) {
      setError('Please select at least one file to upload');
      return;
    }

    setIsUploading(true);
    setUploadStatus([]);
    setError(null);

    const newUploadStatus: UploadStatusItem[] = [];

    try {
      // Use array reduce to process files sequentially
      await selectedFiles.reduce(async (previousPromise: Promise<void>, file: File) => {
        // Wait for the previous file to finish
        await previousPromise;

        try {
          // Step 1: Get presigned URL data
          console.log(`Getting upload credentials for ${file.name}...`);
          console.log(`Using prefix: ${prefix || 'none'}`);

          const response = await client.graphql({
            query: uploadDocument as unknown as string,
            variables: {
              fileName: file.name,
              contentType: file.type,
              prefix: prefix || '', // Use the user-provided prefix or empty string
              bucket: (settings as Record<string, unknown>).InputBucket as string, // Explicitly pass the input bucket
              version: selectedVersion?.value, // Pass selected version (optional)
            },
          });

          const { presignedUrl, objectKey, usePostMethod } = (response as { data: Record<string, unknown> }).data.uploadDocument as {
            presignedUrl: string;
            objectKey: string;
            usePostMethod: boolean;
          };

          if (!usePostMethod) {
            throw new Error('Server returned PUT method which is not supported. Please update your backend code.');
          }

          console.log('Received presigned POST data for:', objectKey);

          // Parse the presigned post data
          const presignedPostData = JSON.parse(presignedUrl);
          console.log('Parsed presigned POST data:', presignedPostData);

          // Step 2: Upload file using FormData and POST
          console.log(`Uploading ${file.name} to S3 using POST method...`);

          const formData = new FormData();

          // Add all the fields from the presigned POST data to the form
          Object.entries(presignedPostData.fields).forEach(([key, value]) => {
            formData.append(key, value as string);
          });

          // Append the file last
          formData.append('file', file);

          // Post the form to S3
          const uploadResponse = await fetch(presignedPostData.url, {
            method: 'POST',
            body: formData,
          });

          console.log(`Upload response status: ${uploadResponse.status}`);

          if (!uploadResponse.ok) {
            console.error(`Upload failed with status: ${uploadResponse.status}`);
            // Try to get more error details
            const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
            console.error(`Error details: ${errorText}`);
            throw new Error(`HTTP error! status: ${uploadResponse.status}`);
          }

          console.log(`Successfully uploaded ${file.name}`);
          newUploadStatus.push({
            file: file.name,
            status: 'success',
            objectKey,
          });
        } catch (err) {
          console.error(`Error uploading ${file.name}:`, err);
          newUploadStatus.push({
            file: file.name,
            status: 'error',
            error: err.message,
          });
        }

        // Update status after each file
        setUploadStatus([...newUploadStatus]);
      }, Promise.resolve() as Promise<void>);
    } catch (err) {
      console.error('Error in overall upload process:', err);
      setError(`Upload process failed: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Container header={<Header variant="h2">Upload Documents</Header>}>
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      <SpaceBetween size="l">
        <FormField label="Optional folder prefix (e.g., invoices/2024)">
          <Input value={prefix} onChange={handlePrefixChange} placeholder="Leave empty for root folder" disabled={isUploading} />
        </FormField>

        <FormField label="Configuration Version" description="Select which configuration version to use for processing these documents">
          <Select
            selectedOption={selectedVersion}
            onChange={({ detail }) => setSelectedVersion(detail.selectedOption)}
            options={getVersionOptions()}
            placeholder={versions.length === 0 ? 'Loading versions...' : 'Select configuration version'}
            disabled={isUploading || versions.length === 0}
            loadingText="Loading versions..."
          />
        </FormField>

        <FormField label="Select files to upload" constraintText="Supported formats: PDF, PNG, JPEG, TIFF. Multiple files allowed.">
          <FileUpload
            onChange={({ detail }) => handleFileChange(detail.value)}
            value={selectedFiles}
            i18nStrings={{
              uploadButtonText: (multiple: boolean) => (multiple ? 'Choose files' : 'Choose file'),
              dropzoneText: (multiple: boolean) => (multiple ? 'Drop files to upload' : 'Drop file to upload'),
              removeFileAriaLabel: (fileIndex: number) => `Remove file ${fileIndex + 1}`,
              errorIconAriaLabel: 'Error',
              warningIconAriaLabel: 'Warning',
            }}
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
            multiple
            showFileSize
            showFileLastModified
            {...({ showFileThumbnail: true, tokenLimit: 10, disabled: isUploading } as Record<string, unknown>)}
          />
        </FormField>

        <Button variant="primary" onClick={uploadFiles} loading={isUploading} disabled={selectedFiles.length === 0 || isUploading}>
          Upload {selectedFiles.length > 0 ? `(${selectedFiles.length} files)` : ''}
        </Button>

        {uploadStatus.length > 0 && (
          <div>
            <h3>Upload Results:</h3>
            <SpaceBetween size="s">
              {uploadStatus.map((item, index) => (
                // eslint-disable-next-line react/no-array-index-key
                <div key={index}>
                  <StatusIndicator type={item.status === 'success' ? 'success' : 'error'}>
                    {item.file}: {item.status === 'success' ? 'Uploaded successfully' : `Failed - ${item.error}`}
                    {item.status === 'success' && (
                      <div>
                        <small>Object Key: {item.objectKey}</small>
                      </div>
                    )}
                  </StatusIndicator>
                </div>
              ))}
            </SpaceBetween>
          </div>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default UploadDocumentPanel;
