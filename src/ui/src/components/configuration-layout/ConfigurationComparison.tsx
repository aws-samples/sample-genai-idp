// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import { Table, Box, SpaceBetween, Badge, Header, ButtonDropdown } from '@cloudscape-design/components';

interface ConfigurationComparisonProps {
  versions: string[];
  configs: Record<string, unknown>;
}

const ConfigurationComparison = ({ versions, configs }: ConfigurationComparisonProps): React.JSX.Element => {
  // Safety checks
  if (!versions || !Array.isArray(versions) || !configs) {
    return (
      <Box textAlign="center" color="inherit">
        <SpaceBetween size="m">
          <b>Invalid comparison data</b>
          <Box variant="p">Unable to compare configurations due to missing data.</Box>
        </SpaceBetween>
      </Box>
    );
  }

  // Find differences between configurations with deep diff support for classes and rules
  const findDifferences = (configsToCompare: Record<string, unknown>) => {
    const differences: { field: string; values: Record<string, string> }[] = [];
    const ignoredFields = new Set(['UpdatedAt', 'Description', 'CreatedAt', 'IsActive', 'Configuration', 'version_name']);

    // Check if an array contains identity-keyed objects (e.g., classes, rule_classes with $id fields)
    const isIdentityKeyedArray = (arr: unknown): boolean => {
      return Array.isArray(arr) && arr.length > 0 && arr.every((item) => typeof item === 'object' && item !== null && '$id' in item);
    };

    // Recursively extract all leaf paths from a value, using $id-based keys for identity arrays
    const getPathsFromValue = (value: unknown, currentPath: string): string[] => {
      const paths: string[] = [];

      if (Array.isArray(value)) {
        if (isIdentityKeyedArray(value)) {
          // Identity-keyed array (classes, rule_classes): use $id as key segment
          for (const item of value) {
            const itemPrefix = `${currentPath}[${item['$id']}]`;
            for (const [propKey, propValue] of Object.entries(item)) {
              if (propKey === '$id') continue; // Skip the identity key itself
              getPathsFromValue(propValue, `${itemPrefix}.${propKey}`).forEach((p) => paths.push(p));
            }
          }
        } else {
          // Regular array: treat as leaf value (will be stringified for comparison)
          paths.push(currentPath);
        }
      } else if (typeof value === 'object' && value !== null) {
        for (const [key, val] of Object.entries(value)) {
          if (ignoredFields.has(key)) continue;
          const childPath = currentPath ? `${currentPath}.${key}` : key;
          getPathsFromValue(val, childPath).forEach((p) => paths.push(p));
        }
      } else {
        paths.push(currentPath);
      }

      return paths;
    };

    // Get nested value using dot notation path with identity-keyed array bracket support
    // Supports paths like: "classes[Payslip].description" or "rule_classes[global_periods].rule_properties.field"
    const getNestedValue = (dictionary: Record<string, unknown>, path: string): unknown => {
      const parts = path.split('.');
      let current: Record<string, unknown> | null = dictionary;

      for (const part of parts) {
        if (current === null || current === undefined) return null;

        // Check for identity bracket notation: fieldName[id]
        const bracketMatch = part.match(/^(.+?)\[(.+)\]$/);
        if (bracketMatch) {
          const arrayKey = bracketMatch[1];
          const id = bracketMatch[2];
          const arr = current[arrayKey];
          if (!Array.isArray(arr)) return null;
          current = (arr.find((item) => item && item['$id'] === id) || null) as Record<string, unknown> | null;
        } else if (typeof current === 'object' && current !== null && part in current) {
          current = current[part] as Record<string, unknown> | null;
        } else {
          return null;
        }
      }
      return current;
    };

    // Get all possible paths from all configs
    const allPaths = new Set<string>();
    Object.values(configsToCompare).forEach((config) => {
      getPathsFromValue(config || {}, '').forEach((path) => {
        if (path) allPaths.add(path);
      });
    });

    // Sort paths for consistent ordering
    const sortedPaths = Array.from(allPaths).sort();

    // Stringify a value for comparison (handles arrays, objects, primitives)
    const stringifyValue = (value: unknown): string => {
      if (value === null || value === undefined) return '<missing>';
      if (typeof value === 'string') return value.trim();
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value).trim();
    };

    // Numeric-aware comparison: treats "5" and "5.0" as equal
    const isNumeric = (v: unknown): boolean => {
      if (v === '<missing>') return false;
      if (typeof v === 'number') return true;
      if (typeof v === 'string' && v.trim() !== '') return !Number.isNaN(Number(v));
      return false;
    };
    const areStrValuesEqual = (a: string, b: string): boolean => {
      if (a === b) return true;
      if (isNumeric(a) && isNumeric(b)) return Number(a) === Number(b);
      return false;
    };

    // Check each path for differences
    sortedPaths.forEach((path) => {
      const values: Record<string, string> = {};
      let hasDifferences = false;
      let firstValue: string | null = null;
      let firstValueSet = false;

      versions.forEach((version) => {
        const config = configsToCompare[version];
        const value = getNestedValue((config || {}) as Record<string, unknown>, path);
        const strValue = stringifyValue(value);

        values[version] = strValue;

        // Check for differences using numeric-aware comparison
        if (!firstValueSet) {
          firstValue = strValue;
          firstValueSet = true;
        } else if (!areStrValuesEqual(firstValue, strValue)) {
          hasDifferences = true;
        }
      });

      // Include if there are differences (including missing vs present)
      if (hasDifferences) {
        differences.push({
          field: path,
          values,
        });
      }
    });

    return differences.sort((a, b) => a.field.localeCompare(b.field));
  };

  // Format value for display
  const formatValue = (value: unknown): React.ReactNode => {
    if (value === '<missing>') return <Badge color="grey">Missing</Badge>;
    if (value === undefined) return <Badge color="grey">Not set</Badge>;
    if (value === null) return <Badge color="grey">null</Badge>;
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    // Handle JSON-stringified arrays/objects from deep diff
    if (typeof value === 'string' && value.startsWith('[') && value.endsWith(']')) {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) return `[${parsed.length} items]`;
      } catch {
        // Not valid JSON, display as-is
      }
    }
    if (typeof value === 'string' && value.startsWith('{') && value.endsWith('}')) {
      try {
        JSON.parse(value);
        // Truncate long JSON objects for display
        return value.length > 80 ? `${value.substring(0, 77)}...` : value;
      } catch {
        // Not valid JSON, display as-is
      }
    }
    if (Array.isArray(value)) return `[${value.length} items]`;
    if (typeof value === 'object') return '[Object]';
    return String(value);
  };

  // Now configs are already merged, no need to parse old format
  const differences = findDifferences(configs);

  // Export functions
  const exportToCSV = () => {
    const headers = ['Field', ...versions];
    const rows = differences.map((diff) => [diff.field, ...versions.map((version) => diff.values[version] || 'Not set')]);

    const csvContent = [headers, ...rows].map((row) => row.map((cell) => `"${cell}"`).join(',')).join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `config-differences-${versions.join('-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportToJSON = () => {
    const exportData = {
      versions,
      differences: differences.map((diff) => ({
        field: diff.field,
        values: diff.values,
      })),
    };

    const jsonContent = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `config-differences-${versions.join('-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Debug logging
  console.log('Configs received:', configs);
  console.log('Differences found:', differences);

  // Create column definitions with equal width distribution
  const totalColumns = versions.length + 1; // +1 for field column
  const equalWidth = Math.floor(100 / totalColumns);

  const columnDefinitions = [
    {
      id: 'field',
      header: 'Field',
      cell: (item) => item.field,
      sortingField: 'field',
      width: `${equalWidth}%`,
    },
    ...versions.map((version) => ({
      id: version,
      header: version,
      cell: (item) => formatValue(item.values[version]),
      width: `${equalWidth}%`,
    })),
  ];

  return (
    <SpaceBetween size="m">
      {differences.length === 0 ? (
        <Box textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>No differences found</b>
            <Box variant="p">The selected configuration versions are identical.</Box>
          </SpaceBetween>
        </Box>
      ) : (
        <Table
          resizableColumns
          wrapLines={true}
          columnDefinitions={columnDefinitions}
          items={differences}
          sortingDisabled={false}
          header={
            <Header
              actions={
                <ButtonDropdown
                  items={[
                    { text: 'Export as CSV', id: 'csv' },
                    { text: 'Export as JSON', id: 'json' },
                  ]}
                  onItemClick={({ detail }) => {
                    if (detail.id === 'csv') exportToCSV();
                    if (detail.id === 'json') exportToJSON();
                  }}
                >
                  Export
                </ButtonDropdown>
              }
            >
              Config differences between versions: [{versions.join(', ')}]
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit">
              No differences found
            </Box>
          }
        />
      )}
    </SpaceBetween>
  );
};

export default ConfigurationComparison;
