// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable prettier/prettier */
 

import React, { useState, useEffect, useRef, memo } from 'react';
import {
  Modal,
  Box,
  SpaceBetween,
  Container,
  Header,
  Spinner,
  Button,
  Toggle,
  Alert,
  Tabs,
} from '@cloudscape-design/components';
import { generateClient } from '../../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import { useDocumentVersion } from '../../contexts/document-version';
import useUserRole from '../../hooks/use-user-role';
import { getFileContents, uploadDocument, completeSectionReview } from '../../graphql/generated';
import FormFieldRenderer from './FormFieldRenderer';
import JSONEditorTab from './JSONEditorTab';
import type { BoxProps } from '@cloudscape-design/components';
import EditHistoryTab from './EditHistoryTab';
import ProcessingReportTab from './ProcessingReportTab';

// Extended Box props to allow native HTML attributes that Cloudscape passes through at runtime
type ExtendedBoxProps = BoxProps & React.HTMLAttributes<HTMLDivElement>;
const ExtBox = Box as React.ComponentType<ExtendedBoxProps>;

interface BoundingBoxDimensions {
  width?: number;
  height?: number;
  transformedWidth?: number;
  transformedHeight?: number;
  transformedOffsetX?: number;
  transformedOffsetY?: number;
}


const client = generateClient();

const logger = new ConsoleLogger('VisualEditorModal');

// Memoized component to render a bounding box on an image
interface BoundingBoxProps {
  box: Record<string, unknown> | null;
  page: string;
  currentPage: string;
  imageRef: React.RefObject<HTMLImageElement | null>;
  zoomLevel?: number;
  panOffset?: { x: number; y: number };
}
const BoundingBox = memo(({ box, page, currentPage, imageRef, zoomLevel = 1, panOffset = { x: 0, y: 0 } }: BoundingBoxProps) => {
  const [dimensions, setDimensions] = useState<BoundingBoxDimensions>({ width: 0, height: 0 });

  useEffect(() => {
    if (imageRef.current && page === currentPage) {
      const updateDimensions = () => {
        const img = imageRef.current;
        if (!img || !img.parentElement) return;
        const rect = img.getBoundingClientRect();
        const containerRect = img.parentElement.getBoundingClientRect();

        // Get the actual displayed dimensions and position after all transforms
        const transformedWidth = rect.width;
        const transformedHeight = rect.height;
        const transformedOffsetX = rect.left - containerRect.left;
        const transformedOffsetY = rect.top - containerRect.top;

        setDimensions({
          transformedWidth,
          transformedHeight,
          transformedOffsetX,
          transformedOffsetY,
        });

        logger.debug('VisualEditorModal - BoundingBox dimensions updated:', {
          imageWidth: img.width,
          imageHeight: img.height,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          offsetX: rect.left - containerRect.left,
          offsetY: rect.top - containerRect.top,
          imageRect: rect,
          containerRect,
        });
      };

      // Update dimensions when image loads
      if (imageRef.current.complete && imageRef.current.naturalWidth > 0) {
        updateDimensions();
      } else {
        imageRef.current.addEventListener('load', updateDimensions);
      }

      return () => {
        if (imageRef.current) {
          imageRef.current.removeEventListener('load', updateDimensions);
        }
      };
    }
    return undefined;
  }, [imageRef, page, currentPage]);

  // Update dimensions when zoom or pan changes
  useEffect(() => {
    if (imageRef.current && page === currentPage) {
      const updateDimensions = () => {
        const img = imageRef.current;
        if (!img || !img.parentElement) return;
        const rect = img.getBoundingClientRect();
        const containerRect = img.parentElement.getBoundingClientRect();

        // Get the actual displayed dimensions and position after all transforms
        const transformedWidth = rect.width;
        const transformedHeight = rect.height;
        const transformedOffsetX = rect.left - containerRect.left;
        const transformedOffsetY = rect.top - containerRect.top;

        setDimensions({
          transformedWidth,
          transformedHeight,
          transformedOffsetX,
          transformedOffsetY,
        });
      };
      // Delay to allow transforms to complete
      const timeoutId = setTimeout(updateDimensions, 150);
      // Ensure accuracy after reset
      const secondTimeoutId = setTimeout(updateDimensions, 300);
      return () => {
        clearTimeout(timeoutId);
        clearTimeout(secondTimeoutId);
      };
    }
    return undefined;
  }, [zoomLevel, panOffset, imageRef, page, currentPage]);

  if (page !== currentPage || !box || !dimensions.transformedWidth) {
    return null;
  }

  // Calculate position based on image dimensions with proper zoom and pan handling
  if (!box.boundingBox) {
    return null;
  }

  const padding = 5;
  const bbox = box.boundingBox as { left: number; top: number; width: number; height: number };

  // Calculate position and size directly on the transformed image
  const finalLeft = bbox.left * (dimensions.transformedWidth ?? 0) + (dimensions.transformedOffsetX ?? 0) - padding;
  const finalTop = bbox.top * (dimensions.transformedHeight ?? 0) + (dimensions.transformedOffsetY ?? 0) - padding;
  const finalWidth = bbox.width * (dimensions.transformedWidth ?? 0) + padding * 2;
  const finalHeight = bbox.height * (dimensions.transformedHeight ?? 0) + padding * 2;

  // Position the bounding box directly without additional transforms
  const style = {
    position: 'absolute',
    left: `${finalLeft}px`,
    top: `${finalTop}px`,
    width: `${finalWidth}px`,
    height: `${finalHeight}px`,
    border: '2px solid red',
    pointerEvents: 'none',
    zIndex: 10,
    transition: 'all 0.1s ease-out',
  };

  logger.debug('VisualEditorModal - BoundingBox style calculated:', {
    bbox,
    dimensions,
    finalLeft,
    finalTop,
    finalWidth,
    finalHeight,
    style,
  });

  return <div style={style as React.CSSProperties} />;
});

BoundingBox.displayName = 'BoundingBox';


interface VisualEditorModalProps {
  visible: boolean;
  onDismiss: () => void;
  jsonData: Record<string, unknown> | null;
  onChange: ((jsonString: string) => void) | null;
  isReadOnly: boolean;
  sectionData: Record<string, unknown> | null;
  allSections?: Array<{ Id: string; Class: string; PageIds: number[]; OutputJSONUri?: string }>;
  currentSectionIndex?: number;
  onNavigateToSection?: ((index: number) => void) | null;
}

