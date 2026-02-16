import React, { useState } from 'react';
import { Box, SpaceBetween, Header, Button, Badge, Icon, Container } from '@cloudscape-design/components';
import { formatTypeBadge, getTypeBadgeText } from './utils/badgeHelpers';
import { X_AWS_IDP_RULE_TYPE } from '../../constants/schemaConstants';

interface SchemaAttribute {
  type?: string;
  $ref?: string;
  items?: {
    type?: string;
    $ref?: string;
    properties?: Record<string, unknown>;
    [key: string]: unknown;
  };
  description?: string;
  [key: string]: unknown;
}

interface SchemaClass {
  id: string;
  name: string;
  attributes?: {
    properties?: Record<string, SchemaAttribute>;
    required?: string[];
  };
  [key: string]: unknown;
}

interface SchemaCanvasProps {
  selectedClass?: SchemaClass | null;
  selectedAttributeId?: string | null;
  onSelectAttribute: (attributeId: string | null) => void;
  onUpdateAttribute: (name: string, updates: Partial<SchemaAttribute>) => void;
  onRemoveAttribute: (name: string) => void;
  onReorder: (oldIndex: number, newIndex: number) => void;
  onNavigateToClass?: ((classId: string) => void) | null;
  onNavigateToAttribute?: ((classId: string, attributeName: string | null) => void) | null;
  availableClasses?: SchemaClass[];
  isRuleSchema?: boolean;
}

