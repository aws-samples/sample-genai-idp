// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useMemo } from 'react';
import { Table, Box, Input, StatusIndicator, Toggle, SpaceBetween, Button } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';

interface FlatField {
  path: (string | number)[];
  pathString: string;
  fieldName: string;
  value: unknown;
  type: string;
}

interface BoundingBoxGeometry {
  boundingBox?: Record<string, number>;
  page?: number | string;
  vertices?: unknown;
}

interface FieldExplainabilityResult {
  confidence: number | null;
  geometry: BoundingBoxGeometry | null;
}

interface ComparisonItem extends FlatField {
  expectedValue: unknown;
  predictedValue: unknown;
  displayExpected: unknown;
  displayPredicted: unknown;
  isMatch: boolean;
  hasExpectedCorrection: boolean;
  hasPredictedCorrection: boolean;
  confidence: number | null;
  geometry: BoundingBoxGeometry | null;
}

interface CorrectionItem {
  path: (string | number)[];
  pathString: string;
  fieldName: string;
  originalValue: unknown;
  newValue: string;
  source: string;
}

interface FieldComparisonTableProps {
  expectedData: Record<string, unknown> | null;
  predictedData: Record<string, unknown> | null;
  explainabilityInfo?: unknown[] | null;
  onExpectedChange?: ((correction: CorrectionItem) => void) | null;
  onPredictedChange?: ((correction: CorrectionItem) => void) | null;
  onFieldFocus?: ((geometry: BoundingBoxGeometry) => void) | null;
  corrections?: CorrectionItem[];
  showMismatchesOnly?: boolean;
  onShowMismatchesOnlyChange?: ((checked: boolean) => void) | null;
}

const _logger = new ConsoleLogger('FieldComparisonTable');

/**
 * Flattens nested JSON objects into a flat array of field entries
 * Each entry has: path, fieldName, value
 */
const flattenObject = (obj: unknown, path: (string | number)[] = [], results: FlatField[] = []): FlatField[] => {
  if (obj === null || obj === undefined) {
    return results;
  }

  if (typeof obj !== 'object') {
    return results;
  }

  Object.entries(obj).forEach(([key, value]) => {
    const currentPath = [...path, key];
    const pathString = currentPath.join('.');

    if (value === null || value === undefined) {
      results.push({
        path: currentPath,
        pathString,
        fieldName: key,
        value: null,
        type: 'null',
      });
    } else if (Array.isArray(value)) {
      // For arrays of primitives, treat as a single field
      if (value.length === 0 || typeof value[0] !== 'object') {
        results.push({
          path: currentPath,
          pathString,
          fieldName: key,
          value,
          type: 'array',
        });
      } else {
        // For arrays of objects, recurse into each item
        value.forEach((item, index) => {
          flattenObject(item, [...currentPath, index], results);
        });
      }
    } else if (typeof value === 'object') {
      // Recurse into nested objects
      flattenObject(value, currentPath, results);
    } else {
      // Primitive value
      results.push({
        path: currentPath,
        pathString,
        fieldName: key,
        value,
        type: typeof value,
      });
    }
  });

  return results;
};

/**
 * Gets a value from a nested object using a path array
 * Filters out structural keys like 'inference_result' for explainability lookups
 */
const _getValueByPath = (obj: unknown, path: (string | number)[], filterStructural = false): unknown => {
  if (!obj || !path || path.length === 0) return undefined;

  // Filter out structural keys from the path for explainability lookup
  const structuralKeys = ['inference_result', 'inferenceResult', 'explainability_info'];
  const filteredPath = filterStructural ? path.filter((p) => !structuralKeys.includes(String(p))) : path;

  let current: unknown = obj;
  for (const key of filteredPath) {
    if (current === null || current === undefined) return undefined;
    current = (current as Record<string | number, unknown>)[key];
  }
  return current;
};

/**
 * Gets confidence and geometry info for a field from explainability_info
 * Handles the nested structure of explainability data
 */
