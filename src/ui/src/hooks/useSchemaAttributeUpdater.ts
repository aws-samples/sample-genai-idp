import { useCallback } from 'react';
import { validateAttribute } from '../components/json-schema-builder/utils/schemaValidators';

export const useSchemaAttributeUpdater = (
  selectedAttribute: Record<string, unknown> | null,
  onUpdate: ((attr: Record<string, unknown>) => void) | null,
): {
  safeUpdate: (updates: Record<string, unknown>) => boolean;
  updateField: (fieldName: string, value: unknown) => boolean;
  updateFields: (fields: Record<string, unknown>) => boolean;
  clearField: (fieldName: string) => boolean;
} => {
  const safeUpdate = useCallback(
    (updates: Record<string, unknown>) => {
      if (!selectedAttribute || !onUpdate) return false;

      const mergedAttribute = { ...selectedAttribute, ...updates };

      Object.keys(updates).forEach((key) => {
        if (updates[key] === undefined) {
          delete mergedAttribute[key];
        }
      });

      const validation = validateAttribute(mergedAttribute);

      if (!validation.valid && validation.errors.length > 0) {
        console.warn('Attribute validation warnings:', validation.errors);
      }

      onUpdate(mergedAttribute);
      return true;
    },
    [selectedAttribute, onUpdate],
  );

  const updateField = useCallback(
    (fieldName: string, value: unknown) => {
      return safeUpdate({ [fieldName]: value });
    },
    [safeUpdate],
  );

  const updateFields = useCallback(
    (fields: Record<string, unknown>) => {
      return safeUpdate(fields);
    },
    [safeUpdate],
  );

  const clearField = useCallback(
    (fieldName: string) => {
      return safeUpdate({ [fieldName]: undefined });
    },
    [safeUpdate],
  );

  return {
    safeUpdate,
    updateField,
    updateFields,
    clearField,
  };
};