const SchemaCanvas = ({
  selectedClass = null,
  selectedAttributeId = null,
  onSelectAttribute,
  onRemoveAttribute,
  onReorder,
  onNavigateToClass = null,
  onNavigateToAttribute = null,
  availableClasses = [],
  isRuleSchema = false,
}: SchemaCanvasProps): React.JSX.Element => {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  // Dynamic labels based on schema type
  const attributeLabel = isRuleSchema ? 'Rule' : 'Attribute';
  const attributesLabel = isRuleSchema ? 'Rules' : 'Attributes';

  if (!selectedClass) {
    return (
      <Box textAlign="center" padding="xxl">
        <SpaceBetween size="m">
          <Header variant="h3">{attributesLabel} Canvas</Header>
          <p>Select a class from the panel to view and manage its {attributesLabel.toLowerCase()}</p>
        </SpaceBetween>
      </Box>
    );
  }

  const properties = selectedClass.attributes?.properties || {};
  const required = selectedClass.attributes?.required || [];
  const attributeNames = Object.keys(properties);

  const handleDragStart = (index: number): void => {
    setDragIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number): void => {
    e.preventDefault();
    if (dragIndex !== null && dragIndex !== index) {
      setDragOverIndex(index);
    }
  };

  const handleDrop = (index: number): void => {
    if (dragIndex !== null && dragIndex !== index) {
      onReorder(dragIndex, index);
    }
    setDragIndex(null);
    setDragOverIndex(null);
  };

  const handleDragEnd = (): void => {
    setDragIndex(null);
    setDragOverIndex(null);
  };

  // Helper to find the class being referenced
  const findReferencedClass = (ref: string): SchemaClass | undefined => {
    const className = ref.replace('#/$defs/', '');
    return availableClasses.find((cls) => cls.name === className);
  };

  // Render reference link for navigating to referenced classes
  const renderReferenceLink = (ref: string): React.JSX.Element | null => {
    const referencedClass = findReferencedClass(ref);
    if (!referencedClass) return null;

    return (
      <Button
        variant="inline-link"
        iconName="external"
        onClick={(e) => {
          e.stopPropagation();
          if (onNavigateToAttribute) {
            onNavigateToAttribute(referencedClass.id, null);
          } else if (onNavigateToClass) {
            onNavigateToClass(referencedClass.id);
          }
        }}
      >
        Go to {referencedClass.name}
      </Button>
    );
  };

  return (
    <Box>
      <SpaceBetween size="m">
        <Header variant="h3">
          {attributesLabel}: {selectedClass.name} ({attributeNames.length})
        </Header>

        {attributeNames.length === 0 && (
          <Box textAlign="center" padding="l" color="text-body-secondary">
            <p>
              No {attributesLabel.toLowerCase()} yet. Click &quot;Add {attributeLabel}&quot; to start building.
            </p>
          </Box>
        )}

        {attributeNames.map((attrName, index) => {
          const attr = properties[attrName];
          const isRequired = required.includes(attrName);
          const isSelected = selectedAttributeId === attrName;
          const isDragging = dragIndex === index;
          const isDragOver = dragOverIndex === index;
          const badgeInfo = getTypeBadgeText(attr);

          return (
            <Container key={attrName} disableContentPaddings={false}>
              <div
                role="button"
                tabIndex={0}
                draggable
                onDragStart={() => handleDragStart(index)}
                onDragOver={(e) => handleDragOver(e, index)}
                onDrop={() => handleDrop(index)}
                onDragEnd={handleDragEnd}
                onClick={() => onSelectAttribute(attrName)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    onSelectAttribute(attrName);
                  }
                }}
                style={{
                  cursor: 'pointer',
                  padding: '12px',
                  borderRadius: '8px',
                  border: isSelected ? '2px solid #0972d3' : isDragOver ? '2px dashed #0972d3' : '2px solid transparent',
                  backgroundColor: isSelected ? '#e8f4fd' : isDragging ? '#f0f0f0' : 'transparent',
                  opacity: isDragging ? 0.5 : 1,
                  transition: 'all 0.2s ease',
                }}
              >
                <SpaceBetween size="xs">
                  <Box>
                    <SpaceBetween direction="horizontal" size="s" alignItems="center">
                      <Icon name="drag-indicator" size="normal" />
                      <Box fontWeight="bold">{attrName}</Box>
                      {isRequired && <Badge color="red">required</Badge>}
                      {isRuleSchema && attr[X_AWS_IDP_RULE_TYPE] && <Badge color="blue">Rule</Badge>}
                      {formatTypeBadge(attr)}

                      <Box float="right">
                        <Button
                          variant="icon"
                          iconName="close"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveAttribute(attrName);
                          }}
                          ariaLabel={`Remove ${attrName}`}
                        />
                      </Box>
                    </SpaceBetween>
                  </Box>

                  {attr.description && (
                    <Box fontSize="body-s" color="text-body-secondary">
                      {attr.description.length > 120 ? `${attr.description.substring(0, 120)}...` : attr.description}
                    </Box>
                  )}

                  {/* Show reference link if attribute references another class */}
                  {attr.$ref && renderReferenceLink(attr.$ref)}
                  {attr.type === 'array' && attr.items?.$ref && renderReferenceLink(attr.items.$ref)}

                  {/* For referenced classes, show their attributes as nested items */}
                  {badgeInfo?.className && (
                    <Box padding={{ left: 'l' }}>
                      {(() => {
                        const referencedClass = findReferencedClass(attr.$ref || (attr.items?.$ref as string) || '');
                        if (!referencedClass) return null;

                        const refProps = referencedClass.attributes?.properties || {};
                        const refPropNames = Object.keys(refProps);
                        if (refPropNames.length === 0) return null;

                        return (
                          <SpaceBetween size="xxs">
                            <Box fontSize="body-s" color="text-body-secondary" fontWeight="bold">
                              {referencedClass.name} fields:
                            </Box>
                            {refPropNames.slice(0, 5).map((propName) => (
                              <div
                                key={propName}
                                role="button"
                                tabIndex={0}
                                style={{ cursor: 'pointer', fontSize: '0.875rem', color: '#5f6b7a' }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (onNavigateToAttribute) {
                                    onNavigateToAttribute(referencedClass.id, propName);
                                  }
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    e.stopPropagation();
                                    if (onNavigateToAttribute) {
                                      onNavigateToAttribute(referencedClass.id, propName);
                                    }
                                  }
                                }}
                              >
                                &nbsp;&nbsp;• {propName} {formatTypeBadge(refProps[propName])}
                              </div>
                            ))}
                            {refPropNames.length > 5 && (
                              <Box fontSize="body-s" color="text-body-secondary">
                                &nbsp;&nbsp;...and {refPropNames.length - 5} more
                              </Box>
                            )}
                          </SpaceBetween>
                        );
                      })()}
                    </Box>
                  )}
                </SpaceBetween>
              </div>
            </Container>
          );
        })}
      </SpaceBetween>
    </Box>
  );
};

export default SchemaCanvas;