const getFieldExplainabilityInfo = (
  path: (string | number)[],
  explainabilityInfo: unknown[] | null | undefined,
): FieldExplainabilityResult => {
  if (!explainabilityInfo || !Array.isArray(explainabilityInfo) || !explainabilityInfo[0]) {
    return { confidence: null, geometry: null };
  }

  // Filter out structural keys from the path
  const structuralKeys = ['inference_result', 'inferenceResult', 'explainability_info'];
  const filteredPath = path.filter((p) => !structuralKeys.includes(String(p)) && typeof p !== 'undefined');

  // Navigate to the field in explainability data
  let fieldInfo: unknown = explainabilityInfo[0];
  for (const pathPart of filteredPath) {
    if (fieldInfo && typeof fieldInfo === 'object') {
      const info = fieldInfo as Record<string | number, unknown>;
      if (Array.isArray(fieldInfo) && !Number.isNaN(parseInt(String(pathPart), 10))) {
        const arrayIndex = parseInt(String(pathPart), 10);
        if (arrayIndex >= 0 && arrayIndex < fieldInfo.length) {
          fieldInfo = fieldInfo[arrayIndex];
        } else {
          fieldInfo = null;
        }
      } else if (info[pathPart] !== undefined) {
        fieldInfo = info[pathPart];
      } else {
        fieldInfo = null;
      }
    } else {
      fieldInfo = null;
    }
  }

  let confidence: number | null = null;
  let geometry: BoundingBoxGeometry | null = null;

  if (fieldInfo) {
    const info = fieldInfo as Record<string, unknown>;
    // Get confidence
    if (typeof info.confidence === 'number') {
      confidence = info.confidence;
    }

    // Get geometry
    if (info.geometry && Array.isArray(info.geometry) && (info.geometry as unknown[]).length > 0) {
      const geomData = (info.geometry as Record<string, unknown>[])[0];
      if (geomData.boundingBox && geomData.page !== undefined) {
        geometry = {
          boundingBox: geomData.boundingBox as Record<string, number>,
          page: geomData.page as number | string,
          vertices: geomData.vertices,
        };
      }
    }
  }

  return { confidence, geometry };
};

/**
 * Formats a value for display
 */
const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return (value as unknown[]).join(', ');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
};

/**
 * Compares two values for equality
 */
const valuesMatch = (expected: unknown, predicted: unknown): boolean => {
  const expectedStr = formatValue(expected).toLowerCase().trim();
  const predictedStr = formatValue(predicted).toLowerCase().trim();
  return expectedStr === predictedStr;
};

/**
 * FieldComparisonTable - Displays expected vs predicted values with edit capability
 */
