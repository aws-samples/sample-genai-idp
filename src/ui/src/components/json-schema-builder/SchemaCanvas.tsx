import React, { useState } from 'react';
import { Box, SpaceBetween, Header, Button, Badge, Icon, Container } from '@cloudscape-design/components';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, DragEndEvent } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { getTypeColor, getTypeBadgeText } from './utils/badgeHelpers';

interface SchemaAttribute {
  type?: string;
  description?: string;
  'x-aws-idp-attribute-type'?: string;
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  const?: unknown;
  enum?: unknown[];
  oneOf?: Record<string, unknown>[];
  anyOf?: Record<string, unknown>[];
  allOf?: Record<string, unknown>[];
  if?: Record<string, unknown>;
  else?: Record<string, unknown>;
  properties?: Record<string, SchemaAttribute>;
  items?: SchemaAttribute;
  $ref?: string;
  [key: string]: unknown;
}

interface AvailableClass {
  name: string;
  id: string;
  [key: string]: unknown;
}

interface SortableAttributeItemProps {
  id: string;
  name: string;
  attribute: SchemaAttribute;
  isSelected: boolean;
  isRequired: boolean;
  onSelect: (name: string) => void;
  onRemove: (name: string) => void;
  onNavigateToClass?: ((classId: string) => void) | null;
  onNavigateToAttribute?: ((classId: string, attributeName: string | null) => void) | null;
  availableClasses?: AvailableClass[];
}

interface SelectedClass {
  name?: string;
  attributes: {
    properties?: Record<string, SchemaAttribute>;
    required?: string[];
  };
  [key: string]: unknown;
}

interface SchemaCanvasProps {
  selectedClass?: SelectedClass | null;
  selectedAttributeId?: string | null;
  onSelectAttribute: (name: string) => void;
  onUpdateAttribute?: (name: string, updates: Record<string, unknown>) => void;
  onRemoveAttribute: (name: string) => void;
  onReorder: (oldIndex: number, newIndex: number) => void;
  onNavigateToClass?: ((classId: string) => void) | null;
  onNavigateToAttribute?: ((classId: string, attributeName: string | null) => void) | null;
  availableClasses?: AvailableClass[];
  isRuleSchema?: boolean;
}

