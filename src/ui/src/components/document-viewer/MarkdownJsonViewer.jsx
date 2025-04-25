/* eslint-disable react/prop-types, react/destructuring-assignment, no-nested-ternary, no-use-before-define */
import React, { useState, useEffect } from 'react';
import { Box, SpaceBetween, Button, Toggle, Alert, SegmentedControl } from '@awsui/components-react';
import { API, Logger } from 'aws-amplify';
import { Editor } from '@monaco-editor/react';
import getFileContents from '../../graphql/queries/getFileContents';
import uploadDocument from '../../graphql/queries/uploadDocument';
import MarkdownViewer from './MarkdownViewer';

const logger = new Logger('MarkdownJsonViewer');

const EDITOR_DEFAULT_HEIGHT = '600px';

const TextEditorView = ({ fileContent, onChange, isReadOnly, fileType }) => {
  const [isEditorReady, setIsEditorReady] = useState(false);

  useEffect(() => {
    let timeoutId;
    if (isEditorReady) {
      timeoutId = setTimeout(() => {
        if (window.monacoEditor) {
          window.monacoEditor.layout();
        }
      }, 100);
    }
    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      if (window.editorResizeTimeout) {
        clearTimeout(window.editorResizeTimeout);
      }
      // Clear any global references when component unmounts
      window.monacoEditor = null;
    };
  }, [isEditorReady]);

  const handleEditorDidMount = (editor) => {
    window.monacoEditor = editor;
    editor.layout();
    setIsEditorReady(true);

    // Add a resize observer to handle editor resizing
    const resizeObserver = new ResizeObserver(() => {
      // Debounce the layout call to prevent excessive updates
      if (window.editorResizeTimeout) {
        clearTimeout(window.editorResizeTimeout);
      }
      window.editorResizeTimeout = setTimeout(() => {
        editor.layout();
      }, 100);
    });

    // Observe the editor's container
    const container = editor.getContainerDomNode();
    if (container) {
      resizeObserver.observe(container.parentElement);
    }
  };

  return (
    <Box className="file-editor-container" style={{ border: '2px solid #e9ebed', width: '100%', minWidth: '600px' }}>
      <div style={{ height: EDITOR_DEFAULT_HEIGHT, position: 'relative', overflow: 'hidden', width: '100%' }}>
        <Editor
          height="100%"
          defaultLanguage={fileType}
          value={fileContent}
          onChange={onChange}
          onMount={handleEditorDidMount}
          options={{
            readOnly: isReadOnly,
            minimap: { enabled: false },
            fontSize: 14,
            wordWrap: 'on',
            wrappingIndent: 'indent',
            automaticLayout: false,
            scrollBeyondLastLine: false,
            fixedOverflowWidgets: true,
            scrollbar: {
              vertical: 'visible',
              horizontal: 'visible',
            },
          }}
          theme="vs-light"
          loading={<Box padding="s">Loading editor...</Box>}
        />
      </div>
    </Box>
  );
};

const FileEditorView = ({ fileContent, onChange, isReadOnly = true, fileType = 'text' }) => {
  const [isValid, setIsValid] = useState(true);
  const [jsonData, setJsonData] = useState(null);
  const [viewMode, setViewMode] = useState('markdown');

  useEffect(() => {
    if (fileType === 'json') {
      try {
        const parsed = typeof fileContent === 'string' ? JSON.parse(fileContent) : fileContent;
        setJsonData(parsed);
        setIsValid(true);
      } catch (error) {
        setIsValid(false);
        logger.error('Invalid JSON:', error);
      }
    }
  }, [fileContent, fileType]);

  const handleTextEditorChange = (value) => {
    if (fileType === 'json') {
      try {
        const parsed = JSON.parse(value);
        setJsonData(parsed);
        setIsValid(true);
        if (onChange) {
          onChange(value);
        }
      } catch (error) {
        setIsValid(false);
        logger.error('Invalid JSON:', error);
      }
    } else if (onChange) {
      onChange(value);
    }
  };

  const handleViewModeChange = ({ detail }) => {
    setViewMode(detail.selectedId);
  };

  return (
    <Box>
      <SpaceBetween direction="vertical" size="xs">
        <SegmentedControl
          selectedId={viewMode}
          onChange={handleViewModeChange}
          options={[
            { id: 'markdown', text: 'Markdown View' },
            { id: 'text', text: 'Text View' },
          ]}
        />

        {!isValid && (
          <Alert type="error" header="Invalid format">
            The content format is invalid. Please correct any syntax errors.
          </Alert>
        )}
      </SpaceBetween>

      {viewMode === 'markdown' ? (
        <MarkdownViewer
          simple
          content={
            typeof fileContent === 'string'
              ? (() => {
                  try {
                    // Try to parse it as JSON and extract text content
                    const parsed = JSON.parse(fileContent);
                    return parsed.text || parsed.Text || fileContent;
                  } catch (e) {
                    // If it's not valid JSON, just return the content as is
                    return fileContent;
                  }
                })()
              : jsonData?.text || jsonData?.Text || JSON.stringify(jsonData, null, 2)
          }
        />
      ) : (
        <TextEditorView
          fileContent={typeof fileContent === 'string' ? fileContent : JSON.stringify(jsonData, null, 2)}
          onChange={handleTextEditorChange}
          isReadOnly={isReadOnly}
          fileType={fileType}
        />
      )}
    </Box>
  );
};

