// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useMemo, Suspense, useEffect } from 'react';
import { Box, Button, Spinner } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import getFileContents from '../../graphql/queries/getFileContents';
import uploadDocument from '../../graphql/queries/uploadDocument';

// Lazy load VisualEditorModal for better performance
const VisualEditorModal = React.lazy(
  () => import('./VisualEditorModal') as unknown as Promise<{ default: React.ComponentType<Record<string, unknown>> }>,
);

interface JSONViewerProps {
  fileUri: string;
  fileType?: string;
  buttonText?: string;
  sectionData?: Record<string, unknown>;
  onOpen?: () => void;
  onClose?: () => void;
  disabled?: boolean;
  isReadOnly?: boolean;
  allSections?: Record<string, unknown>[];
  currentSectionIndex?: number;
  onNavigateToSection?: (index: number) => void;
  isExternallyOpen?: boolean;
}

const client = generateClient();
const logger = new ConsoleLogger('JSONViewer');

const JSONViewer = ({
  fileUri,
  fileType: _fileType = 'text',
  buttonText = 'View/Edit Data',
  sectionData,
  onOpen,
  onClose,
  disabled,
  isReadOnly = false,
  // Section navigation props
  allSections = [],
  currentSectionIndex = 0,
  onNavigateToSection,
  // External control props for navigation
  isExternallyOpen = false,
}: JSONViewerProps): React.JSX.Element => {
  const [jsonData, setJsonData] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showVisualEditor, setShowVisualEditor] = useState<boolean>(false);
  const [_originalContent, setOriginalContent] = useState<string | null>(null);

  // Handle external open request (for section navigation)
  useEffect(() => {
    if (isExternallyOpen && !showVisualEditor && !isLoading) {
      // Trigger the same flow as clicking the button
      handleViewEditData();
    } else if (!isExternallyOpen && showVisualEditor) {
      // External close request
      handleDismiss();
    }
  }, [isExternallyOpen]);

  // Memoize section data for the modal
  const memoizedSectionData = useMemo(
    () => ({
      ...sectionData,
      documentItem: sectionData?.documentItem || sectionData?.item,
    }),
    [sectionData],
  );

  // Fetch content and immediately open Visual Editor
  const handleViewEditData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      logger.info('Fetching content:', fileUri);

      const response = await client.graphql({
        query: getFileContents as unknown as string,
        variables: { s3Uri: fileUri },
      });

      const result = (response as { data: { getFileContents: { isBinary: boolean; content: string } } }).data.getFileContents;

      if (result.isBinary === true) {
        setError('This file contains binary content that cannot be viewed.');
        return;
      }

      const fetchedContent = result.content;
      logger.debug('Received content');

      // Parse JSON content
      const parsed = JSON.parse(fetchedContent);
      setJsonData(parsed);
      setOriginalContent(fetchedContent);

      // Immediately open Visual Editor
      setShowVisualEditor(true);

      // Notify parent that viewer is now open
      if (onOpen) {
        onOpen();
      }
    } catch (err) {
      logger.error('Error fetching content:', err);
      setError(`Failed to load content. Please try again.`);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle JSON data changes from the Visual Editor
  const handleJsonChange = (jsonString: string) => {
    try {
      const parsed = JSON.parse(jsonString);
      setJsonData(parsed);
    } catch (err) {
      logger.error('Error parsing JSON:', err);
    }
  };

  // Handle saving changes
  const handleSave = async (editedJsonData: Record<string, unknown>) => {
    try {
      const editedContent = JSON.stringify(editedJsonData, null, 2);

      logger.info('Saving changes to file:', fileUri);

      // Parse the S3 URI to get the correct path
      const s3UriMatch = fileUri.match(/^s3:\/\/([^/]+)\/(.+)$/);
      if (!s3UriMatch) {
        throw new Error('Invalid S3 URI format');
      }

      const [, bucket, fullPath] = s3UriMatch;
      const fileName = fullPath.split('/').pop();
      const prefix = fullPath.substring(0, fullPath.lastIndexOf('/'));

      // Get presigned URL
      const response = await client.graphql({
        query: uploadDocument as unknown as string,
        variables: {
          fileName,
          contentType: 'application/json',
          prefix,
          bucket,
        },
      });

      const { presignedUrl, usePostMethod } = (response as { data: { uploadDocument: { presignedUrl: string; usePostMethod: boolean } } })
        .data.uploadDocument;

      if (!usePostMethod) {
        throw new Error('Server returned PUT method which is not supported');
      }

      // Parse the presigned post data
      const presignedPostData = JSON.parse(presignedUrl);

      // Create form data
      const formData = new FormData();

      // Add all fields from presigned POST data
      Object.entries(presignedPostData.fields as Record<string, string>).forEach(([key, value]) => {
        formData.append(key, value);
      });

      // Create a Blob from the JSON content and append it as a file
      const blob = new Blob([editedContent], { type: 'application/json' });
      formData.append('file', blob, fileName);

      // Upload to S3
      const uploadResponse = await fetch(presignedPostData.url, {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
        throw new Error(`Upload failed: ${errorText}`);
      }

      // Update the original content state
      setOriginalContent(editedContent);
      logger.info('Successfully saved changes');

      return true;
    } catch (err) {
      logger.error('Error saving changes:', err);
      throw err;
    }
  };

  // Handle dismissing the Visual Editor
  const handleDismiss = () => {
    setShowVisualEditor(false);
    setJsonData(null);
    setOriginalContent(null);

    // Notify parent that viewer is now closed
    if (onClose) {
      onClose();
    }
  };

  if (!fileUri) {
    return (
      <Box color="text-status-inactive" padding={{ top: 's' }}>
        File content not available
      </Box>
    );
  }

  return (
    <Box>
      <Button onClick={handleViewEditData} loading={isLoading} disabled={isLoading || disabled}>
        {buttonText}
      </Button>

      {error && (
        <Box color="text-status-error" padding="s">
          {error}
        </Box>
      )}

      {/* Visual Editor Modal - Directly opens when content is loaded */}
      {showVisualEditor && jsonData && (
        <Suspense
          fallback={
            <Box padding="l" textAlign="center">
              <Spinner /> Loading Visual Editor...
            </Box>
          }
        >
          <VisualEditorModal
            visible={showVisualEditor}
            onDismiss={handleDismiss}
            jsonData={jsonData}
            onChange={handleJsonChange}
            onSave={handleSave}
            isReadOnly={isReadOnly}
            sectionData={memoizedSectionData}
            allSections={allSections}
            currentSectionIndex={currentSectionIndex}
            onNavigateToSection={onNavigateToSection}
          />
        </Suspense>
      )}
    </Box>
  );
};

export default JSONViewer;
