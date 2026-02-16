import React from 'react';
import { Badge } from '@cloudscape-design/components';

export const DOCUMENT_TYPE_BADGE_COLOR = 'blue';

interface DocumentTypeBadgeProps {
  isRuleSchema?: boolean;
}

interface BadgeInfo {
  text: string;
  color: string;
  className: string | null;
}

interface SchemaAttribute {
  type?: string;
  $ref?: string;
  items?: {
    type?: string;
    $ref?: string;
    properties?: Record<string, unknown>;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export const DocumentTypeBadge = ({ isRuleSchema = false }: DocumentTypeBadgeProps): React.JSX.Element => (
  <Badge color={DOCUMENT_TYPE_BADGE_COLOR}>{isRuleSchema ? 'Rule Type' : 'Document Type'}</Badge>
);

export const getTypeColor = (type: string | undefined): string => {
  switch (type) {
    case 'string':
      return 'blue';
    case 'number':
      return 'green';
    case 'boolean':
      return 'grey';
    case 'object':
      return 'red';
    case 'array':
      return 'blue';
    default:
      return 'grey';
  }
};

export const getTypeBadgeText = (attribute: SchemaAttribute | null | undefined): BadgeInfo | null => {
  if (!attribute) return null;

  // Object with reference: show as "ClassName" (without object prefix)
  // Note: When an attribute has a $ref, it typically doesn't have a type field
  if (attribute.$ref) {
    const className = attribute.$ref.replace('#/$defs/', '');
    return { text: `${className}`, color: getTypeColor('object'), className };
  }

  // Array with reference: show as "array[ClassName]"
  if (attribute.type === 'array' && attribute.items?.$ref) {
    const className = attribute.items.$ref.replace('#/$defs/', '');
    return { text: `array[${className}]`, color: getTypeColor('array'), className };
  }

  // Array with simple type: show as "array[type]"
  if (attribute.type === 'array' && attribute.items?.type) {
    return { text: `array[${attribute.items.type}]`, color: getTypeColor('array'), className: null };
  }

  // Array with inline objects: show as "array[object]"
  if (attribute.type === 'array' && attribute.items?.properties) {
    return { text: 'array[object]', color: getTypeColor('array'), className: null };
  }

  // Array without items: show generic "array"
  if (attribute.type === 'array') {
    return { text: 'array', color: getTypeColor('array'), className: null };
  }

  // Simple type or no type
  const typeValue = attribute.type || 'any';
  return { text: typeValue, color: getTypeColor(typeValue), className: null };
};

export const formatTypeBadge = (attribute: SchemaAttribute | null | undefined): React.JSX.Element | null => {
  const badgeInfo = getTypeBadgeText(attribute);
  if (!badgeInfo) return null;
  return <Badge color={badgeInfo.color as 'blue' | 'green' | 'grey' | 'red'}>{badgeInfo.text}</Badge>;
};
