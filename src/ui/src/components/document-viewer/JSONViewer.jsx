// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/prop-types, react/destructuring-assignment, no-nested-ternary, no-use-before-define */
import React, { useState, useEffect, useMemo, Suspense } from 'react';
import {
  Box,
  SpaceBetween,
  Button,
  Alert,
  SegmentedControl,
  FormField,
  Input,
  Checkbox,
} from '@awsui/components-react';
import { API, Logger } from 'aws-amplify';
import { Editor } from '@monaco-editor/react';
import getFileContents from '../../graphql/queries/getFileContents';
import uploadDocument from '../../graphql/queries/uploadDocument';
import { getFieldHighlightInfo, getFieldConfidenceInfo } from '../common/confidence-alerts-utils';
// Lazy load VisualEditorModal for better performance
const VisualEditorModal = React.lazy(() => import('./VisualEditorModal'));

const logger = new Logger('FileEditor');

const EDITOR_DEFAULT_HEIGHT = '600px';

// A simplified form-based JSON editor
const FormEditorView = ({ jsonData, onChange, isReadOnly, sectionData }) => {
  // Render primitive values like strings, numbers, booleans, null
  function renderPrimitiveValue(value, onChangeValue, fieldPath) {
    if (value === null || value === undefined) {
      return (
        <FormField>
          <Input value="null" disabled={isReadOnly} onChange={() => !isReadOnly && onChangeValue(null)} />
        </FormField>
      );
    }

    if (typeof value === 'boolean') {
      return (
        <FormField>
          <Checkbox
            checked={value}
            disabled={isReadOnly}
            onChange={({ detail }) => !isReadOnly && onChangeValue(detail.checked)}
          >
            {String(value)}
          </Checkbox>
        </FormField>
      );
    }

    // Handle numeric values with proper input configuration
    if (typeof value === 'number') {
      const fieldPathString = Array.isArray(fieldPath) ? fieldPath.join('.') : fieldPath || '';
      const isConfidenceField =
        fieldPathString &&
        (fieldPathString.includes('confidence') ||
          fieldPathString.includes('Confidence') ||
          fieldPathString.endsWith('_confidence') ||
          fieldPathString.endsWith('_Confidence'));

      const inputProps = {
        value: String(value),
        disabled: isReadOnly,
        type: 'number',
        step: isConfidenceField ? '0.01' : 'any',
        onChange: ({ detail }) => {
          if (isReadOnly) return;

          const newValue = detail.value;
          const parsed = Number(newValue);
          if (!Number.isNaN(parsed)) {
            // For confidence fields, clamp between 0 and 1
            if (isConfidenceField) {
              const clampedValue = Math.max(0, Math.min(1, parsed));
              onChangeValue(clampedValue);
            } else {
              onChangeValue(parsed);
            }
          } else if (newValue === '') {
            // Allow empty value for editing
            onChangeValue(0);
          }
        },
      };

      // Add min/max for confidence fields
      if (isConfidenceField) {
        inputProps.min = '0';
        inputProps.max = '1';
      }

      return (
        <FormField>
          <Input
            value={inputProps.value}
            disabled={inputProps.disabled}
            type={inputProps.type}
            step={inputProps.step}
            min={inputProps.min}
            max={inputProps.max}
            onChange={inputProps.onChange}
          />
        </FormField>
      );
    }

    // Handle string values
    return (
      <FormField>
        <Input
          value={String(value)}
          disabled={isReadOnly}
          onChange={({ detail }) => {
            if (isReadOnly) return;
            onChangeValue(detail.value);
          }}
        />
      </FormField>
    );
  }

  // Render a key-value pair with the key on the left
  function renderKeyValuePair(key, value, onChangeValue, parentPath = [], isArrayIndex = false) {
    // For array indices, the key is like "[0]", so we extract the index
    const cleanKey = key.replace(/[[\]]/g, '');
    const currentPath = isArrayIndex ? [...parentPath, parseInt(cleanKey, 10)] : [...parentPath, cleanKey];

    // Get confidence information from explainability data (for all fields)
    const explainabilityInfo = jsonData?.explainability_info;
    // For array items, we don't look for confidence of the index itself, but pass the current path
    // For regular fields, we look for confidence of the field name using the parent path

    // Filter out structural keys from the path for explainability lookup
    // We need to remove top-level keys like 'inference_result', 'explainability_info', etc.
    const structuralKeys = ['inference_result', 'inferenceResult', 'explainability_info'];
    const filteredParentPath = parentPath.filter(
      (pathSegment) => !structuralKeys.includes(pathSegment) && typeof pathSegment !== 'undefined',
    );

    const confidenceInfo = isArrayIndex
      ? { hasConfidenceInfo: false } // Array indices don't have confidence, their contents do
      : getFieldConfidenceInfo(cleanKey, explainabilityInfo, filteredParentPath);

    // Check if this field should be highlighted due to low confidence (legacy alert-based highlighting)
    const confidenceThresholdAlerts = sectionData?.ConfidenceThresholdAlerts || [];
    const highlightInfo = getFieldHighlightInfo(key, value, confidenceThresholdAlerts);

    const boxStyle =
      highlightInfo.shouldHighlight || confidenceInfo.shouldHighlight
        ? { backgroundColor: '#ffeaa7', border: '2px solid #e17055' }
        : {};

    return (
      <Box padding="xxxs" borderBottom="divider-light" style={boxStyle}>
        <Box display="flex" alignItems="center">
          <Box width="30%" padding="xxxs" fontWeight="bold" fontSize="body-s">
            {key}:
            {confidenceInfo.hasConfidenceInfo && (
              <Box fontSize="body-s" padding={{ top: 'xxxs' }} style={{ color: confidenceInfo.textColor }}>
                {confidenceInfo.displayMode === 'with-threshold'
                  ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                      confidenceInfo.confidenceThreshold * 100
                    ).toFixed(1)}%`
                  : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
              </Box>
            )}
          </Box>
          <Box width="70%">
            {renderJsonValue(
              value,
              (newValue) => {
                if (isReadOnly) return;
                onChangeValue(newValue);
              },
              currentPath,
            )}
          </Box>
        </Box>
      </Box>
    );
  }

  // The main recursive renderer for JSON values
  function renderJsonValue(value, onChangeValue, fieldPath = []) {
    // Handle primitive values
    if (
      value === null ||
      value === undefined ||
      typeof value === 'boolean' ||
      typeof value === 'number' ||
      typeof value === 'string'
    ) {
      return renderPrimitiveValue(value, onChangeValue, fieldPath);
    }

    // Handle arrays
    if (Array.isArray(value)) {
      return (
        <Box padding="xxxs">
          <Box fontSize="body-s" color="text-status-info" padding="xxxs">
            Array ({value.length} items)
          </Box>
          <Box padding={{ left: 'xs' }}>
            <SpaceBetween size="xxxs">
              {value.map((item, index) => {
                // Create a stable key based on index only
                const itemKey =
                  typeof item === 'object' && item !== null && item.id
                    ? `array-item-${item.id}-${index}`
                    : `array-item-${index}`;
                return (
                  <Box key={itemKey}>
                    {renderKeyValuePair(
                      `[${index}]`,
                      item,
                      (newValue) => {
                        const newArray = [...value];
                        newArray[index] = newValue;
                        onChangeValue(newArray);
                      },
                      fieldPath,
                      true, // isArrayIndex
                    )}
                  </Box>
                );
              })}
              {!isReadOnly && (
                <Button
                  variant="link"
                  onClick={() => {
                    const newValue = [...value, value.length > 0 ? null : ''];
                    onChangeValue(newValue);
                  }}
                >
                  Add Item
                </Button>
              )}
            </SpaceBetween>
          </Box>
        </Box>
      );
    }

    // Handle objects
    if (typeof value === 'object') {
      return (
        <Box padding="xxxs">
          <SpaceBetween size="xxxs">
            {Object.entries(value).map(([key, propValue]) => (
              <Box key={`prop-${key}`}>
                {renderKeyValuePair(
                  key,
                  propValue,
                  (newValue) => {
                    const newObj = { ...value };
                    newObj[key] = newValue;
                    onChangeValue(newObj);
                  },
                  fieldPath,
                  false, // isArrayIndex
                )}
              </Box>
            ))}
            {!isReadOnly && (
              <Button
                variant="link"
                onClick={() => {
                  const newKey = prompt('Enter new property name:');
                  if (newKey && !value[newKey]) {
                    const newObj = { ...value };
                    newObj[newKey] = '';
                    onChangeValue(newObj);
                  }
                }}
              >
                Add Property
              </Button>
            )}
          </SpaceBetween>
        </Box>
      );
    }

    return <div>Unsupported type: {typeof value}</div>;
  }

  const handleChange = (newValue) => {
    if (onChange && !isReadOnly) {
      try {
        const jsonString = JSON.stringify(newValue, null, 2);
        onChange(jsonString);
      } catch (error) {
        logger.error('Error stringifying JSON:', error);
      }
    }
  };

  return (
    <Box
      style={{
        height: EDITOR_DEFAULT_HEIGHT,
        position: 'relative',
        overflow: 'auto',
        padding: '16px',
        backgroundColor: '#ffffff',
        border: '2px solid #e9ebed',
        borderRadius: '4px',
        width: '100%',
        minWidth: '600px',
      }}
    >
      {jsonData ? (
        renderJsonValue(jsonData, handleChange, [])
      ) : (
        <Box textAlign="center" padding="l">
          No valid JSON data to display
        </Box>
      )}
    </Box>
  );
};

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
          defaultLanguage={fileType === 'json' ? 'json' : fileType}
          value={
            fileType === 'json' && typeof fileContent === 'string'
              ? JSON.stringify(JSON.parse(fileContent), null, 2)
              : fileContent
          }
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
            formatOnPaste: true,
            formatOnType: true,
          }}
          theme="vs-light"
          loading={<Box padding="s">Loading editor...</Box>}
        />
      </div>
    </Box>
  );
};

const FileEditorView = ({ fileContent, onChange, isReadOnly = true, fileType = 'text', sectionData }) => {
  const [isValid, setIsValid] = useState(true);
  const [jsonData, setJsonData] = useState(null);
  const [viewMode, setViewMode] = useState(fileType === 'markdown' ? 'markdown' : 'form');
  const [showVisualEditor, setShowVisualEditor] = useState(false);

  // Memoize expensive props for better performance
  const memoizedSectionData = useMemo(
    () => ({
      ...sectionData,
      documentItem: sectionData?.documentItem || sectionData?.item,
    }),
    [sectionData],
  );

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

  const handleFormChange = (jsonString) => {
    try {
      const parsed = JSON.parse(jsonString);
      setJsonData(parsed);
      setIsValid(true);
      if (onChange) {
        onChange(jsonString);
      }
    } catch (error) {
      setIsValid(false);
      logger.error('Error updating JSON:', error);
    }
  };

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

  if (fileType !== 'json') {
    return (
      <TextEditorView
        fileContent={fileContent}
        onChange={handleTextEditorChange}
        isReadOnly={isReadOnly}
        fileType={fileType}
      />
    );
  }

  const handleViewModeChange = ({ detail }) => {
    if (detail.selectedId === 'visual') {
      setShowVisualEditor(true);
      // Don't change viewMode, keep it as current
    } else {
      setViewMode(detail.selectedId);
    }
  };

  return (
    <Box>
      {fileType === 'json' && (
        <SpaceBetween direction="vertical" size="xs">
          <SegmentedControl
            selectedId={viewMode}
            onChange={handleViewModeChange}
            options={[
              { id: 'form', text: 'Form View' },
              { id: 'text', text: 'Text View' },
              { id: 'visual', text: 'Visual Edit' },
            ]}
          />

          {!isValid && (
            <Alert type="error" header="Invalid JSON format">
              The JSON content is invalid. Please correct any syntax errors.
            </Alert>
          )}
        </SpaceBetween>
      )}

      {isValid && fileType === 'json' ? (
        viewMode === 'form' ? (
          <FormEditorView
            jsonData={jsonData}
            onChange={handleFormChange}
            isReadOnly={isReadOnly}
            sectionData={memoizedSectionData}
          />
        ) : (
          <TextEditorView
            fileContent={typeof fileContent === 'string' ? fileContent : JSON.stringify(jsonData, null, 2)}
            onChange={handleTextEditorChange}
            isReadOnly={isReadOnly}
            fileType="json"
          />
        )
      ) : (
        <TextEditorView
          fileContent={typeof fileContent === 'string' ? fileContent : JSON.stringify(jsonData, null, 2)}
          onChange={handleTextEditorChange}
          isReadOnly={isReadOnly}
          fileType={fileType === 'json' ? 'json' : fileType}
        />
      )}

      {/* Visual Editor Modal - Lazy loaded with Suspense for better performance */}
      {showVisualEditor && (
        <Suspense fallback={<Box padding="s">Loading Visual Editor...</Box>}>
          <VisualEditorModal
            visible={showVisualEditor}
            onDismiss={() => setShowVisualEditor(false)}
            jsonData={jsonData}
            onChange={handleFormChange}
            isReadOnly={isReadOnly}
            sectionData={memoizedSectionData}
          />
        </Suspense>
      )}
    </Box>
  );
};

const JSONViewer = ({ fileUri, fileType = 'text', buttonText = 'View File', sectionData }) => {
  const [fileContent, setFileContent] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
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
        setError('This file contains binary content that cannot be viewed in the JSON viewer.');
        return;
      }
      logger.debug('Received content:', `${fetchedContent.substring(0, 100)}...`);
      setFileContent(fetchedContent);
      setEditedContent(fetchedContent); // Initialize edited content for always-on edit mode
    } catch (err) {
      logger.error('Error fetching content:', err);
      setError(`Failed to load ${fileType} content. Please try again.`);
    } finally {
      setIsLoading(false);
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
              <Button variant="primary" onClick={handleSave} disabled={!editedContent || editedContent === fileContent}>
                Save Changes
              </Button>
            </SpaceBetween>
          </Box>
          <div style={{ width: '100%' }}>
            <FileEditorView
              fileContent={editedContent || fileContent}
              onChange={handleContentChange}
              isReadOnly={false}
              fileType={fileType}
              sectionData={sectionData}
            />
          </div>
        </SpaceBetween>
      )}
    </Box>
  );
};

export default JSONViewer;
