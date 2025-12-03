import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Box, SpaceBetween, Header, Button, Badge, Icon, Container } from '@cloudscape-design/components';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { getTypeColor, getTypeBadgeText } from './utils/badgeHelpers';

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
}) => {
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

  const handleBadgeClick = (e, className) => {
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
  const getTypeBadge = () => {
    const badgeInfo = getTypeBadgeText(attribute);
    if (!badgeInfo) return null;

    // If there's a referenced class, make it clickable
    if (badgeInfo.className) {
      return (
        <span
          onClick={(e) => handleBadgeClick(e, badgeInfo.className)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              handleBadgeClick(e, badgeInfo.className);
            }
          }}
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer' }}
        >
          <Badge color={badgeInfo.color}>{badgeInfo.text}</Badge>
        </span>
      );
    }

    // Otherwise just return the badge
    return <Badge color={badgeInfo.color}>{badgeInfo.text}</Badge>;
  };

  const getRequiredBadge = () => {
    if (!isRequired) return null;
    return <Badge color="red">required</Badge>;
  };

  const getReadOnlyBadge = () => {
    if (!attribute.readOnly) return null;
    return <Badge>read-only</Badge>;
  };

  const getWriteOnlyBadge = () => {
    if (!attribute.writeOnly) return null;
    return <Badge>write-only</Badge>;
  };

  const getDeprecatedBadge = () => {
    if (!attribute.deprecated) return null;
    return <Badge>deprecated</Badge>;
  };

  const getConstBadge = () => {
    // Check both attribute level and items level (for simple arrays)
    const hasConst = attribute.const !== undefined || (attribute.type === 'array' && attribute.items?.const !== undefined);
    if (!hasConst) return null;
    return <Badge color="blue">const</Badge>;
  };

  const getEnumBadge = () => {
    // Check both attribute level and items level (for simple arrays)
    const hasEnum = attribute.enum || (attribute.type === 'array' && attribute.items?.enum);
    if (!hasEnum) return null;
    return <Badge color="blue">enum</Badge>;
  };

  const getCompositionBadge = () => {
    if (!hasComposition) return null;
    let compositionType = 'allOf';
    if (attribute.oneOf) {
      compositionType = 'oneOf';
    } else if (attribute.anyOf) {
      compositionType = 'anyOf';
    }
    return <Badge color="blue">{compositionType}</Badge>;
  };

  const getConditionalBadge = () => {
    if (!hasConditional) return null;
    return <Badge color="blue">if/then</Badge>;
  };

  const renderNestedContent = () => {
    if (hasNestedProperties) {
      return (
        <Box padding={{ left: 'l' }}>
          <SpaceBetween size="xs">
            {Object.entries(attribute.properties).map(([propName, propValue]) => (
              <Box key={propName} padding="xs" style={{ borderLeft: '2px solid #ddd' }}>
                <div style={{ fontSize: '12px' }}>
                  <strong>{propName}</strong>: <Badge color={getTypeColor(propValue.type)}>{propValue.type}</Badge>
                  {propValue.description && <div style={{ color: '#666', marginTop: '2px' }}>{propValue.description}</div>}
                </div>
              </Box>
            ))}
          </SpaceBetween>
        </Box>
      );
    }

    if (hasComposition) {
      let compositionKey = 'allOf';
      if (attribute.oneOf) {
        compositionKey = 'oneOf';
      } else if (attribute.anyOf) {
        compositionKey = 'anyOf';
      }
      const schemas = attribute[compositionKey];
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

SortableAttributeItem.propTypes = {
  id: PropTypes.string.isRequired,
  name: PropTypes.string.isRequired,
  attribute: PropTypes.shape({
    type: PropTypes.string,
    description: PropTypes.string,
    'x-aws-idp-attribute-type': PropTypes.string,
  }).isRequired,
  isSelected: PropTypes.bool.isRequired,
  isRequired: PropTypes.bool.isRequired,
  onSelect: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired,
  onNavigateToClass: PropTypes.func,
  onNavigateToAttribute: PropTypes.func,
  availableClasses: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string,
      id: PropTypes.string,
    }),
  ),
};

// Memoize SortableAttributeItem to prevent re-renders of unselected items
const MemoizedSortableAttributeItem = React.memo(SortableAttributeItem);

const SchemaCanvas = ({
  selectedClass,
  selectedAttributeId,
  onSelectAttribute,
  onRemoveAttribute,
  onReorder,
  onNavigateToClass,
  onNavigateToAttribute,
  availableClasses,
}) => {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  if (!selectedClass) {
    return (
      <Box textAlign="center" padding="xxl">
        <Header variant="h3">No Class Selected</Header>
        <p>Select or create a class to start defining attributes</p>
      </Box>
    );
  }

  const attributes = Object.entries(selectedClass.attributes.properties || {});
  const attributeIds = attributes.map(([attributeName]) => attributeName);
  const requiredAttributes = selectedClass.attributes.required || [];

  const handleDragEnd = (event) => {
    const { active, over } = event;

    if (!over || !active) return;

    if (active.id !== over.id) {
      const oldIndex = attributeIds.indexOf(active.id);
      const newIndex = attributeIds.indexOf(over.id);
      onReorder(oldIndex, newIndex);
    }
  };

  return (
    <Box>
      <Header
        variant="h3"
        description="Click an attribute to view and modify its properties. Use the drag handle to reorder, or click the expand arrow to preview nested content."
      >
        Attributes ({attributes.length})
      </Header>
      <SpaceBetween size="s">
        {attributes.length === 0 ? (
          <Box textAlign="center" padding="l" color="text-body-secondary">
            No attributes defined. Click &quot;Add Attribute&quot; to get started.
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

SchemaCanvas.propTypes = {
  selectedClass: PropTypes.shape({
    attributes: PropTypes.shape({
      properties: PropTypes.shape({}),
    }),
  }),
  selectedAttributeId: PropTypes.string,
  onSelectAttribute: PropTypes.func.isRequired,
  onRemoveAttribute: PropTypes.func.isRequired,
  onReorder: PropTypes.func.isRequired,
  onNavigateToClass: PropTypes.func,
  onNavigateToAttribute: PropTypes.func,
  availableClasses: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string,
      id: PropTypes.string,
    }),
  ),
};

SchemaCanvas.defaultProps = {
  selectedClass: null,
  selectedAttributeId: null,
  onNavigateToClass: null,
  onNavigateToAttribute: null,
  availableClasses: [],
};

// Memoize the component to prevent re-renders when props haven't changed
export default React.memo(SchemaCanvas);
