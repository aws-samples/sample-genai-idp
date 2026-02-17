import React from 'react';
import { Header, FormField, Input, Checkbox } from '@cloudscape-design/components';

interface SchemaAttribute {
  type?: string;
  $ref?: string;
  minProperties?: number;
  maxProperties?: number;
  additionalProperties?: boolean | Record<string, unknown>;
  [key: string]: unknown;
}

interface ObjectConstraintsProps {
  attribute: SchemaAttribute;
  onUpdate: (updates: Partial<SchemaAttribute>) => void;
}

const ObjectConstraints = ({ attribute, onUpdate }: ObjectConstraintsProps): React.JSX.Element | null => {
  if (attribute.type !== 'object' || attribute.$ref) return null;

  return (
    <>
      <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Object Constraints</Header>

      <FormField label="Min Properties" description="Minimum number of properties">
        <Input
          type="number"
          value={attribute.minProperties?.toString() || ''}
          onChange={({ detail }) => onUpdate({ minProperties: detail.value ? parseInt(detail.value, 10) : undefined })}
        />
      </FormField>

      <FormField label="Max Properties" description="Maximum number of properties">
        <Input
          type="number"
          value={attribute.maxProperties?.toString() || ''}
          onChange={({ detail }) => onUpdate({ maxProperties: detail.value ? parseInt(detail.value, 10) : undefined })}
        />
      </FormField>

      <Checkbox
        checked={attribute.additionalProperties === false}
        onChange={({ detail }) => onUpdate({ additionalProperties: detail.checked ? false : undefined })}
      >
        Disallow Additional Properties
      </Checkbox>
    </>
  );
};

export default ObjectConstraints;