const MarkdownJsonViewer = ({ fileUri, fileType = 'text', buttonText = 'View File' }) => {
  const [fileContent, setFileContent] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(null);

  const fetchContent = async () => {
    setIsLoading(true);
    setError(null);
    try {
      logger.info('Fetching content:', fileUri);

      const response = await API.graphql({
        query: getFileContents,
        variables: { s3Uri: fileUri },
      });

      // Handle the updated response structure
      const result = response.data.getFileContents;
      const fetchedContent = result.content;
      logger.debug('Received content type:', result.contentType);
      logger.debug('Binary content?', result.isBinary);
      if (result.isBinary === true) {
        setError('This file contains binary content that cannot be viewed in the Markdown viewer.');
        return;
      }
      logger.debug('Received content:', `${fetchedContent.substring(0, 100)}...`);
      setFileContent(fetchedContent);
    } catch (err) {
      logger.error('Error fetching content:', err);
      setError(`Failed to load ${fileType} content. Please try again.`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditToggle = ({ detail }) => {
    setIsEditing(detail.checked);
    if (detail.checked && !editedContent) {
      setEditedContent(fileContent);
    }
  };

  const handleContentChange = (newContent) => {
    setEditedContent(newContent);
  };

  const handleSave = async () => {
    try {
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
      const response = await API.graphql({
        query: uploadDocument,
        variables: {
          fileName,
          contentType: 'application/json',
          prefix,
          bucket,
        },
      });

      const { presignedUrl, usePostMethod } = response.data.uploadDocument;

      if (!usePostMethod) {
        throw new Error('Server returned PUT method which is not supported');
      }

      // Parse the presigned post data
      const presignedPostData = JSON.parse(presignedUrl);

      // Create form data
      const formData = new FormData();

      // Add all fields from presigned POST data
      Object.entries(presignedPostData.fields).forEach(([key, value]) => {
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

      // Update the file content state to reflect saved changes
      setFileContent(editedContent);
      setIsEditing(false);
      setSuccess('File saved and uploaded successfully');
      logger.info('Successfully saved changes');

      // Clear success message after 3 seconds
      setTimeout(() => {
        setSuccess(null);
      }, 3000);
    } catch (err) {
      logger.error('Error saving changes:', err);
      setError(`Failed to save changes: ${err.message}`);
    }
  };

  const closeViewer = () => {
    setFileContent(null);
    setEditedContent(null);
    setIsEditing(false);
  };

  if (!fileUri) {
    return (
      <Box color="text-status-inactive" padding={{ top: 's' }}>
        File content not available
      </Box>
    );
  }

  return (
    <Box className="w-full">
      {!fileContent && (
        <Button onClick={fetchContent} loading={isLoading} disabled={isLoading}>
          {buttonText}
        </Button>
      )}

      {error && (
        <Box color="text-status-error" padding="s">
          {error}
        </Box>
      )}

      {success && (
        <Box color="text-status-success" padding="s">
          {success}
        </Box>
      )}

      {fileContent && (
        <SpaceBetween size="s" className="json-viewer-container" style={{ width: '100%', minWidth: '700px' }}>
          <Box>
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={closeViewer}>Close</Button>
              <Toggle onChange={handleEditToggle} checked={isEditing}>
                Edit mode
              </Toggle>
              {isEditing && (
                <Button
                  variant="primary"
                  onClick={handleSave}
                  disabled={!editedContent || editedContent === fileContent}
                >
                  Save Changes
                </Button>
              )}
            </SpaceBetween>
          </Box>
          <div style={{ width: '100%' }}>
            <FileEditorView
              fileContent={isEditing ? editedContent : fileContent}
              onChange={handleContentChange}
              isReadOnly={!isEditing}
              fileType={fileType}
            />
          </div>
        </SpaceBetween>
      )}
    </Box>
  );
};

export default MarkdownJsonViewer;
