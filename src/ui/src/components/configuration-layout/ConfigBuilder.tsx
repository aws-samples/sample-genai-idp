// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/no-array-index-key */
/* eslint-disable no-use-before-define */
import React, { useState, useRef, useEffect } from 'react';
import {
  Box,
  SpaceBetween,
  FormField,
  Input,
  Textarea,
  Toggle,
  Select,
  Button,
  Header,
  Container,
  Modal,
  Tabs,
} from '@cloudscape-design/components';
import type { BoxProps } from '@cloudscape-design/components';
import SchemaBuilder from '../json-schema-builder/SchemaBuilder';

// Type for schema property definitions used throughout the config builder
interface SchemaProperty {
  type?: string;
  properties?: Record<string, SchemaProperty>;
  items?: SchemaProperty;
  enum?: string[];
  default?: unknown;
  order?: string | number;
  description?: string;
  dependsOn?: { field: string; values?: unknown[]; value?: unknown };
  sectionLabel?: string;
  nestLevel?: number;
  columns?: string | number;
  listLabel?: string;
  itemLabel?: string;
  minimum?: number;
  maximum?: number;
  format?: string;
  [key: string]: unknown;
}

// Extended Box props that allow style, className, event handlers, and relaxed spacing values.
// Cloudscape Box doesn't type these but passes them through to the DOM element.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ExtendedBoxProps = Omit<BoxProps, 'padding' | 'margin' | 'display' | 'color'> & {
  [key: string]: unknown;
  style?: React.CSSProperties;
  className?: string;
  onMouseDown?: React.MouseEventHandler;
  onClick?: React.MouseEventHandler;
  children?: React.ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  padding?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  margin?: any;
  display?: string;
  color?: string;
};

// Cast Box to accept extended props (style, className, event handlers, etc.)
// Cloudscape Box doesn't type these but passes them through to the DOM element
const ExtBox = Box as unknown as React.FC<ExtendedBoxProps>;

// Numeric-aware value comparison: treats "5" and "5.0" as equal, "0" and "0.0" as equal, etc.
const areValuesEqual = (val1: unknown, val2: unknown): boolean => {
  // Fast path: strict equality
  if (val1 === val2) return true;
  // JSON.stringify equality for objects/arrays
  const str1 = JSON.stringify(val1);
  const str2 = JSON.stringify(val2);
  if (str1 === str2) return true;
  // Numeric comparison: if both can be parsed as numbers, compare numerically
  const isNumeric = (v: unknown): boolean => {
    if (typeof v === 'number') return true;
    if (typeof v === 'string' && v.trim() !== '') return !Number.isNaN(Number(v));
    return false;
  };
  if (isNumeric(val1) && isNumeric(val2)) {
    return Number(val1) === Number(val2);
  }
  return false;
};

// Add custom styles for compact form layout
const customStyles = `
  .expandable-textarea {
    max-height: 250px;
    overflow-y: auto !important;
    resize: vertical;
  }
  
  /* Make form fields more compact */
  .awsui-form-field {
    margin-bottom: 4px !important;
  }
  
  /* Reduce space inside form fields */
  .awsui-form-field-control {
    margin-top: 2px !important;  
  }
  
  /* Minimize space between label and control */
  .awsui-form-field-label {
    margin-bottom: 0 !important;
    padding-bottom: 0 !important;
  }
  
  /* Highlight modified fields */
  .modified-field {
    background-color: rgba(255, 240, 179, 0.2) !important;
    border-left: 3px solid #f2a900 !important;
    padding-left: 8px !important;
    border-radius: 4px !important;
  }
  
  /* Style for the restore default button */
  .restore-default-button {
    margin-left: 8px;
    font-size: 12px;
  }

  /* Unsaved change indicator dot */
  .unsaved-change-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: #0073bb;
    margin-left: 6px;
    vertical-align: middle;
  }

  /* Unsaved change field highlight */
  .unsaved-field {
    border-left: 3px solid #0073bb !important;
    padding-left: 8px !important;
    border-radius: 4px !important;
  }
  
  /* More compact list and nested list styling */
  .awsui-button-icon {
    padding: 2px !important;
    height: auto !important;
    min-height: auto !important;
    display: inline-flex !important;
    align-items: center !important;
  }
  
  /* Make nested lists more compact - target specific AWSUI class patterns */
  .awsui-box,
  div[class*="awsui_box_"],
  div[class*="awsui_root_"],
  div[class*="awsui_p-s_"],
  div[class*="awsui_p-top_"],
  div[class*="awsui_p-bottom_"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
  }
  
  /* Target specific padding for containers */
  div[class*="awsui_p-s_"] {
    padding: 2px !important;
  }
  
  /* Fix box alignment */
  .awsui-box-inline {
    display: inline-flex !important;
    align-items: center !important;
  }
  
  /* Target container tables */
  table, tbody, tr, td {
    margin: 0 !important;
    padding: 0 !important;
  }
  
  /* Target space-between components */
  div[class*="awsui_space-between_"],
  div[class*="awsui_container_"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
  }
  
  /* Remove excess padding in list items */
  div[class*="awsui_content-"] {
    padding: 2px !important;
  }
  
  /* Target form field spacing */
  div[class*="awsui_form-field_"] {
    margin-bottom: 4px !important;
  }
  
  /* Indentation visual indicator */
  .list-content-indented {
    border-left: 2px solid #aab7b8;
    margin-left: 12px;
    padding-left: 12px !important;
  }
  
  /* Property indentation style - more subtle than list indentation */
  .property-content-indented {
    border-left: 1px solid #d5dbdb;
    margin-left: 8px;
    padding-left: 8px !important;
  }
  
  /* Add button spacing */
  .list-add-button-container {
    padding: 8px 4px 12px 4px !important;
    margin: 0 0 8px 0 !important;
  }
  
  /* Base add button container styling */
  .list-add-button-container {
    position: relative;
    margin-top: 0 !important;
  }
  
  /* Specific styling for nested list add buttons */
  .property-content-indented .list-add-button-container,
  .list-content-indented .list-content-indented .list-add-button-container {
    padding-top: 8px !important;
    margin-top: 4px !important;
  }
  
  /* List separator styling */
  .list-separator {
    margin: 16px 0 16px 0 !important;
  }
  
  /* Nested list separator - more space without a visible line */
  .property-content-indented .list-separator,
  .list-content-indented .list-content-indented .list-separator {
    margin: 10px 0 6px 0 !important;
  }
`;

// Helper functions outside the component to avoid hoisting issues
const getConstraintText = (property: Record<string, unknown>): string => {
  const constraints: string[] = [];
  if (property.minimum !== undefined) {
    constraints.push(`Min: ${property.minimum}`);
  }
  if (property.maximum !== undefined) {
    constraints.push(`Max: ${property.maximum}`);
  }
  return constraints.join(', ');
};

// Resizable Columns Component
interface ResizableColumnsProps {
  columns: number;
  children?: React.ReactNode;
  columnSpacing?: string;
}