const VisualEditorModal = ({
  visible,
  onDismiss,
  jsonData,
  onChange,
  isReadOnly,
  sectionData,
  // Section navigation props
  allSections = [],
  currentSectionIndex = 0,
  onNavigateToSection,
}: VisualEditorModalProps) => {
  const { currentCredentials, user } = useAppContext();
  const { settings } = useSettingsContext();
  // Role flags from the Cognito token (reliable regardless of how the modal was
  // opened). Reviewers (Admin/Reviewer) cannot call uploadDocument (Admin/Author
  // only), so their edits must be saved via completeSectionReview — see handleSaveChanges.
  const { canWrite, canReview } = useUserRole();
  // Pin page-image previews to the selected run when viewing a past version.
  const { versionIdForUri, runId: viewingRunId } = useDocumentVersion();
  const [pageImages, setPageImages] = useState<Record<string, string>>({});
  const [loadingImages, setLoadingImages] = useState(true);
  const [currentPage, setCurrentPage] = useState<string | number | null>(null);
  const [activeFieldGeometry, setActiveFieldGeometry] = useState<Record<string, unknown> | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [localJsonData, setLocalJsonData] = useState<Record<string, unknown> | null>(jsonData);
  // Evaluation comparison state
  const [baselineData, setBaselineData] = useState<Record<string, unknown> | null>(null);
  const [evaluationResults, setEvaluationResults] = useState<Record<string, unknown> | null>(null);
  const [loadingEvaluation, setLoadingEvaluation] = useState(false);
  const [showEvaluation, setShowEvaluation] = useState(false);
  // Collapse/expand state - stores path keys of collapsed items
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(new Set());
  // Filter mode state
  const [filterMode, setFilterMode] = useState('none'); // 'none', 'confidence-alerts', 'eval-mismatches'

  // Change tracking state for saving edits
  const [predictionChanges, setPredictionChanges] = useState<Map<string, { original: unknown; current: unknown }>>(new Map());
  const [baselineChanges, setBaselineChanges] = useState<Map<string, { original: unknown; current: unknown }>>(new Map());
  const [originalPredictionData, setOriginalPredictionData] = useState<Record<string, unknown> | null>(null);
  const [originalBaselineData, setOriginalBaselineData] = useState<Record<string, unknown> | null>(null);
  const [localBaselineData, setLocalBaselineData] = useState<Record<string, unknown> | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [_saveError, setSaveError] = useState<string | null>(null);
  const [_showUnsavedChangesModal, setShowUnsavedChangesModal] = useState(false);
  const [_pendingDismiss, setPendingDismiss] = useState(false);
  // Tab navigation state
  const [activeTabId, setActiveTabId] = useState('visual');

  // Drag-to-pan state
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const imageRef = useRef<HTMLImageElement | null>(null);

  // Toggle collapse handler
  const handleToggleCollapse = (pathKey: string) => {
    setCollapsedPaths((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(pathKey)) {
        newSet.delete(pathKey);
      } else {
        newSet.add(pathKey);
      }
      return newSet;
    });
  };

  // Expand all handler
  const handleExpandAll = () => {
    setCollapsedPaths(new Set());
  };

  // Collapse all handler - recursively collapse ALL arrays and objects at every level
  const handleCollapseAll = () => {
    // Get inferenceResult from jsonData - same logic used later in component
    const result = localJsonData?.inference_result || localJsonData?.inferenceResult || localJsonData;
    const allPaths = new Set<string>();

    // Recursive function to add all collapsible paths
    const addCollapsiblePaths = (obj: unknown, currentPath: string) => {
      if (obj && typeof obj === 'object') {
        if (Array.isArray(obj)) {
          // This is an array - add its path and recurse into items
          if (currentPath) {
            allPaths.add(currentPath);
          }
          obj.forEach((item, index) => {
            addCollapsiblePaths(item, `${currentPath}.[${index}]`);
          });
        } else {
          // This is an object - add its path and recurse into properties
          if (currentPath) {
            allPaths.add(currentPath);
          }
          Object.entries(obj).forEach(([key, val]) => {
            if (Array.isArray(val) || (typeof val === 'object' && val !== null)) {
              const newPath = currentPath ? `${currentPath}.${key}` : key;
              addCollapsiblePaths(val, newPath);
            }
          });
        }
      }
    };

    if (result && typeof result === 'object') {
      Object.entries(result).forEach(([key, val]) => {
        if (Array.isArray(val) || (typeof val === 'object' && val !== null)) {
          addCollapsiblePaths(val, `Document Data.${key}`);
        }
      });
    }

    setCollapsedPaths(allPaths);
  };
  const imageContainerRef = useRef<HTMLDivElement | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Check if baseline is available - check multiple possible paths
  const sectionDocItem = sectionData?.documentItem as Record<string, unknown> | undefined;
  const evaluationStatus = sectionDocItem?.evaluationStatus || sectionDocItem?.EvaluationStatus;
  const isBaselineAvailable = evaluationStatus === 'BASELINE_AVAILABLE' || evaluationStatus === 'COMPLETED';

  // Construct baseline URI from output URI
  const constructBaselineUri = (outputUri: string | undefined) => {
    if (!outputUri) {
      logger.debug('constructBaselineUri: No output URI provided');
      return null;
    }
    const outputBucketName = (settings as Record<string, unknown>)?.OutputBucket as string | undefined;
    const baselineBucketName = (settings as Record<string, unknown>)?.EvaluationBaselineBucket as string | undefined;

    logger.debug('constructBaselineUri:', { outputUri, outputBucketName, baselineBucketName });

    if (!outputBucketName || !baselineBucketName) {
      logger.warn('Bucket names not available in settings:', { outputBucketName, baselineBucketName });
      return null;
    }
    const match = outputUri.match(/^s3:\/\/([^/]+)\/(.+)$/);
    if (!match) {
      logger.warn('Invalid S3 URI format:', outputUri);
      return null;
    }
    const [, , objectKey] = match;
    const baselineUri = `s3://${baselineBucketName}/${objectKey}`;
    logger.debug('Constructed baseline URI:', baselineUri);
    return baselineUri;
  };

  // Construct evaluation results URI from input key
  const constructEvaluationResultsUri = (inputKey: string | undefined, outputBucket: string | undefined) => {
    if (!inputKey || !outputBucket) {
      return null;
    }
    return `s3://${outputBucket}/${inputKey}/evaluation/results.json`;
  };

  // Load baseline data and evaluation results when modal opens
  useEffect(() => {
    logger.debug('Evaluation load effect:', {
      visible,
      isBaselineAvailable,
      evaluationStatus,
      hasBaselineData: !!baselineData,
      hasEvaluationResults: !!evaluationResults,
      outputUri: sectionData?.OutputJSONUri,
    });

    if (!visible || !isBaselineAvailable) return;
    if (baselineData && evaluationResults) return; // Already loaded

    const loadEvaluationData = async () => {
      const outputUri = sectionData?.OutputJSONUri as string | undefined;
      // inputKey can be objectKey or inputKey depending on context
      const inputKey = sectionDocItem?.objectKey || sectionDocItem?.inputKey || sectionDocItem?.InputKey;
      const outputBucket =
        sectionDocItem?.outputBucket ||
        sectionDocItem?.OutputBucket ||
        (settings as Record<string, unknown>)?.OutputBucket;

      setLoadingEvaluation(true);
      try {
        // Load baseline data
        const baselineUri = constructBaselineUri(outputUri);
        if (baselineUri && !baselineData) {
          try {
            const baselineResponse = await client.graphql({
              query: getFileContents,
              variables: { s3Uri: baselineUri },
            });
            const baselineResult = baselineResponse.data.getFileContents;
            if (baselineResult && !baselineResult.isBinary && baselineResult.content) {
              const parsed = JSON.parse(baselineResult.content);
              setBaselineData(parsed);
              logger.info('Baseline data loaded successfully');
            }
          } catch (error) {
            logger.warn('Failed to load baseline data:', error instanceof Error ? error.message : error);
          }
        }

        // Load evaluation results
        const evalResultsUri = constructEvaluationResultsUri(inputKey as string | undefined, outputBucket as string | undefined);
        if (evalResultsUri && !evaluationResults) {
          try {
            const evalResponse = await client.graphql({
              query: getFileContents,
              variables: { s3Uri: evalResultsUri },
            });
            const evalResult = (evalResponse as { data: { getFileContents: { isBinary: boolean; content: string } } }).data.getFileContents;
            if (!evalResult.isBinary && evalResult.content) {
              const parsed = JSON.parse(evalResult.content);
              setEvaluationResults(parsed);
              logger.info('Evaluation results loaded successfully:', parsed);
            }
          } catch (error) {
            logger.warn('Failed to load evaluation results:', (error as Error).message);
          }
        }
      } finally {
        setLoadingEvaluation(false);
      }
    };

    loadEvaluationData();
  }, [visible, isBaselineAvailable, sectionData?.OutputJSONUri, sectionDocItem?.inputKey, settings]);

  // Reset evaluation state when modal closes
  useEffect(() => {
    if (!visible) {
      setBaselineData(null);
      setEvaluationResults(null);
      setShowEvaluation(false);
      setLoadingEvaluation(false);
    }
  }, [visible]);

  // Check if section needs review (either low confidence or HITL triggered)
  const _needsReview =
    (sectionData?.confidenceAlertCount as number) > 0 || (sectionDocItem?.hitlTriggered && !sectionDocItem?.hitlCompleted);

  // Check if this specific section is already completed
  const _isSectionCompleted = sectionData?.isSectionCompleted || false;

  // Check if user is reviewer only (not admin)
  const _isReviewerOnly = sectionData?.isReviewerOnly || false;

  // Sync local data with props and store original for change tracking
  useEffect(() => {
    setLocalJsonData(jsonData);
    // Store original prediction data for change tracking (deep copy)
    // Only set once on initial load (when originalPredictionData is null)
    if (jsonData) {
      logger.info('🔧 useEffect - setting localJsonData', { hasJsonData: !!jsonData, hasOriginal: !!originalPredictionData });
      if (!originalPredictionData) {
        const originalCopy = JSON.parse(JSON.stringify(jsonData));
        setOriginalPredictionData(originalCopy);
        logger.info('🔧 Set originalPredictionData:', { keys: Object.keys(originalCopy || {}) });
      }
    }
  }, [jsonData]);

  // Initialize localBaselineData when baselineData loads
  useEffect(() => {
    if (baselineData && !localBaselineData) {
      setLocalBaselineData(JSON.parse(JSON.stringify(baselineData)));
      setOriginalBaselineData(JSON.parse(JSON.stringify(baselineData)));
    }
  }, [baselineData]);

  // Calculate change counts for display
  const predictionChangeCount = predictionChanges.size;
  const baselineChangeCount = baselineChanges.size;
  const hasUnsavedChanges = predictionChangeCount > 0 || baselineChangeCount > 0;

  // Track a field change
  const trackPredictionChange = (fieldPath: string, originalValue: unknown, newValue: unknown) => {
    logger.info('📝 TRACK PREDICTION CHANGE:', { fieldPath, originalValue, newValue });
    setPredictionChanges((prev) => {
      const newMap = new Map(prev);
      if (JSON.stringify(originalValue) === JSON.stringify(newValue)) {
        // Value reverted to original, remove from changes
        newMap.delete(fieldPath);
        logger.info('📝 Removed from changes (reverted):', fieldPath);
      } else {
        newMap.set(fieldPath, { original: originalValue, current: newValue });
        logger.info('📝 Added to changes:', { fieldPath, mapSize: newMap.size, allKeys: [...newMap.keys()] });
      }
      return newMap;
    });
  };

  const trackBaselineChange = (fieldPath: string, originalValue: unknown, newValue: unknown) => {
    setBaselineChanges((prev) => {
      const newMap = new Map(prev);
      if (JSON.stringify(originalValue) === JSON.stringify(newValue)) {
        newMap.delete(fieldPath);
      } else {
        newMap.set(fieldPath, { original: originalValue, current: newValue });
      }
      return newMap;
    });
  };

  // Discard all changes
  const handleDiscardAllChanges = () => {
    if (originalPredictionData) {
      setLocalJsonData(JSON.parse(JSON.stringify(originalPredictionData)));
    }
    if (originalBaselineData) {
      setLocalBaselineData(JSON.parse(JSON.stringify(originalBaselineData)));
    }
    setPredictionChanges(new Map());
    setBaselineChanges(new Map());
  };

  // Save changes to S3
  const handleSaveChanges = async () => {
    setIsSaving(true);
    setSaveError(null);

    try {
      // Extract the actual file path from OutputJSONUri to ensure we save to the exact same location
      const outputUri = sectionData?.OutputJSONUri as string | undefined;
      logger.info('💾 handleSaveChanges - outputUri:', outputUri);

      if (!outputUri) {
        throw new Error('Cannot determine output URI for saving');
      }

      // Parse the S3 URI to get bucket and key
      const outputUriMatch = outputUri.match(/^s3:\/\/([^/]+)\/(.+)$/);
      if (!outputUriMatch) {
        throw new Error(`Invalid S3 URI format: ${outputUri}`);
      }
      const [, outputBucketFromUri, outputFileKey] = outputUriMatch;
      logger.info('💾 Parsed output URI:', { bucket: outputBucketFromUri, key: outputFileKey });

      // Reviewers are NOT authorized to call the `uploadDocument` mutation
      // (restricted to Admin/Author by RBAC). They persist HITL edits through
      // the reviewer-permitted `completeSectionReview` mutation instead.
      // Derive this from the Cognito token (canReview && !canWrite = reviewer,
      // not Admin/Author) rather than relying solely on the `isReviewerOnly`
      // prop, which some SectionsPanel FileViewer entry points hardcode to false.
      const isReviewerOnly = (canReview && !canWrite) || Boolean(sectionData?.isReviewerOnly);

      const results: {
        predictions: { success: boolean; changedFields: string[] } | null;
        baseline: { success: boolean; changedFields: string[] } | null;
      } = { predictions: null, baseline: null };

      // Build combined edit entry for both files
      const username = user?.username || 'unknown';
      const timestamp = new Date().toISOString();

      // Build prediction diffs
      const predictionDiffs: Record<string, { originalValue: unknown; newValue: unknown }> = {};
      predictionChanges.forEach((change: { original: unknown; current: unknown }, fieldPath: string) => {
        predictionDiffs[fieldPath] = {
          originalValue: change.original,
          newValue: change.current,
        };
      });

      // Build baseline diffs
      const baselineDiffs: Record<string, { originalValue: unknown; newValue: unknown }> = {};
      baselineChanges.forEach((change: { original: unknown; current: unknown }, fieldPath: string) => {
        baselineDiffs[fieldPath] = {
          originalValue: change.original,
          newValue: change.current,
        };
      });

      // Combined edit entry that will be saved to both files
      const editEntry = {
        timestamp,
        editedBy: username,
        predictionEdits: {
          changedFields: [...predictionChanges.keys()],
          changeCount: predictionChangeCount,
          diffs: predictionDiffs,
        },
        baselineEdits: {
          changedFields: [...baselineChanges.keys()],
          changeCount: baselineChangeCount,
          diffs: baselineDiffs,
        },
      };

      // Save predictions if changed
      if (predictionChangeCount > 0) {
        logger.info('💾 Saving prediction changes...', { count: predictionChangeCount });

        // Add edit history metadata with combined changes
        const dataToSave: Record<string, unknown> = { ...localJsonData };
        const editHistory = (dataToSave._editHistory as unknown[]) || [];
        editHistory.push(editEntry);
        dataToSave._editHistory = editHistory;

        // Reviewers are NOT authorized to call the `uploadDocument` mutation
        // (restricted to Admin/Author by RBAC). They persist their HITL edits
        // through the reviewer-permitted `completeSectionReview` mutation, which
        // writes the full JSON to the section's output URI server-side (no
        // presigned URL needed) and records the section as reviewed. The
        // Admin/Author presigned-upload path is preserved below.
        if (isReviewerOnly) {
          const reviewObjectKey = (sectionDocItem?.ObjectKey ||
            sectionDocItem?.objectKey ||
            sectionDocItem?.key ||
            sectionDocItem?.Key ||
            sectionDocItem?.id ||
            sectionDocItem?.Id) as string | undefined;
          const reviewSectionId = (sectionData?.Id ?? sectionData?.SectionId) as string | number | undefined;

          if (!reviewObjectKey) {
            throw new Error('Cannot determine document object key for saving reviewer changes');
          }
          if (reviewSectionId === undefined || reviewSectionId === null) {
            throw new Error('Cannot determine section id for saving reviewer changes');
          }

          logger.info('💾 Saving prediction changes via completeSectionReview (reviewer path):', {
            objectKey: reviewObjectKey,
            sectionId: reviewSectionId,
          });

          const reviewResponse = await client.graphql({
            query: completeSectionReview,
            variables: {
              objectKey: reviewObjectKey,
              sectionId: String(reviewSectionId),
              // editedData is AWSJSON — send the full JSON structure as a string.
              // The resolver saves it verbatim to the section's output URI.
              editedData: JSON.stringify(dataToSave),
            },
          });

          if (!reviewResponse?.data?.completeSectionReview) {
            throw new Error('completeSectionReview returned no data');
          }
          logger.info('✅ Predictions saved via completeSectionReview');
        } else {
          // Admin/Author path: request a presigned upload URL and write to S3 directly.
          // Use the exact same path from the original output URI
          logger.info('💾 Prediction file path:', outputFileKey);

          // Extract prefix (directory) and filename for uploadDocument
          const predictionPrefix = outputFileKey.substring(0, outputFileKey.lastIndexOf('/'));
          const predictionFilename = outputFileKey.split('/').pop() ?? outputFileKey;

          const predictionUploadResponse = await client.graphql({
            query: uploadDocument,
            variables: {
              fileName: predictionFilename,
              prefix: predictionPrefix,
              contentType: 'application/json',
              bucket: outputBucketFromUri,
            },
          });

          const predUploadData = predictionUploadResponse.data.uploadDocument;
          const predictionPresignedUrl = predUploadData.presignedUrl;
          const predictionUsePost = predUploadData.usePostMethod?.toLowerCase() === 'true';

          // Upload the JSON data
          const predictionContent = JSON.stringify(dataToSave, null, 2);

          if (predictionUsePost) {
            // POST method using presigned POST data (contains url + fields)
            const presignedPostData = JSON.parse(predictionPresignedUrl);
            const formData = new FormData();

            // Add all required fields from presigned POST data
            Object.entries(presignedPostData.fields).forEach(([key, fieldValue]) => {
              formData.append(key, fieldValue as string);
            });

            // Append the file content as last field (required for S3 presigned POST)
            const blob = new Blob([predictionContent], { type: 'application/json' });
            formData.append('file', blob, predictionFilename);

            logger.info('📤 Uploading predictions via presigned POST to:', presignedPostData.url);
            const uploadResponse = await fetch(presignedPostData.url, {
              method: 'POST',
              body: formData,
            });

            if (!uploadResponse.ok) {
              const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
              throw new Error(`Prediction upload failed: ${errorText}`);
            }
          } else {
            // PUT method (standard presigned URL)
            await fetch(predictionPresignedUrl, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: predictionContent,
            });
          }

          logger.info('✅ Predictions saved successfully');
        }

        results.predictions = { success: true, changedFields: [...predictionChanges.keys()] };
      }

      // Save baseline if changed.
      // Baseline edits are an evaluation/Author feature and require the
      // `uploadDocument` mutation (Admin/Author only). Reviewers cannot write to
      // the EvaluationBaselineBucket, so skip the baseline save for reviewers to
      // avoid an Unauthorized error (they should not be editing baselines).
      if (baselineChangeCount > 0 && localBaselineData && !isReviewerOnly) {
        logger.info('💾 Saving baseline changes...', { count: baselineChangeCount });

        // Add edit history metadata with combined changes (same as predictions)
        const baselineToSave: Record<string, unknown> = { ...localBaselineData };
        const baselineEditHistory = (baselineToSave._editHistory as unknown[]) || [];
        baselineEditHistory.push(editEntry);
        baselineToSave._editHistory = baselineEditHistory;

        // Get presigned URL for baseline (EvaluationBaselineBucket)
        // Baseline uses the same path as predictions, just in a different bucket
        const baselineBucket = (settings as Record<string, unknown>)?.EvaluationBaselineBucket as string | undefined;
        if (!baselineBucket) {
          throw new Error('EvaluationBaselineBucket not configured in settings');
        }

        // Use the same file path as predictions (outputFileKey) since baseline mirrors the structure
        logger.info('💾 Baseline file path:', outputFileKey);

        // Extract prefix (directory) and filename for uploadDocument
        const baselinePrefix = outputFileKey.substring(0, outputFileKey.lastIndexOf('/'));
        const baselineFilename = outputFileKey.split('/').pop() ?? outputFileKey;

        const baselineUploadResponse = await client.graphql({
          query: uploadDocument,
          variables: {
            fileName: baselineFilename,
            prefix: baselinePrefix,
            contentType: 'application/json',
            bucket: baselineBucket,
          },
        });

        const baseUploadData = baselineUploadResponse.data.uploadDocument;
        const baselinePresignedUrl = baseUploadData.presignedUrl;
        const baselineUsePost = baseUploadData.usePostMethod?.toLowerCase() === 'true';

        // Upload the JSON data
        const baselineContent = JSON.stringify(baselineToSave, null, 2);

        if (baselineUsePost) {
          // POST method using presigned POST data (contains url + fields)
          const presignedPostData = JSON.parse(baselinePresignedUrl);
          const formData = new FormData();

          // Add all required fields from presigned POST data
          Object.entries(presignedPostData.fields).forEach(([key, fieldValue]) => {
            formData.append(key, fieldValue as string);
          });

          // Append the file content as last field (required for S3 presigned POST)
          const blob = new Blob([baselineContent], { type: 'application/json' });
          formData.append('file', blob, baselineFilename as string);

          logger.info('📤 Uploading baseline via presigned POST to:', presignedPostData.url);
          const uploadResponse = await fetch(presignedPostData.url, {
            method: 'POST',
            body: formData,
          });

          if (!uploadResponse.ok) {
            const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
            throw new Error(`Baseline upload failed: ${errorText}`);
          }
        } else {
          // PUT method (standard presigned URL)
          await fetch(baselinePresignedUrl, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: baselineContent,
          });
        }

        results.baseline = { success: true, changedFields: [...baselineChanges.keys()] };
        logger.info('✅ Baseline saved successfully');
      }

      // Success! Reset change tracking and update originals for what was saved.
      setOriginalPredictionData(JSON.parse(JSON.stringify(localJsonData)));
      setPredictionChanges(new Map());

      // Baseline edits are only persisted on the Admin/Author path. For reviewers
      // the baseline save is skipped, so keep their baseline changes (and the
      // "unsaved" indicator) rather than silently discarding them and falsely
      // reporting success.
      const baselineSkippedForReviewer = isReviewerOnly && baselineChangeCount > 0;
      if (!baselineSkippedForReviewer) {
        if (localBaselineData) {
          setOriginalBaselineData(JSON.parse(JSON.stringify(localBaselineData)));
        }
        setBaselineChanges(new Map());
      }

      // Show an accurate message about what was (and wasn't) saved.
      const savedItems = [];
      if (results.predictions) savedItems.push(`${results.predictions.changedFields.length} prediction field(s)`);
      if (results.baseline) savedItems.push(`${results.baseline.changedFields.length} baseline field(s)`);

      let saveMessage = savedItems.length > 0 ? `✅ Successfully saved:\n${savedItems.join('\n')}` : 'ℹ️ No changes were saved.';
      if (baselineSkippedForReviewer) {
        saveMessage += `\n\n⚠️ ${baselineChangeCount} baseline edit(s) were NOT saved — editing evaluation baselines requires an Author or Admin role.`;
      }
      alert(saveMessage);
    } catch (error) {
      logger.error('❌ Error saving changes:', error);
      setSaveError((error as Error).message || 'Failed to save changes');
      alert(`❌ Error saving changes:\n${(error as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Debounced parent onChange function with non-blocking execution
  const debouncedParentOnChange = (jsonString: string) => {
    // Clear existing timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Set new timer - call parent after 1 second of no typing
    debounceTimerRef.current = setTimeout(() => {
      if (onChange) {
        const parentCallStart = performance.now();
        logger.debug('🚀 DEBOUNCED PARENT onChange - Calling parent onChange...');

        // Use requestIdleCallback to ensure parent onChange doesn't block UI
        // If not available, fall back to setTimeout with 0 delay
        const executeParentChange = () => {
          try {
            onChange(jsonString);
            const parentCallEnd = performance.now();
            logger.debug('🏁 DEBOUNCED PARENT onChange - Parent onChange completed:', {
              duration: `${(parentCallEnd - parentCallStart).toFixed(2)}ms`,
            });
          } catch (error) {
            logger.error('Error in parent onChange:', error);
          }
        };

        if (window.requestIdleCallback) {
          // Use requestIdleCallback to run during browser idle time
          window.requestIdleCallback(executeParentChange, { timeout: 5000 });
        } else {
          // Fallback: use setTimeout to yield control back to browser
          setTimeout(executeParentChange, 0);
        }
      }
    }, 1000); // 1 second debounce
  };

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  // Extract inference results and page IDs from local data for immediate UI updates
  const inferenceResult = localJsonData?.inference_result || localJsonData?.inferenceResult || localJsonData;
  const pageIds = (sectionData?.PageIds as Array<string | number>) || [];

  // Load page images - only when modal opens or when core data changes
  useEffect(() => {
    if (!visible) {
      // Reset state when modal closes
      setPageImages({});
      setCurrentPage(null);
      setActiveFieldGeometry(null);
      return;
    }

    const loadImages = async () => {
      if (!pageIds || pageIds.length === 0) {
        setLoadingImages(false);
        return;
      }

      setLoadingImages(true);

      try {
        const documentPages = (sectionDocItem?.pages as Record<string, unknown>[]) || [];
        logger.debug('VisualEditorModal - Loading images for pageIds:', pageIds);

        const images: Record<string, string> = {};

        await Promise.all(
          pageIds.map(async (pageId: unknown) => {
            // Find the page in the document's pages array by matching the Id
            const page = documentPages.find((p: Record<string, unknown>) => p.Id === pageId);

            if (page?.ImageUri) {
              try {
                logger.debug(`VisualEditorModal - generating presigned URL for page ${pageId}`);
                const url = await generateS3PresignedUrl(page.ImageUri as string, currentCredentials as Record<string, unknown>, {
                  versionId: versionIdForUri(page.ImageUri as string),
                });
                images[String(pageId)] = url;
              } catch (err) {
                logger.error(`Error generating presigned URL for page ${pageId}:`, err);
              }
            }
          }),
        );

        logger.debug('VisualEditorModal - Successfully loaded images for', Object.keys(images).length, 'pages');

        setPageImages(images);

        // Set the first page as current if not already set
        if (!currentPage && pageIds.length > 0) {
          setCurrentPage(pageIds[0]);
        }
      } catch (err) {
        logger.error('Error loading page images:', err);
      } finally {
        setLoadingImages(false);
      }
    };

    loadImages();
    // Only reload images when modal opens or when pageIds/sectionData changes, not when switching pages
  }, [visible, pageIds, sectionDocItem?.pages, currentCredentials, viewingRunId]);

  // Zoom controls
  const handleZoomIn = () => {
    setZoomLevel((prev) => Math.min(prev * 1.25, 4));
  };

  const handleZoomOut = () => {
    setZoomLevel((prev) => Math.max(prev / 1.25, 0.25));
  };

  // Pan controls
  const panStep = 50;

  const handlePanLeft = () => {
    setPanOffset((prev) => ({ ...prev, x: prev.x + panStep }));
  };

  const handlePanRight = () => {
    setPanOffset((prev) => ({ ...prev, x: prev.x - panStep }));
  };

  const handlePanUp = () => {
    setPanOffset((prev) => ({ ...prev, y: prev.y + panStep }));
  };

  const handlePanDown = () => {
    setPanOffset((prev) => ({ ...prev, y: prev.y - panStep }));
  };

  const handleResetView = () => {
    setZoomLevel(1);
    setPanOffset({ x: 0, y: 0 });
  };

  // Handle mouse wheel for zoom (no modifier key needed)
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 1.1 : 0.9;
    setZoomLevel((prev) => Math.min(Math.max(prev * delta, 0.25), 4));
  };

  // Handle drag-to-pan - mouse down starts drag
  const handleMouseDown = (e: React.MouseEvent) => {
    // Only pan when zoomed in
    if (zoomLevel <= 1) return;

    // Prevent default to avoid text selection
    e.preventDefault();
    setIsDragging(true);
    setDragStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
  };

  // Handle drag-to-pan - mouse move updates pan offset
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;

    e.preventDefault();
    const newX = e.clientX - dragStart.x;
    const newY = e.clientY - dragStart.y;
    setPanOffset({ x: newX, y: newY });
  };

  // Handle drag-to-pan - mouse up ends drag
  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // Handle mouse leave - end drag if mouse leaves the container
  const handleMouseLeave = () => {
    if (isDragging) {
      setIsDragging(false);
    }
  };

  // Handle field focus - update active field geometry and switch to the correct page
  // This function is intentionally kept lightweight and independent of debounced operations
  const handleFieldFocus = (geometry: Record<string, unknown> | null) => {
    const focusStart = performance.now();
    logger.debug('VisualEditorModal - handleFieldFocus START:', { timestamp: focusStart });

    // Use setTimeout to make this completely asynchronous and non-blocking
    setTimeout(() => {
      if (geometry) {
        setActiveFieldGeometry(geometry);

        // If geometry has a page field, switch to that page
        if (geometry.page !== undefined && pageIds.length > 0) {
          const pageIndex = (geometry.page as number) - 1;
          if (pageIndex >= 0 && pageIndex < pageIds.length) {
            const targetPageId = pageIds[pageIndex];
            setCurrentPage(targetPageId);
          }
        }
      } else {
        setActiveFieldGeometry(null);
      }

      const focusEnd = performance.now();
      logger.debug('VisualEditorModal - handleFieldFocus END:', {
        duration: `${(focusEnd - focusStart).toFixed(2)}ms`,
      });
    }, 0);
  };

  // Handle field double-click - zoom to 200% and center on field
  const handleFieldDoubleClick = (geometry: Record<string, unknown> | null) => {
    logger.debug('VisualEditorModal - handleFieldDoubleClick called with geometry:', geometry);

    if (geometry && imageRef.current && imageContainerRef.current) {
      // First switch to the correct page if needed
      if (geometry.page !== undefined && pageIds.length > 0) {
        const pageIndex = (geometry.page as number) - 1;
        if (pageIndex >= 0 && pageIndex < pageIds.length) {
          const targetPageId = pageIds[pageIndex];
          if (targetPageId !== currentPage) {
            setCurrentPage(targetPageId);
          }
        }
      }

      // Set zoom to 200%
      const targetZoom = 2.0;
      setZoomLevel(targetZoom);

      // Calculate pan offset to center the field
      setTimeout(() => {
        if (imageRef.current && imageContainerRef.current) {
          const img = imageRef.current;
          const container = imageContainerRef.current;

          // Get image and container dimensions
          const imgRect = img.getBoundingClientRect();
          const containerRect = container.getBoundingClientRect();

          const imageWidth = img.width || img.naturalWidth;
          const imageHeight = img.height || img.naturalHeight;
          const offsetX = imgRect.left - containerRect.left;
          const offsetY = imgRect.top - containerRect.top;

          // Get bounding box coordinates
          const bbox = geometry?.boundingBox as { left: number; top: number; width: number; height: number } | undefined;

          if (bbox) {
            const { left, top, width, height } = bbox;

            // Calculate field center in image coordinates
            const fieldCenterX = (left + width / 2) * imageWidth + offsetX;
            const fieldCenterY = (top + height / 2) * imageHeight + offsetY;

            // Calculate viewport center
            const viewportCenterX = containerRect.width / 2;
            const viewportCenterY = containerRect.height / 2;

            // Calculate image center
            const imageCenterX = offsetX + imageWidth / 2;
            const imageCenterY = offsetY + imageHeight / 2;

            // Calculate relative position of field center from image center
            const relativeX = fieldCenterX - imageCenterX;
            const relativeY = fieldCenterY - imageCenterY;

            // At 200% zoom, calculate where the field center will be
            const scaledRelativeX = relativeX * targetZoom;
            const scaledRelativeY = relativeY * targetZoom;

            // Calculate required pan offset to center the field in viewport
            const requiredPanX = viewportCenterX - (imageCenterX + scaledRelativeX);
            const requiredPanY = viewportCenterY - (imageCenterY + scaledRelativeY);

            logger.debug('VisualEditorModal - Auto-centering calculation:', {
              fieldCenterX,
              fieldCenterY,
              viewportCenterX,
              viewportCenterY,
              imageCenterX,
              imageCenterY,
              relativeX,
              relativeY,
              scaledRelativeX,
              scaledRelativeY,
              requiredPanX,
              requiredPanY,
            });

            setPanOffset({ x: requiredPanX, y: requiredPanY });
          }
        }
      }, 100); // Small delay to allow zoom to take effect

      // Also set the active geometry for bounding box display
      setActiveFieldGeometry(geometry);
    }
  };

  // Create carousel items from page images
  const carouselItems = pageIds.map((pageId: unknown) => ({
    id: pageId,
    content: (
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions
      <div
        ref={pageId === currentPage ? imageContainerRef : null}
        style={{
          position: 'relative',
          width: '100%',
          height: '450px', // Fixed height for consistent container size across all sections
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          overflow: 'hidden',
          cursor: isDragging ? 'grabbing' : zoomLevel > 1 ? 'grab' : 'default',
          backgroundColor: '#f5f5f5', // Light background to show container bounds
          userSelect: 'none', // Prevent text selection during drag
          outline: 'none', // Remove focus outline for cleaner look
        }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        {pageImages[String(pageId)] ? (
          <>
            <img
              ref={pageId === currentPage ? imageRef : null}
              src={pageImages[String(pageId)]}
              alt={`Page ${pageId}`}
              style={{
                maxWidth: '100%',
                maxHeight: '100%', // Constrain to container height
                width: 'auto',
                height: 'auto',
                objectFit: 'contain',
                transform: `scale(${zoomLevel}) translate(${panOffset.x / zoomLevel}px, ${panOffset.y / zoomLevel}px)`,
                transformOrigin: 'center center',
                transition: 'transform 0.1s ease-out',
              }}
              onError={(e) => {
                logger.error(`Error loading image for page ${pageId}:`, e);
                // Fallback image for error state
                const fallbackImage =
                  'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6' +
                  'Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2Yw' +
                  'ZjBmMCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjAi' +
                  'IHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiM5OTkiPkltYWdlIGxvYWQgZXJyb3I8L3RleHQ+PC9zdmc+';
                (e.target as HTMLImageElement).src = fallbackImage;
              }}
            />
            {activeFieldGeometry && (
              <BoundingBox
                box={activeFieldGeometry}
                page={String(currentPage)}
                currentPage={String(currentPage)}
                imageRef={imageRef}
                zoomLevel={zoomLevel}
                panOffset={panOffset}
              />
            )}
          </>
        ) : (
          <ExtBox padding="xl" textAlign="center">
            <Spinner />
            <div>Loading image...</div>
          </ExtBox>
        )}
      </div>
    ),
  }));

  // Handle unsaved changes modal actions
  const _handleDiscardAndClose = () => {
    setShowUnsavedChangesModal(false);
    setPendingDismiss(false);
    handleDiscardAllChanges();
    onDismiss();
  };

  const _handleReturnToEditor = () => {
    setShowUnsavedChangesModal(false);
    setPendingDismiss(false);
  };

  return (
    <Modal
      onDismiss={() => {
        if (hasUnsavedChanges) {
          const confirmDiscard = window.confirm(
            `You have unsaved changes:\n` +
              `• ${predictionChangeCount} prediction edit(s)\n` +
              `• ${baselineChangeCount} baseline edit(s)\n\n` +
              `Discard changes and close?`,
          );
          if (confirmDiscard) {
            handleDiscardAllChanges();
            onDismiss();
          }
        } else {
          onDismiss();
        }
      }}
      visible={visible}
      header="Visual Document Editor"
      size="max"
      footer={
        <ExtBox>
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            {/* Left side - Section info */}
            <ExtBox>
              <SpaceBetween direction="horizontal" size="m">
                <ExtBox>
                  <strong>Section:</strong> {String(sectionData?.Id || sectionData?.SectionId || 'N/A')}
                </ExtBox>
                <ExtBox>
                  <strong>Type:</strong> {(localJsonData?.document_class as Record<string, unknown>)?.type as string || 'N/A'}
                </ExtBox>
              </SpaceBetween>
            </ExtBox>

            {/* Change indicator */}
            {!isReadOnly && hasUnsavedChanges && (
              <ExtBox color="text-status-warning">
                <SpaceBetween direction="horizontal" size="xs">
                  <span>📝</span>
                  <span>
                    Unsaved: {predictionChangeCount > 0 && `${predictionChangeCount} prediction`}
                    {predictionChangeCount > 0 && baselineChangeCount > 0 && ', '}
                    {baselineChangeCount > 0 && `${baselineChangeCount} baseline`}
                  </span>
                </SpaceBetween>
              </ExtBox>
            )}

            {/* Spacer */}
            <ExtBox style={{ flex: 1 }} />

            {/* Right side - buttons */}
            <SpaceBetween direction="horizontal" size="xs">
              {/* Discard button - only when there are changes */}
              {!isReadOnly && hasUnsavedChanges && (
                <Button variant="link" onClick={handleDiscardAllChanges}>
                  Discard All Changes
                </Button>
              )}

              {/* Save button - only when there are unsaved changes */}
              {!isReadOnly && hasUnsavedChanges && (
                <Button variant="primary" onClick={handleSaveChanges} loading={isSaving} disabled={isSaving}>
                  {isSaving ? 'Saving...' : 'Save All Changes'}
                </Button>
              )}

              {/* Section Navigation buttons */}
              {allSections.length > 1 && onNavigateToSection && (
                <>
                  <Button
                    iconName="angle-left"
                    variant="normal"
                    onClick={() => {
                      if (hasUnsavedChanges) {
                        alert('Please save or discard your changes before navigating to another section.');
                      } else if (currentSectionIndex > 0) {
                        onNavigateToSection(currentSectionIndex - 1);
                      }
                    }}
                    disabled={currentSectionIndex === 0 || hasUnsavedChanges}
                  >
                    Previous Section
                  </Button>
                  <Button
                    iconAlign="right"
                    iconName="angle-right"
                    variant="normal"
                    onClick={() => {
                      if (hasUnsavedChanges) {
                        alert('Please save or discard your changes before navigating to another section.');
                      } else if (currentSectionIndex < allSections.length - 1) {
                        onNavigateToSection(currentSectionIndex + 1);
                      }
                    }}
                    disabled={currentSectionIndex === allSections.length - 1 || hasUnsavedChanges}
                  >
                    Next Section
                  </Button>
                </>
              )}

              {/* Close button */}
              <Button
                variant={hasUnsavedChanges ? 'normal' : 'primary'}
                onClick={() => {
                  if (hasUnsavedChanges) {
                    const confirmDiscard = window.confirm(
                      `You have unsaved changes:\n` +
                        `• ${predictionChangeCount} prediction edit(s)\n` +
                        `• ${baselineChangeCount} baseline edit(s)\n\n` +
                        `Discard changes and close?`,
                    );
                    if (confirmDiscard) {
                      handleDiscardAllChanges();
                      onDismiss();
                    }
                  } else {
                    onDismiss();
                  }
                }}
              >
                Close
              </Button>
            </SpaceBetween>
          </SpaceBetween>
        </ExtBox>
      }
    >
      <Tabs
        activeTabId={activeTabId}
        onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
        tabs={[
          {
            id: 'visual',
            label: 'Visual Editor',
            content: (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'flex-start',
                  gap: '20px',
                  height: 'calc(100vh - 300px)',
                  maxHeight: '700px',
                  minHeight: '450px',
                  width: '100%',
                }}
              >
                {/* Left side - Page images carousel - Fixed height, non-scrollable */}
                <div
                  style={{
                    width: '50%',
                    minWidth: '50%',
                    maxWidth: '50%',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    flex: '0 0 50%',
                    overflow: 'hidden',
                  }}
                >
                  <Container header={<Header variant="h3">Document Pages ({pageIds.length})</Header>}>
                    <div style={{ height: '550px', display: 'flex', flexDirection: 'column' }}>
                      {(() => {
                        if (loadingImages) {
                          return (
                            <ExtBox padding="xl" textAlign="center">
                              <Spinner />
                              <div>Loading page images...</div>
                            </ExtBox>
                          );
                        }
                        if (carouselItems.length > 0) {
                          return (
                            <SpaceBetween size="xs">
                              {/* Image display area */}
                              <ExtBox style={{ position: 'relative', overflow: 'hidden', height: '450px', minHeight: '300px' }}>
                                {/* Display current page */}
                                {carouselItems.find((item: { id: unknown; content: React.ReactNode }) => item.id === currentPage)?.content}

                                {/* Simple navigation arrows */}
                                <ExtBox
                                  style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    position: 'absolute',
                                    width: '100%',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    pointerEvents: 'none',
                                  }}
                                >
                                  <Button
                                    iconName="angle-left"
                                    variant="icon"
                                    onClick={() => {
                                      const currentIndex = pageIds.indexOf(currentPage as string | number);
                                      if (currentIndex > 0) {
                                        setCurrentPage(pageIds[currentIndex - 1]);
                                        setActiveFieldGeometry(null);
                                      }
                                    }}
                                    disabled={pageIds.indexOf(currentPage as string | number) === 0}
                                  />
                                  <Button
                                    iconName="angle-right"
                                    variant="icon"
                                    onClick={() => {
                                      const currentIndex = pageIds.indexOf(currentPage as string | number);
                                      if (currentIndex < pageIds.length - 1) {
                                        setCurrentPage(pageIds[currentIndex + 1]);
                                        setActiveFieldGeometry(null);
                                      }
                                    }}
                                    disabled={pageIds.indexOf(currentPage as string | number) === pageIds.length - 1}
                                  />
                                </ExtBox>
                              </ExtBox>

                              {/* Controls area - outside of image area in normal flow */}
                              <ExtBox
                                style={{
                                  display: 'flex',
                                  flexDirection: 'column',
                                  alignItems: 'center',
                                  gap: '8px',
                                  padding: '8px 0',
                                }}
                              >
                                {/* Page indicator */}
                                <ExtBox
                                  style={{
                                    backgroundColor: 'rgba(240, 240, 240, 0.9)',
                                    padding: '4px 12px',
                                    borderRadius: '4px',
                                  }}
                                >
                                  Page {pageIds.indexOf(currentPage as string | number) + 1} of {pageIds.length}
                                </ExtBox>

                                {/* Zoom and Pan Controls */}
                                <ExtBox
                                  style={{
                                    backgroundColor: 'rgba(240, 240, 240, 0.9)',
                                    padding: '6px 12px',
                                    borderRadius: '4px',
                                    boxShadow: '0 1px 4px rgba(0, 0, 0, 0.1)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    fontSize: '12px',
                                  }}
                                >
                                  <span style={{ fontWeight: 'bold' }}>Zoom:</span>
                                  <span
                                    onClick={handleZoomOut}
                                    onKeyDown={(e) => e.key === 'Enter' && handleZoomOut()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel <= 0.25 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel <= 0.25 ? 0.5 : 1,
                                      fontSize: '14px',
                                      fontWeight: 'bold',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Zoom Out"
                                  >
                                    −
                                  </span>
                                  <span style={{ fontSize: '12px', minWidth: '30px', textAlign: 'center' }}>
                                    {Math.round(zoomLevel * 100)}%
                                  </span>
                                  <span
                                    onClick={handleZoomIn}
                                    onKeyDown={(e) => e.key === 'Enter' && handleZoomIn()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel >= 4 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel >= 4 ? 0.5 : 1,
                                      fontSize: '14px',
                                      fontWeight: 'bold',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Zoom In"
                                  >
                                    +
                                  </span>
                                  <span style={{ fontWeight: 'bold', marginLeft: '8px' }}>Pan:</span>
                                  <span
                                    onClick={handlePanLeft}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePanLeft()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel <= 1 ? 0.5 : 1,
                                      fontSize: '14px',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Pan Left"
                                  >
                                    ←
                                  </span>
                                  <span
                                    onClick={handlePanRight}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePanRight()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel <= 1 ? 0.5 : 1,
                                      fontSize: '14px',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Pan Right"
                                  >
                                    →
                                  </span>
                                  <span
                                    onClick={handlePanUp}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePanUp()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel <= 1 ? 0.5 : 1,
                                      fontSize: '14px',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Pan Up"
                                  >
                                    ↑
                                  </span>
                                  <span
                                    onClick={handlePanDown}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePanDown()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                                      opacity: zoomLevel <= 1 ? 0.5 : 1,
                                      fontSize: '14px',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                    }}
                                    title="Pan Down"
                                  >
                                    ↓
                                  </span>
                                  <span
                                    onClick={handleResetView}
                                    onKeyDown={(e) => e.key === 'Enter' && handleResetView()}
                                    role="button"
                                    tabIndex={0}
                                    style={{
                                      cursor: 'pointer',
                                      fontSize: '12px',
                                      userSelect: 'none',
                                      padding: '2px 4px',
                                      marginLeft: '4px',
                                    }}
                                    title="Reset View"
                                  >
                                    ⟲
                                  </span>
                                </ExtBox>
                              </ExtBox>
                            </SpaceBetween>
                          );
                        }
                        return (
                          <ExtBox padding="xl" textAlign="center">
                            No page images available
                          </ExtBox>
                        );
                      })()}
                    </div>
                  </Container>
                </div>

                {/* Right side - Form fields - Independently scrollable */}
                <div
                  style={{
                    width: '50%',
                    minWidth: '50%',
                    maxWidth: '50%',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    flex: '0 0 50%',
                    overflow: 'hidden',
                  }}
                >
                  <Container
                    header={
                      <Header
                        variant="h3"
                        actions={
                          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                            {/* Expand/Collapse controls */}
                            <Button variant="normal" onClick={handleExpandAll}>
                              + Expand All
                            </Button>
                            <Button variant="normal" onClick={handleCollapseAll}>
                              − Collapse All
                            </Button>
                            {/* Filter dropdown */}
                            <select
                              value={filterMode}
                              onChange={(e) => setFilterMode(e.target.value)}
                              style={{
                                padding: '4px 8px',
                                borderRadius: '4px',
                                border: '1px solid #ccc',
                              }}
                            >
                              <option value="none">Show All</option>
                              <option value="confidence-alerts">Confidence Alerts Only</option>
                              <option value="eval-mismatches" disabled={!showEvaluation}>
                                Eval Mismatches Only
                              </option>
                            </select>
                            {/* Evaluation toggle */}
                            {(isBaselineAvailable || loadingEvaluation) && (
                              <>
                                {loadingEvaluation && <Spinner {...({ size: 'small' } as Record<string, unknown>)} />}
                                <Toggle
                                  checked={showEvaluation}
                                  onChange={({ detail }) => {
                                    setShowEvaluation(detail.checked);
                                    // Reset filter when turning off evaluation
                                    if (!detail.checked) {
                                      setFilterMode('none');
                                    }
                                  }}
                                  disabled={loadingEvaluation || !baselineData}
                                >
                                  Show Evaluation
                                </Toggle>
                              </>
                            )}
                          </SpaceBetween>
                        }
                      >
                        Document Data
                      </Header>
                    }
                  >
                    <div
                      style={{
                        flex: 1,
                        overflowY: 'auto',
                        overflowX: 'hidden',
                        padding: '16px',
                        boxSizing: 'border-box',
                        maxHeight: '550px',
                        minHeight: '350px',
                      }}
                    >
                      <ExtBox style={{ minHeight: 'fit-content' }}>
                        {showEvaluation && baselineData && (
                          <Alert type="info" header="Evaluation Comparison Mode">
                            Showing predicted values with evaluation baseline. Fields with mismatches are highlighted with evaluation scores
                            and reasons.
                          </Alert>
                        )}
                        {inferenceResult ? (
                          <FormFieldRenderer
                            fieldKey="Document Data"
                            value={inferenceResult}
                            baselineValue={
                              showEvaluation
                                ? localBaselineData?.inference_result || localBaselineData?.inferenceResult || localBaselineData
                                : null
                            }
                            showComparison={showEvaluation}
                            evaluationResults={showEvaluation ? evaluationResults : null}
                            sectionId={sectionData?.Id || sectionData?.SectionId}
                            onBaselineChange={(newBaselineValue: Record<string, unknown>) => {
                              if (!isReadOnly && localBaselineData) {
                                const updatedBaseline = { ...localBaselineData };
                                if (updatedBaseline.inference_result) {
                                  updatedBaseline.inference_result = newBaselineValue;
                                } else if (updatedBaseline.inferenceResult) {
                                  updatedBaseline.inferenceResult = newBaselineValue;
                                } else {
                                  Object.keys(updatedBaseline).forEach((key) => {
                                    delete updatedBaseline[key];
                                  });
                                  Object.keys(newBaselineValue).forEach((key) => {
                                    updatedBaseline[key] = newBaselineValue[key];
                                  });
                                }
                                setLocalBaselineData(updatedBaseline);

                                // Track baseline changes at field level
                                if (originalBaselineData) {
                                  const originalBaselineResult =
                                    originalBaselineData.inference_result || originalBaselineData.inferenceResult || originalBaselineData;
                                  // Find what changed by comparing (excluding array indices from path)
                                  const findBaselineChanges = (original: unknown, current: unknown, pathParts: string[] = []) => {
                                    if (typeof current !== 'object' || current === null) {
                                      const pathStr = pathParts.join('.') || 'root';
                                      if (JSON.stringify(original) !== JSON.stringify(current)) {
                                        trackBaselineChange(pathStr, original, current);
                                      } else {
                                        // Value reverted to original
                                        setBaselineChanges((prev) => {
                                          const newMap = new Map(prev);
                                          newMap.delete(pathStr);
                                          return newMap;
                                        });
                                      }
                                      return;
                                    }
                                    if (Array.isArray(current)) {
                                      current.forEach((item, idx) => {
                                        const origItem = original && Array.isArray(original) ? original[idx] : undefined;
                                        // Don't add index to path - just recurse into item
                                        findBaselineChanges(origItem, item, pathParts);
                                      });
                                    } else {
                                      Object.keys(current).forEach((key) => {
                                        const origVal = original ? (original as Record<string, unknown>)[key] : undefined;
                                        findBaselineChanges(origVal, (current as Record<string, unknown>)[key], [...pathParts, key]);
                                      });
                                    }
                                  };
                                  findBaselineChanges(originalBaselineResult, newBaselineValue);
                                }
                              }
                            }}
                            onChange={(newValue: Record<string, unknown>) => {
                              if (!isReadOnly) {
                                // Update local state immediately for responsive UI
                                const updatedData = { ...localJsonData };
                                if (updatedData.inference_result) {
                                  updatedData.inference_result = newValue;
                                } else if (updatedData.inferenceResult) {
                                  updatedData.inferenceResult = newValue;
                                } else {
                                  // If there's no inference_result field, update the entire object
                                  Object.keys(updatedData).forEach((key) => {
                                    delete updatedData[key];
                                  });
                                  Object.keys(newValue).forEach((key) => {
                                    updatedData[key] = newValue[key];
                                  });
                                }

                                // Update local state immediately for responsive UI
                                setLocalJsonData(updatedData);
                                logger.debug('💨 LOCAL UPDATE - Updated local state immediately');

                                // Track prediction changes by comparing with original
                                logger.info('🔄 onChange called - checking if we have original data:', {
                                  hasOriginalPredictionData: !!originalPredictionData,
                                  isReadOnly,
                                });
                                if (originalPredictionData) {
                                  const originalInferenceResult =
                                    originalPredictionData.inference_result ||
                                    originalPredictionData.inferenceResult ||
                                    originalPredictionData;
                                  logger.info('🔄 Comparing values:', {
                                    newValueType: typeof newValue,
                                    originalType: typeof originalInferenceResult,
                                    areDifferent: JSON.stringify(newValue) !== JSON.stringify(originalInferenceResult),
                                  });
                                  // Simple comparison - if different, mark as changed
                                  if (JSON.stringify(newValue) !== JSON.stringify(originalInferenceResult)) {
                                    // Find what changed by comparing
                                    // Note: paths exclude array indices to match FormFieldRenderer's path calculation
                                    const findChanges = (original: unknown, current: unknown, pathParts: string[] = []) => {
                                      if (typeof current !== 'object' || current === null) {
                                        const pathStr = pathParts.join('.') || 'root';
                                        if (JSON.stringify(original) !== JSON.stringify(current)) {
                                          trackPredictionChange(pathStr, original, current);
                                        }
                                        return;
                                      }
                                      if (Array.isArray(current)) {
                                        current.forEach((item, idx) => {
                                          const origItem = original && Array.isArray(original) ? original[idx] : undefined;
                                          // Don't add index to path - just recurse into item
                                          findChanges(origItem, item, pathParts);
                                        });
                                      } else {
                                        Object.keys(current).forEach((key) => {
                                          const origVal = original ? (original as Record<string, unknown>)[key] : undefined;
                                          findChanges(origVal, (current as Record<string, unknown>)[key], [...pathParts, key]);
                                        });
                                      }
                                    };
                                    findChanges(originalInferenceResult, newValue);
                                  } else {
                                    // No changes - clear tracking
                                    setPredictionChanges(new Map());
                                  }
                                }

                                // Debounce expensive parent call
                                if (onChange) {
                                  const jsonStart = performance.now();
                                  logger.debug('🔄 DEBOUNCED - JSON stringify starting...');

                                  try {
                                    const jsonString = JSON.stringify(updatedData, null, 2);
                                    const jsonEnd = performance.now();
                                    logger.debug('✅ DEBOUNCED - JSON stringify completed:', {
                                      duration: `${(jsonEnd - jsonStart).toFixed(2)}ms`,
                                      jsonLength: jsonString.length,
                                    });

                                    // Call debounced parent onChange
                                    debouncedParentOnChange(jsonString);
                                  } catch (error) {
                                    logger.error('Error stringifying JSON:', error);
                                  }
                                }
                              }
                            }}
                            isReadOnly={isReadOnly}
                            onFieldFocus={handleFieldFocus}
                            onFieldDoubleClick={handleFieldDoubleClick}
                            path={[]}
                            explainabilityInfo={jsonData?.explainability_info}
                            mergedConfig={sectionData?.mergedConfig}
                            collapsedPaths={collapsedPaths}
                            onToggleCollapse={handleToggleCollapse}
                            filterMode={filterMode}
                            displayPath={[]}
                            predictionChanges={predictionChanges}
                            baselineChanges={baselineChanges}
                          />
                        ) : (
                          <ExtBox padding="xl" textAlign="center">
                            No data available
                          </ExtBox>
                        )}
                      </ExtBox>
                    </div>
                  </Container>
                </div>
              </div>
            ),
          },
          {
            id: 'json',
            label: 'JSON Editor',
            content: (
              <JSONEditorTab
                predictionData={localJsonData}
                baselineData={localBaselineData}
                isReadOnly={Boolean(isReadOnly)}
                showBaseline={showEvaluation}
                onShowBaselineChange={(checked) => setShowEvaluation(checked)}
                isBaselineAvailable={isBaselineAvailable}
                loadingEvaluation={loadingEvaluation}
                onPredictionChange={(newPredictionValue) => {
                  if (!isReadOnly) {
                    // Update local state - wrap back in the expected structure
                    const updatedData = { ...localJsonData };
                    if (updatedData.inference_result) {
                      updatedData.inference_result = newPredictionValue;
                    } else if (updatedData.inferenceResult) {
                      updatedData.inferenceResult = newPredictionValue;
                    } else {
                      // Update the root level
                      Object.keys(updatedData).forEach((key) => {
                        if (key !== '_editHistory' && key !== 'explainability_info') {
                          delete updatedData[key];
                        }
                      });
                      Object.keys(newPredictionValue).forEach((key) => {
                        updatedData[key] = newPredictionValue[key];
                      });
                    }
                    setLocalJsonData(updatedData);

                    // Track changes
                    if (originalPredictionData) {
                      const originalInferenceResult =
                        originalPredictionData.inference_result || originalPredictionData.inferenceResult || originalPredictionData;
                      if (JSON.stringify(newPredictionValue) !== JSON.stringify(originalInferenceResult)) {
                        trackPredictionChange('json-edit', originalInferenceResult, newPredictionValue);
                      }
                    }
                  }
                }}
                onBaselineChange={(newBaselineValue) => {
                  if (!isReadOnly && localBaselineData) {
                    const updatedBaseline = { ...localBaselineData };
                    if (updatedBaseline.inference_result) {
                      updatedBaseline.inference_result = newBaselineValue;
                    } else if (updatedBaseline.inferenceResult) {
                      updatedBaseline.inferenceResult = newBaselineValue;
                    } else {
                      Object.keys(updatedBaseline).forEach((key) => {
                        if (key !== '_editHistory' && key !== 'explainability_info') {
                          delete updatedBaseline[key];
                        }
                      });
                      Object.keys(newBaselineValue).forEach((key) => {
                        updatedBaseline[key] = newBaselineValue[key];
                      });
                    }
                    setLocalBaselineData(updatedBaseline);

                    // Track changes
                    if (originalBaselineData) {
                      const originalBaselineResult =
                        originalBaselineData.inference_result || originalBaselineData.inferenceResult || originalBaselineData;
                      if (JSON.stringify(newBaselineValue) !== JSON.stringify(originalBaselineResult)) {
                        trackBaselineChange('json-edit', originalBaselineResult, newBaselineValue);
                      }
                    }
                  }
                }}
              />
            ),
          },
          {
            id: 'history',
            label: 'Revision History',
            content: <EditHistoryTab predictionData={localJsonData} baselineData={localBaselineData} />,
          },
          {
            id: 'processing',
            label: 'Processing Report',
            content: (
              <ProcessingReportTab
                metadata={localJsonData?.metadata as Record<string, unknown> | undefined}
                processingReport={localJsonData?.processing_report as string | undefined}
                inferenceResult={
                  (localJsonData?.inference_result || localJsonData?.inferenceResult) as
                    | Record<string, unknown>
                    | undefined
                }
                processingIssues={
                  (localJsonData?.metadata as Record<string, unknown> | undefined)?.processing_issues as
                    | { stage?: string; severity?: string; code?: string; message?: string; rootCause?: string }[]
                    | undefined
                }
              />
            ),
          },
        ]}
      />
    </Modal>
  );
};

export default VisualEditorModal;