const SortableAttributeItem = ({
  id,
  name,
  attribute,
  isSelected,
  isRequired,
  onSelect,
  onRemove,
  onNavigateToClass,
  onNavigateToAttribute,
  availableClasses,
}: SortableAttributeItemProps) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const hasNestedProperties = attribute.type === 'object' && attribute.properties && Object.keys(attribute.properties).length > 0;
  const hasComposition = attribute.oneOf || attribute.anyOf || attribute.allOf;
  const hasConditional = attribute.if;
  // Remove array items from expandable - arrays now only show badges
  const isExpandable = hasNestedProperties || hasComposition || hasConditional;

  const handleBadgeClick = (e: React.MouseEvent | React.KeyboardEvent, className: string) => {
    e.stopPropagation();
    if (availableClasses) {
      const referencedClass = availableClasses.find((cls) => cls.name === className);
      if (referencedClass) {
        if (onNavigateToAttribute) {
          onNavigateToAttribute(referencedClass.id, null);
        } else if (onNavigateToClass) {
          onNavigateToClass(referencedClass.id);
        }
      }
    }
  };

  // Individual badge getter functions - each returns a single badge or null
  const getTypeBadge = (): React.JSX.Element | null => {
    const badgeInfo = getTypeBadgeText(attribute);
    if (!badgeInfo) return null;

    // If there's a referenced class, make it clickable
    if (badgeInfo.className) {
      return (
        <span
          onClick={(e) => handleBadgeClick(e, badgeInfo.className as string)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              handleBadgeClick(e, badgeInfo.className as string);
            }
          }}
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
        >
          <Badge color={badgeInfo.color as 'blue' | 'green' | 'grey' | 'red'}>{badgeInfo.text}</Badge>
        </span>
      );
    }

    // Otherwise just return the badge
    return <Badge color={badgeInfo.color as 'blue' | 'green' | 'grey' | 'red'}>{badgeInfo.text}</Badge>;
  };

  const getRequiredBadge = (): React.JSX.Element | null => {
    if (!isRequired) return null;
    return <Badge color="red">required</Badge>;
  };

  const getReadOnlyBadge = (): React.JSX.Element | null => {
    if (!attribute.readOnly) return null;
    return <Badge>read-only</Badge>;
  };

  const getWriteOnlyBadge = (): React.JSX.Element | null => {
    if (!attribute.writeOnly) return null;
    return <Badge>write-only</Badge>;
  };

  const getDeprecatedBadge = (): React.JSX.Element | null => {
    if (!attribute.deprecated) return null;
    return <Badge>deprecated</Badge>;
  };

  const getConstBadge = (): React.JSX.Element | null => {
    // Check both attribute level and items level (for simple arrays)
    const hasConst = attribute.const !== undefined || (attribute.type === 'array' && attribute.items?.const !== undefined);
    if (!hasConst) return null;
    return <Badge color="blue">const</Badge>;
  };

  const getEnumBadge = (): React.JSX.Element | null => {
    // Check both attribute level and items level (for simple arrays)
    const hasEnum = attribute.enum || (attribute.type === 'array' && attribute.items?.enum);
    if (!hasEnum) return null;
    return <Badge color="blue">enum</Badge>;
  };

  const getCompositionBadge = (): React.JSX.Element | null => {
    if (!hasComposition) return null;
    let compositionType = 'allOf';
    if (attribute.oneOf) {
      compositionType = 'oneOf';
    } else if (attribute.anyOf) {
      compositionType = 'anyOf';
    }
    return <Badge color="blue">{compositionType}</Badge>;
  };

  const getConditionalBadge = (): React.JSX.Element | null => {
    if (!hasConditional) return null;
    return <Badge color="blue">if/then</Badge>;
  };

  const renderNestedContent = (): React.JSX.Element | null => {
    if (hasNestedProperties) {
      return (
        <Box padding={{ left: 'l' }}>
          <SpaceBetween size="xs">
            {Object.entries(attribute.properties as Record<string, SchemaAttribute>).map(([propName, propValue]) => (
              <Box key={propName} padding="xs" {...({ style: { borderLeft: '2px solid #ddd' } } as Record<string, unknown>)}>
                <div style={{ fontSize: '12px' }}>
                  <strong>{propName}</strong>:{' '}
                  <Badge color={getTypeColor(propValue.type) as 'blue' | 'green' | 'grey' | 'red'}>{propValue.type}</Badge>
                  {propValue.description && <div style={{ color: '#666', marginTop: '2px' }}>{propValue.description}</div>}
                </div>
              </Box>
            ))}
          </SpaceBetween>
        </Box>
      );
    }

    if (hasComposition) {
      let compositionKey: 'allOf' | 'oneOf' | 'anyOf' = 'allOf';
      if (attribute.oneOf) {
        compositionKey = 'oneOf';
      } else if (attribute.anyOf) {
        compositionKey = 'anyOf';
      }
      const schemas = attribute[compositionKey] as Record<string, unknown>[];
      return (
        <Box padding={{ left: 'l' }}>
          <div style={{ fontSize: '12px', borderLeft: '2px solid #ddd', paddingLeft: '8px' }}>
            <strong>{compositionKey}:</strong> {schemas.length} schemas
          </div>
        </Box>
      );
    }

    if (hasConditional) {
      return (
        <Box padding={{ left: 'l' }}>
          <div style={{ fontSize: '12px', borderLeft: '2px solid #ddd', paddingLeft: '8px' }}>
            <strong>Conditional:</strong> if/then{attribute.else ? '/else' : ''}
          </div>
        </Box>
      );
    }

    return null;
  };

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        marginBottom: '12px',
      }}
    >
      <Container disableContentPaddings={false}>
        <div
          onClick={() => onSelect(name)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              onSelect(name);
            }
          }}
          role="button"
          tabIndex={0}
          style={{
            cursor: 'pointer',
            padding: '12px',
            borderRadius: '8px',
            border: isSelected ? '2px solid #0972d3' : '2px solid transparent',
            backgroundColor: isSelected ? '#e8f4fd' : 'transparent',
            transition: 'all 0.2s ease',
          }}
        >
          <SpaceBetween size="xs">
            <Box>
              <SpaceBetween direction="horizontal" size="s" alignItems="center">
                <span style={{ cursor: 'grab', display: 'flex', alignItems: 'center' }} {...attributes} {...listeners}>
                  <Icon name="drag-indicator" />
                </span>
                {isExpandable && (
                  <span
                    style={{ cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setIsExpanded(!isExpanded);
                    }}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.stopPropagation();
                        setIsExpanded(!isExpanded);
                      }
                    }}
                    aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                  >
                    <Icon name={isExpanded ? 'caret-down-filled' : 'caret-right-filled'} />
                  </span>
                )}
                <Box fontWeight="bold">{name}</Box>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                  {[
                    { key: 'type', component: getTypeBadge() },
                    { key: 'required', component: getRequiredBadge() },
                    { key: 'readonly', component: getReadOnlyBadge() },
                    { key: 'writeonly', component: getWriteOnlyBadge() },
                    { key: 'deprecated', component: getDeprecatedBadge() },
                    { key: 'const', component: getConstBadge() },
                    { key: 'enum', component: getEnumBadge() },
                    { key: 'composition', component: getCompositionBadge() },
                    { key: 'conditional', component: getConditionalBadge() },
                  ]
                    .filter((item) => item.component)
                    .map((item) => (
                      <React.Fragment key={item.key}>{item.component}</React.Fragment>
                    ))}
                </div>
                <Box float="right">
                  <Button
                    variant="icon"
                    iconName="close"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove(name);
                    }}
                    ariaLabel={`Remove ${name}`}
                  />
                </Box>
              </SpaceBetween>
            </Box>
            {attribute.description && (
              <Box fontSize="body-s" color="text-body-secondary">
                {attribute.description}
              </Box>
            )}
            {isExpanded && isExpandable && renderNestedContent()}
          </SpaceBetween>
        </div>
      </Container>
    </div>
  );
};

