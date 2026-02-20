// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable prettier/prettier */
/* eslint-disable prefer-destructuring */

import React, { useState, useEffect, useRef, memo } from 'react';
import {
  Modal,
  Box,
  SpaceBetween,
  FormField,
  Input,
  Checkbox,
  Container,
  Header,
  Spinner,
  Button,
  Toggle,
  Alert,
  Tabs,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import { getFieldConfidenceInfo } from '../common/confidence-alerts-utils';
import getFileContents from '../../graphql/queries/getFileContents';
import uploadDocument from '../../graphql/queries/uploadDocument';
import JSONEditorTab from './JSONEditorTab';
import type { BoxProps } from '@cloudscape-design/components';
import EditHistoryTab from './EditHistoryTab';

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

type FileContentsResponse = {
  data: { getFileContents: { isBinary: boolean; content: string } };
};
type UploadDocResponse = {
  data: { uploadDocument: { presignedUrl: string; usePostMethod: boolean } };
};

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
  const finalLeft = bbox.left * dimensions.transformedWidth + dimensions.transformedOffsetX - padding;
  const finalTop = bbox.top * dimensions.transformedHeight + dimensions.transformedOffsetY - padding;
  const finalWidth = bbox.width * dimensions.transformedWidth + padding * 2;
  const finalHeight = bbox.height * dimensions.transformedHeight + padding * 2;

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

// Memoized component to render a form field based on its type
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const FormFieldRenderer = memo<Record<string, any>>(
  ({
    fieldKey,
    value,
    onChange,
    onBaselineChange, // New prop for baseline editing
    isReadOnly,
    confidence,
    geometry,
    onFieldFocus,
    onFieldDoubleClick,
    path = [],
    explainabilityInfo = null,
    mergedConfig = null,
    baselineValue = null,
    showComparison = false,
    evaluationResults = null,
    sectionId = null,
    collapsedPaths = new Set(),
    onToggleCollapse,
    filterMode = 'none', // 'none', 'confidence-alerts', 'eval-mismatches'
    displayPath = [], // Separate path for collapse tracking (includes "Document Data" and display keys)
    // Change tracking props
    predictionChanges = new Map(),
    baselineChanges = new Map(),
    _onRevertPrediction = null,
    _onRevertBaseline = null,
  }) => {
    // Calculate path key for collapse state using displayPath
    const pathKey = [...displayPath, fieldKey].join('.');
    const isCollapsed = collapsedPaths.has(pathKey);

    // Helper to check if a value has confidence alerts (recursively)
    const hasConfidenceAlertInTree = (val, currentFilteredPath, explainInfo, config) => {
      // Handle null/undefined values - they can still have low confidence in explainability_info
      if (val === null || val === undefined) {
        const fieldInfo = getFieldConfidenceInfo(fieldKey, explainInfo, currentFilteredPath, config);
        if (fieldInfo.hasConfidenceInfo && fieldInfo.displayMode === 'with-threshold' && !fieldInfo.isAboveThreshold) {
          return true;
        }
        return false;
      }

      // For primitives, check if this field has low confidence
      if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
        const fieldInfo = getFieldConfidenceInfo(fieldKey, explainInfo, currentFilteredPath, config);
        if (fieldInfo.hasConfidenceInfo && fieldInfo.displayMode === 'with-threshold' && !fieldInfo.isAboveThreshold) {
          return true;
        }
      }

      // For objects, check each property
      if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
        return Object.entries(val).some(([k, v]) => {
          const nestedPath = [...currentFilteredPath, k];
          return hasConfidenceAlertInTreeDeep(v, k, nestedPath, explainInfo, config);
        });
      }

      // For arrays, check each item
      if (Array.isArray(val)) {
        return val.some((item, idx) => {
          const nestedPath = [...currentFilteredPath, idx];
          return hasConfidenceAlertInTreeDeep(item, `[${idx}]`, nestedPath, explainInfo, config);
        });
      }

      return false;
    };

    // Deep helper that takes fieldKey as parameter
    const hasConfidenceAlertInTreeDeep = (val, fKey, currentFilteredPath, explainInfo, config) => {
      // Handle null/undefined values - they can still have low confidence in explainability_info
      if (val === null || val === undefined) {
        const fieldInfo = getFieldConfidenceInfo(fKey, explainInfo, currentFilteredPath.slice(0, -1), config);
        if (fieldInfo.hasConfidenceInfo && fieldInfo.displayMode === 'with-threshold' && !fieldInfo.isAboveThreshold) {
          return true;
        }
        return false;
      }

      if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
        const fieldInfo = getFieldConfidenceInfo(fKey, explainInfo, currentFilteredPath.slice(0, -1), config);
        if (fieldInfo.hasConfidenceInfo && fieldInfo.displayMode === 'with-threshold' && !fieldInfo.isAboveThreshold) {
          return true;
        }
      }

      if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
        return Object.entries(val).some(([k, v]) => {
          const nestedPath = [...currentFilteredPath, k];
          return hasConfidenceAlertInTreeDeep(v, k, nestedPath, explainInfo, config);
        });
      }

      if (Array.isArray(val)) {
        return val.some((item, idx) => {
          const nestedPath = [...currentFilteredPath, idx];
          return hasConfidenceAlertInTreeDeep(item, `[${idx}]`, nestedPath, explainInfo, config);
        });
      }

      return false;
    };

    // Helper to check if a value has eval mismatches (recursively)
    const hasEvalMismatchInTree = (val, baseval, evalResults, secId) => {
      if (!evalResults?.section_results) return false;

      // For primitives, check direct mismatch
      if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
        if (baseval !== null && JSON.stringify(val) !== JSON.stringify(baseval)) {
          return true;
        }
      }

      // For objects, check each property
      if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
        return Object.entries(val).some(([k, v]) => {
          const nestedBaseline = baseval && typeof baseval === 'object' ? baseval[k] : null;
          return hasEvalMismatchInTree(v, nestedBaseline, evalResults, secId);
        });
      }

      // For arrays, check each item
      if (Array.isArray(val)) {
        return val.some((item, idx) => {
          const nestedBaseline = baseval && Array.isArray(baseval) ? baseval[idx] : null;
          return hasEvalMismatchInTree(item, nestedBaseline, evalResults, secId);
        });
      }

      return false;
    };

    // Get confidence information from explainability data (for all fields)
    // Filter out structural keys from the path for explainability lookup
    // We need to remove top-level keys like 'inference_result', 'explainability_info', 'Document Data', etc.
    const structuralKeys = ['inference_result', 'inferenceResult', 'explainability_info', 'Document Data'];
    let filteredPath = path.filter((pathSegment) => !structuralKeys.includes(pathSegment) && typeof pathSegment !== 'undefined');

    // Remove the field name itself from the path if it's the last element
    // The path should point to the parent container, not include the field name
    if (filteredPath.length > 0 && filteredPath[filteredPath.length - 1] === fieldKey) {
      filteredPath = filteredPath.slice(0, -1);
    }

    // Check if this field should be filtered out
    const shouldFilterEval = filterMode === 'eval-mismatches' && showComparison;
    const shouldFilterConfidence = filterMode === 'confidence-alerts';

    const hasMismatchInSubtree = shouldFilterEval ? hasEvalMismatchInTree(value, baselineValue, evaluationResults, sectionId) : true;

    // When checking for confidence alerts in a subtree, we need to include the current fieldKey in the path
    // so that the recursive check can properly navigate the explainability data structure.
    // Without this, paths like "ServiceInformation.[1].Charges" would incorrectly try to navigate
    // explainabilityData[1] instead of explainabilityData.ServiceInformation[1]
    // However:
    // 1. For array items, fieldKey is a display string like "[1]" which shouldn't be added to the path
    //    because the numeric index is already present in the path from the parent's recursive call.
    // 2. For primitive/leaf fields, don't add fieldKey because hasConfidenceAlertInTree uses fieldKey
    //    separately when calling getFieldConfidenceInfo - adding it would cause duplication.
    const isArrayItemDisplay = fieldKey.startsWith('[') && fieldKey.endsWith(']');
    const isPrimitiveValue = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null;
    const pathForAlertCheck =
      structuralKeys.includes(fieldKey) || isArrayItemDisplay || isPrimitiveValue ? filteredPath : [...filteredPath, fieldKey];
    const hasConfidenceAlertInSubtree = shouldFilterConfidence
      ? hasConfidenceAlertInTree(value, pathForAlertCheck, explainabilityInfo, mergedConfig)
      : true;

    // If filter is active and no matches in subtree, hide this field (except root)
    if (shouldFilterEval && !hasMismatchInSubtree && fieldKey !== 'Document Data') {
      return null;
    }
    if (shouldFilterConfidence && !hasConfidenceAlertInSubtree && fieldKey !== 'Document Data') {
      return null;
    }

    // Look up evaluation result for this field from evaluationResults
    let evalResult = null;
    if (showComparison && evaluationResults?.section_results) {
      // Get section result (use first if only one)
      let sectionResult = evaluationResults.section_results.find((sr) => String(sr.section_id) === String(sectionId));
      if (!sectionResult && evaluationResults.section_results.length === 1) {
        sectionResult = evaluationResults.section_results[0];
      }

      if (sectionResult?.attributes?.length > 0) {
        // Build the path string from current path and fieldKey
        // path is like [index, "bankInfo"] and fieldKey is like "bank"
        // We need to match against field_comparison_details paths like "checks[0].bankInfo.bank"
        const _fullPath = [...path, fieldKey].filter((p) => p !== undefined && p !== 'Document Data');

        // Look through all attributes' field_comparison_details to find a match
        for (const attr of sectionResult.attributes) {
          if (attr.field_comparison_details && Array.isArray(attr.field_comparison_details)) {
            // Search field_comparison_details for paths that end with our field/path
            for (const detail of attr.field_comparison_details) {
              const expectedKey = detail.expected_key || '';
              // Check if this detail matches our path
              // For nested paths like "checks[0].bankInfo" when looking at "bank" field
              // We check if the actual/expected values contain our field

              // Also extract leaf-level field values from actual_value/expected_value
              if (detail.actual_value && typeof detail.actual_value === 'object') {
                // Check if our fieldKey is a property in actual_value
                if (fieldKey in detail.actual_value) {
                  evalResult = {
                    matched: detail.match,
                    score: detail.score,
                    threshold: attr.evaluation_threshold, // Get threshold from parent attribute
                    reason: detail.reason,
                    expected: detail.expected_value?.[fieldKey],
                    actual: detail.actual_value?.[fieldKey],
                    parentPath: expectedKey,
                  };
                  break;
                }
              }
            }
            if (evalResult) break;
          }
        }
      }
    }

    // Use evaluation result for match status if available, otherwise compare values
    const hasEvalResult = evalResult !== null && evalResult !== undefined;
    const isMatchedFromEval = hasEvalResult ? evalResult.matched : null;
    const valuesMatch = hasEvalResult
      ? isMatchedFromEval
      : !showComparison || baselineValue === null || JSON.stringify(value) === JSON.stringify(baselineValue);
    const hasMismatch = showComparison && baselineValue !== null && !valuesMatch;

    // Extract score, threshold, and reason from evaluation result
    const evalScore = evalResult?.score;
    const _evalThreshold = evalResult?.threshold;
    const evalReason = evalResult?.reason;

    // Determine field type
    let fieldType: string = typeof value;
    if (Array.isArray(value)) {
      fieldType = 'array';
    } else if (value === null || value === undefined) {
      fieldType = 'null';
    }

    const confidenceInfo = getFieldConfidenceInfo(fieldKey, explainabilityInfo, filteredPath, mergedConfig);

    // Determine color and style for confidence display
    let confidenceColor;
    let confidenceStyle;
    if (confidenceInfo.hasConfidenceInfo) {
      if (confidenceInfo.displayMode === 'with-threshold') {
        confidenceColor = confidenceInfo.isAboveThreshold ? 'text-status-success' : 'text-status-error';
        confidenceStyle = undefined;
      } else {
        confidenceColor = undefined;
        confidenceStyle = { color: confidenceInfo.textColor };
      }
    }

    // Create label with confidence score if available (legacy support)
    const label = confidence !== undefined ? `${fieldKey} (${(confidence * 100).toFixed(1)}%)` : fieldKey;

    // Handle field focus - pass geometry info if available
    const handleFocus = () => {
      if (geometry && onFieldFocus) {
        onFieldFocus(geometry);
      }
    };

    // Handle field click - optimized version
    const handleClick = (event) => {
      const clickStart = performance.now();
      logger.debug('🖱️ FIELD CLICK START:', { fieldKey, timestamp: clickStart });

      if (event) {
        event.stopPropagation();
      }

      let actualGeometry = geometry;

      // Try to extract geometry from explainabilityInfo if not provided
      if (!actualGeometry && explainabilityInfo && Array.isArray(explainabilityInfo) && explainabilityInfo[0]) {
        const [firstExplainabilityItem] = explainabilityInfo;

        // Try direct field lookup first
        let fieldInfo = firstExplainabilityItem[fieldKey];

        // If not found directly, try to navigate the full path
        if (!fieldInfo) {
          const fullPathParts = [...path, fieldKey];
          let pathFieldInfo = firstExplainabilityItem;

          fullPathParts.forEach((pathPart) => {
            if (pathFieldInfo && typeof pathFieldInfo === 'object') {
              if (Array.isArray(pathFieldInfo) && !Number.isNaN(parseInt(pathPart, 10))) {
                const arrayIndex = parseInt(pathPart, 10);
                if (arrayIndex >= 0 && arrayIndex < pathFieldInfo.length) {
                  pathFieldInfo = pathFieldInfo[arrayIndex];
                } else {
                  pathFieldInfo = null;
                }
              } else if (pathFieldInfo[pathPart]) {
                pathFieldInfo = pathFieldInfo[pathPart];
              } else {
                pathFieldInfo = null;
              }
            } else {
              pathFieldInfo = null;
            }
          });

          fieldInfo = pathFieldInfo;
        }

        if (fieldInfo && fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry[0]) {
          actualGeometry = fieldInfo.geometry[0];
        }
      }

      if (actualGeometry && onFieldFocus) {
        const focusStart = performance.now();
        logger.debug('🎯 FIELD FOCUS START:', { fieldKey, timestamp: focusStart });
        onFieldFocus(actualGeometry);
        const focusEnd = performance.now();
        logger.debug('✅ FIELD FOCUS END:', { fieldKey, duration: `${(focusEnd - focusStart).toFixed(2)}ms` });
      }

      const clickEnd = performance.now();
      logger.debug('🏁 FIELD CLICK END:', { fieldKey, totalDuration: `${(clickEnd - clickStart).toFixed(2)}ms` });
    };

    // Handle field double-click
    const handleDoubleClick = (event) => {
      if (event) {
        event.stopPropagation();
      }
      logger.debug('=== FIELD DOUBLE-CLICKED ===');
      logger.debug('Field Key:', fieldKey);
      logger.debug('Geometry Passed:', geometry);

      let actualGeometry = geometry;

      // Try to extract geometry from explainabilityInfo if not provided
      if (!actualGeometry && explainabilityInfo && Array.isArray(explainabilityInfo) && explainabilityInfo[0]) {
        const [firstExplainabilityItem] = explainabilityInfo;
        const fieldInfo = firstExplainabilityItem[fieldKey];

        if (fieldInfo && fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry[0]) {
          actualGeometry = fieldInfo.geometry[0];
        }
      }

      if (actualGeometry && onFieldDoubleClick) {
        logger.debug('Calling onFieldDoubleClick with geometry:', actualGeometry);
        onFieldDoubleClick(actualGeometry);
      } else {
        logger.debug('No geometry found for field double-click:', fieldKey);
      }
      logger.debug('=== END FIELD DOUBLE-CLICK ===');
    };

    // Check if this specific field has been edited (for visual highlighting)
    // Note: path already INCLUDES the current field key (from recursive calls like path={[...path, key]})
    // So we should NOT add fieldKey again - just filter the path to exclude array indices and structural keys
    const trackingPath = path.filter((p) => typeof p !== 'number' && p !== undefined && p !== 'Document Data');
    const fieldPathStr = trackingPath.join('.');
    const isPredictionChanged = predictionChanges.has(fieldPathStr);
    const isBaselineChanged = baselineChanges.has(fieldPathStr);
    const hasLocalEdit = isPredictionChanged || isBaselineChanged;

    // Debug logging for change tracking - only for leaf fields (strings/numbers)
    if ((predictionChanges.size > 0 || baselineChanges.size > 0) && (typeof value === 'string' || typeof value === 'number')) {
      logger.debug('🔍 Change tracking check:', {
        fieldKey,
        path,
        trackingPath,
        fieldPathStr,
        isPredictionChanged,
        isBaselineChanged,
        predictionKeys: [...predictionChanges.keys()],
        fieldType: typeof value,
      });
    }

    // Render based on field type
    switch (fieldType) {
      case 'string':
        return (
          <div
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onKeyDown={(e) => e.key === 'Enter' && handleClick(e)}
            role="button"
            tabIndex={0}
            style={{
              cursor: geometry ? 'pointer' : 'default',
              backgroundColor: hasMismatch && !hasLocalEdit ? 'rgba(255, 153, 0, 0.05)' : 'transparent',
              padding: '4px',
              borderRadius: '4px',
              borderLeft: hasMismatch && !hasLocalEdit ? '3px solid #ff9900' : '3px solid transparent',
            }}
          >
            <FormField
              label={
                <ExtBox>
                  <SpaceBetween direction="horizontal" size="xs">
                    <span>{fieldKey}:</span>
                    {isPredictionChanged && (
                      <ExtBox color="text-status-info" fontSize="body-s" fontWeight="bold">
                        ✏️ Edited
                      </ExtBox>
                    )}
                    {isBaselineChanged && !isPredictionChanged && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ✏️ Baseline Edited
                      </ExtBox>
                    )}
                    {hasMismatch && !hasLocalEdit && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ⚠ Mismatch
                      </ExtBox>
                    )}
                    {!hasMismatch && !hasLocalEdit && showComparison && baselineValue !== null && (
                      <ExtBox color="text-status-success" fontSize="body-s">
                        ✓ Match
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  {confidenceInfo.hasConfidenceInfo && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={confidenceColor} style={confidenceStyle}>
                      {confidenceInfo.displayMode === 'with-threshold'
                        ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                            confidenceInfo.confidenceThreshold * 100
                          ).toFixed(1)}%`
                        : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
                    </ExtBox>
                  )}
                  {showComparison && evalScore !== undefined && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={hasMismatch ? 'text-status-warning' : 'text-status-success'}>
                      {`Eval Score: ${(evalScore * 100).toFixed(1)}%`}
                      {evalReason && ` - ${evalReason}`}
                    </ExtBox>
                  )}
                </ExtBox>
              }
            >
              <SpaceBetween size="xxs">
                <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                  <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                    <ExtBox fontSize="body-s" color="text-body-secondary">
                      Predicted:
                    </ExtBox>
                    {isPredictionChanged && (
                      <ExtBox fontSize="body-s" color="text-status-info" fontWeight="bold">
                        ✏️
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      pointerEvents: isReadOnly ? 'none' : 'auto',
                      borderLeft: isPredictionChanged ? '3px solid #0073bb' : '3px solid transparent',
                      paddingLeft: '4px',
                      backgroundColor: isPredictionChanged ? 'rgba(0, 115, 187, 0.08)' : 'transparent',
                      borderRadius: '2px',
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      {isReadOnly ? (
                        <div
                          style={{
                            backgroundColor: '#e9ebed',
                            border: '1px solid #d5dbdb',
                            borderRadius: '4px',
                            minHeight: '32px',
                            display: 'flex',
                            alignItems: 'center',
                            color: '#16191f',
                            padding: '4px 8px',
                            fontSize: '14px',
                          }}
                        >
                          {value || ''}
                        </div>
                      ) : (
                        <Input value={value || ''} onChange={({ detail }) => onChange(detail.value)} onFocus={handleFocus} />
                      )}
                    </div>
                    {!isReadOnly && showComparison && baselineValue !== null && (
                      <Button
                        variant="inline-icon"
                        iconName="arrow-down"
                        ariaLabel="Copy predicted value to baseline"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onBaselineChange) {
                            onBaselineChange(value);
                          }
                        }}
                      />
                    )}
                  </div>
                </ExtBox>
                {showComparison && baselineValue !== null && (
                  <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                      <ExtBox fontSize="body-s" color="text-body-secondary">
                        Expected (baseline):
                      </ExtBox>
                      {isBaselineChanged && (
                        <ExtBox fontSize="body-s" color="text-status-warning" fontWeight="bold">
                          ✏️
                        </ExtBox>
                      )}
                    </SpaceBetween>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        pointerEvents: isReadOnly ? 'none' : 'auto',
                        borderLeft: isBaselineChanged ? '3px solid #ff9900' : '3px solid transparent',
                        paddingLeft: '4px',
                        backgroundColor: isBaselineChanged ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
                        borderRadius: '2px',
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        {isReadOnly ? (
                          <div
                            style={{
                              backgroundColor: '#e9ebed',
                              border: '1px solid #d5dbdb',
                              borderRadius: '4px',
                              minHeight: '32px',
                              display: 'flex',
                              alignItems: 'center',
                              color: '#16191f',
                              padding: '4px 8px',
                              fontSize: '14px',
                            }}
                          >
                            {String(baselineValue ?? '')}
                          </div>
                        ) : (
                          <Input
                            value={String(baselineValue ?? '')}
                            onChange={({ detail }) => {
                              if (onBaselineChange) {
                                onBaselineChange(detail.value);
                              }
                            }}
                          />
                        )}
                      </div>
                      {!isReadOnly && (
                        <Button
                          variant="inline-icon"
                          iconName="arrow-up"
                          ariaLabel="Copy baseline value to predicted"
                          onClick={(e) => {
                            e.stopPropagation();
                            onChange(baselineValue);
                          }}
                        />
                      )}
                    </div>
                  </ExtBox>
                )}
              </SpaceBetween>
            </FormField>
          </div>
        );

      case 'number':
        return (
          <div
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleClick(e);
              }
            }}
            role="button"
            tabIndex={0}
            style={{
              cursor: geometry ? 'pointer' : 'default',
              backgroundColor: hasMismatch && !hasLocalEdit ? 'rgba(255, 153, 0, 0.05)' : 'transparent',
              padding: '4px',
              borderRadius: '4px',
              borderLeft: hasMismatch && !hasLocalEdit ? '3px solid #ff9900' : '3px solid transparent',
            }}
          >
            <FormField
              label={
                <ExtBox>
                  <SpaceBetween direction="horizontal" size="xs">
                    <span>{fieldKey}:</span>
                    {isPredictionChanged && (
                      <ExtBox color="text-status-info" fontSize="body-s" fontWeight="bold">
                        ✏️ Edited
                      </ExtBox>
                    )}
                    {isBaselineChanged && !isPredictionChanged && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ✏️ Baseline Edited
                      </ExtBox>
                    )}
                    {hasMismatch && !hasLocalEdit && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ⚠ Mismatch
                      </ExtBox>
                    )}
                    {!hasMismatch && !hasLocalEdit && showComparison && baselineValue !== null && (
                      <ExtBox color="text-status-success" fontSize="body-s">
                        ✓ Match
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  {confidenceInfo.hasConfidenceInfo && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={confidenceColor} style={confidenceStyle}>
                      {confidenceInfo.displayMode === 'with-threshold'
                        ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                            confidenceInfo.confidenceThreshold * 100
                          ).toFixed(1)}%`
                        : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
                    </ExtBox>
                  )}
                  {showComparison && evalScore !== undefined && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={hasMismatch ? 'text-status-warning' : 'text-status-success'}>
                      {`Eval Score: ${(evalScore * 100).toFixed(1)}%`}
                      {evalReason && ` - ${evalReason}`}
                    </ExtBox>
                  )}
                </ExtBox>
              }
            >
              <SpaceBetween size="xxs">
                <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                  <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                    <ExtBox fontSize="body-s" color="text-body-secondary">
                      Predicted:
                    </ExtBox>
                    {isPredictionChanged && (
                      <ExtBox fontSize="body-s" color="text-status-info" fontWeight="bold">
                        ✏️
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      pointerEvents: isReadOnly ? 'none' : 'auto',
                      borderLeft: isPredictionChanged ? '3px solid #0073bb' : '3px solid transparent',
                      paddingLeft: '4px',
                      backgroundColor: isPredictionChanged ? 'rgba(0, 115, 187, 0.08)' : 'transparent',
                      borderRadius: '2px',
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      {isReadOnly ? (
                        <div
                          style={{
                            backgroundColor: '#e9ebed',
                            border: '1px solid #d5dbdb',
                            borderRadius: '4px',
                            minHeight: '32px',
                            display: 'flex',
                            alignItems: 'center',
                            color: '#16191f',
                            padding: '4px 8px',
                            fontSize: '14px',
                          }}
                        >
                          {String(value)}
                        </div>
                      ) : (
                        <Input
                          type="number"
                          value={String(value)}
                          onChange={({ detail }) => {
                            const numValue = Number(detail.value);
                            onChange(Number.isNaN(numValue) ? 0 : numValue);
                          }}
                          onFocus={handleFocus}
                        />
                      )}
                    </div>
                    {!isReadOnly && showComparison && baselineValue !== null && (
                      <Button
                        variant="inline-icon"
                        iconName="arrow-down"
                        ariaLabel="Copy predicted value to baseline"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onBaselineChange) {
                            onBaselineChange(value);
                          }
                        }}
                      />
                    )}
                  </div>
                </ExtBox>
                {showComparison && baselineValue !== null && (
                  <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                      <ExtBox fontSize="body-s" color="text-body-secondary">
                        Expected (baseline):
                      </ExtBox>
                      {isBaselineChanged && (
                        <ExtBox fontSize="body-s" color="text-status-warning" fontWeight="bold">
                          ✏️
                        </ExtBox>
                      )}
                    </SpaceBetween>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        pointerEvents: isReadOnly ? 'none' : 'auto',
                        borderLeft: isBaselineChanged ? '3px solid #ff9900' : '3px solid transparent',
                        paddingLeft: '4px',
                        backgroundColor: isBaselineChanged ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
                        borderRadius: '2px',
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        {isReadOnly ? (
                          <div
                            style={{
                              backgroundColor: '#e9ebed',
                              border: '1px solid #d5dbdb',
                              borderRadius: '4px',
                              minHeight: '32px',
                              display: 'flex',
                              alignItems: 'center',
                              color: '#16191f',
                              padding: '4px 8px',
                              fontSize: '14px',
                            }}
                          >
                            {String(baselineValue ?? '')}
                          </div>
                        ) : (
                          <Input
                            type="number"
                            value={String(baselineValue ?? '')}
                            onChange={({ detail }) => {
                              if (onBaselineChange) {
                                const numValue = Number(detail.value);
                                onBaselineChange(Number.isNaN(numValue) ? 0 : numValue);
                              }
                            }}
                          />
                        )}
                      </div>
                      {!isReadOnly && (
                        <Button
                          variant="inline-icon"
                          iconName="arrow-up"
                          ariaLabel="Copy baseline value to predicted"
                          onClick={(e) => {
                            e.stopPropagation();
                            onChange(baselineValue);
                          }}
                        />
                      )}
                    </div>
                  </ExtBox>
                )}
              </SpaceBetween>
            </FormField>
          </div>
        );

      case 'boolean':
        return (
          <div
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleClick(e);
              }
            }}
            role="button"
            tabIndex={0}
            style={{
              cursor: geometry ? 'pointer' : 'default',
              backgroundColor: hasMismatch && !hasLocalEdit ? 'rgba(255, 153, 0, 0.05)' : 'transparent',
              padding: '4px',
              borderRadius: '4px',
              borderLeft: hasMismatch && !hasLocalEdit ? '3px solid #ff9900' : '3px solid transparent',
            }}
          >
            <FormField
              label={
                <ExtBox>
                  <SpaceBetween direction="horizontal" size="xs">
                    <span>{fieldKey}:</span>
                    {isPredictionChanged && (
                      <ExtBox color="text-status-info" fontSize="body-s" fontWeight="bold">
                        ✏️ Edited
                      </ExtBox>
                    )}
                    {isBaselineChanged && !isPredictionChanged && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ✏️ Baseline Edited
                      </ExtBox>
                    )}
                    {hasMismatch && !hasLocalEdit && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ⚠ Mismatch
                      </ExtBox>
                    )}
                    {!hasMismatch && !hasLocalEdit && showComparison && baselineValue !== null && (
                      <ExtBox color="text-status-success" fontSize="body-s">
                        ✓ Match
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  {confidenceInfo.hasConfidenceInfo && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={confidenceColor} style={confidenceStyle}>
                      {confidenceInfo.displayMode === 'with-threshold'
                        ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                            confidenceInfo.confidenceThreshold * 100
                          ).toFixed(1)}%`
                        : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
                    </ExtBox>
                  )}
                  {showComparison && evalScore !== undefined && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={hasMismatch ? 'text-status-warning' : 'text-status-success'}>
                      {`Eval Score: ${(evalScore * 100).toFixed(1)}%`}
                      {evalReason && ` - ${evalReason}`}
                    </ExtBox>
                  )}
                </ExtBox>
              }
            >
              <SpaceBetween size="xxs">
                <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                  <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                    <ExtBox fontSize="body-s" color="text-body-secondary">
                      Predicted:
                    </ExtBox>
                    {isPredictionChanged && (
                      <ExtBox fontSize="body-s" color="text-status-info" fontWeight="bold">
                        ✏️
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      pointerEvents: isReadOnly ? 'none' : 'auto',
                      borderLeft: isPredictionChanged ? '3px solid #0073bb' : '3px solid transparent',
                      paddingLeft: '4px',
                      backgroundColor: isPredictionChanged ? 'rgba(0, 115, 187, 0.08)' : 'transparent',
                      borderRadius: '2px',
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      {isReadOnly ? (
                        <div
                          style={{
                            backgroundColor: '#e9ebed',
                            border: '1px solid #d5dbdb',
                            borderRadius: '4px',
                            minHeight: '32px',
                            display: 'flex',
                            alignItems: 'center',
                            color: '#16191f',
                            padding: '4px 8px',
                            fontSize: '14px',
                          }}
                        >
                          {String(value)}
                        </div>
                      ) : (
                        <Checkbox checked={Boolean(value)} onChange={({ detail }) => onChange(detail.checked)} onFocus={handleFocus}>
                          {String(value)}
                        </Checkbox>
                      )}
                    </div>
                    {!isReadOnly && showComparison && baselineValue !== null && (
                      <Button
                        variant="inline-icon"
                        iconName="arrow-down"
                        ariaLabel="Copy predicted value to baseline"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onBaselineChange) {
                            onBaselineChange(value);
                          }
                        }}
                      />
                    )}
                  </div>
                </ExtBox>
                {showComparison && baselineValue !== null && (
                  <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                      <ExtBox fontSize="body-s" color="text-body-secondary">
                        Expected (baseline):
                      </ExtBox>
                      {isBaselineChanged && (
                        <ExtBox fontSize="body-s" color="text-status-warning" fontWeight="bold">
                          ✏️
                        </ExtBox>
                      )}
                    </SpaceBetween>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        pointerEvents: isReadOnly ? 'none' : 'auto',
                        borderLeft: isBaselineChanged ? '3px solid #ff9900' : '3px solid transparent',
                        paddingLeft: '4px',
                        backgroundColor: isBaselineChanged ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
                        borderRadius: '2px',
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        {isReadOnly ? (
                          <div
                            style={{
                              backgroundColor: '#e9ebed',
                              border: '1px solid #d5dbdb',
                              borderRadius: '4px',
                              minHeight: '32px',
                              display: 'flex',
                              alignItems: 'center',
                              color: '#16191f',
                              padding: '4px 8px',
                              fontSize: '14px',
                            }}
                          >
                            {String(baselineValue ?? '')}
                          </div>
                        ) : (
                          <Checkbox
                            checked={Boolean(baselineValue)}
                            onChange={({ detail }) => {
                              if (onBaselineChange) {
                                onBaselineChange(detail.checked);
                              }
                            }}
                          >
                            {String(baselineValue ?? '')}
                          </Checkbox>
                        )}
                      </div>
                      {!isReadOnly && (
                        <Button
                          variant="inline-icon"
                          iconName="arrow-up"
                          ariaLabel="Copy baseline value to predicted"
                          onClick={(e) => {
                            e.stopPropagation();
                            onChange(baselineValue);
                          }}
                        />
                      )}
                    </div>
                  </ExtBox>
                )}
              </SpaceBetween>
            </FormField>
          </div>
        );

      case 'object':
        if (value === null) {
          return (
            <FormField label={label}>
              <div
                style={{
                  backgroundColor: '#e9ebed',
                  border: '1px solid #d5dbdb',
                  borderRadius: '4px',
                  minHeight: '32px',
                  display: 'flex',
                  alignItems: 'center',
                  fontStyle: 'italic',
                  color: '#545b64',
                  padding: '4px 8px',
                  fontSize: '14px',
                }}
              >
                null
              </div>
            </FormField>
          );
        }

        // Look for group-level eval result (e.g., for bankInfo, personalInfo)
        let groupEvalResult = null;
        if (showComparison && evaluationResults?.section_results) {
          let sectionResult = evaluationResults.section_results.find((sr) => String(sr.section_id) === String(sectionId));
          if (!sectionResult && evaluationResults.section_results.length === 1) {
            sectionResult = evaluationResults.section_results[0];
          }
          if (sectionResult?.attributes?.length > 0) {
            for (const attr of sectionResult.attributes) {
              if (attr.field_comparison_details) {
                // Find detail that matches this object path (e.g., checks[0].bankInfo)
                const detail = attr.field_comparison_details.find((d) => {
                  const key = d.expected_key || '';
                  // Check if the detail's expected_key ends with our fieldKey
                  return key.endsWith(`.${fieldKey}`) || key === fieldKey;
                });
                if (detail) {
                  groupEvalResult = {
                    matched: detail.match,
                    score: detail.score,
                    reason: detail.reason,
                  };
                  break;
                }
              }
            }
          }
        }

        return (
          <ExtBox
            padding="xs"
            style={{
              backgroundColor: groupEvalResult && !groupEvalResult.matched ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
              borderRadius: '4px',
            }}
          >
            <ExtBox fontSize="body-m" fontWeight="bold" padding="xxxs" onFocus={handleFocus}>
              <SpaceBetween direction="horizontal" size="xs">
                {onToggleCollapse && (
                  <span
                    onClick={() => onToggleCollapse(pathKey)}
                    onKeyDown={(e) => e.key === 'Enter' && onToggleCollapse(pathKey)}
                    role="button"
                    tabIndex={0}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                  >
                    {isCollapsed ? '▶' : '▼'}
                  </span>
                )}
                <span>{label}</span>
                {groupEvalResult && !groupEvalResult.matched && (
                  <ExtBox color="text-status-warning" fontSize="body-s">
                    ⚠
                  </ExtBox>
                )}
                {groupEvalResult && groupEvalResult.matched && showComparison && (
                  <ExtBox color="text-status-success" fontSize="body-s">
                    ✓
                  </ExtBox>
                )}
              </SpaceBetween>
              {showComparison && groupEvalResult && (
                <ExtBox fontSize="body-s" color={groupEvalResult.matched ? 'text-status-success' : 'text-status-warning'}>
                  {`Group Score: ${(groupEvalResult.score * 100).toFixed(1)}%`}
                  {groupEvalResult.reason && ` - ${groupEvalResult.reason}`}
                </ExtBox>
              )}
            </ExtBox>
            {!isCollapsed && (
              <ExtBox padding={{ left: 'l' }}>
                <SpaceBetween size="xs">
                  {Object.entries(value).map(([key, val]) => {
                    // Get confidence and geometry for this field from explainability_info
                    let fieldConfidence;
                    let fieldGeometry;

                    // Try to get from explainability_info if available
                    if (explainabilityInfo && Array.isArray(explainabilityInfo)) {
                      // Handle nested structure like explainabilityInfo[0].NAME_DETAILS.LAST_NAME
                      const currentPath = [...path, key];
                      const [firstExplainabilityItem] = explainabilityInfo;
                      // eslint-disable-next-line prefer-destructuring
                      let fieldInfo = firstExplainabilityItem;

                      // Navigate through the path to find the field info
                      let pathFieldInfo = fieldInfo;
                      currentPath.forEach((pathPart) => {
                        if (pathFieldInfo && typeof pathFieldInfo === 'object' && pathFieldInfo[pathPart]) {
                          pathFieldInfo = pathFieldInfo[pathPart];
                        } else {
                          pathFieldInfo = null;
                        }
                      });
                      fieldInfo = pathFieldInfo;

                      if (fieldInfo) {
                        fieldConfidence = fieldInfo.confidence;

                        // Extract geometry - handle both direct geometry and geometry arrays
                        if (fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry.length > 0) {
                          const geomData = fieldInfo.geometry[0];
                          if (geomData.boundingBox && geomData.page !== undefined) {
                            fieldGeometry = {
                              boundingBox: geomData.boundingBox,
                              page: geomData.page,
                              vertices: geomData.vertices,
                            };
                          }
                        }
                      }
                    }

                    // Get baseline value for this nested field
                    const nestedBaselineValue =
                      showComparison && baselineValue !== null && typeof baselineValue === 'object' ? baselineValue[key] : null;

                    return (
                      <FormFieldRenderer
                        key={`obj-${fieldKey}-${path.join('.')}-${key}`}
                        fieldKey={key}
                        value={val}
                        onChange={(newVal) => {
                          if (!isReadOnly) {
                            const newObj = { ...value };
                            newObj[key] = newVal;
                            onChange(newObj);
                          }
                        }}
                        onBaselineChange={
                          onBaselineChange
                            ? (newVal) => {
                                if (!isReadOnly && baselineValue) {
                                  const newObj = { ...baselineValue };
                                  newObj[key] = newVal;
                                  onBaselineChange(newObj);
                                }
                              }
                            : undefined
                        }
                        isReadOnly={isReadOnly}
                        confidence={fieldConfidence}
                        geometry={fieldGeometry}
                        onFieldFocus={onFieldFocus}
                        onFieldDoubleClick={onFieldDoubleClick}
                        path={[...path, key]}
                        explainabilityInfo={explainabilityInfo}
                        mergedConfig={mergedConfig}
                        baselineValue={nestedBaselineValue}
                        showComparison={showComparison}
                        evaluationResults={evaluationResults}
                        sectionId={sectionId}
                        collapsedPaths={collapsedPaths}
                        onToggleCollapse={onToggleCollapse}
                        filterMode={filterMode}
                        displayPath={[...displayPath, fieldKey]}
                        predictionChanges={predictionChanges}
                        baselineChanges={baselineChanges}
                      />
                    );
                  })}
                </SpaceBetween>
              </ExtBox>
            )}
          </ExtBox>
        );

      case 'null':
        // Handle null values - make them editable like other field types
        return (
          <div
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onKeyDown={(e) => e.key === 'Enter' && handleClick(e)}
            role="button"
            tabIndex={0}
            style={{
              cursor: geometry ? 'pointer' : 'default',
              backgroundColor: hasMismatch && !hasLocalEdit ? 'rgba(255, 153, 0, 0.05)' : 'transparent',
              padding: '4px',
              borderRadius: '4px',
              borderLeft: hasMismatch && !hasLocalEdit ? '3px solid #ff9900' : '3px solid transparent',
            }}
          >
            <FormField
              label={
                <ExtBox>
                  <SpaceBetween direction="horizontal" size="xs">
                    <span>{fieldKey}:</span>
                    {isPredictionChanged && (
                      <ExtBox color="text-status-info" fontSize="body-s" fontWeight="bold">
                        ✏️ Edited
                      </ExtBox>
                    )}
                    {isBaselineChanged && !isPredictionChanged && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ✏️ Baseline Edited
                      </ExtBox>
                    )}
                    {hasMismatch && !hasLocalEdit && (
                      <ExtBox color="text-status-warning" fontSize="body-s" fontWeight="bold">
                        ⚠ Mismatch
                      </ExtBox>
                    )}
                    {!hasMismatch && !hasLocalEdit && showComparison && baselineValue !== null && (
                      <ExtBox color="text-status-success" fontSize="body-s">
                        ✓ Match
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  {confidenceInfo.hasConfidenceInfo && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={confidenceColor} style={confidenceStyle}>
                      {confidenceInfo.displayMode === 'with-threshold'
                        ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                            confidenceInfo.confidenceThreshold * 100
                          ).toFixed(1)}%`
                        : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
                    </ExtBox>
                  )}
                  {showComparison && evalScore !== undefined && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={hasMismatch ? 'text-status-warning' : 'text-status-success'}>
                      {`Eval Score: ${(evalScore * 100).toFixed(1)}%`}
                      {evalReason && ` - ${evalReason}`}
                    </ExtBox>
                  )}
                </ExtBox>
              }
            >
              <SpaceBetween size="xxs">
                <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                  <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                    <ExtBox fontSize="body-s" color="text-body-secondary">
                      Predicted:
                    </ExtBox>
                    {isPredictionChanged && (
                      <ExtBox fontSize="body-s" color="text-status-info" fontWeight="bold">
                        ✏️
                      </ExtBox>
                    )}
                  </SpaceBetween>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      pointerEvents: isReadOnly ? 'none' : 'auto',
                      borderLeft: isPredictionChanged ? '3px solid #0073bb' : '3px solid transparent',
                      paddingLeft: '4px',
                      backgroundColor: isPredictionChanged ? 'rgba(0, 115, 187, 0.08)' : 'transparent',
                      borderRadius: '2px',
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      {isReadOnly ? (
                        <div
                          style={{
                            backgroundColor: '#e9ebed',
                            border: '1px solid #d5dbdb',
                            borderRadius: '4px',
                            minHeight: '32px',
                            display: 'flex',
                            alignItems: 'center',
                            fontStyle: 'italic',
                            color: '#545b64',
                            padding: '4px 8px',
                            fontSize: '14px',
                          }}
                        >
                          null
                        </div>
                      ) : (
                        <Input
                          value=""
                          onChange={({ detail }) => {
                            // Convert empty string back to null, otherwise use the entered value
                            onChange(detail.value === '' ? null : detail.value);
                          }}
                          onFocus={handleFocus}
                          placeholder="null (enter value to change)"
                        />
                      )}
                    </div>
                    {!isReadOnly && showComparison && (
                      <Button
                        variant="inline-icon"
                        iconName="arrow-down"
                        ariaLabel="Copy predicted value to baseline"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onBaselineChange) {
                            onBaselineChange(value);
                          }
                        }}
                      />
                    )}
                  </div>
                </ExtBox>
                {showComparison && (
                  <ExtBox onClick={handleClick} style={{ cursor: 'pointer' }}>
                    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                      <ExtBox fontSize="body-s" color="text-body-secondary">
                        Expected (baseline):
                      </ExtBox>
                      {isBaselineChanged && (
                        <ExtBox fontSize="body-s" color="text-status-warning" fontWeight="bold">
                          ✏️
                        </ExtBox>
                      )}
                    </SpaceBetween>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        pointerEvents: isReadOnly ? 'none' : 'auto',
                        borderLeft: isBaselineChanged ? '3px solid #ff9900' : '3px solid transparent',
                        paddingLeft: '4px',
                        backgroundColor: isBaselineChanged ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
                        borderRadius: '2px',
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        {isReadOnly ? (
                          <div
                            style={{
                              backgroundColor: '#e9ebed',
                              border: '1px solid #d5dbdb',
                              borderRadius: '4px',
                              minHeight: '32px',
                              display: 'flex',
                              alignItems: 'center',
                              fontStyle: baselineValue === null ? 'italic' : 'normal',
                              color: baselineValue === null ? '#545b64' : '#16191f',
                              padding: '4px 8px',
                              fontSize: '14px',
                            }}
                          >
                            {baselineValue === null ? 'null' : String(baselineValue)}
                          </div>
                        ) : (
                          <Input
                            value={baselineValue === null ? '' : String(baselineValue)}
                            onChange={({ detail }) => {
                              if (onBaselineChange) {
                                // Convert empty string back to null, otherwise use the entered value
                                onBaselineChange(detail.value === '' ? null : detail.value);
                              }
                            }}
                            placeholder={baselineValue === null ? 'null (enter value to change)' : undefined}
                          />
                        )}
                      </div>
                      {!isReadOnly && (
                        <Button
                          variant="inline-icon"
                          iconName="arrow-up"
                          ariaLabel="Copy baseline value to predicted"
                          onClick={(e) => {
                            e.stopPropagation();
                            onChange(baselineValue);
                          }}
                        />
                      )}
                    </div>
                  </ExtBox>
                )}
              </SpaceBetween>
            </FormField>
          </div>
        );

      case 'array': {
        // Look for array-level eval result (e.g., for checks array)
        let arrayEvalResult = null;
        if (showComparison && evaluationResults?.section_results) {
          let sectionResult = evaluationResults.section_results.find((sr) => String(sr.section_id) === String(sectionId));
          if (!sectionResult && evaluationResults.section_results.length === 1) {
            sectionResult = evaluationResults.section_results[0];
          }
          if (sectionResult?.attributes?.length > 0) {
            // Look for top-level attribute that matches our array name
            const attr = sectionResult.attributes.find((a) => a.name === fieldKey || a.name?.toLowerCase() === fieldKey?.toLowerCase());
            if (attr) {
              arrayEvalResult = {
                matched: attr.matched,
                score: attr.score,
                reason: attr.reason,
                evaluationMethod: attr.evaluation_method,
              };
            }
          }
        }

        return (
          <ExtBox
            padding="xs"
            style={{
              backgroundColor: arrayEvalResult && !arrayEvalResult.matched ? 'rgba(255, 153, 0, 0.08)' : 'transparent',
              borderRadius: '4px',
            }}
          >
            <ExtBox fontSize="body-m" fontWeight="bold" padding="xxxs" onFocus={handleFocus}>
              <SpaceBetween direction="horizontal" size="xs">
                {onToggleCollapse && (
                  <span
                    onClick={() => onToggleCollapse(pathKey)}
                    onKeyDown={(e) => e.key === 'Enter' && onToggleCollapse(pathKey)}
                    role="button"
                    tabIndex={0}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                  >
                    {isCollapsed ? '▶' : '▼'}
                  </span>
                )}
                <span>
                  {label} ({value.length} items)
                </span>
                {arrayEvalResult && !arrayEvalResult.matched && (
                  <ExtBox color="text-status-warning" fontSize="body-s">
                    ⚠
                  </ExtBox>
                )}
                {arrayEvalResult && arrayEvalResult.matched && showComparison && (
                  <ExtBox color="text-status-success" fontSize="body-s">
                    ✓
                  </ExtBox>
                )}
              </SpaceBetween>
              {showComparison && arrayEvalResult && (
                <ExtBox fontSize="body-s" color={arrayEvalResult.matched ? 'text-status-success' : 'text-status-warning'}>
                  {`List Score: ${(arrayEvalResult.score * 100).toFixed(1)}%`}
                  {arrayEvalResult.reason && ` - ${arrayEvalResult.reason}`}
                  {arrayEvalResult.evaluationMethod && (
                    <ExtBox fontSize="body-s" color="text-body-secondary">
                      Method: {arrayEvalResult.evaluationMethod}
                    </ExtBox>
                  )}
                </ExtBox>
              )}
            </ExtBox>
            {!isCollapsed && (
              <ExtBox padding={{ left: 'l' }}>
                <SpaceBetween size="xs">
                  {value.map((item, index) => {
                    // Create a stable unique key for each array item
                    const itemKey = `arr-${fieldKey}-${path.join('.')}-${index}`;

                    // Extract confidence and geometry for array items
                    let itemConfidence;
                    let itemGeometry;

                    // Try to get from explainability_info if available
                    if (explainabilityInfo && Array.isArray(explainabilityInfo)) {
                      const [firstExplainabilityItem] = explainabilityInfo;

                      // Handle nested structure - navigate to the array field first
                      let arrayFieldInfo = firstExplainabilityItem;
                      path.forEach((pathPart) => {
                        if (arrayFieldInfo && typeof arrayFieldInfo === 'object' && arrayFieldInfo[pathPart]) {
                          arrayFieldInfo = arrayFieldInfo[pathPart];
                        } else {
                          arrayFieldInfo = null;
                        }
                      });

                      // For arrays, the explainability info structure can be:
                      // 1. An array where each element has confidence/geometry (e.g., ENDORSEMENTS, RESTRICTIONS)
                      // 2. An object with nested structure
                      if (arrayFieldInfo && Array.isArray(arrayFieldInfo) && arrayFieldInfo[index]) {
                        const itemInfo = arrayFieldInfo[index];
                        if (itemInfo) {
                          itemConfidence = itemInfo.confidence;

                          // Extract geometry
                          if (itemInfo.geometry && Array.isArray(itemInfo.geometry) && itemInfo.geometry.length > 0) {
                            const geomData = itemInfo.geometry[0];
                            if (geomData.boundingBox && geomData.page !== undefined) {
                              itemGeometry = {
                                boundingBox: geomData.boundingBox,
                                page: geomData.page,
                                vertices: geomData.vertices,
                              };
                            }
                          }
                        }
                      }
                    }

                    // Get baseline value for this array item
                    const arrayBaselineValue =
                      showComparison && baselineValue !== null && Array.isArray(baselineValue) ? baselineValue[index] : null;

                    return (
                      <FormFieldRenderer
                        key={itemKey}
                        fieldKey={`[${index}]`}
                        value={item}
                        onChange={(newVal) => {
                          if (!isReadOnly) {
                            const newArray = [...value];
                            newArray[index] = newVal;
                            onChange(newArray);
                          }
                        }}
                        onBaselineChange={
                          onBaselineChange
                            ? (newVal) => {
                                if (!isReadOnly && baselineValue && Array.isArray(baselineValue)) {
                                  const newArray = [...baselineValue];
                                  newArray[index] = newVal;
                                  onBaselineChange(newArray);
                                }
                              }
                            : undefined
                        }
                        isReadOnly={isReadOnly}
                        confidence={itemConfidence}
                        geometry={itemGeometry}
                        onFieldFocus={onFieldFocus}
                        onFieldDoubleClick={onFieldDoubleClick}
                        path={[...path, index]}
                        explainabilityInfo={explainabilityInfo}
                        mergedConfig={mergedConfig}
                        baselineValue={arrayBaselineValue}
                        showComparison={showComparison}
                        evaluationResults={evaluationResults}
                        sectionId={sectionId}
                        collapsedPaths={collapsedPaths}
                        onToggleCollapse={onToggleCollapse}
                        filterMode={filterMode}
                        displayPath={[...displayPath, fieldKey]}
                        predictionChanges={predictionChanges}
                        baselineChanges={baselineChanges}
                      />
                    );
                  })}
                </SpaceBetween>
              </ExtBox>
            )}
          </ExtBox>
        );
      }

      default:
        return (
          <div
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleClick(e);
              }
            }}
            role="button"
            tabIndex={0}
            style={{ cursor: geometry ? 'pointer' : 'default' }}
          >
            <FormField
              label={
                <ExtBox>
                  {fieldKey}:
                  {confidenceInfo.hasConfidenceInfo && (
                    <ExtBox fontSize="body-s" padding={{ top: 'xxxs' }} color={confidenceColor} style={confidenceStyle}>
                      {confidenceInfo.displayMode === 'with-threshold'
                        ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(
                            confidenceInfo.confidenceThreshold * 100
                          ).toFixed(1)}%`
                        : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`}
                    </ExtBox>
                  )}
                </ExtBox>
              }
            >
              {isReadOnly ? (
                <div
                  style={{
                    backgroundColor: '#e9ebed',
                    border: '1px solid #d5dbdb',
                    borderRadius: '4px',
                    minHeight: '32px',
                    display: 'flex',
                    alignItems: 'center',
                    color: '#16191f',
                    padding: '4px 8px',
                    fontSize: '14px',
                  }}
                >
                  {String(value)}
                </div>
              ) : (
                <Input value={String(value)} onChange={({ detail }) => onChange(detail.value)} onFocus={handleFocus} />
              )}
            </FormField>
          </div>
        );
    }
  },
);

