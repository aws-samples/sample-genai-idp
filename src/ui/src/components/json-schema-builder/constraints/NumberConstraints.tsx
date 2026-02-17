import React from 'react';
import { Header, FormField, Input } from '@cloudscape-design/components';

interface SchemaAttribute {
  type?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;
  [key: string]: unknown;
}

interface NumberConstraintsProps {
  attribute: SchemaAttribute;
  onUpdate: (updates: Partial<SchemaAttribute>) => void;
}

const NumberConstraints = ({ attribute, onUpdate }: NumberConstraintsProps): React.JSX.Element | null => {
  if (attribute.type !== 'number' && attribute.type !== 'integer') return null;

  return (
    <>
      <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Number Constraints</Header>

      <FormField label="Minimum" description="Minimum value (inclusive)">
        <Input
          type="number"
          step="any"
          value={attribute.minimum?.toString() || ''}
          onChange={({ detail }) => {
            const updates: Partial<SchemaAttribute> = { minimum: detail.value ? parseFloat(detail.value) : undefined };
            if (detail.value && attribute.exclusiveMinimum !== undefined) {
              updates.exclusiveMinimum = undefined;
            }
            onUpdate(updates);
          }}
          disabled={attribute.exclusiveMinimum !== undefined}
        />
      </FormField>

      <FormField label="Exclusive Minimum" description="Minimum value (exclusive, value must be greater than this)">
        <Input
          type="number"
          step="any"
          value={attribute.exclusiveMinimum?.toString() || ''}
          onChange={({ detail }) => {
            const updates: Partial<SchemaAttribute> = { exclusiveMinimum: detail.value ? parseFloat(detail.value) : undefined };
            if (detail.value && attribute.minimum !== undefined) {
              updates.minimum = undefined;
            }
            onUpdate(updates);
          }}
          disabled={attribute.minimum !== undefined}
        />
      </FormField>

      <FormField label="Maximum" description="Maximum value (inclusive)">
        <Input
          type="number"
          step="any"
          value={attribute.maximum?.toString() || ''}
          onChange={({ detail }) => {
            const updates: Partial<SchemaAttribute> = { maximum: detail.value ? parseFloat(detail.value) : undefined };
            if (detail.value && attribute.exclusiveMaximum !== undefined) {
              updates.exclusiveMaximum = undefined;
            }
            onUpdate(updates);
          }}
          disabled={attribute.exclusiveMaximum !== undefined}
        />
      </FormField>

      <FormField label="Exclusive Maximum" description="Maximum value (exclusive, value must be less than this)">
        <Input
          type="number"
          step="any"
          value={attribute.exclusiveMaximum?.toString() || ''}
          onChange={({ detail }) => {
            const updates: Partial<SchemaAttribute> = { exclusiveMaximum: detail.value ? parseFloat(detail.value) : undefined };
            if (detail.value && attribute.maximum !== undefined) {
              updates.maximum = undefined;
            }
            onUpdate(updates);
          }}
          disabled={attribute.maximum !== undefined}
        />
      </FormField>

      <FormField label="Multiple Of" description="Value must be a multiple of this number">
        <Input
          type="number"
          step="any"
          value={attribute.multipleOf?.toString() || ''}
          onChange={({ detail }) => onUpdate({ multipleOf: detail.value ? parseFloat(detail.value) : undefined })}
          placeholder="e.g., 0.01 for currency, 5 for intervals"
        />
      </FormField>
    </>
  );
};

export default NumberConstraints;
