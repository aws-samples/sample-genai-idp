import React from 'react';
import PropTypes from 'prop-types';
import { Header, FormField, Input, Select } from '@cloudscape-design/components';
import { FORMAT_OPTIONS } from '../../../constants/schemaConstants';

const StringConstraints = ({ attribute, onUpdate }) => {
  if (attribute.type !== 'string') return null;

  return (
    <>
      <Header variant="h4">String Constraints (JSON Schema)</Header>

      <FormField label="Pattern (regex)" description="Regular expression pattern to validate the extracted string format">
        <Input
          value={attribute.pattern || ''}
          onChange={({ detail }) => onUpdate({ pattern: detail.value || undefined })}
          placeholder="e.g., ^\d{3}-\d{2}-\d{4}$ for SSN format"
        />
      </FormField>

      <FormField
        label="Format (JSON Schema)"
        description="JSON Schema built-in format validation. Values must match the specified format exactly."
        constraintText="Select a format to enforce validation on extracted values"
      >
        <Select
          selectedOption={FORMAT_OPTIONS.find((opt) => opt.value === (attribute.format || '')) || FORMAT_OPTIONS[0]}
          onChange={({ detail }) => onUpdate({ format: detail.selectedOption.value || undefined })}
          options={FORMAT_OPTIONS}
        />
      </FormField>

      <FormField label="Min Length" description="Minimum number of characters required">
        <Input
          type="number"
          value={attribute.minLength?.toString() || ''}
          onChange={({ detail }) => onUpdate({ minLength: detail.value ? parseInt(detail.value, 10) : undefined })}
          placeholder="e.g., 3"
        />
      </FormField>

      <FormField label="Max Length" description="Maximum number of characters allowed">
        <Input
          type="number"
          value={attribute.maxLength?.toString() || ''}
          onChange={({ detail }) => onUpdate({ maxLength: detail.value ? parseInt(detail.value, 10) : undefined })}
          placeholder="e.g., 100"
        />
      </FormField>
    </>
  );
};

StringConstraints.propTypes = {
  attribute: PropTypes.shape({
    type: PropTypes.string,
    pattern: PropTypes.string,
    format: PropTypes.string,
    minLength: PropTypes.number,
    maxLength: PropTypes.number,
  }).isRequired,
  onUpdate: PropTypes.func.isRequired,
};

export default StringConstraints;