// Memoize SortableAttributeItem to prevent re-renders of unselected items
const MemoizedSortableAttributeItem = React.memo(SortableAttributeItem);

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
}: SchemaCanvasProps) => {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const attributeLabel = isRuleSchema ? 'rule' : 'attribute';
  const attributesLabel = isRuleSchema ? 'Rules' : 'Attributes';

  if (!selectedClass) {
    return (
      <Box textAlign="center" padding="xxl">
        <Header variant="h3">No Class Selected</Header>
        <p>Select or create a class to start defining {attributeLabel}s</p>
      </Box>
    );
  }

  const attributes = Object.entries(selectedClass.attributes.properties || {});
  const attributeIds = attributes.map(([attributeName]) => attributeName);
  const requiredAttributes = selectedClass.attributes.required || [];

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || !active) return;

    if (active.id !== over.id) {
      const oldIndex = attributeIds.indexOf(active.id as string);
      const newIndex = attributeIds.indexOf(over.id as string);
      onReorder(oldIndex, newIndex);
    }
  };

  return (
    <Box>
      <Header
        variant="h3"
        description={`Click ${
          isRuleSchema ? 'a rule' : 'an attribute'
        } to view and modify its properties. Use the drag handle to reorder, or click the expand arrow to preview nested content.`}
      >
        {attributesLabel} ({attributes.length})
      </Header>
      <SpaceBetween size="s">
        {attributes.length === 0 ? (
          <Box textAlign="center" padding="l" color="text-body-secondary">
            No {attributeLabel}s defined. Click &quot;Add {isRuleSchema ? 'Rule' : 'Attribute'}&quot; to get started.
          </Box>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={attributeIds} strategy={verticalListSortingStrategy}>
              {attributes.map(([attributeName, attribute]) => (
                <MemoizedSortableAttributeItem
                  key={attributeName}
                  id={attributeName}
                  name={attributeName}
                  attribute={attribute}
                  isSelected={selectedAttributeId === attributeName}
                  isRequired={requiredAttributes.includes(attributeName)}
                  onSelect={onSelectAttribute}
                  onRemove={onRemoveAttribute}
                  onNavigateToClass={onNavigateToClass}
                  onNavigateToAttribute={onNavigateToAttribute}
                  availableClasses={availableClasses}
                />
              ))}
            </SortableContext>
          </DndContext>
        )}
      </SpaceBetween>
    </Box>
  );
};

// Memoize the component to prevent re-renders when props haven't changed
export default React.memo(SchemaCanvas);
