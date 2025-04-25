/* eslint-disable react/no-array-index-key */
/* eslint-disable no-use-before-define */
import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
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
} from '@awsui/components-react';

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
const getConstraintText = (property) => {
  const constraints = [];
  if (property.minimum !== undefined) {
    constraints.push(`Min: ${property.minimum}`);
  }
  if (property.maximum !== undefined) {
    constraints.push(`Max: ${property.maximum}`);
  }
  return constraints.join(', ');
};

// Resizable Columns Component
const ResizableColumns = ({ columns, children, columnSpacing = '8px' }) => {
  const [columnWidths, setColumnWidths] = useState([]);
  const containerRef = useRef(null);
  const resizingRef = useRef(null);

  // Initialize column widths
  useEffect(() => {
    if (containerRef.current) {
      // Initialize with equal width columns
      const initialWidth = `${100 / columns}%`;
      setColumnWidths(Array(columns).fill(initialWidth));
    }
  }, [columns]);

  // Start resizing
  const startResize = (index, e) => {
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
  const handleResize = (e) => {
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
      <Box
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
          <Box
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
            <Box
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
            <Box
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
          </Box>
        )}
      </Box>,
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

// PropTypes for ResizableColumns
ResizableColumns.propTypes = {
  columns: PropTypes.number.isRequired,
  children: PropTypes.node,
  columnSpacing: PropTypes.string,
};

ResizableColumns.defaultProps = {
  children: null,
  columnSpacing: '8px',
};

const FormView = ({ schema, formValues, defaultConfig, isCustomized, onResetToDefault, onChange }) => {
  // Track expanded state for all list items across the form - default to collapsed
  const [expandedItems, setExpandedItems] = useState({});

  // State for add item modals
  const [activeAddModal, setActiveAddModal] = useState(null); // Path of the list currently showing add modal
  const [newItemName, setNewItemName] = useState('');
  const [nameError, setNameError] = useState('');
  // For handling dropdown selection in modal
  const [showNameAsDropdown, setShowNameAsDropdown] = useState(false);

  // Component-level function to add a new item with a name
  const addNewItem = (path, name) => {
    // Get current values
    const values = getValueAtPath(formValues, path) || [];
    const property = getPropertyFromPath(path);

    // Validate name first
    if (!name || !name.trim()) {
      setNameError('Name is required');
      return;
    }

    // Check if name already exists
    if (values.some((item) => item && item.name === name.trim())) {
      setNameError('An item with this name already exists');
      return;
    }

    // Create a new empty item
    let newItem;
    if (property && property.items && property.items.type === 'object') {
      newItem = {};
      if (property.items.properties) {
        Object.entries(property.items.properties).forEach(([propKey, propSchema]) => {
          if (propKey === 'name') {
            newItem[propKey] = name.trim();
          } else if (propSchema.type === 'list' || propSchema.type === 'array') {
            newItem[propKey] = [];
          } else if (propSchema.type === 'object') {
            newItem[propKey] = {};
          } else {
            newItem[propKey] = '';
          }
        });
      }
    } else {
      newItem = name.trim();
    }

    // Add to values and update
    updateValue(path, [...values, newItem]);

    // Close modal and reset
    setActiveAddModal(null);
    setNewItemName('');
    setNameError('');
  };

  // Helper to get property definition from path
  const getPropertyFromPath = (path) => {
    if (!schema || !schema.properties) return null;

    const pathParts = path.split(/[.[\]]+/).filter(Boolean);
    let current = schema.properties;
    let property = null;

    // Find the property by traversing the schema
    for (let i = 0; i < pathParts.length; i += 1) {
      const part = pathParts[i];

      if (!Number.isNaN(parseInt(part, 10))) {
        // Skip array indices
        return property;
      }

      if (!current[part]) {
        return null;
      }

      property = current[part];

      // Navigate deeper if there are properties
      if (property.properties) {
        current = property.properties;
      } else if (property.items && property.items.properties) {
        current = property.items.properties;
      }
    }

    return property;
  };

  const getValueAtPath = (obj, path) => {
    const segments = path.split(/[.[\]]+/).filter(Boolean);

    const result = segments.reduce((acc, segment) => {
      if (acc === null || acc === undefined) {
        return undefined;
      }
      return acc[segment];
    }, obj);

    return result;
  };

  const updateValue = (path, value) => {
    const newValues = { ...formValues };
    const segments = path.split(/[.[\]]+/).filter(Boolean);
    let current = newValues;

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
      current = current[segment];
    });

    current[segments[segments.length - 1]] = value;
    onChange(newValues);
  };

  // Define renderField first as a function declaration
  function renderField(key, property, path = '') {
    const currentPath = path ? `${path}.${key}` : key;
    const value = getValueAtPath(formValues, currentPath);

    if (property.type === 'list' || property.type === 'array') {
      return renderListField(key, property, currentPath);
    }

    if (property.type === 'object') {
      return renderObjectField(key, property, path);
    }

    return renderInputField(key, property, value, currentPath);
  }

  function renderObjectField(key, property, path) {
    if (!property.properties) {
      return null;
    }

    // Get the full path for this object
    const fullPath = path ? `${path}.${key}` : key;

    // Calculate nesting level for indentation
    const nestLevel = property.nestLevel || 0;

    // Check if this is a top-level object (path is empty)
    const isTopLevel = path === '';

    // Sort properties by their order attribute if present
    const getSortedObjectProperties = (properties) => {
      const entries = Object.entries(properties);
      // Add an order property if not present (default to 999)
      const withOrder = entries.map(([propKey, propSchema]) => ({
        propKey,
        propSchema,
        order: propSchema.order !== undefined ? parseInt(propSchema.order, 10) : 999,
      }));
      // Sort by order
      return withOrder.sort((a, b) => a.order - b.order);
    };

    // For top-level objects with sectionLabel, we shouldn't add a container here
    // as it's already being added in renderTopLevelProperty
    if (property.sectionLabel && isTopLevel) {
      return (
        <SpaceBetween size="s">
          {getSortedObjectProperties(property.properties).map(({ propKey, propSchema }) => {
            return <Box key={propKey}>{renderField(propKey, propSchema, fullPath)}</Box>;
          })}
        </SpaceBetween>
      );
    }

    // For nested objects with sectionLabel, use container with section header
    if (property.sectionLabel && !isTopLevel) {
      const sectionTitle = property.sectionLabel;
      return (
        <Container header={<Header variant="h3">{sectionTitle}</Header>}>
          <SpaceBetween size="s">
            {getSortedObjectProperties(property.properties).map(({ propKey, propSchema }) => {
              return <Box key={propKey}>{renderField(propKey, propSchema, fullPath)}</Box>;
            })}
          </SpaceBetween>
        </Container>
      );
    }

    // Default compact layout for objects without sectionLabel
    return (
      <Box padding="s">
        <SpaceBetween size="xs">
          {getSortedObjectProperties(property.properties).map(({ propKey, propSchema }) => {
            const nestedPropSchema =
              propSchema.type === 'list' || propSchema.type === 'array'
                ? { ...propSchema, nestLevel: nestLevel + 1 }
                : propSchema;
            return <Box key={propKey}>{renderField(propKey, nestedPropSchema, fullPath)}</Box>;
          })}
        </SpaceBetween>
      </Box>
    );
  }

  function renderListField(key, property, path) {
    const values = getValueAtPath(formValues, path) || [];

    // Add debug info
    console.log(`Rendering list field: ${key}, type: ${property.type}, path: ${path}`, property, values);

    // Get list item display settings from schema metadata
    const columnCount = property.columns ? parseInt(property.columns, 10) : 2;
    const nestLevel = property.nestLevel || 0;
    const nextNestLevel = nestLevel + 1;

    // Get list labels
    const listLabel = property.listLabel || key.charAt(0).toUpperCase() + key.slice(1);
    const itemLabel = property.itemLabel || key.charAt(0).toUpperCase() + key.slice(1).replace(/s$/, '');

    // Check if any item in this list is customized
    const hasCustomizedItems = values.some((item, index) => {
      if (!item || !item.name) return false;
      const itemPath = `${path}[${index}]`;
      // Check if the item itself or any of its properties are customized
      return isCustomized(itemPath);
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
      <Box
        padding={{ left: `${nestLevel * 16}px`, top: '0', bottom: '0' }}
        borderBottom="divider-light"
        backgroundColor={hasCustomizedItems ? 'background-paper-info-emphasis' : 'background-paper-default'}
        borderRadius="xs"
        style={{ minHeight: '24px', marginBottom: '2px' }}
      >
        <Box
          display="flex"
          alignItems="center"
          justifyContent="space-between"
          onClick={toggleListExpand}
          style={{ cursor: 'pointer', padding: '2px 0' }}
        >
          <Box display="flex" alignItems="center" flexDirection="row" className="awsui-box-inline">
            <Button
              variant="icon"
              iconName={isListExpanded ? 'caret-down-filled' : 'caret-right-filled'}
              onClick={(e) => {
                // Stop propagation to prevent double-toggle
                e.stopPropagation();
                toggleListExpand();
              }}
              ariaLabel={isListExpanded ? 'Collapse list' : 'Expand list'}
              style={{ margin: '0', padding: '0', display: 'inline-flex' }}
              className="awsui-button-icon"
            />
            <Box fontWeight="bold" fontSize="body-m" marginLeft="xxs" display="inline-block">
              {`${listLabel} (${values.length})`}
              {hasCustomizedItems && (
                <Box as="span" color="text-status-info" fontSize="body-s" fontWeight="normal" marginLeft="xs">
                  (customized)
                </Box>
              )}
            </Box>
          </Box>
        </Box>
      </Box>
    );

    // List content with items - only shown when expanded
    const itemsContent = isListExpanded && (
      <Box padding={{ left: `${nestLevel * 50 + 200}px`, top: '0' }} className="list-content-indented">
        <SpaceBetween size="none">
          {values.length === 0 && (
            <Box fontStyle="italic" color="text-body-secondary" padding="xs">
              No items added yet
            </Box>
          )}

          {values.map((item, index) => {
            const itemPath = `${path}[${index}]`;
            const isLastItem = index === values.length - 1;

            return (
              <Box
                key={`${itemPath}-${index}`}
                borderBottom="divider-light"
                padding={{ bottom: 'none', top: '0' }}
                style={{
                  marginTop: '1px',
                  marginBottom: isLastItem ? '8px' : '1px',
                }}
              >
                {/* Item header showing the item name prominently */}
                <Box
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
                  <Box display="flex" alignItems="center" style={{ padding: '1px 0' }}>
                    <Box display="flex" alignItems="center" className="awsui-box-inline">
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
                        style={{ padding: '0', margin: '0 4px 0 0', display: 'inline-flex' }}
                        className="awsui-button-icon"
                      />

                      <Box
                        fontWeight="bold"
                        fontSize="body-m"
                        color={isCustomized(`${itemPath}`) ? 'text-status-info' : 'text-body-default'}
                        display="inline-block"
                      >
                        {item.name || `${itemLabel} ${index + 1}`}
                        {isCustomized(`${itemPath}`) && (
                          <Box as="span" fontSize="body-s" fontWeight="normal" marginLeft="xs" color="text-status-info">
                            (customized)
                          </Box>
                        )}
                      </Box>
                    </Box>
                  </Box>
                </Box>

                {/* Content area with property fields and nested lists - no extra row for delete button */}
                <Box padding={{ top: 'none', bottom: 'none', left: '40px' }} className="property-content-indented">
                  <Box flex="1">
                    {property.items.type === 'object' ? (
                      (() => {
                        // First, get all property entries sorted by their order if available
                        const propEntries = Object.entries(property.items.properties || {})
                          .map(([propKey, prop]) => ({
                            propKey,
                            prop,
                            // Use the specific order if provided, otherwise default to 999
                            order: prop.order !== undefined ? parseInt(prop.order, 10) : 999,
                          }))
                          .sort((a, b) => a.order - b.order);

                        // Add debugging to see actual column count
                        console.log(`Rendering ${columnCount} columns for ${propEntries.length} properties`);

                        // Separate regular fields from list fields
                        const regularProps = [];
                        const listProps = [];

                        // Identify and separate the fields
                        propEntries.forEach(({ propKey, prop: propSchema }) => {
                          if (propSchema.type === 'list' || propSchema.type === 'array') {
                            listProps.push({ propKey, propSchema });
                          } else {
                            regularProps.push({ propKey, propSchema });
                          }
                        });

                        // Render the regular fields using HTML table for guaranteed columns
                        const renderedRegularFields = (
                          <Box padding="0" style={{ margin: 0 }}>
                            <table
                              style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '4px 0', margin: 0 }}
                            >
                              <tbody style={{ margin: 0, padding: 0 }}>
                                {/* Split fields into rows based on columnCount */}
                                {Array.from({ length: Math.ceil(regularProps.length / columnCount) }).map(
                                  (rowItem, rowIndex) => (
                                    <tr key={`row-${rowIndex}`}>
                                      {Array.from({ length: columnCount }).map((colItem, colIndex) => {
                                        const fieldIndex = rowIndex * columnCount + colIndex;
                                        if (fieldIndex >= regularProps.length)
                                          return <td key={`empty-${colIndex}`} aria-hidden="true" />;

                                        const { propKey, propSchema } = regularProps[fieldIndex];
                                        const propPath = `${itemPath}.${propKey}`;
                                        const propValue = getValueAtPath(formValues, propPath);

                                        // Skip rendering the name field since it's already shown in the header
                                        if (propKey === 'name') {
                                          return <td key={propKey} style={{ display: 'none' }} aria-hidden="true" />;
                                        }

                                        return (
                                          <td
                                            key={propKey}
                                            style={{ verticalAlign: 'top', width: `${100 / columnCount}%` }}
                                          >
                                            <Box padding="0">
                                              {renderInputField(propKey, propSchema, propValue, propPath)}
                                            </Box>
                                          </td>
                                        );
                                      })}
                                    </tr>
                                  ),
                                )}
                              </tbody>
                            </table>
                          </Box>
                        );

                        // Render any list fields (like attributes)
                        const renderedListFields = listProps.map(({ propKey, propSchema }) => {
                          const propPath = `${itemPath}.${propKey}`;

                          // Configure nested list with proper indentation
                          const nestedListProps = {
                            ...propSchema,
                            // Add 1 to nestLevel for each nesting level with higher multiplier
                            nestLevel: nextNestLevel + 1, // Increase nesting level for better visual distinction
                            // Explicitly set columns for the nested list
                            columns: propSchema.columns || 2,
                          };

                          return (
                            <Box
                              key={propKey}
                              padding={{ top: '0', bottom: '8px' }}
                              width="100%"
                              margin={{ bottom: '4px' }}
                            >
                              {renderListField(propKey, nestedListProps, propPath)}
                            </Box>
                          );
                        });

                        // Return both the regular fields and any list fields
                        return (
                          <Box style={{ margin: 0, padding: 0 }}>
                            {renderedRegularFields}
                            {renderedListFields.length > 0 && (
                              <>
                                {regularProps.length > 0 && <Box padding="4px 0" margin="4px 0" />}
                                <Box padding="0">{renderedListFields}</Box>
                              </>
                            )}
                          </Box>
                        );
                      })()
                    ) : (
                      // Simple list item (non-object)
                      <Box padding="xs">
                        {renderInputField(`${key}[${index}]`, property.items, values[index], itemPath)}
                      </Box>
                    )}
                  </Box>
                </Box>
              </Box>
            );
          })}

          {/* Space before add button - only use visual separator for top-level lists */}
          <Box
            className="list-separator"
            padding="0"
            margin="16px 0"
            style={{ borderTop: nestLevel === 0 ? '1px solid #e0e0e0' : 'none' }}
          />

          {/* Add new item button */}
          <Box className="list-add-button-container" display="flex" alignItems="center">
            <Box style={{ width: '24px', display: 'inline-block' }}>
              {/* This empty box provides the same spacing as the delete button */}
            </Box>
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
          </Box>
        </SpaceBetween>
      </Box>
    );

    // Combine header and content
    return (
      <Box margin={{ top: '8px', bottom: '8px' }}>
        {listHeader}
        {itemsContent}
      </Box>
    );
  }

  function renderInputField(key, property, value, path) {
    // Check if this field depends on another field's value
    if (property.dependsOn) {
      const dependencyField = property.dependsOn.field;
      const dependencyValues = Array.isArray(property.dependsOn.values)
        ? property.dependsOn.values
        : [property.dependsOn.value];

      // Get the parent path (directory containing the current field)
      const parentPath = path.substring(0, path.lastIndexOf('.'));

      // Get the full path to the dependency field
      const dependencyPath = parentPath.length > 0 ? `${parentPath}.${dependencyField}` : dependencyField;

      // Get the current value of the dependency field
      const dependencyValue = getValueAtPath(formValues, dependencyPath);

      // If dependency value doesn't match any required values, hide this field
      if (dependencyValue === undefined || !dependencyValues.includes(dependencyValue)) {
        return null; // Don't render this field
      }
    }

    let input;

    // Add debug info
    console.log(`Rendering input field: ${key}, type: ${property.type}, path: ${path}`, { property, value });

    // Check if we're trying to render an array as an input field (which would be incorrect)
    if (Array.isArray(value) && (property.type === 'array' || property.type === 'list')) {
      console.warn(`Attempting to render array as input field at path: ${path}`, value);
      return renderListField(key, property, path);
    }

    // Check if this field is customized (different from default)
    let isFieldCustomized = false;
    isFieldCustomized = isCustomized(path);

    // Check if this is a 'name' field inside an array item by looking for array indices in path
    const isNameInArray =
      key === 'name' &&
      (/\[\d+\]/.test(path) || // Bracket notation - array[0]
        /\.\d+\./.test(path) || // Dot notation with property after - array.0.property
        /\.\d+$/.test(path)); // Dot notation at end - array.0

    // Create a handler for restoring default value
    const handleRestoreDefault = () => {
      if (onResetToDefault) {
        // Use the provided onResetToDefault function if available
        onResetToDefault(path)
          .then(() => {
            console.log(`Restored default value for ${path} using onResetToDefault`);
          })
          .catch((error) => {
            console.error(`Error restoring default value: ${error.message}`);

            // Fallback to manual restore if onResetToDefault fails
            if (defaultConfig) {
              const defaultValue = getValueAtPath(defaultConfig, path);
              if (defaultValue !== undefined) {
                updateValue(path, defaultValue);
                console.log(`Manually restored default value for ${path}: ${defaultValue}`);
              }
            }
          });
      } else if (defaultConfig) {
        // Manual restore if onResetToDefault is not provided
        const defaultValue = getValueAtPath(defaultConfig, path);
        if (defaultValue !== undefined) {
          updateValue(path, defaultValue);
          console.log(`Manually restored default value for ${path}: ${defaultValue}`);
        }
      }
    };

    // For name fields inside arrays, use a read-only display instead of an editable input
    if (isNameInArray) {
      input = (
        <Box
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
        </Box>
      );
    } else if (property.enum) {
      input = (
        <Select
          selectedOption={{ value: value || '', label: value || '' }}
          onChange={({ detail }) => updateValue(path, detail.selectedOption.value)}
          options={property.enum.map((opt) => ({ value: opt, label: opt }))}
        />
      );
    } else if (
      property.format === 'text-area' ||
      path.toLowerCase().includes('prompt') ||
      path.toLowerCase().includes('description')
    ) {
      input = (
        <Textarea
          value={value !== undefined && value !== null ? String(value) : ''}
          onChange={({ detail }) => updateValue(path, detail.value)}
          rows={3}
          className="expandable-textarea"
        />
      );
    } else if (property.type === 'boolean') {
      input = <Toggle checked={!!value} onChange={({ detail }) => updateValue(path, detail.checked)} />;
    } else if (property.type === 'array' || property.type === 'list') {
      // This should not happen if renderField is working correctly
      console.error(`Incorrectly trying to render array as input field: ${path}`);
      return renderListField(key, property, path);
    } else {
      input = (
        <Input
          value={value !== undefined && value !== null ? String(value) : ''}
          type={property.type === 'number' ? 'number' : 'text'}
          onChange={({ detail }) => {
            let finalValue = detail.value;
            if (property.type === 'number' && detail.value !== '') {
              finalValue = Number(detail.value);
            }
            updateValue(path, finalValue);
          }}
        />
      );
    }

    // Use description as the label
    const displayText = property.description || key;
    const constraints = getConstraintText(property);

    // Create a wrapper for the input with restore button if customized
    const inputWithRestoreButton = isFieldCustomized ? (
      <Box display="flex" alignItems="center">
        <Box flex="1">{input}</Box>
        <Button variant="link" onClick={handleRestoreDefault} className="restore-default-button" iconName="undo">
          Restore default
        </Button>
      </Box>
    ) : (
      input
    );

    return (
      <FormField
        label={displayText}
        constraintText={constraints.length > 0 ? constraints : undefined}
        stretch
        className={`compact-form-field ${isFieldCustomized ? 'modified-field' : ''}`}
      >
        {inputWithRestoreButton}
      </FormField>
    );
  }

  // Create a sorted list of properties based on their order attribute
  const getSortedProperties = () => {
    const entries = Object.entries(schema?.properties || {});

    // Add an order property if not present (default to 999)
    const withOrder = entries.map(([key, prop]) => ({
      key,
      property: prop,
      // Use the specific order if provided, otherwise default to 999
      order: prop.order !== undefined ? parseInt(prop.order, 10) : 999,
    }));

    // Sort by order
    return withOrder.sort((a, b) => a.order - b.order);
  };

  // Check if a property needs a container with section header
  const shouldUseContainer = (key, property) => {
    return (
      property.sectionLabel && (property.type === 'object' || property.type === 'list' || property.type === 'array')
    );
  };

  // Render each top-level property
  const renderTopLevelProperty = ({ key, property }) => {
    // Debug info for sections
    console.log(
      `Rendering top level property: ${key}, type: ${property.type}, sectionLabel: ${property.sectionLabel}`,
      property,
    );

    // If property should have a section container, wrap it
    if (shouldUseContainer(key, property)) {
      const sectionTitle = property.sectionLabel;
      console.log(`Creating section container for ${key} with title: ${sectionTitle}`);

      return (
        <Container key={key} header={<Header variant="h3">{sectionTitle}</Header>}>
          <Box padding="s">{renderField(key, property)}</Box>
        </Container>
      );
    }

    // If it's an array/list with sectionLabel but not caught by shouldUseContainer
    if (property.sectionLabel && (property.type === 'array' || property.type === 'list')) {
      console.warn(`Property ${key} has sectionLabel but wasn't wrapped in container`, property);
    }

    // Default rendering
    return <Box key={key}>{renderField(key, property)}</Box>;
  };

  return (
    <Box style={{ height: '70vh', overflow: 'auto' }} padding="s">
      <style>{customStyles}</style>
      <SpaceBetween size="l">{getSortedProperties().map(renderTopLevelProperty)}</SpaceBetween>

      {/* Global modal for adding new items */}
      <Modal
        visible={!!activeAddModal}
        onDismiss={() => setActiveAddModal(null)}
        header={activeAddModal ? `Add new ${getPropertyFromPath(activeAddModal)?.itemLabel || 'Item'}` : 'Add Item'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setActiveAddModal(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => activeAddModal && addNewItem(activeAddModal, newItemName)}>
                Add
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        {activeAddModal && (
          <FormField
            label="Name"
            description={
              getPropertyFromPath(activeAddModal)?.items?.properties?.name?.description ||
              'Enter a unique name for this item'
            }
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
                autoFocus
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
                autoFocus
              />
            )}
          </FormField>
        )}
      </Modal>
    </Box>
  );
};

FormView.propTypes = {
  schema: PropTypes.shape({
    properties: PropTypes.objectOf(
      PropTypes.shape({
        type: PropTypes.string,
        description: PropTypes.string,
      }),
    ),
  }),
  formValues: PropTypes.shape({}),
  defaultConfig: PropTypes.shape({}),
  isCustomized: PropTypes.func,
  onResetToDefault: PropTypes.func,
  onChange: PropTypes.func.isRequired,
};

FormView.defaultProps = {
  schema: { properties: {} },
  formValues: {},
  defaultConfig: null,
  isCustomized: null,
  onResetToDefault: null,
};

export default FormView;