const _ResizableColumns = ({ columns, children = null, columnSpacing = '8px' }: ResizableColumnsProps): React.JSX.Element => {
  const [columnWidths, setColumnWidths] = useState<string[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const resizingRef = useRef<{ index: number; startX: number; initialWidths: string[] } | null>(null);

  // Initialize column widths
  useEffect(() => {
    if (containerRef.current) {
      // Initialize with equal width columns
      const initialWidth = `${100 / columns}%`;
      setColumnWidths(Array(columns).fill(initialWidth));
    }
  }, [columns]);

  // Start resizing
  const startResize = (index: number, e: React.MouseEvent): void => {
    e.preventDefault();
    resizingRef.current = {
      index,
      startX: e.clientX,
      initialWidths: [...columnWidths],
    };

    document.addEventListener('mousemove', handleResize);
    document.addEventListener('mouseup', stopResize);
  };

  // Handle resize
  const handleResize = (e: MouseEvent): void => {
    if (!resizingRef.current || !containerRef.current) return;

    const { index, startX, initialWidths } = resizingRef.current;
    const containerWidth = containerRef.current.offsetWidth;
    const deltaPixels = e.clientX - startX;
    const deltaPercent = (deltaPixels / containerWidth) * 100;

    // Calculate new widths
    const newWidths = [...initialWidths];
    newWidths[index] = `calc(${initialWidths[index]} + ${deltaPercent}%)`;
    if (index + 1 < columns) {
      newWidths[index + 1] = `calc(${initialWidths[index + 1]} - ${deltaPercent}%)`;
    }

    setColumnWidths(newWidths);
  };

  // Stop resizing
  const stopResize = () => {
    resizingRef.current = null;
    document.removeEventListener('mousemove', handleResize);
    document.removeEventListener('mouseup', stopResize);
  };

  // Create column containers with proper distribution
  const columnElements = [];

  // Prepare to distribute children into columns - properly group elements
  const childrenArray = React.Children.toArray(children);

  // Calculate how many items should go in each column
  const itemsPerColumn = Math.ceil(childrenArray.length / columns);

  // Create columns with their children
  for (let i = 0; i < columns; i += 1) {
    // Calculate which children go in this column
    const startIndex = i * itemsPerColumn;
    const endIndex = Math.min(startIndex + itemsPerColumn, childrenArray.length);
    const columnChildren = childrenArray.slice(startIndex, endIndex);

    // Only create columns that have children or are the first column
    columnElements.push(
      <ExtBox
        key={i}
        style={{
          width: columnWidths[i] || `${100 / columns}%`,
          padding: `0 ${columnSpacing}`,
          transition: 'none',
          position: 'relative',
        }}
      >
        {columnChildren}

        {i < columns - 1 && (
          <ExtBox
            style={{
              position: 'absolute',
              right: '0',
              top: '0',
              width: '8px',
              height: '100%',
              cursor: 'col-resize',
              zIndex: 1,
              touchAction: 'none',
            }}
            onMouseDown={(e) => startResize(i, e)}
          >
            <ExtBox
              style={{
                position: 'absolute',
                right: '3px',
                top: '0',
                width: '2px',
                height: '100%',
                backgroundColor: 'var(--color-border-divider-default, #e9ebed)',
              }}
            />
            {/* Visual indicator on hover */}
            <ExtBox
              style={{
                position: 'absolute',
                right: '3px',
                top: '50%',
                marginTop: '-10px',
                width: '4px',
                height: '20px',
                backgroundColor: 'var(--color-border-control-default, #aab7b8)',
                borderRadius: '2px',
                opacity: 0,
                transition: 'opacity 0.2s',
              }}
              className="resize-handle-indicator"
            />
          </ExtBox>
        )}
      </ExtBox>,
    );
  }

  return (
    <div ref={containerRef} style={{ display: 'flex', width: '100%', position: 'relative' }}>
      {columnElements}
      <style>
        {`
          .resize-handle-indicator {
            opacity: 0;
          }
          *:hover > .resize-handle-indicator {
            opacity: 0.5;
          }
          *:active > .resize-handle-indicator {
            opacity: 0.8;
          }
        `}
      </style>
    </div>
  );
};

interface ConfigBuilderProps {
  schema?: Record<string, unknown>;
  formValues?: Record<string, unknown>;
  defaultConfig?: Record<string, unknown> | null;
  mergedConfig?: Record<string, unknown> | null;
  isCustomized?: ((key: string) => boolean) | null;
  onResetToDefault?: ((key: string) => void) | null;
  onChange: (values: Record<string, unknown>) => void;
  extractionSchema?: Record<string, unknown> | unknown[] | null;
  currentVersionName?: string | null;
  onSchemaChange?: ((schema: unknown, isDirty: boolean) => void) | null;
  onSchemaValidate?: ((isValid: boolean, errors: unknown[]) => void) | null;
  activeTabId?: string;
  onTabChange?: ((tabId: string) => void) | null;
  showRuleSchema?: boolean;
  ruleSchema?: Record<string, unknown> | unknown[] | null;
  onRuleSchemaChange?: ((schema: unknown, isDirty: boolean) => void) | null;
  onRuleSchemaValidate?: ((isValid: boolean, errors: unknown[]) => void) | null;
  versionDescription?: string;
  onDescriptionChange?: ((description: string) => void) | null;
}

const ConfigBuilder = ({
  schema = { properties: {} },
  formValues = {},
  defaultConfig = null,
  mergedConfig = null,
  isCustomized = null,
  onResetToDefault = null,
  onChange,
  extractionSchema = null,
  currentVersionName = null,
  onSchemaChange = null,
  onSchemaValidate = null,
  activeTabId: controlledActiveTabId = 'configuration',
  onTabChange = null,
  showRuleSchema = false,
  ruleSchema = null,
  onRuleSchemaChange = null,
  onRuleSchemaValidate = null,
  versionDescription = '',
  onDescriptionChange = null,
}: ConfigBuilderProps): React.JSX.Element => {
  // Track expanded state for all list items across the form - default to collapsed
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  // State for add item modals
  const [activeAddModal, setActiveAddModal] = useState<string | null>(null); // Path of the list currently showing add modal
  const [newItemName, setNewItemName] = useState('');
  const [nameError, setNameError] = useState('');
  // For handling dropdown selection in modal
  const [showNameAsDropdown, setShowNameAsDropdown] = useState(false);

  // State for tab selection - use controlled props if provided, otherwise local state
  const [localActiveTabId, setLocalActiveTabId] = useState('configuration');
  const activeTabId = onTabChange ? controlledActiveTabId : localActiveTabId;
  const setActiveTabId = onTabChange || setLocalActiveTabId;

  // Component-level function to add a new item with a name
  const addNewItem = (path: string, name: string): void => {
    // Get current values
    const values = getValueAtPath(formValues, path) || [];
    const property = getPropertyFromPath(path);

    // Validate name first
    if (!name || !name.trim()) {
      setNameError('Name is required');
      return;
    }

    // Check if name already exists
    if ((values as Record<string, unknown>[]).some((item) => item && (item as Record<string, unknown>).name === name.trim())) {
      setNameError('An item with this name already exists');
      return;
    }

    // Create a new item with only required properties and meaningful defaults
    let newItem: unknown;
    if (property && property.items && property.items.type === 'object') {
      const newItemObj: Record<string, unknown> = {};
      if (property.items.properties) {
        Object.entries(property.items.properties).forEach(([propKey, propSchema]) => {
          const ps = propSchema as SchemaProperty;
          if (propKey === 'name') {
            // Always include the name
            newItemObj[propKey] = name.trim();
          } else if (ps.enum && ps.enum.length > 0) {
            // Include enum properties with their first option as default
            const [firstEnumValue] = ps.enum;
            newItemObj[propKey] = firstEnumValue;
          } else if (
            ps.default !== undefined &&
            ps.default !== '' &&
            ps.default !== null &&
            !(Array.isArray(ps.default) && (ps.default as unknown[]).length === 0) &&
            !(
              typeof ps.default === 'object' &&
              ps.default !== null &&
              !Array.isArray(ps.default) &&
              Object.keys(ps.default as Record<string, unknown>).length === 0
            )
          ) {
            // Only include properties with meaningful non-empty default values
            newItemObj[propKey] = ps.default;
          }
          // Skip ALL other properties including:
          // - Empty strings, arrays, objects
          // - Properties without defaults
          // - Properties with empty/null defaults
          // They will be added later when the user actually fills them in
        });
      }
      newItem = newItemObj;
    } else {
      newItem = name.trim();
    }

    // Add to values and update
    updateValue(path, [...(values as unknown[]), newItem]);

    // Close modal and reset
    setActiveAddModal(null);
    setNewItemName('');
    setNameError('');
  };

  // Helper to get property definition from path
  const getPropertyFromPath = (path: string): SchemaProperty | null => {
    if (!schema || !schema.properties) return null;

    const pathParts = path.split(/[.[\]]+/).filter(Boolean);
    let current = schema.properties as Record<string, SchemaProperty>;
    let property: SchemaProperty | null = null;

    // Find the property by traversing the schema
    for (let i = 0; i < pathParts.length; i += 1) {
      const part = pathParts[i];

      if (!Number.isNaN(parseInt(part, 10))) {
        // Skip array indices but continue traversing
        // eslint-disable-next-line no-continue
        continue;
      }

      if (!current[part]) {
        return null;
      }

      property = current[part];

      // Navigate deeper if there are properties
      if (property.properties) {
        current = property.properties as Record<string, SchemaProperty>;
      } else if (property.items && property.items.properties) {
        current = property.items.properties as Record<string, SchemaProperty>;
      }
    }

    return property;
  };

  const getValueAtPath = (obj: Record<string, unknown>, path: string): unknown => {
    const segments = path.split(/[.[\]]+/).filter(Boolean);

    const result = segments.reduce((acc: Record<string, unknown> | undefined, segment: string) => {
      if (acc === null || acc === undefined) {
        return undefined;
      }
      return (acc as Record<string, unknown>)[segment] as Record<string, unknown> | undefined;
    }, obj as Record<string, unknown> | undefined);

    return result;
  };

  const updateValue = (path: string, value: unknown): void => {
    // Don't create properties for empty/meaningless values, BUT preserve empty arrays
    // as they represent intentional user deletions of list items
    // IMPORTANT: Don't filter out boolean false values - they are meaningful!
    if (
      value === '' ||
      value === null ||
      (typeof value === 'object' && value !== null && !Array.isArray(value) && Object.keys(value).length === 0)
    ) {
      // Instead of setting empty values, check if we should remove the property entirely
      const newValues: Record<string, unknown> = { ...formValues };
      const segments = path.split(/[.[\]]+/).filter(Boolean);
      let current: Record<string, unknown> = newValues;

      // Navigate to the parent of the property we want to delete
      for (let i = 0; i < segments.length - 1; i += 1) {
        if (!current[segments[i]]) {
          // Parent doesn't exist, so we can't delete anything
          return;
        }
        current = current[segments[i]] as Record<string, unknown>; // nosemgrep: javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop - Index from controlled array iteration
      }

      const [lastSegment] = segments.slice(-1);
      // Only delete the property if it exists
      if (current && typeof current === 'object' && lastSegment in current) {
        delete current[lastSegment];
        onChange(newValues);
      }
      return;
    }

    // Special handling for empty arrays: preserve them to represent intentional list clearing
    if (Array.isArray(value) && value.length === 0) {
      // Check if this path represents a list field that the user has interacted with
      // We always want to preserve empty arrays as they represent intentional deletions
      const newValues: Record<string, unknown> = { ...formValues };
      const segments = path.split(/[.[\]]+/).filter(Boolean);
      let current: Record<string, unknown> = newValues;

      segments.slice(0, -1).forEach((segment) => {
        if (!current[segment]) {
          // Initialize arrays for list items
          const nextSegment = segments[segments.indexOf(segment) + 1];
          if (nextSegment && !Number.isNaN(parseInt(nextSegment, 10))) {
            current[segment] = [];
          } else {
            current[segment] = {};
          }
        }
        current = current[segment] as Record<string, unknown>; // nosemgrep: javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop - Index from controlled array iteration
      });

      const [lastSegment] = segments.slice(-1);
      current[lastSegment] = value; // Preserve the empty array
      onChange(newValues);
      return;
    }

    const newValues: Record<string, unknown> = { ...formValues };
    const segments = path.split(/[.[\]]+/).filter(Boolean);
    let current: Record<string, unknown> = newValues;

    segments.slice(0, -1).forEach((segment) => {
      if (!current[segment]) {
        // Initialize arrays for list items
        const nextSegment = segments[segments.indexOf(segment) + 1];
        if (nextSegment && !Number.isNaN(parseInt(nextSegment, 10))) {
          current[segment] = [];
        } else {
          current[segment] = {};
        }
      }
      current = current[segment] as Record<string, unknown>; // nosemgrep: javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop - Index from controlled array iteration
    });

    const [lastSegment] = segments.slice(-1);
    current[lastSegment] = value;
    onChange(newValues);
  };

  // Debug: Check if isCustomized function is properly passed
  console.log('ConfigBuilder received isCustomized:', typeof isCustomized, !!isCustomized);

  // Define renderField first as a function declaration
  function renderField(key: string, property: SchemaProperty, path = ''): React.JSX.Element | null {
    const currentPath = path ? `${path}.${key}` : key;
    const value = getValueAtPath(formValues, currentPath);

    // Add debugging for granular assessment
    if (currentPath.includes('granular')) {
      console.log(`DEBUG: Rendering granular field '${key}' at path '${currentPath}':`, {
        // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
        property,
        value,
        formValues: getValueAtPath(formValues, 'assessment'),
      });
    }

    // For objects with properties, ensure the object exists in formValues
    if (property.type === 'object' && property.properties && value === undefined) {
      return null;
    }

    // Check dependencies FIRST, before any rendering - applies to all field types
    if (property.dependsOn) {
      const dependencyField = property.dependsOn.field;
      const dependencyValues = Array.isArray(property.dependsOn.values) ? property.dependsOn.values : [property.dependsOn.value];

      let dependencyPath;

      // Special handling for nested attributes looking for attributeType
      if (
        dependencyField === 'attributeType' &&
        (currentPath.includes('groupAttributes[') || currentPath.includes('listItemTemplate.itemAttributes['))
      ) {
        // For nested attributes, attributeType is in the parent attribute, not the nested attribute itself
        if (currentPath.includes('groupAttributes[')) {
          // For groupAttributes: classes[0].attributes[1].groupAttributes[0].field
          // -> classes[0].attributes[1].attributeType
          const attributeMatch = currentPath.match(/^(.+\.attributes\[\d+\])\.groupAttributes/);
          dependencyPath = attributeMatch ? `${attributeMatch[1]}.attributeType` : null;
        } else if (currentPath.includes('listItemTemplate.itemAttributes[')) {
          // For listItemTemplate: classes[0].attributes[1].listItemTemplate.itemAttributes[0].field
          // -> classes[0].attributes[1].attributeType
          const attributeMatch = currentPath.match(/^(.+\.attributes\[\d+\])\.listItemTemplate\.itemAttributes/);
          dependencyPath = attributeMatch ? `${attributeMatch[1]}.attributeType` : null;
        }

        if (!dependencyPath) {
          console.warn(`Could not resolve attributeType dependency path for nested attribute: ${currentPath}`);
          return null; // Hide field if we can't resolve the dependency
        }
      } else {
        // Normal dependency resolution: first try sibling (same parent), then fall back to top-level
        const parentPath = currentPath.substring(0, currentPath.lastIndexOf('.'));
        const siblingPath = parentPath.length > 0 ? `${parentPath}.${dependencyField}` : dependencyField;
        // Check if the sibling path resolves to a value; if not, try top-level
        if (getValueAtPath(formValues, siblingPath) !== undefined) {
          dependencyPath = siblingPath;
        } else {
          // Fall back to top-level field (e.g., use_bda is at root, not inside assessment)
          dependencyPath = dependencyField;
        }
      }

      // Get the current value of the dependency field
      const dependencyValue = getValueAtPath(formValues, dependencyPath);

      // Enhanced debug logging for dependency checking
      console.log(`DEBUG renderField dependency check for ${key}:`, {
        // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
        key,
        currentPath,
        dependencyField,
        dependencyPath,
        dependencyValue,
        dependencyValueType: typeof dependencyValue,
        dependencyValues,
        dependencyValuesTypes: dependencyValues.map((v) => typeof v),
        isNestedAttribute: currentPath.includes('groupAttributes[') || currentPath.includes('listItemTemplate.itemAttributes['),
        shouldHide: dependencyValue === undefined || !dependencyValues.includes(dependencyValue),
      });

      // Special handling for boolean dependencies
      let normalizedDependencyValue = dependencyValue;
      let normalizedDependencyValues = dependencyValues;

      // If the dependency field is expected to be boolean, normalize the values
      if (dependencyValues.some((v) => typeof v === 'boolean') || typeof dependencyValue === 'boolean') {
        // Convert string representations to boolean
        if (typeof dependencyValue === 'string') {
          if (dependencyValue === 'true') {
            normalizedDependencyValue = true;
          } else if (dependencyValue === 'false') {
            normalizedDependencyValue = false;
          } else {
            normalizedDependencyValue = dependencyValue;
          }
        }

        // Normalize the expected values array
        normalizedDependencyValues = dependencyValues.map((v) => {
          if (typeof v === 'string') {
            if (v === 'true') {
              return true;
            }
            if (v === 'false') {
              return false;
            }
            return v;
          }
          return v;
        });
      }

      // If dependency value doesn't match any required values, hide this field
      if (normalizedDependencyValue === undefined || !normalizedDependencyValues.includes(normalizedDependencyValue)) {
        console.log(`Hiding field ${key} due to dependency mismatch:`, {
          // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Data from trusted internal source only
          normalizedDependencyValue,
          normalizedDependencyValues,
          includes: normalizedDependencyValues.includes(normalizedDependencyValue),
        });
        return null; // Don't render this field
      }
    }

    if (property.type === 'list' || property.type === 'array') {
      return renderListField(key, property, currentPath);
    }

    if (property.type === 'object') {
      return renderObjectField(key, property, path);
    }

    return renderInputField(key, property, value, currentPath);
  }

  function renderObjectField(key: string, property: SchemaProperty, path: string): React.JSX.Element {
    if (!property.properties) {
      return null;
    }

    // Get the full path for this object
    const fullPath = path ? `${path}.${key}` : key;

    // Calculate nesting level for indentation
    const nestLevel = Number(property.nestLevel) || 0;

    // Check if this is a top-level object (path is empty)
    const isTopLevel = path === '';

    // Sort properties by their order attribute if present
    const getSortedObjectProperties = (properties: Record<string, SchemaProperty>) => {
      const entries = Object.entries(properties);
      // Add an order property if not present (default to 999)
      const withOrder = entries.map(([propKey, propSchema]) => ({
        propKey,
        propSchema,
        order: propSchema.order !== undefined ? parseInt(String(propSchema.order), 10) : 999,
      }));
      // Sort by order
      return withOrder.sort((a, b) => a.order - b.order);
    };

    // For top-level objects with sectionLabel, we shouldn't add a container here
    // as it's already being added in renderTopLevelProperty
    if (property.sectionLabel && isTopLevel) {
      // Pre-render fields and filter out nulls to avoid empty Box wrappers causing whitespace
      const renderedFields = getSortedObjectProperties(property.properties)
        .map(({ propKey, propSchema }) => {
          const rendered = renderField(propKey, propSchema, fullPath);
          return rendered ? <ExtBox key={propKey}>{rendered}</ExtBox> : null;
        })
        .filter(Boolean);

      return <SpaceBetween size="s">{renderedFields}</SpaceBetween>;
    }

    // For nested objects with sectionLabel, use the same styling as list headers
    if (property.sectionLabel && !isTopLevel) {
      const sectionTitle = property.sectionLabel as string;
      const objectKey = `object:${fullPath}`;

      // Toggle expansion state
      const toggleExpand = () => {
        setExpandedItems((prev) => ({
          ...prev,
          [objectKey]: !prev[objectKey],
        }));
      };

      // Check if expanded - default to collapsed
      const isExpanded = expandedItems[objectKey] === true;

      // Object header similar to list header
      const objectHeader = (
        <ExtBox
          padding={{ left: `${nestLevel * 16}px`, top: '0', bottom: '0' }}
          borderBottom="divider-light"
          backgroundColor="background-paper-default"
          borderRadius="xs"
          style={{ minHeight: '24px', marginBottom: '2px' }}
        >
          <ExtBox
            display="flex"
            alignItems="center"
            justifyContent="space-between"
            onClick={toggleExpand}
            style={{ cursor: 'pointer', padding: '2px 0' }}
          >
            <ExtBox display="flex" alignItems="center" flexDirection="row" className="awsui-box-inline">
              <Button
                variant="icon"
                iconName={isExpanded ? 'caret-down-filled' : 'caret-right-filled'}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleExpand();
                }}
                ariaLabel={isExpanded ? 'Collapse section' : 'Expand section'}
              />
              <ExtBox fontWeight="bold" fontSize="body-m" marginLeft="xxs" display="inline-block">
                {sectionTitle}
              </ExtBox>
            </ExtBox>
          </ExtBox>
        </ExtBox>
      );

      // Object content - only shown when expanded
      const objectContent = isExpanded && (
        <ExtBox padding={{ left: `${nestLevel * 50 + 200}px`, top: '0' }} className="list-content-indented">
          <SpaceBetween size="s">
            {getSortedObjectProperties(property.properties).map(({ propKey, propSchema }) => {
              return <ExtBox key={propKey}>{renderField(propKey, propSchema, fullPath)}</ExtBox>;
            })}
          </SpaceBetween>
        </ExtBox>
      );

      return (
        <ExtBox margin={{ top: '8px', bottom: '8px' }}>
          {objectHeader}
          {objectContent}
        </ExtBox>
      );
    }

    // Default compact layout for objects without sectionLabel
    return (
      <ExtBox padding="s">
        <SpaceBetween size="xs">
          {getSortedObjectProperties(property.properties).map(({ propKey, propSchema }) => {
            const nestedPropSchema: SchemaProperty =
              propSchema.type === 'list' || propSchema.type === 'array' ? { ...propSchema, nestLevel: nestLevel + 1 } : propSchema;
            return <ExtBox key={propKey}>{renderField(propKey, nestedPropSchema, fullPath)}</ExtBox>;
          })}
        </SpaceBetween>
      </ExtBox>
    );
  }

  function renderListField(key: string, property: SchemaProperty, path: string): React.JSX.Element {
    // Dependencies are now checked in the main renderField function

    const values = (getValueAtPath(formValues, path) || []) as Record<string, unknown>[];

    // Add debug info
    console.log(`Rendering list field: ${key}, type: ${property.type}, path: ${path}`, property, values); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data

    // Get list item display settings from schema metadata
    const columnCount = property.columns ? parseInt(String(property.columns), 10) : 2;
    const nestLevel = Number(property.nestLevel) || 0;
    const nextNestLevel = nestLevel + 1;

    // Get list labels
    const listLabel = (property.listLabel as string) || key.charAt(0).toUpperCase() + key.slice(1);
    const itemLabel = (property.itemLabel as string) || key.charAt(0).toUpperCase() + key.slice(1).replace(/s$/, '');

    // Check if any item in this list is customized
    const hasCustomizedItems = values.some((item: Record<string, unknown>, index: number) => {
      if (!item || !(item as Record<string, unknown>).name) return false;
      const itemPath = `${path}[${index}]`;
      // Check if the item itself or any of its properties are customized
      return isCustomized?.(itemPath);
    });

    // Create unique key for this list's expanded state
    const listKey = `list:${path}`;

    // Toggle expansion of list
    const toggleListExpand = () => {
      setExpandedItems((prev) => ({
        ...prev,
        [listKey]: !prev[listKey],
      }));
    };

    // Check if list is expanded - default to collapsed
    const isListExpanded = expandedItems[listKey] === true;

    // List header with expand/collapse icon and label in the same row
    const listHeader = (
      <ExtBox
        padding={{ left: `${nestLevel * 16}px`, top: '0', bottom: '0' }}
        borderBottom="divider-light"
        backgroundColor={hasCustomizedItems ? 'background-paper-info-emphasis' : 'background-paper-default'}
        borderRadius="xs"
        style={{ minHeight: '24px', marginBottom: '2px' }}
      >
        <ExtBox
          display="flex"
          alignItems="center"
          justifyContent="space-between"
          onClick={toggleListExpand}
          style={{ cursor: 'pointer', padding: '2px 0' }}
        >
          <ExtBox display="flex" alignItems="center" flexDirection="row" className="awsui-box-inline">
            <Button
              variant="icon"
              iconName={isListExpanded ? 'caret-down-filled' : 'caret-right-filled'}
              onClick={(e) => {
                // Stop propagation to prevent double-toggle
                e.stopPropagation();
                toggleListExpand();
              }}
              ariaLabel={isListExpanded ? 'Collapse list' : 'Expand list'}
            />
            <ExtBox fontWeight="bold" fontSize="body-m" marginLeft="xxs" display="inline-block">
              {`${listLabel} (${values.length})`}
              {hasCustomizedItems && (
                <ExtBox as="span" color="text-status-info" fontSize="body-s" fontWeight="normal" marginLeft="xs">
                  (customized)
                </ExtBox>
              )}
            </ExtBox>
          </ExtBox>
        </ExtBox>
      </ExtBox>
    );

    // List content with items - only shown when expanded
    const itemsContent = isListExpanded && (
      <ExtBox padding={{ left: `${nestLevel * 50 + 200}px`, top: '0' }} className="list-content-indented">
        <SpaceBetween size="xs" {...({ size: 'none' } as Record<string, unknown>)}>
          {values.length === 0 && (
            <ExtBox fontStyle="italic" color="text-body-secondary" padding="xs">
              No items added yet
            </ExtBox>
          )}

          {values.map((item, index) => {
            const itemPath = `${path}[${index}]`;
            const isLastItem = index === values.length - 1;

            return (
              <ExtBox
                key={`${itemPath}-${index}`}
                borderBottom="divider-light"
                padding={{ bottom: 'none', top: '0' }}
                style={{
                  marginTop: '1px',
                  marginBottom: isLastItem ? '8px' : '1px',
                }}
              >
                {/* Item header showing the item name prominently */}
                <ExtBox
                  padding={{ top: '0', bottom: '0', left: '4px', right: '4px' }}
                  backgroundColor="background-paper-default"
                  borderBottom="divider-light"
                  style={{
                    marginBottom: '2px',
                    borderTopLeftRadius: '4px',
                    borderTopRightRadius: '4px',
                    minHeight: '22px',
                  }}
                >
                  <ExtBox display="flex" alignItems="center" style={{ padding: '1px 0' }}>
                    <ExtBox display="flex" alignItems="center" className="awsui-box-inline">
                      {/* Delete button - moved to the left of the label */}
                      <Button
                        variant="icon"
                        iconName="remove"
                        onClick={() => {
                          const newValues = [...values];
                          newValues.splice(index, 1);
                          updateValue(path, newValues);
                        }}
                        ariaLabel="Remove item"
                      />

                      <ExtBox
                        fontWeight="bold"
                        fontSize="body-m"
                        color={isCustomized?.(`${itemPath}`) ? 'text-status-info' : 'text-body-default'}
                        display="inline-block"
                      >
                        {String((item as Record<string, unknown>).name || `${itemLabel} ${index + 1}`)}
                        {isCustomized?.(`${itemPath}`) && (
                          <ExtBox as="span" fontSize="body-s" fontWeight="normal" marginLeft="xs" color="text-status-info">
                            (customized)
                          </ExtBox>
                        )}
                      </ExtBox>
                    </ExtBox>
                  </ExtBox>
                </ExtBox>

                {/* Content area with property fields and nested lists - no extra row for delete button */}
                <ExtBox padding={{ top: 'none', bottom: 'none', left: '40px' }} className="property-content-indented">
                  <ExtBox flex="1">
                    {property.items?.type === 'object' ? (
                      (() => {
                        // First, get all property entries sorted by their order if available
                        const propEntries = Object.entries((property.items?.properties || {}) as Record<string, SchemaProperty>)
                          .map(([propKey, prop]) => ({
                            propKey,
                            prop,
                            // Use the specific order if provided, otherwise default to 999
                            order: prop.order !== undefined ? parseInt(String(prop.order), 10) : 999,
                          }))
                          .sort((a, b) => a.order - b.order);

                        // Function to check if a field should be visible (not hidden by dependencies)
                        const isFieldVisible = (propKey: string, propSchema: SchemaProperty) => {
                          if (!propSchema.dependsOn) return true;

                          const dependencyField = propSchema.dependsOn.field;
                          const dependencyValues = Array.isArray(propSchema.dependsOn.values)
                            ? propSchema.dependsOn.values
                            : [propSchema.dependsOn.value];

                          let dependencyPath;
                          const fieldPath = `${itemPath}.${propKey}`;

                          // Special handling for nested attributes looking for attributeType
                          if (
                            dependencyField === 'attributeType' &&
                            (fieldPath.includes('groupAttributes[') || fieldPath.includes('listItemTemplate.itemAttributes['))
                          ) {
                            if (fieldPath.includes('groupAttributes[')) {
                              const attributeMatch = fieldPath.match(/^(.+\.attributes\[\d+\])\.groupAttributes/);
                              dependencyPath = attributeMatch ? `${attributeMatch[1]}.attributeType` : null;
                            } else if (fieldPath.includes('listItemTemplate.itemAttributes[')) {
                              const attributeMatch = fieldPath.match(/^(.+\.attributes\[\d+\])\.listItemTemplate\.itemAttributes/);
                              dependencyPath = attributeMatch ? `${attributeMatch[1]}.attributeType` : null;
                            }
                          } else {
                            const parentPath = fieldPath.substring(0, fieldPath.lastIndexOf('.'));
                            dependencyPath = parentPath.length > 0 ? `${parentPath}.${dependencyField}` : dependencyField;
                          }

                          if (!dependencyPath) return false;

                          const dependencyValue = getValueAtPath(formValues, dependencyPath);
                          return dependencyValue !== undefined && dependencyValues.includes(dependencyValue);
                        };

                        // Separate regular fields from special fields (lists, objects with dependencies)
                        const regularProps = [];
                        const specialProps = []; // For lists, objects with dependsOn, or objects with sectionLabel

                        // Identify and separate the fields, filtering out hidden ones
                        propEntries.forEach(({ propKey, prop: propSchema }: { propKey: string; prop: SchemaProperty }) => {
                          if (
                            propSchema.type === 'list' ||
                            propSchema.type === 'array' ||
                            (propSchema.type === 'object' && (propSchema.dependsOn || propSchema.sectionLabel))
                          ) {
                            specialProps.push({ propKey, propSchema });
                          } else if (isFieldVisible(propKey, propSchema)) {
                            // Only include regular fields that are actually visible
                            regularProps.push({ propKey, propSchema });
                          }
                        });

                        // Add debugging to see field distribution
                        console.log(`Field distribution for ${key}:`, {
                          // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
                          totalProperties: propEntries.length,
                          requestedColumns: columnCount,
                          visibleRegularFields: regularProps.length,
                          specialFields: specialProps.length,
                          hiddenByDependencies: propEntries.length - regularProps.length - specialProps.length,
                        });

                        // Enhanced column distribution algorithm - only for visible fields
                        const distributeFieldsToColumns = (
                          fields: { propKey: string; propSchema: SchemaProperty }[],
                          numColumns: number,
                        ) => {
                          // Create columns array
                          const columns = Array.from({ length: numColumns }, () => []);

                          // Special handling for description field - it should span full width if it exists
                          const descriptionField = fields.find(({ propKey }) => propKey === 'description');
                          const nonDescriptionFields = fields.filter(({ propKey }) => propKey !== 'description');

                          // Calculate optimal column count based on actual field count
                          const actualColumnCount = Math.min(numColumns, Math.max(1, nonDescriptionFields.length));

                          // Distribute non-description fields evenly across columns using round-robin
                          nonDescriptionFields.forEach((field, fieldIndex) => {
                            const targetColumn = fieldIndex % actualColumnCount;
                            columns[targetColumn].push(field);
                          });

                          // Return only the columns that have content
                          const nonEmptyColumns = columns.slice(0, actualColumnCount);

                          return {
                            columns: nonEmptyColumns,
                            descriptionField,
                            actualColumnCount,
                          };
                        };

                        const {
                          columns: fieldColumns,
                          descriptionField,
                          actualColumnCount,
                        } = distributeFieldsToColumns(regularProps, columnCount);

                        // Calculate maximum rows needed
                        const maxRows = Math.max(...fieldColumns.map((col) => col.length));

                        // Validation and debugging for field distribution
                        console.log(`Distribution result for ${key}:`, {
                          // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
                          actualColumnCount,
                          maxRows,
                          columnLengths: fieldColumns.map((col) => col.length),
                          totalFieldsDistributed: fieldColumns.reduce((sum, col) => sum + col.length, 0),
                          hasDescription: !!descriptionField,
                        });

                        // Render the regular fields using HTML table for guaranteed columns
                        const renderedRegularFields = (
                          <ExtBox padding="0" style={{ margin: 0 }}>
                            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '4px 0', margin: 0 }}>
                              <tbody style={{ margin: 0, padding: 0 }}>
                                {/* Render description field first if it exists, spanning full width */}
                                {descriptionField && (
                                  <tr key="description-row">
                                    <td colSpan={actualColumnCount} style={{ verticalAlign: 'top' }}>
                                      <ExtBox padding="0">
                                        {renderField(descriptionField.propKey, descriptionField.propSchema, itemPath)}
                                      </ExtBox>
                                    </td>
                                  </tr>
                                )}

                                {/* Render fields in balanced columns - only create rows with content */}
                                {maxRows > 0 &&
                                  Array.from({ length: maxRows })
                                    .map((_, rowIndex) => {
                                      // Check if this row has any actual content
                                      const rowHasContent = fieldColumns.some((column) => {
                                        const field = column[rowIndex];
                                        return field && field.propKey !== 'name';
                                      });

                                      // Skip empty rows
                                      if (!rowHasContent) {
                                        return null;
                                      }

                                      return (
                                        <tr key={`row-${rowIndex}`}>
                                          {fieldColumns
                                            .map((column, colIndex) => {
                                              const field = column[rowIndex];

                                              // Skip name field - already shown in header
                                              if (field && field.propKey === 'name') {
                                                return null;
                                              }

                                              // Only render cells that have actual content
                                              if (!field) {
                                                return null;
                                              }

                                              const { propKey, propSchema } = field;

                                              return (
                                                <td
                                                  key={`${propKey}-${colIndex}-${rowIndex}`}
                                                  style={{
                                                    verticalAlign: 'top',
                                                    width: `${100 / actualColumnCount}%`,
                                                    padding: '0 4px',
                                                  }}
                                                >
                                                  <ExtBox padding="0">{renderField(propKey, propSchema, itemPath)}</ExtBox>
                                                </td>
                                              );
                                            })
                                            .filter(Boolean)}
                                        </tr>
                                      );
                                    })
                                    .filter(Boolean)}
                              </tbody>
                            </table>
                          </ExtBox>
                        );

                        // Render any special fields (lists, objects with dependencies)
                        const renderedSpecialFields = specialProps.map(
                          ({ propKey, propSchema }: { propKey: string; propSchema: SchemaProperty }) => {
                            // Configure nested field with proper indentation
                            const nestedProps: SchemaProperty = {
                              ...propSchema,
                              // Add 1 to nestLevel for each nesting level with higher multiplier
                              nestLevel: nextNestLevel + 1, // Increase nesting level for better visual distinction
                              // Explicitly set columns for nested fields
                              columns: propSchema.columns || 2,
                            };

                            return (
                              <ExtBox key={propKey} padding={{ top: '0', bottom: '8px' }} width="100%" margin={{ bottom: '4px' }}>
                                {renderField(propKey, nestedProps, itemPath)}
                              </ExtBox>
                            );
                          },
                        );

                        // Return both the regular fields and any special fields
                        return (
                          <ExtBox style={{ margin: 0, padding: 0 }}>
                            {renderedRegularFields}
                            {renderedSpecialFields.length > 0 && (
                              <>
                                {regularProps.length > 0 && <ExtBox padding="4px 0" margin="4px 0" />}
                                <ExtBox padding="0">{renderedSpecialFields}</ExtBox>
                              </>
                            )}
                          </ExtBox>
                        );
                      })()
                    ) : (
                      // Simple list item (non-object)
                      <ExtBox padding="xs">
                        {renderInputField(`${key}[${index}]`, property.items as SchemaProperty, values[index], itemPath)}
                      </ExtBox>
                    )}
                  </ExtBox>
                </ExtBox>
              </ExtBox>
            );
          })}

          {/* Space before add button - only use visual separator for top-level lists */}
          <ExtBox
            className="list-separator"
            padding="0"
            margin="16px 0"
            style={{ borderTop: nestLevel === 0 ? '1px solid #e0e0e0' : 'none' }}
          />

          {/* Add new item button */}
          <ExtBox className="list-add-button-container" display="flex" alignItems="center">
            <ExtBox style={{ width: '24px', display: 'inline-block' }}>
              {/* This empty box provides the same spacing as the delete button */}
            </ExtBox>
            <Button
              iconName="add-plus"
              onClick={() => {
                setActiveAddModal(path);
                setNewItemName('');
                setNameError('');

                // Check if name field has enum property for dropdown
                const propertyDefinition = getPropertyFromPath(path);
                const hasEnumForName = propertyDefinition?.items?.properties?.name?.enum !== undefined;
                setShowNameAsDropdown(hasEnumForName);

                // If it's a dropdown with enum values, set the default value to the first option
                if (hasEnumForName && propertyDefinition.items.properties.name.enum.length > 0) {
                  setNewItemName(propertyDefinition.items.properties.name.enum[0]);
                }
              }}
            >
              Add {itemLabel}
            </Button>
          </ExtBox>
        </SpaceBetween>
      </ExtBox>
    );

    // Combine header and content
    return (
      <ExtBox margin={{ top: '8px', bottom: '8px' }}>
        {listHeader}
        {itemsContent}
      </ExtBox>
    );
  }

  function renderInputField(key: string, property: SchemaProperty, value: unknown, path: string): React.JSX.Element {
    // Special handling for fields with default values
    let displayValue = value;

    // Handle attributeType field default - just for display, actual update handled by useEffect
    if (key === 'attributeType' && (value === undefined || value === null || value === '')) {
      displayValue = 'simple';
    }

    // Handle boolean fields with default values - just for display, actual update handled by useEffect
    if (property.type === 'boolean' && property.default !== undefined && (value === undefined || value === null)) {
      displayValue = property.default;
    }

    // Dependencies are now checked in the main renderField function

    // If this is an object type, it should be rendered as an object field, not an input field
    if (property.type === 'object') {
      console.log(`Redirecting object type ${key} to renderObjectField`); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
      return renderObjectField(key, property, path.substring(0, path.lastIndexOf('.')) || '');
    }

    let input;

    // Add debug info
    console.log(`Rendering input field: ${key}, type: ${property.type}, path: ${path}`, { property, value }); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data

    // Check if we're trying to render an array as an input field (which would be incorrect)
    if (Array.isArray(value) && (property.type === 'array' || property.type === 'list')) {
      console.warn(`Attempting to render array as input field at path: ${path}`, value);
      return renderListField(key, property, path);
    }

    // Check if this field is customized (different from default) using saved config
    let isFieldCustomized = false;
    isFieldCustomized = isCustomized?.(path) ?? false;

    // Check if current form value differs from default (for "Restore to default" button visibility)
    // This uses formValues (live edits) vs defaultConfig, so the button hides immediately after restoring
    // Uses numeric-aware comparison so "5" and "5.0" are treated as equal
    let isFormValueDifferentFromDefault = false;
    if (defaultConfig) {
      const defaultValue = getValueAtPath(defaultConfig, path);
      const formValue = getValueAtPath(formValues, path);
      isFormValueDifferentFromDefault = !areValuesEqual(formValue, defaultValue);
    }

    // Check if current form value differs from last-saved config (for unsaved change indicator)
    let hasUnsavedChange = false;
    if (mergedConfig) {
      const savedValue = getValueAtPath(mergedConfig, path);
      const formValue = getValueAtPath(formValues, path);
      hasUnsavedChange = !areValuesEqual(formValue, savedValue);
    }

    // Show "Restore to default" only if form value currently differs from default
    const showRestoreDefault = isFormValueDifferentFromDefault && onResetToDefault;

    // Check if this is a 'name' field inside an array item by looking for array indices in path
    const isNameInArray =
      key === 'name' &&
      (/\[\d+\]/.test(path) || // Bracket notation - array[0]
        /\.\d+\./.test(path) || // Dot notation with property after - array.0.property
        /\.\d+$/.test(path)); // Dot notation at end - array.0

    // Create a handler for restoring default value (LOCAL ONLY - requires Save to persist)
    const handleRestoreDefault = () => {
      if (onResetToDefault) {
        // resetToDefault returns { path, defaultValue } synchronously
        const result = onResetToDefault(path) as unknown as { path: string; defaultValue: unknown } | void;
        if (result && (result as { defaultValue: unknown }).defaultValue !== undefined) {
          updateValue((result as { path: string }).path, (result as { defaultValue: unknown }).defaultValue);
          console.log(`Restored default value for ${path} (unsaved - click Save to persist)`); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Data from trusted internal source only
        } else if (defaultConfig) {
          // Fallback: get default value directly
          const defaultValue = getValueAtPath(defaultConfig, path);
          if (defaultValue !== undefined) {
            updateValue(path, defaultValue);
            console.log(`Restored default value for ${path} from defaultConfig`); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Data from trusted internal source only
          }
        }
      } else if (defaultConfig) {
        // Manual restore if onResetToDefault is not provided
        const defaultValue = getValueAtPath(defaultConfig, path);
        if (defaultValue !== undefined) {
          updateValue(path, defaultValue);
          console.log(`Restored default value for ${path} from defaultConfig`); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Data from trusted internal source only
        }
      }
    };

    // For name fields inside arrays, use a read-only display instead of an editable input
    if (isNameInArray) {
      input = (
        <ExtBox
          padding="s"
          style={{
            border: '1px solid #ccc',
            borderRadius: '4px',
            backgroundColor: '#f0f0f0',
            color: '#333',
            minHeight: '32px',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span>{value !== undefined && value !== null ? String(value) : ''}</span>
        </ExtBox>
      );
    } else if (property.enum) {
      input = (
        <Select
          selectedOption={{ value: String(displayValue || ''), label: String(displayValue || '') }}
          onChange={({ detail }) => updateValue(path, detail.selectedOption.value)}
          options={(property.enum as string[]).map((opt: string) => ({ value: opt, label: opt }))}
        />
      );
    } else if (property.format === 'text-area' || path.toLowerCase().includes('prompt') || path.toLowerCase().includes('description')) {
      input = (
        <Textarea
          value={displayValue !== undefined && displayValue !== null ? String(displayValue) : ''}
          onChange={({ detail }) => updateValue(path, detail.value)}
          rows={3}
          className="expandable-textarea"
        />
      );
    } else if (property.type === 'boolean') {
      input = <Toggle checked={!!displayValue} onChange={({ detail }) => updateValue(path, detail.checked)} />;
    } else if (property.type === 'array' || property.type === 'list') {
      // This should not happen if renderField is working correctly
      console.error(`Incorrectly trying to render array as input field: ${path}`);
      return renderListField(key, property, path);
    } else {
      input = (
        <Input
          value={displayValue !== undefined && displayValue !== null ? String(displayValue) : ''}
          type={property.type === 'number' ? 'number' : 'text'}
          {...({ min: property.minimum, max: property.maximum } as Record<string, unknown>)}
          onChange={({ detail }) => {
            let finalValue: string | number = detail.value;
            if (property.type === 'number' && detail.value !== '') {
              finalValue = Number(detail.value);
            }
            updateValue(path, finalValue);
          }}
          placeholder={undefined}
        />
      );
    }

    // Use description as the label
    const displayText = (property.description as string) || key;
    const constraints = getConstraintText(property);

    // Stable flex wrapper prevents input remount/focus loss
    // Input is always inside <ExtBox flex="1"> — adding/removing sibling Button
    // doesn't unmount the input, just changes siblings
    const inputWithActions = (
      <ExtBox display="flex" alignItems="center">
        <ExtBox flex="1">{input}</ExtBox>
        {showRestoreDefault && (
          <Button variant="link" onClick={handleRestoreDefault} className="restore-default-button" iconName="undo">
            Restore default
          </Button>
        )}
      </ExtBox>
    );

    // Use standard constraints
    const finalConstraints = constraints.length > 0 ? constraints : undefined;

    // Build CSS class: modified-field (different from default), unsaved-field (unsaved edit)
    const fieldClasses = ['compact-form-field'];
    if (isFieldCustomized) fieldClasses.push('modified-field');
    if (hasUnsavedChange) fieldClasses.push('unsaved-field');

    // Build label with unsaved change dot indicator
    const labelContent = hasUnsavedChange ? (
      <span>
        {displayText}
        <span className="unsaved-change-dot" title="Unsaved change" />
      </span>
    ) : (
      displayText
    );

    return (
      <FormField label={labelContent} constraintText={finalConstraints} stretch className={fieldClasses.join(' ')}>
        {inputWithActions}
      </FormField>
    );
  }

  // Create a sorted list of properties based on their order attribute
  const getSortedProperties = () => {
    const entries = Object.entries((schema?.properties || {}) as Record<string, SchemaProperty>);

    // Add an order property if not present (default to 999)
    const withOrder = entries.map(([key, prop]) => ({
      key,
      property: prop,
      // Use the specific order if provided, otherwise default to 999
      order: prop.order !== undefined ? parseInt(String(prop.order), 10) : 999,
    }));

    // Sort by order
    return withOrder.sort((a, b) => a.order - b.order);
  };

  // Check if a property needs a container with section header
  const shouldUseContainer = (_key: string, property: SchemaProperty) => {
    return property.sectionLabel && (property.type === 'object' || property.type === 'list' || property.type === 'array');
  };

  // Render each top-level property
  const renderTopLevelProperty = ({ key, property }: { key: string; property: SchemaProperty }) => {
    // Debug info for sections
    console.log(
      `Rendering top level property: ${key}, type: ${property.type}, sectionLabel: ${property.sectionLabel}`, // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
      property,
    );

    // Check top-level dependsOn before rendering (hides entire sections when dependency not met)
    if (property.dependsOn) {
      const depField = property.dependsOn.field;
      const depValues = Array.isArray(property.dependsOn.values) ? property.dependsOn.values : [property.dependsOn.value];
      const currentValue = getValueAtPath(formValues, depField);
      // Handle boolean comparison: normalize string "true"/"false" to actual booleans
      let normalizedValue = currentValue;
      if (typeof currentValue === 'string' && (currentValue === 'true' || currentValue === 'false')) {
        normalizedValue = currentValue === 'true';
      }
      const normalizedDepValues = depValues.map((v) => {
        if (typeof v === 'string' && (v === 'true' || v === 'false')) return v === 'true';
        return v;
      });
      if (!normalizedDepValues.includes(normalizedValue)) {
        return null;
      }
    }

    // If property should have a section container, wrap it
    if (shouldUseContainer(key, property)) {
      const sectionTitle = property.sectionLabel as string;
      console.log(`Creating section container for ${key} with title: ${sectionTitle}`); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data

      return (
        <Container key={key} header={<Header variant="h3">{sectionTitle}</Header>}>
          <ExtBox padding="s">{renderField(key, property)}</ExtBox>
        </Container>
      );
    }

    // If it's an array/list with sectionLabel but not caught by shouldUseContainer
    if (property.sectionLabel && (property.type === 'array' || property.type === 'list')) {
      console.warn(`Property ${key} has sectionLabel but wasn't wrapped in container`, property);
    }

    // Default rendering
    return <ExtBox key={key}>{renderField(key, property)}</ExtBox>;
  };

  return (
    <ExtBox style={{ height: '70vh' }} padding="s">
      <style>{customStyles}</style>
      <Tabs
        activeTabId={activeTabId}
        onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
        tabs={[
          {
            id: 'configuration',
            label: 'Configuration',
            content: (
              <ExtBox style={{ height: 'calc(70vh - 60px)', overflow: 'auto' }} padding="s">
                <SpaceBetween size="l">
                  {/* Version Description Field */}
                  <FormField
                    label="Version Description"
                    description="Optional description for this configuration version (max 200 characters)"
                    errorText={versionDescription && versionDescription.length > 200 ? 'Description cannot exceed 200 characters' : ''}
                  >
                    <Input
                      value={versionDescription}
                      onChange={({ detail }) => onDescriptionChange?.(detail.value)}
                      placeholder="Enter a description for this configuration version..."
                      invalid={versionDescription && versionDescription.length > 200}
                    />
                  </FormField>

                  {getSortedProperties().map(renderTopLevelProperty)}
                </SpaceBetween>
              </ExtBox>
            ),
          },
          {
            id: 'extraction-schema',
            label: 'Document Schema',
            content: (
              <ExtBox style={{ height: 'calc(70vh - 60px)' }}>
                <SchemaBuilder
                  key={`schema-${currentVersionName || 'default'}`}
                  initialSchema={extractionSchema as Record<string, unknown> | null}
                  onChange={onSchemaChange}
                  onValidate={onSchemaValidate}
                />
              </ExtBox>
            ),
          },
          // Only show Rule Schema tab for Pattern2
          ...(showRuleSchema
            ? [
                {
                  id: 'rule-schema',
                  label: 'Rule Schema',
                  content: (
                    <ExtBox style={{ height: 'calc(70vh - 60px)' }}>
                      <SchemaBuilder
                        initialSchema={ruleSchema as Record<string, unknown> | null}
                        onChange={onRuleSchemaChange}
                        onValidate={onRuleSchemaValidate}
                        isRuleSchema={true}
                      />
                    </ExtBox>
                  ),
                },
              ]
            : []),
        ]}
      />

      {/* Global modal for adding new items */}
      <Modal
        visible={!!activeAddModal}
        onDismiss={() => setActiveAddModal(null)}
        header={activeAddModal ? `Add new ${getPropertyFromPath(activeAddModal)?.itemLabel || 'Item'}` : 'Add Item'}
        footer={
          <ExtBox float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setActiveAddModal(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => activeAddModal && addNewItem(activeAddModal, newItemName)}>
                Add
              </Button>
            </SpaceBetween>
          </ExtBox>
        }
      >
        {activeAddModal && (
          <FormField
            label="Name"
            description={getPropertyFromPath(activeAddModal)?.items?.properties?.name?.description || 'Enter a unique name for this item'}
            errorText={nameError}
          >
            {showNameAsDropdown ? (
              // Dropdown select for enum values
              <Select
                selectedOption={{
                  value: newItemName || '',
                  label: newItemName || '',
                }}
                onChange={({ detail }) => {
                  setNewItemName(detail.selectedOption.value);
                  setNameError('');
                }}
                options={
                  getPropertyFromPath(activeAddModal)?.items?.properties?.name?.enum?.map((opt) => ({
                    value: opt,
                    label: opt,
                  })) || []
                }
              />
            ) : (
              // Text input for regular string values
              <Input
                value={newItemName}
                onChange={({ detail }) => {
                  setNewItemName(detail.value);
                  if (detail.value.trim()) {
                    setNameError('');
                  }
                }}
                placeholder="Enter name"
              />
            )}
          </FormField>
        )}
      </Modal>
    </ExtBox>
  );
};

export default ConfigBuilder;
