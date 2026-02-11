import { TYPE_COLORS } from '../../../constants/schemaConstants';

const typeColorCache = new Map<string, string>();

export const getTypeColor = (type: string): string => {
  if (typeColorCache.has(type)) {
    return typeColorCache.get(type)!;
  }
  const color = TYPE_COLORS[type as keyof typeof TYPE_COLORS] || 'grey';
  typeColorCache.set(type, color);
  return color;
};

export const sanitizeAttribute = (attr: unknown): unknown => {
  if (!attr || typeof attr !== 'object') {
    return attr;
  }

  const cleaned: Record<string, unknown> = { ...(attr as Record<string, unknown>) };
  delete cleaned.id;
  delete cleaned.name;

  if (cleaned.items) {
    cleaned.items = sanitizeAttribute(cleaned.items);
  }

  if (cleaned.properties) {
    const cleanedProperties: Record<string, unknown> = {};
    Object.entries(cleaned.properties as Record<string, unknown>).forEach(([key, value]) => {
      cleanedProperties[key] = sanitizeAttribute(value);
    });
    cleaned.properties = cleanedProperties;
  }

  return cleaned;
};

export const generateUniqueId = (prefix = 'item'): string => {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

export const isValidJSON = (str: string): boolean => {
  try {
    JSON.parse(str);
    return true;
  } catch {
    return false;
  }
};

export const safeParseJSON = (str: string, fallback: unknown = null): unknown => {
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
};

interface SchemaClassObj {
  name: string;
  description?: string;
  attributes: {
    properties?: Record<string, unknown>;
    required?: string[];
  };
}

export const buildJSONSchema = (classObj: SchemaClassObj, allClasses: SchemaClassObj[] = []): Record<string, unknown> => {
  const defs: Record<string, unknown> = {};

  allClasses.forEach((cls) => {
    const sanitizedProperties: Record<string, unknown> = {};
    Object.entries(cls.attributes?.properties || {}).forEach(([key, value]) => {
      sanitizedProperties[key] = sanitizeAttribute(value);
    });

    defs[cls.name] = {
      type: 'object',
      ...(cls.description ? { description: cls.description } : {}),
      properties: sanitizedProperties,
      ...(cls.attributes.required && cls.attributes.required.length > 0 ? { required: cls.attributes.required } : {}),
    };
  });

  const sanitizedProperties: Record<string, unknown> = {};
  Object.entries(classObj.attributes?.properties || {}).forEach(([key, value]) => {
    sanitizedProperties[key] = sanitizeAttribute(value);
  });

  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: classObj.name,
    type: 'object',
    ...(classObj.description ? { description: classObj.description } : {}),
    properties: sanitizedProperties,
    ...(classObj.attributes.required && classObj.attributes.required.length > 0 ? { required: classObj.attributes.required } : {}),
    $defs: defs,
  };
};

export const formatValueForInput = (value: unknown): string => {
  if (value === undefined || value === null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

export const parseInputValue = (input: string, originalType = 'string'): unknown => {
  if (!input || !input.trim()) return undefined;

  if (originalType === 'object' || originalType === 'array') {
    return safeParseJSON(input, input);
  }

  if (originalType === 'number' || originalType === 'integer') {
    const num = parseFloat(input);
    return Number.isNaN(num) ? input : num;
  }

  return input;
};
