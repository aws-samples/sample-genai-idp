export interface SchemaValidationError {
  field: string;
  message: string;
}

interface SchemaAttribute {
  type?: string;
  $ref?: string;
  oneOf?: unknown[];
  anyOf?: unknown[];
  allOf?: unknown[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;
  minItems?: number;
  maxItems?: number;
  minContains?: number;
  maxContains?: number;
  minProperties?: number;
  maxProperties?: number;
  const?: unknown;
  enum?: unknown[];
  readOnly?: boolean;
  writeOnly?: boolean;
  [key: string]: unknown;
}

export const validateStringConstraints = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.minLength !== undefined && attribute.maxLength !== undefined) {
    if (attribute.minLength > attribute.maxLength) {
      errors.push({ field: 'minLength', message: 'minLength cannot be greater than maxLength' });
    }
  }

  if (attribute.minLength !== undefined && attribute.minLength < 0) {
    errors.push({ field: 'minLength', message: 'minLength must be non-negative' });
  }

  if (attribute.maxLength !== undefined && attribute.maxLength < 0) {
    errors.push({ field: 'maxLength', message: 'maxLength must be non-negative' });
  }

  return errors;
};

export const validateNumberConstraints = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.minimum !== undefined && attribute.exclusiveMinimum !== undefined) {
    errors.push({ field: 'minimum', message: 'Cannot have both minimum and exclusiveMinimum' });
  }

  if (attribute.maximum !== undefined && attribute.exclusiveMaximum !== undefined) {
    errors.push({ field: 'maximum', message: 'Cannot have both maximum and exclusiveMaximum' });
  }

  const min = attribute.minimum ?? attribute.exclusiveMinimum;
  const max = attribute.maximum ?? attribute.exclusiveMaximum;

  if (min !== undefined && max !== undefined && min > max) {
    errors.push({ field: 'minimum', message: 'Minimum cannot be greater than maximum' });
  }

  if (attribute.multipleOf !== undefined && attribute.multipleOf <= 0) {
    errors.push({ field: 'multipleOf', message: 'multipleOf must be greater than 0' });
  }

  return errors;
};

export const validateArrayConstraints = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.minItems !== undefined && attribute.maxItems !== undefined) {
    if (attribute.minItems > attribute.maxItems) {
      errors.push({ field: 'minItems', message: 'minItems cannot be greater than maxItems' });
    }
  }

  if (attribute.minContains !== undefined && attribute.maxContains !== undefined) {
    if (attribute.minContains > attribute.maxContains) {
      errors.push({ field: 'minContains', message: 'minContains cannot be greater than maxContains' });
    }
  }

  if (attribute.minItems !== undefined && attribute.minItems < 0) {
    errors.push({ field: 'minItems', message: 'minItems must be non-negative' });
  }

  if (attribute.maxItems !== undefined && attribute.maxItems < 0) {
    errors.push({ field: 'maxItems', message: 'maxItems must be non-negative' });
  }

  return errors;
};

export const validateObjectConstraints = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.minProperties !== undefined && attribute.maxProperties !== undefined) {
    if (attribute.minProperties > attribute.maxProperties) {
      errors.push({ field: 'minProperties', message: 'minProperties cannot be greater than maxProperties' });
    }
  }

  if (attribute.minProperties !== undefined && attribute.minProperties < 0) {
    errors.push({ field: 'minProperties', message: 'minProperties must be non-negative' });
  }

  if (attribute.maxProperties !== undefined && attribute.maxProperties < 0) {
    errors.push({ field: 'maxProperties', message: 'maxProperties must be non-negative' });
  }

  return errors;
};

export const validateValueConstraints = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.const !== undefined && attribute.enum !== undefined) {
    errors.push({ field: 'const', message: 'Cannot have both const and enum' });
  }

  return errors;
};

export const validateMetadata = (attribute: SchemaAttribute): SchemaValidationError[] => {
  const errors: SchemaValidationError[] = [];

  if (attribute.readOnly && attribute.writeOnly) {
    errors.push({ field: 'readOnly', message: 'Cannot be both readOnly and writeOnly' });
  }

  return errors;
};

export const validateAttribute = (attribute: unknown): { valid: boolean; errors: SchemaValidationError[] } => {
  if (!attribute || typeof attribute !== 'object') {
    return { valid: false, errors: [{ field: 'attribute', message: 'Attribute must be an object' }] };
  }

  const attr = attribute as SchemaAttribute;
  const allErrors: SchemaValidationError[] = [];

  if (!attr.type && !attr.$ref && !attr.oneOf && !attr.anyOf && !attr.allOf) {
    allErrors.push({ field: 'type', message: 'Attribute must have a type, $ref, or composition keyword' });
  }

  if (attr.type === 'string') {
    allErrors.push(...validateStringConstraints(attr));
  }

  if (attr.type === 'number' || attr.type === 'integer') {
    allErrors.push(...validateNumberConstraints(attr));
  }

  if (attr.type === 'array') {
    allErrors.push(...validateArrayConstraints(attr));
  }

  if (attr.type === 'object') {
    allErrors.push(...validateObjectConstraints(attr));
  }

  allErrors.push(...validateValueConstraints(attr));
  allErrors.push(...validateMetadata(attr));

  return {
    valid: allErrors.length === 0,
    errors: allErrors,
  };
};
