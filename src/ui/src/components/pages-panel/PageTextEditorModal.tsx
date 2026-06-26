// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect, useMemo } from 'react';
import { Modal, Box, SpaceBetween, Button, SegmentedControl, Alert, Spinner, Badge } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Editor } from '@monaco-editor/react';
import MarkdownViewer from '../document-viewer/MarkdownViewer';
import PageImageViewer from '../common/PageImageViewer';
import { getFileContents, uploadDocument } from '../../graphql/generated';

const client = generateClient();
const logger = new ConsoleLogger('PageTextEditorModal');

const EDITOR_HEIGHT = '600px';

// Confidence color thresholds for OCR bounding-box overlays.
const CONFIDENCE_HIGH = 90;
const CONFIDENCE_MEDIUM = 70;

/**
 * One text unit (LINE) from the consolidated pageData.json artifact.
 * confidence/geometry are independently optional per the OCR backend.
 */
interface OcrPageDataLine {
  text?: string;
  confidence?: number | null;
  geometry?: {
    boundingBox?: { left: number; top: number; width: number; height: number };
  } | null;
}

interface OcrPageData {
  provider?: string;
  geometryAvailable?: boolean;
  confidenceAvailable?: boolean;
  lines?: OcrPageDataLine[];
}

interface PageTextEditorModalProps {
  visible: boolean;
  pageId?: string | number;
  textUri?: string;
  confidenceUri?: string;
  imageUri?: string;
  ocrPageDataUri?: string;
  isReadOnly?: boolean;
  onSave?: (pageId: string | number | undefined, newTextUri: string | null, newConfidenceUri: string | null) => void;
  onClose?: () => void;
}

/**
 * Map an OCR confidence score (0-100) to an overlay color.
 * Lines without confidence are drawn neutral.
 */
const confidenceColor = (confidence: number | null | undefined): string => {
  if (confidence === null || confidence === undefined) return '#888';
  if (confidence >= CONFIDENCE_HIGH) return '#2ca02c';
  if (confidence >= CONFIDENCE_MEDIUM) return '#ff7f0e';
  return '#d62728';
};

/**
 * Extract plain text from JSON-wrapped content
 * Handles both {"text": "..."} and plain text formats
 */
const extractPlainText = (content: string): string => {
  if (!content) return '';

  try {
    const parsed = JSON.parse(content);
    return parsed.text || parsed.Text || content;
  } catch (e) {
    // Already plain text
    return content;
  }
};

/**
 * Wrap plain text in JSON structure for backward compatibility
 */
const wrapInJson = (text: string): string => {
  return JSON.stringify({ text: text || '' }, null, 2);
};

