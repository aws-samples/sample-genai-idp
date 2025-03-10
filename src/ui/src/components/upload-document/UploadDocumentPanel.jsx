// src/components/upload-document/UploadDocumentPanel.jsx
import React, { useState } from 'react';
import {
  Button,
  Container,
  Header,
  SpaceBetween,
  FormField,
  StatusIndicator,
  Alert,
  Input,
} from '@awsui/components-react';
import { API, graphqlOperation } from 'aws-amplify';
import uploadDocument from '../../graphql/queries/uploadDocument';
import useSettingsContext from '../../contexts/settings';

const UploadDocumentPanel = () => {
  const { settings } = useSettingsContext();
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState([]);
  const [error, setError] = useState(null);
  const [prefix, setPrefix] = useState('');

  if (!settings.InputBucket) {
    return (
      <Container header={<Header variant="h2">Upload Documents</Header>}>
        <Alert type="error">Input bucket not configured</Alert>
      </Container>
    );
  }

  const handleFileChange = (e) => {
    setSelectedFiles(Array.from(e.target.files));
    setUploadStatus([]);
    setError(null);
  };

  const handlePrefixChange = (e) => {
    setPrefix(e.detail.value);
  };

  const uploadFiles = async () => {
    if (selectedFiles.length === 0) {
      setError('Please select at least one file to upload');
      return;
    }

    setIsUploading(true);
    setUploadStatus([]);
    setError(null);

    const newUploadStatus = [];

    try {
      // Use array reduce to process files sequentially
      await selectedFiles.reduce(async (previousPromise, file) => {
        // Wait for the previous file to finish
        await previousPromise;

        try {
          // Step 1: Get presigned URL data
          console.log(`Getting upload credentials for ${file.name}...`);
          console.log(`Using prefix: ${prefix || 'none'}`);

          const response = await API.graphql(
            graphqlOperation(uploadDocument, {
              fileName: file.name,
              contentType: file.type,
              prefix: prefix || '', // Use the user-provided prefix or empty string
              bucket: settings.InputBucket, // Explicitly pass the input bucket
            }),
          );

          const { presignedUrl, objectKey, usePostMethod } = response.data.uploadDocument;

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
            formData.append(key, value);
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
      }, Promise.resolve());
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
          <Input
            value={prefix}
            onChange={handlePrefixChange}
            placeholder="Leave empty for root folder"
            disabled={isUploading}
          />
        </FormField>

        <FormField label="Select files to upload">
          <input type="file" multiple onChange={handleFileChange} disabled={isUploading} />
        </FormField>

        <Button
          variant="primary"
          onClick={uploadFiles}
          loading={isUploading}
          disabled={selectedFiles.length === 0 || isUploading}
        >
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
