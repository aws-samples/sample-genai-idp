import React, { useState, useEffect } from 'react';
import { Box, SpaceBetween, Header, FormField, Input, Select, Textarea, Checkbox, Button, Alert } from '@cloudscape-design/components';
import StringConstraints from './constraints/StringConstraints';
import NumberConstraints from './constraints/NumberConstraints';
import ArrayConstraints from './constraints/ArrayConstraints';
import ObjectConstraints from './constraints/ObjectConstraints';
import MetadataFields from './constraints/MetadataFields';
import ValueConstraints from './constraints/ValueConstraints';
import ExamplesEditor from './constraints/ExamplesEditor';
import {
  TYPE_OPTIONS,
  EVALUATION_METHOD_OPTIONS,
  EVALUATION_THRESHOLD_DEFAULTS,
  EVALUATION_MATCH_THRESHOLD_DEFAULTS,
  METHODS_REQUIRING_THRESHOLD,
  METHODS_REQUIRING_MATCH_THRESHOLD,
  EVALUATION_METHOD_HUNGARIAN,
  X_AWS_IDP_DOCUMENT_TYPE,
  X_AWS_IDP_EVALUATION_METHOD,
  X_AWS_IDP_EVALUATION_THRESHOLD,
  X_AWS_IDP_EVALUATION_WEIGHT,
  X_AWS_IDP_EVALUATION_MATCH_THRESHOLD,
  X_AWS_IDP_CONFIDENCE_THRESHOLD,
  X_AWS_IDP_EXAMPLES,
  X_AWS_IDP_DOCUMENT_NAME_REGEX,
  X_AWS_IDP_PAGE_CONTENT_REGEX,
} from '../../constants/schemaConstants';