const PageTextEditorModal = ({
  visible,
  pageId,
  textUri,
  confidenceUri,
  imageUri,
  ocrPageDataUri,
  isReadOnly = true,
  onSave,
  onClose,
}: PageTextEditorModalProps): React.JSX.Element => {
  // Whether the visual (image) view is available for this page.
  const hasVisualView = Boolean(imageUri);

  const [viewMode, setViewMode] = useState(hasVisualView ? 'visual-editor' : 'text-markdown');
  const [textContent, setTextContent] = useState('');
  const [confidenceContent, setConfidenceContent] = useState('');
  const [originalTextContent, setOriginalTextContent] = useState('');
  const [originalConfidenceContent, setOriginalConfidenceContent] = useState('');
  const [pageData, setPageData] = useState<OcrPageData | null>(null);
  const [selectedLineIndex, setSelectedLineIndex] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showCloseWarning, setShowCloseWarning] = useState(false);

  const geometryAvailable = Boolean(pageData?.geometryAvailable);
  const lines = useMemo(() => pageData?.lines ?? [], [pageData]);

  // Only the currently-selected line's box is drawn on the image (the section
  // Visual Editor pattern). Drawing every line at once is unreadable.
  const activeFieldGeometry = useMemo(() => {
    if (selectedLineIndex === null) return null;
    const line = lines[selectedLineIndex];
    if (!line?.geometry?.boundingBox) return null;
    return { boundingBox: line.geometry.boundingBox, page: 1 };
  }, [selectedLineIndex, lines]);

  const documentPages = useMemo(() => (imageUri ? [{ Id: String(pageId), ImageUri: imageUri }] : []), [imageUri, pageId]);

  // Reset selection / default view whenever the modal (re)opens for a page.
  useEffect(() => {
    if (visible) {
      setSelectedLineIndex(null);
      setViewMode(hasVisualView ? 'visual-editor' : 'text-markdown');
    }
  }, [visible, pageId, hasVisualView]);

  // Fetch content when modal opens
  useEffect(() => {
    if (visible && textUri) {
      fetchContent();
    }
  }, [visible, textUri, confidenceUri, ocrPageDataUri]);

  // Track unsaved changes
  useEffect(() => {
    const textChanged = textContent !== originalTextContent;
    const confidenceChanged = confidenceContent !== originalConfidenceContent;
    setHasUnsavedChanges(textChanged || confidenceChanged);
  }, [textContent, confidenceContent, originalTextContent, originalConfidenceContent]);

  const fetchContent = async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Fetch text content
      const textResponse = await client.graphql({
        query: getFileContents,
        variables: { s3Uri: textUri as string },
      });

      const textResult = textResponse.data?.getFileContents;
      if (!textResult) {
        throw new Error('No response from getFileContents');
      }
      if (textResult.isBinary) {
        throw new Error('Text file contains binary content');
      }

      // Extract plain text from JSON wrapper
      const plainText = extractPlainText(textResult.content ?? '');
      setTextContent(plainText);
      setOriginalTextContent(plainText);

      // Fetch confidence content if available
      if (confidenceUri) {
        try {
          const confResponse = await client.graphql({
            query: getFileContents,
            variables: { s3Uri: confidenceUri },
          });

          const confResult = confResponse.data?.getFileContents;
          if (confResult && !confResult.isBinary) {
            // Extract markdown from JSON wrapper for confidence content
            const confidenceMarkdown = extractPlainText(confResult.content ?? '');
            setConfidenceContent(confidenceMarkdown);
            setOriginalConfidenceContent(confidenceMarkdown);
          }
        } catch (err) {
          logger.warn('Failed to load confidence content:', err);
          // Not critical - continue without confidence
        }
      }

      // Fetch consolidated OCR page data (text + confidence + geometry) if
      // available. Older documents predate this artifact, so absence is normal
      // and the visual view simply omits bounding-box overlays.
      if (ocrPageDataUri) {
        try {
          const pageDataResponse = await client.graphql({
            query: getFileContents,
            variables: { s3Uri: ocrPageDataUri },
          });

          const pageDataResult = pageDataResponse.data?.getFileContents;
          if (pageDataResult && !pageDataResult.isBinary && pageDataResult.content) {
            setPageData(JSON.parse(pageDataResult.content) as OcrPageData);
          }
        } catch (err) {
          logger.warn('Failed to load OCR page data:', err);
          // Not critical - continue without geometry overlays
        }
      }
    } catch (err) {
      logger.error('Error fetching content:', err);
      setError(`Failed to load page content: ${(err as Error).message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleTextChange = (value: string | undefined): void => {
    setTextContent(value || '');
  };

  const handleConfidenceChange = (value: string | undefined): void => {
    // Store the raw markdown - will wrap in JSON when saving
    setConfidenceContent(value || '');
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);

    try {
      let newTextUri = null;
      let newConfidenceUri = null;

      // Save text content if changed
      if (textContent !== originalTextContent) {
        newTextUri = await saveToS3(textUri!, wrapInJson(textContent), 'application/json');
        logger.info('Saved text content to:', newTextUri);
      }

      // Save confidence content if changed (wrap in JSON)
      if (confidenceContent !== originalConfidenceContent && confidenceUri) {
        newConfidenceUri = await saveToS3(confidenceUri, wrapInJson(confidenceContent), 'application/json');
        logger.info('Saved confidence content to:', newConfidenceUri);
      }

      // Update original content to mark as saved
      setOriginalTextContent(textContent);
      setOriginalConfidenceContent(confidenceContent);

      // Notify parent of save
      if (onSave) {
        onSave(pageId, newTextUri, newConfidenceUri);
      }

      // Close modal after successful save
      handleCloseModal();
    } catch (err) {
      logger.error('Error saving content:', err);
      setError(`Failed to save changes: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const saveToS3 = async (s3Uri: string, content: string, contentType: string): Promise<string> => {
    // Parse S3 URI to get bucket and key
    const match = s3Uri.match(/^s3:\/\/([^/]+)\/(.+)$/);
    if (!match) {
      throw new Error('Invalid S3 URI format');
    }

    const [, bucket, fullPath] = match;
    const fileName = fullPath.split('/').pop() ?? fullPath;
    const prefix = fullPath.substring(0, fullPath.lastIndexOf('/'));

    // Get presigned URL
    const response = await client.graphql({
      query: uploadDocument,
      variables: {
        fileName,
        contentType,
        prefix,
        bucket,
      },
    });

    const { presignedUrl, usePostMethod } = response.data.uploadDocument;
    const usePost = usePostMethod?.toLowerCase() === 'true';

    if (!usePost) {
      throw new Error('Server returned PUT method which is not supported');
    }

    // Parse presigned POST data
    const presignedPostData = JSON.parse(presignedUrl);

    // Create form data
    const formData = new FormData();
    Object.entries(presignedPostData.fields).forEach(([key, value]) => {
      formData.append(key, value as string);
    });

    // Add file
    const blob = new Blob([content], { type: contentType });
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

    return s3Uri; // Return the same URI (content updated in place)
  };

  const handleCloseClick = () => {
    if (hasUnsavedChanges && !isReadOnly) {
      setShowCloseWarning(true);
    } else {
      handleCloseModal();
    }
  };

  const handleCloseModal = () => {
    setShowCloseWarning(false);
    setTextContent('');
    setConfidenceContent('');
    setOriginalTextContent('');
    setOriginalConfidenceContent('');
    setPageData(null);
    setSelectedLineIndex(null);
    setError(null);
    setHasUnsavedChanges(false);
    if (onClose) {
      onClose();
    }
  };

  const handleForceClose = () => {
    handleCloseModal();
  };

  return (
    <>
      <Modal
        visible={visible}
        onDismiss={handleCloseClick}
        size="max"
        header={`${isReadOnly ? 'View' : 'Edit'} Page ${pageId} Text`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={handleCloseClick} disabled={isSaving}>
                {hasUnsavedChanges ? 'Cancel' : 'Close'}
              </Button>
              {!isReadOnly && (
                <Button variant="primary" onClick={handleSave} disabled={!hasUnsavedChanges || isSaving} loading={isSaving}>
                  Save
                </Button>
              )}
            </SpaceBetween>
          </Box>
        }
      >
        <Box>
          {error && (
            <Box margin={{ bottom: 's' }}>
              <Alert type="error" header="Error">
                {error}
              </Alert>
            </Box>
          )}

          {isLoading ? (
            <Box textAlign="center" padding="xxl">
              <Spinner size="large" />
              <Box variant="p" color="text-body-secondary">
                Loading page content...
              </Box>
            </Box>
          ) : (
            <>
              <Box margin={{ bottom: 's' }}>
                <SegmentedControl
                  selectedId={viewMode}
                  onChange={({ detail }) => setViewMode(detail.selectedId)}
                  options={[
                    { id: 'visual-editor', text: 'Visual Editor', disabled: !hasVisualView },
                    { id: 'text-markdown', text: 'Text + Markdown' },
                    { id: 'text-confidence', text: 'Text + Confidence', disabled: !confidenceUri },
                  ]}
                />
              </Box>

              {viewMode === 'visual-editor' ? (
                <div style={{ display: 'flex', gap: '12px', minHeight: EDITOR_HEIGHT, alignItems: 'stretch' }}>
                  {/* Left pane: page image with the selected line's bounding box */}
                  <div style={{ flex: '0 0 55%', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <PageImageViewer
                      pageIds={[String(pageId)]}
                      documentPages={documentPages}
                      initialPage={String(pageId)}
                      height={EDITOR_HEIGHT}
                      activeFieldGeometry={activeFieldGeometry}
                    />
                  </div>

                  {/* Right pane: clickable OCR text lines */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <Box fontSize="body-s" color="text-label" margin={{ bottom: 'xxxs' }}>
                      OCR Text Lines {geometryAvailable ? '(click a line to highlight it on the image)' : ''}
                    </Box>
                    {!geometryAvailable && (
                      <Box margin={{ bottom: 'xs' }}>
                        <Alert type="info">
                          This OCR backend did not provide bounding-box geometry for this page, so lines cannot be highlighted on the image.
                        </Alert>
                      </Box>
                    )}
                    <div
                      style={{
                        border: '1px solid #e9ebed',
                        height: EDITOR_HEIGHT,
                        overflow: 'auto',
                        backgroundColor: '#fff',
                      }}
                    >
                      {lines.length === 0 ? (
                        <Box padding="m" color="text-body-secondary">
                          No OCR text lines available for this page.
                        </Box>
                      ) : (
                        lines.map((line, index) => {
                          const hasGeometry = Boolean(line.geometry?.boundingBox);
                          const isSelected = selectedLineIndex === index;
                          return (
                            <div
                              // eslint-disable-next-line react/no-array-index-key -- lines are a stable ordered OCR list
                              key={`ocr-line-${index}`}
                              onClick={() => hasGeometry && setSelectedLineIndex(isSelected ? null : index)}
                              role={hasGeometry ? 'button' : undefined}
                              tabIndex={hasGeometry ? 0 : undefined}
                              onKeyDown={(e) => {
                                if (hasGeometry && (e.key === 'Enter' || e.key === ' ')) {
                                  e.preventDefault();
                                  setSelectedLineIndex(isSelected ? null : index);
                                }
                              }}
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                gap: '8px',
                                padding: '4px 8px',
                                borderBottom: '1px solid #f2f3f3',
                                cursor: hasGeometry ? 'pointer' : 'default',
                                backgroundColor: isSelected ? '#f0f7ff' : 'transparent',
                                borderLeft: isSelected ? '3px solid #0972d3' : '3px solid transparent',
                              }}
                            >
                              <span style={{ fontSize: '13px', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
                                {line.text || <em style={{ color: '#888' }}>(empty)</em>}
                              </span>
                              {line.confidence != null && (
                                <span style={{ flexShrink: 0, color: confidenceColor(line.confidence), fontSize: '12px', fontWeight: 600 }}>
                                  {line.confidence}
                                </span>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                    {geometryAvailable && (
                      <Box fontSize="body-s" color="text-body-secondary" margin={{ top: 'xxs' }}>
                        Confidence color: <Badge color="green">≥ {CONFIDENCE_HIGH}</Badge>{' '}
                        <Badge color="severity-medium">≥ {CONFIDENCE_MEDIUM}</Badge> <Badge color="red">below</Badge>
                      </Box>
                    )}
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: '4px', minHeight: EDITOR_HEIGHT }}>
                  {/* Left pane: Text editor */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, margin: 0 }}>
                    <Box fontSize="body-s" color="text-label" margin={{ bottom: 'xxxs' }}>
                      {viewMode === 'text-markdown'
                        ? `Text (${isReadOnly ? 'read-only' : 'editable'})`
                        : `Confidence Table (${isReadOnly ? 'read-only' : 'editable'})`}
                    </Box>
                    <div style={{ border: '1px solid #e9ebed', height: EDITOR_HEIGHT }}>
                      <Editor
                        key={`editor-${viewMode}`}
                        height={EDITOR_HEIGHT}
                        defaultLanguage="text"
                        value={viewMode === 'text-markdown' ? textContent : confidenceContent}
                        onChange={viewMode === 'text-markdown' ? handleTextChange : handleConfidenceChange}
                        options={{
                          readOnly: isReadOnly,
                          minimap: { enabled: false },
                          fontSize: 14,
                          wordWrap: 'on',
                          wrappingIndent: 'indent',
                          automaticLayout: true,
                          scrollBeyondLastLine: false,
                        }}
                        theme="vs-light"
                      />
                    </div>
                  </div>

                  {/* Right pane: Markdown Preview */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, margin: 0 }}>
                    <Box fontSize="body-s" color="text-label" margin={{ bottom: 'xxxs' }}>
                      Markdown Preview (read-only)
                    </Box>
                    <div
                      style={{
                        border: '1px solid #e9ebed',
                        height: EDITOR_HEIGHT,
                        overflow: 'auto',
                        padding: '16px',
                        backgroundColor: '#fafafa',
                      }}
                      className="page-text-markdown-preview"
                    >
                      <MarkdownViewer simple content={viewMode === 'text-markdown' ? textContent : confidenceContent} />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </Box>
      </Modal>

      {/* Unsaved changes warning modal */}
      <Modal
        visible={showCloseWarning}
        onDismiss={() => setShowCloseWarning(false)}
        header="Unsaved Changes"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setShowCloseWarning(false)}>Continue Editing</Button>
              <Button variant="primary" onClick={handleForceClose}>
                Discard Changes
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        You have unsaved changes. Are you sure you want to close without saving?
      </Modal>
    </>
  );
};

export default PageTextEditorModal;