FormFieldRenderer.displayName = 'FormFieldRenderer';

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
}) => {
  const { currentCredentials, user } = useAppContext();
  const { settings } = useSettingsContext();
  const [pageImages, setPageImages] = useState({});
  const [loadingImages, setLoadingImages] = useState(true);
  const [currentPage, setCurrentPage] = useState(null);
  const [activeFieldGeometry, setActiveFieldGeometry] = useState(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [localJsonData, setLocalJsonData] = useState(jsonData);
  // Evaluation comparison state
  const [baselineData, setBaselineData] = useState(null);
  const [evaluationResults, setEvaluationResults] = useState(null);
  const [loadingEvaluation, setLoadingEvaluation] = useState(false);
  const [showEvaluation, setShowEvaluation] = useState(false);
  // Collapse/expand state - stores path keys of collapsed items
  const [collapsedPaths, setCollapsedPaths] = useState(new Set());
  // Filter mode state
  const [filterMode, setFilterMode] = useState('none'); // 'none', 'confidence-alerts', 'eval-mismatches'

  // Change tracking state for saving edits
  const [predictionChanges, setPredictionChanges] = useState(new Map()); // Map<fieldPath, { original, current }>
  const [baselineChanges, setBaselineChanges] = useState(new Map()); // Map<fieldPath, { original, current }>
  const [originalPredictionData, setOriginalPredictionData] = useState(null);
  const [originalBaselineData, setOriginalBaselineData] = useState(null);
  const [localBaselineData, setLocalBaselineData] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [_saveError, setSaveError] = useState(null);
  const [_showUnsavedChangesModal, setShowUnsavedChangesModal] = useState(false);
  const [_pendingDismiss, setPendingDismiss] = useState(false);
  // Tab navigation state
  const [activeTabId, setActiveTabId] = useState('visual');

  // Drag-to-pan state
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const imageRef = useRef(null);

  // Toggle collapse handler
  const handleToggleCollapse = (pathKey) => {
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
    const allPaths = new Set();

    // Recursive function to add all collapsible paths
    const addCollapsiblePaths = (obj, currentPath) => {
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
  const imageContainerRef = useRef(null);
  const debounceTimerRef = useRef(null);

  // Check if baseline is available - check multiple possible paths
  const evaluationStatus = sectionData?.documentItem?.evaluationStatus || sectionData?.documentItem?.EvaluationStatus;
  const isBaselineAvailable = evaluationStatus === 'BASELINE_AVAILABLE' || evaluationStatus === 'COMPLETED';

  // Construct baseline URI from output URI
  const constructBaselineUri = (outputUri) => {
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
  const constructEvaluationResultsUri = (inputKey, outputBucket) => {
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
      const outputUri = sectionData?.OutputJSONUri;
      // inputKey can be objectKey or inputKey depending on context
      const inputKey = sectionData?.documentItem?.objectKey || sectionData?.documentItem?.inputKey || sectionData?.documentItem?.InputKey;
      const outputBucket =
        sectionData?.documentItem?.outputBucket ||
        sectionData?.documentItem?.OutputBucket ||
        (settings as Record<string, unknown>)?.OutputBucket;

      setLoadingEvaluation(true);
      try {
        // Load baseline data
        const baselineUri = constructBaselineUri(outputUri);
        if (baselineUri && !baselineData) {
          try {
            const baselineResponse = await client.graphql({
              query: getFileContents as unknown as string,
              variables: { s3Uri: baselineUri },
            });
            const baselineResult = (baselineResponse as FileContentsResponse).data.getFileContents;
            if (!baselineResult.isBinary && baselineResult.content) {
              const parsed = JSON.parse(baselineResult.content);
              setBaselineData(parsed);
              logger.info('Baseline data loaded successfully');
            }
          } catch (error) {
            logger.warn('Failed to load baseline data:', error.message);
          }
        }

        // Load evaluation results
        const evalResultsUri = constructEvaluationResultsUri(inputKey, outputBucket);
        if (evalResultsUri && !evaluationResults) {
          try {
            const evalResponse = await client.graphql({
              query: getFileContents as unknown as string,
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
  }, [visible, isBaselineAvailable, sectionData?.OutputJSONUri, sectionData?.documentItem?.inputKey, settings]);

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
    sectionData?.confidenceAlertCount > 0 || (sectionData?.documentItem?.hitlTriggered && !sectionData?.documentItem?.hitlCompleted);

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
  const trackPredictionChange = (fieldPath, originalValue, newValue) => {
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

  const trackBaselineChange = (fieldPath, originalValue, newValue) => {
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
      const outputUri = sectionData?.OutputJSONUri;
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

      const results = { predictions: null, baseline: null };

      // Build combined edit entry for both files
      const username = ((user as Record<string, unknown>)?.username as string) || 'unknown';
      const timestamp = new Date().toISOString();

      // Build prediction diffs
      const predictionDiffs = {};
      predictionChanges.forEach((change, fieldPath) => {
        predictionDiffs[fieldPath] = {
          originalValue: change.original,
          newValue: change.current,
        };
      });

      // Build baseline diffs
      const baselineDiffs = {};
      baselineChanges.forEach((change, fieldPath) => {
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
        const dataToSave = { ...localJsonData };
        const editHistory = dataToSave._editHistory || [];
        editHistory.push(editEntry);
        dataToSave._editHistory = editHistory;

        // Use the exact same path from the original output URI
        logger.info('💾 Prediction file path:', outputFileKey);

        // Extract prefix (directory) and filename for uploadDocument
        const predictionPrefix = outputFileKey.substring(0, outputFileKey.lastIndexOf('/'));
        const predictionFilename = outputFileKey.split('/').pop();

        const predictionUploadResponse = await client.graphql({
          query: uploadDocument as unknown as string,
          variables: {
            fileName: predictionFilename,
            prefix: predictionPrefix,
            contentType: 'application/json',
            bucket: outputBucketFromUri,
          },
        });

        const predUploadData = (predictionUploadResponse as UploadDocResponse).data.uploadDocument;
        const predictionPresignedUrl = predUploadData.presignedUrl;
        const predictionUsePost = predUploadData.usePostMethod;

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
          formData.append('file', blob, predictionFilename as string);

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

        results.predictions = { success: true, changedFields: [...predictionChanges.keys()] };
        logger.info('✅ Predictions saved successfully');
      }

      // Save baseline if changed
      if (baselineChangeCount > 0 && localBaselineData) {
        logger.info('💾 Saving baseline changes...', { count: baselineChangeCount });

        // Add edit history metadata with combined changes (same as predictions)
        const baselineToSave = { ...localBaselineData };
        const baselineEditHistory = baselineToSave._editHistory || [];
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
        const baselineFilename = outputFileKey.split('/').pop();

        const baselineUploadResponse = await client.graphql({
          query: uploadDocument as unknown as string,
          variables: {
            fileName: baselineFilename,
            prefix: baselinePrefix,
            contentType: 'application/json',
            bucket: baselineBucket,
          },
        });

        const baseUploadData = (baselineUploadResponse as UploadDocResponse).data.uploadDocument;
        const baselinePresignedUrl = baseUploadData.presignedUrl;
        const baselineUsePost = baseUploadData.usePostMethod;

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

      // Success! Reset change tracking and update originals
      setOriginalPredictionData(JSON.parse(JSON.stringify(localJsonData)));
      if (localBaselineData) {
        setOriginalBaselineData(JSON.parse(JSON.stringify(localBaselineData)));
      }
      setPredictionChanges(new Map());
      setBaselineChanges(new Map());

      // Show success message
      const savedItems = [];
      if (results.predictions) savedItems.push(`${results.predictions.changedFields.length} prediction field(s)`);
      if (results.baseline) savedItems.push(`${results.baseline.changedFields.length} baseline field(s)`);

      alert(`✅ Successfully saved:\n${savedItems.join('\n')}`);
    } catch (error) {
      logger.error('❌ Error saving changes:', error);
      setSaveError(error.message || 'Failed to save changes');
      alert(`❌ Error saving changes:\n${error.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Debounced parent onChange function with non-blocking execution
  const debouncedParentOnChange = (jsonString) => {
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
  const pageIds = sectionData?.PageIds || [];

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
        const documentPages = sectionData?.documentItem?.pages || [];
        logger.debug('VisualEditorModal - Loading images for pageIds:', pageIds);

        const images = {};

        await Promise.all(
          pageIds.map(async (pageId) => {
            // Find the page in the document's pages array by matching the Id
            const page = documentPages.find((p) => p.Id === pageId);

            if (page?.ImageUri) {
              try {
                logger.debug(`VisualEditorModal - generating presigned URL for page ${pageId}`);
                const url = await generateS3PresignedUrl(page.ImageUri as string, currentCredentials as Record<string, unknown>);
                images[pageId] = url;
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
  }, [visible, pageIds, sectionData?.documentItem?.pages, currentCredentials]);

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
  const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 1.1 : 0.9;
    setZoomLevel((prev) => Math.min(Math.max(prev * delta, 0.25), 4));
  };

  // Handle drag-to-pan - mouse down starts drag
  const handleMouseDown = (e) => {
    // Only pan when zoomed in
    if (zoomLevel <= 1) return;

    // Prevent default to avoid text selection
    e.preventDefault();
    setIsDragging(true);
    setDragStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
  };

  // Handle drag-to-pan - mouse move updates pan offset
  const handleMouseMove = (e) => {
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
  const handleFieldFocus = (geometry) => {
    const focusStart = performance.now();
    logger.debug('VisualEditorModal - handleFieldFocus START:', { timestamp: focusStart });

    // Use setTimeout to make this completely asynchronous and non-blocking
    setTimeout(() => {
      if (geometry) {
        setActiveFieldGeometry(geometry);

        // If geometry has a page field, switch to that page
        if (geometry.page !== undefined && pageIds.length > 0) {
          const pageIndex = geometry.page - 1;
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
  const handleFieldDoubleClick = (geometry) => {
    logger.debug('VisualEditorModal - handleFieldDoubleClick called with geometry:', geometry);

    if (geometry && imageRef.current && imageContainerRef.current) {
      // First switch to the correct page if needed
      if (geometry.page !== undefined && pageIds.length > 0) {
        const pageIndex = geometry.page - 1;
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
          const bbox = geometry.boundingBox;

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
  const carouselItems = pageIds.map((pageId) => ({
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
        {pageImages[pageId] ? (
          <>
            <img
              ref={pageId === currentPage ? imageRef : null}
              src={pageImages[pageId]}
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
                page={currentPage}
                currentPage={currentPage}
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
                  <strong>Section:</strong> {sectionData?.Id || sectionData?.SectionId || 'N/A'}
                </ExtBox>
                <ExtBox>
                  <strong>Type:</strong> {localJsonData?.document_class?.type || 'N/A'}
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
                                {carouselItems.find((item) => item.id === currentPage)?.content}

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
                                      const currentIndex = pageIds.indexOf(currentPage);
                                      if (currentIndex > 0) {
                                        setCurrentPage(pageIds[currentIndex - 1]);
                                        setActiveFieldGeometry(null);
                                      }
                                    }}
                                    disabled={pageIds.indexOf(currentPage) === 0}
                                  />
                                  <Button
                                    iconName="angle-right"
                                    variant="icon"
                                    onClick={() => {
                                      const currentIndex = pageIds.indexOf(currentPage);
                                      if (currentIndex < pageIds.length - 1) {
                                        setCurrentPage(pageIds[currentIndex + 1]);
                                        setActiveFieldGeometry(null);
                                      }
                                    }}
                                    disabled={pageIds.indexOf(currentPage) === pageIds.length - 1}
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
                                  Page {pageIds.indexOf(currentPage) + 1} of {pageIds.length}
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
                            onBaselineChange={(newBaselineValue) => {
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
                                  const findBaselineChanges = (original, current, pathParts = []) => {
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
                                        const origVal = original ? original[key] : undefined;
                                        findBaselineChanges(origVal, current[key], [...pathParts, key]);
                                      });
                                    }
                                  };
                                  findBaselineChanges(originalBaselineResult, newBaselineValue);
                                }
                              }
                            }}
                            onChange={(newValue) => {
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
                                    const findChanges = (original, current, pathParts = []) => {
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
                                          const origVal = original ? original[key] : undefined;
                                          findChanges(origVal, current[key], [...pathParts, key]);
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
        ]}
      />
    </Modal>
  );
};

export default VisualEditorModal;