interface SchemaAttribute {
  type?: string;
  $ref?: string;
  description?: string;
  properties?: Record<string, unknown>;
  required?: string[];
  minProperties?: number;
  maxProperties?: number;
  additionalProperties?: boolean | Record<string, unknown>;
  items?: {
    type?: string;
    $ref?: string;
    properties?: Record<string, unknown>;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface Example {
  id?: string;
  name: string;
  classPrompt: string;
  attributesPrompt: string;
  imagePath: string;
}

interface SchemaClass {
  id: string;
  name: string;
  description?: string;
  attributes?: {
    properties?: Record<string, SchemaAttribute>;
    required?: string[];
  };
  [key: string]: unknown;
}

interface UsageInfo {
  className: string;
  classId: string;
  attributeName: string;
  type: string;
}

interface SchemaInspectorProps {
  selectedClass?: SchemaClass | null;
  selectedAttribute?: SchemaAttribute | null;
  selectedAttributeName?: string | null;
  onUpdate: (updates: Partial<SchemaAttribute>) => void;
  onUpdateClass?: (updates: Record<string, unknown>) => void;
  onRenameAttribute?: (newName: string) => boolean;
  availableClasses?: SchemaClass[];
  isRequired?: boolean;
  onToggleRequired?: (checked: boolean) => void;
  onNavigateToClass?: ((classId: string) => void) | null;
  onNavigateToAttribute?: ((classId: string, attributeName: string | null) => void) | null;
  isRuleSchema?: boolean;
}

const SchemaInspector = ({
  selectedClass = null,
  selectedAttribute = null,
  selectedAttributeName = null,
  onUpdate,
  onUpdateClass = () => {},
  onRenameAttribute = () => true,
  availableClasses = [],
  isRequired = false,
  onToggleRequired = () => {},
  onNavigateToClass = null,
  onNavigateToAttribute = null,
  isRuleSchema = false,
}: SchemaInspectorProps): React.JSX.Element => {
  // Dynamic labels based on schema type
  const typeLabel = isRuleSchema ? 'rule' : 'document';
  const TypeLabel = isRuleSchema ? 'Rule' : 'Document';

  // Show class-level settings when class is selected but no attribute is selected
  if (selectedClass && (!selectedAttribute || !selectedAttributeName)) {
    // Find where this class is being used
    const usedIn: UsageInfo[] = [];
    if (availableClasses) {
      availableClasses.forEach((cls) => {
        if (cls.id === selectedClass.id) return; // Skip self

        const properties = cls.attributes?.properties || {};
        Object.entries(properties).forEach(([attrName, attrSchema]) => {
          // Check if attribute references this class
          if (attrSchema.$ref === `#/$defs/${selectedClass.name}`) {
            usedIn.push({
              className: cls.name,
              classId: cls.id,
              attributeName: attrName,
              type: 'object',
            });
          } else if (attrSchema.items?.$ref === `#/$defs/${selectedClass.name}`) {
            usedIn.push({
              className: cls.name,
              classId: cls.id,
              attributeName: attrName,
              type: 'array',
            });
          }
        });
      });
    }

    return (
      <Box>
        <Header variant="h3">{isRuleSchema ? 'Rule Class Properties' : `Class Inspector: ${selectedClass.name}`}</Header>
        <SpaceBetween size="m">
          <FormField
            label={`${TypeLabel} Type`}
            description={`${TypeLabel} types become top-level schemas. ${
              isRuleSchema ? 'Uncheck this for non-rule-type classes.' : 'Shared classes are reusable definitions.'
            }`}
          >
            <Checkbox
              checked={(selectedClass[X_AWS_IDP_DOCUMENT_TYPE] as boolean) || false}
              onChange={({ detail }) => onUpdateClass({ [X_AWS_IDP_DOCUMENT_TYPE]: detail.checked })}
            >
              This is a {typeLabel} type
            </Checkbox>
          </FormField>

          {selectedClass[X_AWS_IDP_DOCUMENT_TYPE] ? (
            <Alert type="info">
              <strong>{TypeLabel} Type</strong>
              <br />
              This class will be exported as a standalone JSON schema. Each {typeLabel} type schema will only include $defs for classes it
              actually references, keeping schemas minimal and focused.
            </Alert>
          ) : (
            !isRuleSchema && (
              <Alert type="info">
                <strong>Shared Class</strong>
                <br />
                This class is available to be referenced by {typeLabel} types and other classes. It will only appear in the $defs section of
                schemas that reference it.
              </Alert>
            )
          )}

          <FormField label={isRuleSchema ? 'Rule Class Description' : 'Class Description'} description="Describe the purpose of this class">
            <Textarea
              value={selectedClass.description || ''}
              onChange={({ detail }) => onUpdateClass({ description: detail.value || undefined })}
              rows={3}
              placeholder="Describe what this class represents"
            />
          </FormField>

          {selectedClass[X_AWS_IDP_DOCUMENT_TYPE] && !isRuleSchema && (
            <>
              <ExamplesEditor
                examples={(selectedClass[X_AWS_IDP_EXAMPLES] as Example[]) || []}
                onChange={(examples) => onUpdateClass({ [X_AWS_IDP_EXAMPLES]: examples })}
              />

              <FormField
                label={`${TypeLabel} Name Regex (Optional)`}
                description={`Pattern to match ${typeLabel} ID/name. When matched, instantly classifies all pages as this type (single-class configs only). Use case-insensitive patterns like (?i).*(invoice|bill).*`}
              >
                <Input
                  value={(selectedClass[X_AWS_IDP_DOCUMENT_NAME_REGEX] as string) || ''}
                  onChange={({ detail }) => onUpdateClass({ [X_AWS_IDP_DOCUMENT_NAME_REGEX]: detail.value || undefined })}
                  placeholder="e.g., (?i).*(invoice|bill).*"
                />
              </FormField>

              <FormField
                label="Page Content Regex (Optional)"
                description="Pattern to match page text content. When matched during page-level classification, classifies the page as this type. Use case-insensitive patterns like (?i)(invoice\\s+number|amount\\s+due)"
              >
                <Input
                  value={(selectedClass[X_AWS_IDP_PAGE_CONTENT_REGEX] as string) || ''}
                  onChange={({ detail }) => onUpdateClass({ [X_AWS_IDP_PAGE_CONTENT_REGEX]: detail.value || undefined })}
                  placeholder="e.g., (?i)(invoice\\s+number|bill\\s+to)"
                />
              </FormField>

              <Header {...({ variant: 'h5' } as Record<string, unknown>)}>Evaluation Configuration</Header>

              <FormField
                label="Overall Match Threshold"
                description={`Minimum weighted score for ${typeLabel}-level baseline evaluation match (0-1)`}
              >
                <Input
                  type="number"
                  {...({ step: '0.01', min: '0', max: '1' } as Record<string, unknown>)}
                  value={(selectedClass[X_AWS_IDP_EVALUATION_MATCH_THRESHOLD] as number)?.toString() || '0.8'}
                  onChange={({ detail }) => {
                    const value = detail.value ? parseFloat(detail.value) : 0.8;
                    if (value >= 0 && value <= 1) {
                      onUpdateClass({
                        [X_AWS_IDP_EVALUATION_MATCH_THRESHOLD]: value,
                      });
                    }
                  }}
                  placeholder="0.8"
                />
              </FormField>
            </>
          )}

          {usedIn.length > 0 && (
            <FormField
              label="Used In"
              description={`This class is referenced by ${usedIn.length} attribute${usedIn.length > 1 ? 's' : ''}`}
            >
              <SpaceBetween size="xs">
                {usedIn.map((usage) => (
                  <Button
                    key={`${usage.classId}-${usage.attributeName}`}
                    variant="inline-link"
                    iconName="external"
                    onClick={() => {
                      if (onNavigateToAttribute) {
                        onNavigateToAttribute(usage.classId, usage.attributeName);
                      } else if (onNavigateToClass) {
                        onNavigateToClass(usage.classId);
                      }
                    }}
                  >
                    {usage.className}.{usage.attributeName} ({usage.type === 'array' ? `${selectedClass.name}[]` : selectedClass.name})
                  </Button>
                ))}
              </SpaceBetween>
            </FormField>
          )}
        </SpaceBetween>
      </Box>
    );
  }

  if (!selectedAttribute || !selectedAttributeName) {
    return (
      <Box textAlign="center" padding="xxl">
        <Header variant="h3">No Selection</Header>
        <p>Select a class or attribute from the canvas to edit its properties</p>
      </Box>
    );
  }

  const [attributeLabel, setAttributeLabel] = useState(selectedAttributeName || '');

  useEffect(() => {
    setAttributeLabel(selectedAttributeName || '');
  }, [selectedAttributeName]);

  const handleRenameSubmit = (): void => {
    const trimmed = attributeLabel.trim();
    if (!trimmed || trimmed === selectedAttributeName) {
      setAttributeLabel(selectedAttributeName || '');
      return;
    }

    if (onRenameAttribute && !onRenameAttribute(trimmed)) {
      setAttributeLabel(selectedAttributeName || '');
    }
  };

  return (
    <Box>
      <Header variant="h3">{isRuleSchema ? 'Rule Properties' : `Property Inspector: ${selectedAttributeName}`}</Header>
      <SpaceBetween size="m">
        <FormField label={isRuleSchema ? 'Rule Name' : 'Attribute Name'}>
          <Input
            value={attributeLabel}
            onChange={({ detail }) => setAttributeLabel(detail.value)}
            onBlur={handleRenameSubmit}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onKeyDown={(event: any) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleRenameSubmit();
              }
            }}
          />
        </FormField>

        <Checkbox checked={isRequired} onChange={({ detail }) => onToggleRequired(detail.checked)}>
          Required field
        </Checkbox>

        <FormField
          label={isRuleSchema ? 'Rule Output Data Type' : 'Type'}
          description={isRuleSchema ? 'The type of data this rule outputs' : 'JSON Schema type for this attribute'}
        >
          <Select
            selectedOption={
              TYPE_OPTIONS.find((opt) => opt.value === selectedAttribute.type) ||
              // If no type but has $ref, assume it's an object reference
              (selectedAttribute.$ref ? TYPE_OPTIONS.find((opt) => opt.value === 'object') : null) ||
              null
            }
            onChange={({ detail }) => {
              // When changing type, remove $ref if it exists (it's incompatible with inline type)
              const updates: Record<string, unknown> = { type: detail.selectedOption.value };
              if (selectedAttribute.$ref) {
                updates.$ref = undefined;
              }
              onUpdate(updates);
            }}
            options={TYPE_OPTIONS}
          />
        </FormField>

        {(selectedAttribute.type === 'object' || selectedAttribute.$ref) &&
          availableClasses &&
          availableClasses.length > 0 &&
          !isRuleSchema && (
            <>
              <FormField
                label="Reference Existing Class (Optional)"
                description="Link to a reusable class definition instead of defining properties inline"
              >
                <SpaceBetween size="xs">
                  <Select
                    selectedOption={
                      selectedAttribute.$ref
                        ? {
                            label: selectedAttribute.$ref.replace('#/$defs/', ''),
                            value: selectedAttribute.$ref,
                          }
                        : null
                    }
                    onChange={({ detail }) => {
                      if (detail.selectedOption.value) {
                        const updates: Record<string, unknown> = { ...selectedAttribute, $ref: detail.selectedOption.value };
                        // Remove inline object properties as they conflict with $ref
                        delete updates.properties;
                        delete updates.required;
                        delete updates.minProperties;
                        delete updates.maxProperties;
                        delete updates.additionalProperties;
                        // Note: Keep type as 'object' for UI purposes, but it won't be exported in the final schema
                        if (!updates.type) {
                          updates.type = 'object';
                        }
                        onUpdate(updates);
                      } else {
                        const updates: Record<string, unknown> = { ...selectedAttribute, $ref: undefined };
                        // Restore type to object when removing $ref
                        if (!updates.type) {
                          updates.type = 'object';
                        }
                        onUpdate(updates);
                      }
                    }}
                    options={[
                      { label: 'None (inline properties)', value: '' },
                      ...availableClasses.map((cls) => ({
                        label: cls.name,
                        value: `#/$defs/${cls.name}`,
                      })),
                    ]}
                    placeholder="Select a class to reference"
                  />
                  {selectedAttribute.$ref && (onNavigateToClass || onNavigateToAttribute) && (
                    <Button
                      iconName="external"
                      onClick={() => {
                        const className = selectedAttribute.$ref!.replace('#/$defs/', '');
                        const referencedClass = availableClasses.find((cls) => cls.name === className);
                        if (referencedClass) {
                          if (onNavigateToAttribute) {
                            onNavigateToAttribute(referencedClass.id, null);
                          } else if (onNavigateToClass) {
                            onNavigateToClass(referencedClass.id);
                          }
                        }
                      }}
                    >
                      Go to {selectedAttribute.$ref.replace('#/$defs/', '')} class
                    </Button>
                  )}
                </SpaceBetween>
              </FormField>

              {!selectedAttribute.$ref && <ObjectConstraints attribute={selectedAttribute} onUpdate={onUpdate} />}
            </>
          )}

        {selectedAttribute.type === 'array' && availableClasses && availableClasses.length > 0 && (
          <>
            <FormField label="Array Item Type" description="Define what each item in the array should be">
              <SpaceBetween size="xs">
                <Select
                  selectedOption={
                    selectedAttribute.items?.$ref
                      ? {
                          label: selectedAttribute.items.$ref.replace('#/$defs/', ''),
                          value: selectedAttribute.items.$ref,
                        }
                      : {
                          label: `Simple (${selectedAttribute.items?.type || 'string'})`,
                          value: 'simple',
                        }
                  }
                  onChange={({ detail }) => {
                    if (detail.selectedOption.value === 'simple') {
                      onUpdate({ items: { type: 'string' } });
                    } else {
                      onUpdate({ items: { $ref: detail.selectedOption.value } });
                    }
                  }}
                  options={[
                    { label: 'Simple (string)', value: 'simple' },
                    ...availableClasses.map((cls) => ({
                      label: `Class: ${cls.name}`,
                      value: `#/$defs/${cls.name}`,
                    })),
                  ]}
                />
                {selectedAttribute.items?.$ref && (onNavigateToClass || onNavigateToAttribute) && (
                  <Button
                    iconName="external"
                    onClick={() => {
                      const className = selectedAttribute.items!.$ref!.replace('#/$defs/', '');
                      const referencedClass = availableClasses.find((cls) => cls.name === className);
                      if (referencedClass) {
                        if (onNavigateToAttribute) {
                          onNavigateToAttribute(referencedClass.id, null);
                        } else if (onNavigateToClass) {
                          onNavigateToClass(referencedClass.id);
                        }
                      }
                    }}
                  >
                    Go to {selectedAttribute.items.$ref.replace('#/$defs/', '')} class
                  </Button>
                )}
              </SpaceBetween>
            </FormField>

            <ArrayConstraints attribute={selectedAttribute} onUpdate={onUpdate} availableClasses={availableClasses} />
          </>
        )}

        {isRuleSchema && (
          <FormField label="Description" description="Describe what information this rule validates and provide specific instructions.">
            <Textarea
              value={selectedAttribute.description || ''}
              onChange={({ detail }) => onUpdate({ description: detail.value || undefined })}
              rows={3}
              placeholder="e.g., Validates that the patient consent form is properly signed"
            />
          </FormField>
        )}

        {!isRuleSchema && <MetadataFields attribute={selectedAttribute} onUpdate={onUpdate} />}

        {!isRuleSchema && <StringConstraints attribute={selectedAttribute} onUpdate={onUpdate} />}

        {!isRuleSchema && <NumberConstraints attribute={selectedAttribute} onUpdate={onUpdate} />}

        {!isRuleSchema && <ValueConstraints attribute={selectedAttribute} onUpdate={onUpdate} />}

        {!isRuleSchema && (
          <>
            <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Assessment Configuration</Header>

            <FormField
              label="Confidence Threshold"
              description="Minimum confidence score for extraction quality - triggers alert if below this threshold (0-1)"
            >
              <Input
                type="number"
                {...({ step: '0.01', min: '0', max: '1' } as Record<string, unknown>)}
                value={(selectedAttribute[X_AWS_IDP_CONFIDENCE_THRESHOLD] as number)?.toString() || ''}
                onChange={({ detail }) =>
                  onUpdate({
                    [X_AWS_IDP_CONFIDENCE_THRESHOLD]: detail.value ? parseFloat(detail.value) : undefined,
                  })
                }
                placeholder="e.g., 0.9"
              />
            </FormField>

            <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Evaluation Configuration (Baseline Accuracy)</Header>
          </>
        )}

        {!isRuleSchema &&
          (() => {
            // Detect if this is a structured array (List[Object])
            // Must check BOTH inline objects AND $ref to classes (matches backend logic)
            const isStructuredArray =
              selectedAttribute.type === 'array' && (selectedAttribute.items?.type === 'object' || selectedAttribute.items?.$ref);

            // Filter available methods based on field type
            const availableMethods = EVALUATION_METHOD_OPTIONS.filter((opt) => {
              // HUNGARIAN requires structured array
              if (opt.requiresStructuredItems) {
                return isStructuredArray;
              }
              // Methods with validFor restrictions
              if (opt.validFor) {
                // For arrays with SIMPLE items (Array[String], Array[Number], etc.)
                // check if method is valid for the ITEM type
                if (selectedAttribute.type === 'array' && !isStructuredArray) {
                  const itemType = selectedAttribute.items?.type || 'string';
                  return opt.validFor.includes(itemType);
                }
                // For structured arrays (Array[Object]), check if method is valid for arrays
                if (selectedAttribute.type === 'array' && isStructuredArray) {
                  return opt.validFor.includes('array');
                }
                // For other types, check directly
                return opt.validFor.includes(selectedAttribute.type as string);
              }
              // Default: allow for non-structured-arrays
              return !isStructuredArray;
            });

            const currentMethod = selectedAttribute[X_AWS_IDP_EVALUATION_METHOD] as string | undefined;

            return (
              <>
                <FormField label="Evaluation Method" description="Comparison algorithm for baseline accuracy assessment">
                  <Select
                    selectedOption={availableMethods.find((opt) => opt.value === currentMethod) || null}
                    onChange={({ detail }) => {
                      const method = detail.selectedOption.value;
                      const updates: Record<string, unknown> = {
                        [X_AWS_IDP_EVALUATION_METHOD]: method,
                      };

                      // Auto-set appropriate threshold based on field type
                      if (isStructuredArray) {
                        // For structured arrays, use match_threshold
                        if ((EVALUATION_MATCH_THRESHOLD_DEFAULTS as Record<string, number>)[method]) {
                          updates[X_AWS_IDP_EVALUATION_MATCH_THRESHOLD] = (EVALUATION_MATCH_THRESHOLD_DEFAULTS as Record<string, number>)[
                            method
                          ];
                        }
                        // Clear regular threshold if present
                        updates[X_AWS_IDP_EVALUATION_THRESHOLD] = undefined;
                      } else {
                        // For regular fields, use threshold
                        if ((EVALUATION_THRESHOLD_DEFAULTS as Record<string, number>)[method]) {
                          updates[X_AWS_IDP_EVALUATION_THRESHOLD] = (EVALUATION_THRESHOLD_DEFAULTS as Record<string, number>)[method];
                        }
                        // Clear match_threshold if present
                        updates[X_AWS_IDP_EVALUATION_MATCH_THRESHOLD] = undefined;
                      }

                      onUpdate(updates);
                    }}
                    options={availableMethods}
                    placeholder="Select evaluation method"
                  />
                </FormField>

                {/* Show match-threshold for structured arrays */}
                {isStructuredArray && currentMethod && METHODS_REQUIRING_MATCH_THRESHOLD.includes(currentMethod) && (
                  <FormField
                    label="Match Threshold"
                    description="Minimum score for matching items in the array (0-1). Stickler uses Hungarian algorithm to find optimal item pairing."
                  >
                    <Input
                      type="number"
                      {...({ step: '0.01', min: '0', max: '1' } as Record<string, unknown>)}
                      value={(selectedAttribute[X_AWS_IDP_EVALUATION_MATCH_THRESHOLD] as number)?.toString() || ''}
                      onChange={({ detail }) =>
                        onUpdate({
                          [X_AWS_IDP_EVALUATION_MATCH_THRESHOLD]: detail.value ? parseFloat(detail.value) : undefined,
                        })
                      }
                      placeholder={`Default: ${(EVALUATION_MATCH_THRESHOLD_DEFAULTS as Record<string, number>)[currentMethod] || '0.8'}`}
                    />
                  </FormField>
                )}

                {/* Show threshold for non-array fields */}
                {!isStructuredArray && currentMethod && METHODS_REQUIRING_THRESHOLD.includes(currentMethod) && (
                  <FormField label="Evaluation Threshold" description="Minimum similarity score to consider a baseline match (0-1)">
                    <Input
                      type="number"
                      {...({ step: '0.01', min: '0', max: '1' } as Record<string, unknown>)}
                      value={(selectedAttribute[X_AWS_IDP_EVALUATION_THRESHOLD] as number)?.toString() || ''}
                      onChange={({ detail }) =>
                        onUpdate({
                          [X_AWS_IDP_EVALUATION_THRESHOLD]: detail.value ? parseFloat(detail.value) : undefined,
                        })
                      }
                      placeholder={`Default: ${(EVALUATION_THRESHOLD_DEFAULTS as Record<string, number>)[currentMethod] || ''}`}
                    />
                  </FormField>
                )}

                {/* Show weight for non-array fields */}
                {!isStructuredArray && (
                  <FormField
                    label="Evaluation Weight"
                    description="Field importance for business criticality (1.0=normal, 2.0=critical, 0.5=optional)"
                  >
                    <Input
                      type="number"
                      {...({ step: '0.1', min: '0.1' } as Record<string, unknown>)}
                      value={(selectedAttribute[X_AWS_IDP_EVALUATION_WEIGHT] as number)?.toString() || '1.0'}
                      onChange={({ detail }) => {
                        const value = detail.value ? parseFloat(detail.value) : 1.0;
                        // Validate minimum
                        if (value >= 0.1) {
                          onUpdate({
                            [X_AWS_IDP_EVALUATION_WEIGHT]: value,
                          });
                        }
                      }}
                      placeholder="1.0"
                    />
                  </FormField>
                )}

                {/* Info alert for structured arrays */}
                {isStructuredArray && currentMethod === EVALUATION_METHOD_HUNGARIAN && (
                  <Alert type="info">
                    <strong>Hungarian Matching</strong>
                    <br />
                    Stickler uses the Hungarian algorithm to find the optimal pairing between expected and actual list items. The match
                    threshold you set applies to individual item comparisons.
                  </Alert>
                )}
              </>
            );
          })()}
      </SpaceBetween>
    </Box>
  );
};

// Memoize the component to prevent re-renders when props haven't changed
export default React.memo(SchemaInspector);