const FieldComparisonTable = ({
  expectedData,
  predictedData,
  explainabilityInfo = null,
  onExpectedChange,
  onPredictedChange,
  onFieldFocus,
  corrections = [],
  showMismatchesOnly = false,
  onShowMismatchesOnlyChange,
}: FieldComparisonTableProps): React.JSX.Element => {
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editingSource, setEditingSource] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  // Build comparison data from flattened expected and predicted objects
  const comparisonData = useMemo(() => {
    const expectedFlat = flattenObject(expectedData?.inference_result || expectedData || {});
    const predictedFlat = flattenObject(predictedData?.inference_result || predictedData || {});

    // Merge fields from both sources
    const fieldMap = new Map();

    expectedFlat.forEach((field) => {
      fieldMap.set(field.pathString, {
        ...field,
        expectedValue: field.value,
        predictedValue: undefined,
      });
    });

    predictedFlat.forEach((field) => {
      if (fieldMap.has(field.pathString)) {
        const existing = fieldMap.get(field.pathString);
        existing.predictedValue = field.value;
      } else {
        fieldMap.set(field.pathString, {
          ...field,
          expectedValue: undefined,
          predictedValue: field.value,
        });
      }
    });

    // Convert to array and add match status
    let items = Array.from(fieldMap.values()).map((field) => {
      // Check if there's a correction for this field
      const expectedCorrection = corrections.find((c) => c.pathString === field.pathString && c.source === 'baseline');
      const predictedCorrection = corrections.find((c) => c.pathString === field.pathString && c.source === 'prediction');

      // Use corrected values if available
      const displayExpected = expectedCorrection ? expectedCorrection.newValue : field.expectedValue;
      const displayPredicted = predictedCorrection ? predictedCorrection.newValue : field.predictedValue;

      // Get confidence and geometry from explainability info
      const explainInfo = getFieldExplainabilityInfo(field.path, explainabilityInfo);
      const { confidence } = explainInfo;
      const { geometry } = explainInfo;

      return {
        ...field,
        expectedValue: field.expectedValue,
        predictedValue: field.predictedValue,
        displayExpected,
        displayPredicted,
        isMatch: valuesMatch(displayExpected, displayPredicted),
        hasExpectedCorrection: !!expectedCorrection,
        hasPredictedCorrection: !!predictedCorrection,
        confidence,
        geometry,
      };
    });

    // Filter to mismatches only if requested
    if (showMismatchesOnly) {
      items = items.filter((item) => !item.isMatch);
    }

    return items;
  }, [expectedData, predictedData, explainabilityInfo, corrections, showMismatchesOnly]);

  // Start editing a field
  const handleStartEdit = (pathString: string, source: string, currentValue: unknown) => {
    setEditingField(pathString);
    setEditingSource(source);
    setEditValue(formatValue(currentValue));
  };

  // Save edit
  const handleSaveEdit = (item: ComparisonItem) => {
    if (editingSource === 'baseline' && onExpectedChange) {
      onExpectedChange({
        path: item.path,
        pathString: item.pathString,
        fieldName: item.fieldName,
        originalValue: item.expectedValue,
        newValue: editValue,
        source: 'baseline',
      });
    } else if (editingSource === 'prediction' && onPredictedChange) {
      onPredictedChange({
        path: item.path,
        pathString: item.pathString,
        fieldName: item.fieldName,
        originalValue: item.predictedValue,
        newValue: editValue,
        source: 'prediction',
      });
    }
    setEditingField(null);
    setEditingSource(null);
    setEditValue('');
  };

  // Cancel edit
  const handleCancelEdit = () => {
    setEditingField(null);
    setEditingSource(null);
    setEditValue('');
  };

  // Handle row click to focus on field in image
  const handleRowClick = (item: ComparisonItem) => {
    if (item.geometry && onFieldFocus) {
      onFieldFocus(item.geometry);
    }
  };

  const columnDefinitions = [
    {
      id: 'field',
      header: 'Field',
      cell: (item: ComparisonItem) => (
        <Box fontWeight={item.isMatch ? 'normal' : 'bold'} color={item.isMatch ? 'text-body-secondary' : 'text-status-warning'}>
          {item.pathString}
        </Box>
      ),
      sortingField: 'pathString',
      width: 200,
    },
    {
      id: 'expected',
      header: 'Expected (Baseline)',
      cell: (item: ComparisonItem) => {
        const isEditing = editingField === item.pathString && editingSource === 'baseline';
        const displayValue = formatValue(item.displayExpected);

        if (isEditing) {
          return (
            <SpaceBetween direction="horizontal" size="xs">
              <Input
                value={editValue}
                onChange={({ detail }) => setEditValue(detail.value)}
                onKeyDown={(e) => {
                  if (e.detail.key === 'Enter') handleSaveEdit(item);
                  if (e.detail.key === 'Escape') handleCancelEdit();
                }}
              />
              <Button variant="icon" iconName="check" onClick={() => handleSaveEdit(item)} />
              <Button variant="icon" iconName="close" onClick={handleCancelEdit} />
            </SpaceBetween>
          );
        }

        return (
          <SpaceBetween direction="horizontal" size="xs">
            <Box color={item.hasExpectedCorrection ? 'text-status-info' : undefined}>
              {displayValue || <em>empty</em>}
              {item.hasExpectedCorrection && ' (corrected)'}
            </Box>
            <Button
              variant="icon"
              iconName="edit"
              onClick={(e) => {
                e.stopPropagation();
                handleStartEdit(item.pathString, 'baseline', item.displayExpected);
              }}
              ariaLabel="Edit expected value"
            />
          </SpaceBetween>
        );
      },
      width: 250,
    },
    {
      id: 'predicted',
      header: 'Predicted (Output)',
      cell: (item: ComparisonItem) => {
        const isEditing = editingField === item.pathString && editingSource === 'prediction';
        const displayValue = formatValue(item.displayPredicted);

        if (isEditing) {
          return (
            <SpaceBetween direction="horizontal" size="xs">
              <Input
                value={editValue}
                onChange={({ detail }) => setEditValue(detail.value)}
                onKeyDown={(e) => {
                  if (e.detail.key === 'Enter') handleSaveEdit(item);
                  if (e.detail.key === 'Escape') handleCancelEdit();
                }}
              />
              <Button variant="icon" iconName="check" onClick={() => handleSaveEdit(item)} />
              <Button variant="icon" iconName="close" onClick={handleCancelEdit} />
            </SpaceBetween>
          );
        }

        return (
          <SpaceBetween direction="horizontal" size="xs">
            <Box color={item.hasPredictedCorrection ? 'text-status-info' : undefined}>
              {displayValue || <em>empty</em>}
              {item.hasPredictedCorrection && ' (corrected)'}
            </Box>
            <Button
              variant="icon"
              iconName="edit"
              onClick={(e) => {
                e.stopPropagation();
                handleStartEdit(item.pathString, 'prediction', item.displayPredicted);
              }}
              ariaLabel="Edit predicted value"
            />
          </SpaceBetween>
        );
      },
      width: 250,
    },
    {
      id: 'confidence',
      header: 'Confidence',
      cell: (item: ComparisonItem) => {
        if (item.confidence === null) return '-';
        const percentage = (item.confidence * 100).toFixed(1);
        const color = item.confidence >= 0.9 ? 'text-status-success' : item.confidence >= 0.7 ? 'text-status-warning' : 'text-status-error';
        return <Box color={color}>{percentage}%</Box>;
      },
      width: 100,
    },
    {
      id: 'match',
      header: 'Match',
      cell: (item: ComparisonItem) => (
        <StatusIndicator type={item.isMatch ? 'success' : 'error'}>{item.isMatch ? 'Match' : 'Mismatch'}</StatusIndicator>
      ),
      width: 100,
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (item: ComparisonItem) => (
        <Button
          variant="icon"
          iconName="zoom-to-fit"
          onClick={(e) => {
            e.stopPropagation();
            handleRowClick(item);
          }}
          disabled={!item.geometry}
          ariaLabel="Focus on field in document"
        />
      ),
      width: 80,
    },
  ];

  const mismatchCount = comparisonData.filter((item) => !item.isMatch).length;
  const totalCount = comparisonData.length;

  return (
    <Box>
      <SpaceBetween size="s">
        <SpaceBetween direction="horizontal" size="m" alignItems="center">
          <Box>
            <strong>Fields:</strong> {totalCount} total, {mismatchCount} mismatches
          </Box>
          <Toggle
            checked={showMismatchesOnly}
            onChange={({ detail }) => onShowMismatchesOnlyChange && onShowMismatchesOnlyChange(detail.checked)}
          >
            Show mismatches only
          </Toggle>
        </SpaceBetween>

        <Table
          columnDefinitions={columnDefinitions}
          items={comparisonData}
          sortingDisabled
          wrapLines
          stripedRows
          onRowClick={({ detail }) => handleRowClick(detail.item)}
          empty={
            <Box textAlign="center" color="inherit">
              <b>No fields to compare</b>
              <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                {showMismatchesOnly ? 'No mismatches found - all fields match!' : 'No data available for comparison.'}
              </Box>
            </Box>
          }
        />
      </SpaceBetween>
    </Box>
  );
};

export default FieldComparisonTable;
