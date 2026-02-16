import React, { useState, useRef } from 'react';
import { Box, SpaceBetween, Header, FormField, Select, Button, Container, ExpandableSection, Alert } from '@cloudscape-design/components';

interface SchemaAttribute {
  oneOf?: Array<Record<string, unknown>>;
  anyOf?: Array<Record<string, unknown>>;
  allOf?: Array<Record<string, unknown>>;
  not?: Record<string, unknown>;
  [key: string]: unknown;
}

interface AvailableClass {
  name: string;
  id?: string;
}

interface SchemaCompositionEditorProps {
  selectedAttribute?: SchemaAttribute | null;
  availableClasses?: AvailableClass[];
  onUpdate: (updates: SchemaAttribute) => void;
}

const SchemaCompositionEditor = ({
  selectedAttribute = null,
  availableClasses = [],
  onUpdate,
}: SchemaCompositionEditorProps): React.JSX.Element | null => {
  const [compositionType, setCompositionType] = useState('');
  const schemaIdCounterRef = useRef(0);

  const compositionOptions = [
    { label: 'None', value: '', description: 'No composition' },
    { label: 'One Of (Exclusive Choice)', value: 'oneOf', description: 'Must match exactly one schema' },
    { label: 'Any Of (Inclusive Choice)', value: 'anyOf', description: 'Must match at least one schema' },
    { label: 'All Of (Combination)', value: 'allOf', description: 'Must match all schemas' },
    { label: 'Not (Negation)', value: 'not', description: 'Must not match the schema' },
  ];

  const hasComposition =
    selectedAttribute && (selectedAttribute.oneOf || selectedAttribute.anyOf || selectedAttribute.allOf || selectedAttribute.not);

  let currentComposition = '';
  if (hasComposition) {
    if (selectedAttribute.oneOf) {
      currentComposition = 'oneOf';
    } else if (selectedAttribute.anyOf) {
      currentComposition = 'anyOf';
    } else if (selectedAttribute.allOf) {
      currentComposition = 'allOf';
    } else if (selectedAttribute.not) {
      currentComposition = 'not';
    }
  }

  const handleAddComposition = (): void => {
    if (!compositionType || !selectedAttribute) return;

    const updates = { ...selectedAttribute } as Record<string, unknown>;

    if (compositionType === 'not') {
      const schemaId = schemaIdCounterRef.current;
      schemaIdCounterRef.current += 1;
      updates.not = { type: 'string', schemaId };
    } else {
      const schemaId1 = schemaIdCounterRef.current;
      schemaIdCounterRef.current += 1;
      const schemaId2 = schemaIdCounterRef.current;
      schemaIdCounterRef.current += 1;
      updates[compositionType] = [
        { type: 'string', schemaId: schemaId1 },
        { type: 'number', schemaId: schemaId2 },
      ];
    }

    onUpdate(updates as SchemaAttribute);
    setCompositionType('');
  };

  const handleRemoveComposition = (): void => {
    if (!selectedAttribute) return;
    const updates = { ...selectedAttribute };
    delete updates.oneOf;
    delete updates.anyOf;
    delete updates.allOf;
    delete updates.not;
    onUpdate(updates);
  };

  const handleAddSchema = (): void => {
    if (!currentComposition || currentComposition === 'not' || !selectedAttribute) return;

    const updates = { ...selectedAttribute } as Record<string, unknown>;
    const schemaId = schemaIdCounterRef.current;
    schemaIdCounterRef.current += 1;
    updates[currentComposition] = [
      ...((updates[currentComposition] as Array<Record<string, unknown>>) || []),
      { type: 'string', schemaId },
    ];
    onUpdate(updates as SchemaAttribute);
  };

  const handleRemoveSchema = (index: number): void => {
    if (!currentComposition || currentComposition === 'not' || !selectedAttribute) return;

    const updates = { ...selectedAttribute } as Record<string, unknown>;
    const schemas = [...((updates[currentComposition] as Array<Record<string, unknown>>) || [])];
    schemas.splice(index, 1);

    if (schemas.length === 0) {
      delete updates[currentComposition];
    } else {
      updates[currentComposition] = schemas;
    }

    onUpdate(updates as SchemaAttribute);
  };

  const handleUpdateSchema = (index: number, newType: string): void => {
    if (!currentComposition || currentComposition === 'not' || !selectedAttribute) return;

    const updates = { ...selectedAttribute } as Record<string, unknown>;
    const schemas = [...((updates[currentComposition] as Array<Record<string, unknown>>) || [])];
    const existingSchemaId = (schemas[index] as Record<string, unknown>).schemaId;

    if (newType.startsWith('#/$defs/')) {
      schemas[index] = { $ref: newType, schemaId: existingSchemaId };
    } else {
      schemas[index] = { type: newType, schemaId: existingSchemaId };
    }

    updates[currentComposition] = schemas;
    onUpdate(updates as SchemaAttribute);
  };

  const handleUpdateNotSchema = (newType: string): void => {
    if (!selectedAttribute) return;
    const updates = { ...selectedAttribute };

    if (newType.startsWith('#/$defs/')) {
      updates.not = { $ref: newType };
    } else {
      updates.not = { type: newType };
    }

    onUpdate(updates);
  };

  const schemaTypeOptions = [
    { label: 'String', value: 'string' },
    { label: 'Number', value: 'number' },
    { label: 'Integer', value: 'integer' },
    { label: 'Boolean', value: 'boolean' },
    { label: 'Object', value: 'object' },
    { label: 'Array', value: 'array' },
    { label: 'Null', value: 'null' },
    ...(availableClasses || []).map((cls) => ({
      label: `Ref: ${cls.name}`,
      value: `#/$defs/${cls.name}`,
    })),
  ];

  if (!selectedAttribute) return null;

  return (
    <ExpandableSection headerText="Schema Composition (Advanced)" variant="container">
      <SpaceBetween size="m">
        <Alert type="info">
          Schema composition allows you to combine multiple schemas using logical operators. This enables complex validation scenarios like
          discriminated unions, polymorphic types, and conditional logic.
        </Alert>

        {!hasComposition ? (
          <Container>
            <SpaceBetween size="m">
              <FormField label="Add Composition" description="Choose how to combine multiple schemas">
                <Select
                  selectedOption={compositionOptions.find((opt) => opt.value === compositionType) || compositionOptions[0]}
                  onChange={({ detail }) => setCompositionType(detail.selectedOption.value)}
                  options={compositionOptions}
                  placeholder="Select composition type"
                />
              </FormField>
              <Button onClick={handleAddComposition} disabled={!compositionType}>
                Add Composition
              </Button>
            </SpaceBetween>
          </Container>
        ) : (
          <Container>
            <SpaceBetween size="m">
              <Header
                variant="h3"
                actions={
                  <Button onClick={handleRemoveComposition} variant="normal">
                    Remove Composition
                  </Button>
                }
              >
                {compositionOptions.find((opt) => opt.value === currentComposition)?.label || 'Composition'}
              </Header>

              {currentComposition === 'not' ? (
                <FormField label="Schema to Negate" description="Value must NOT match this schema">
                  <Select
                    selectedOption={
                      schemaTypeOptions.find(
                        (opt) =>
                          (selectedAttribute.not as Record<string, unknown>)?.$ref === opt.value ||
                          (selectedAttribute.not as Record<string, unknown>)?.type === opt.value,
                      ) || schemaTypeOptions[0]
                    }
                    onChange={({ detail }) => handleUpdateNotSchema(detail.selectedOption.value)}
                    options={schemaTypeOptions}
                  />
                </FormField>
              ) : (
                <>
                  {(((selectedAttribute as Record<string, unknown>)[currentComposition] as Array<Record<string, unknown>>) || []).map(
                    (schema, idx) => (
                      <Box
                        key={(schema.schemaId as string | number) || `${currentComposition}-fallback-${idx}`}
                        padding="s"
                        {...({ style: { border: '1px solid #ddd', borderRadius: '4px' } } as Record<string, unknown>)}
                      >
                        <SpaceBetween size="s">
                          <Header
                            {...({ variant: 'h4' } as Record<string, unknown>)}
                            actions={<Button variant="icon" iconName="close" onClick={() => handleRemoveSchema(idx)} />}
                          >
                            Schema {idx + 1}
                          </Header>
                          <FormField label="Type">
                            <Select
                              selectedOption={
                                schemaTypeOptions.find((opt) => schema.$ref === opt.value || schema.type === opt.value) ||
                                schemaTypeOptions[0]
                              }
                              onChange={({ detail }) => handleUpdateSchema(idx, detail.selectedOption.value)}
                              options={schemaTypeOptions}
                            />
                          </FormField>
                        </SpaceBetween>
                      </Box>
                    ),
                  )}
                  <Button onClick={handleAddSchema} variant="normal">
                    Add Schema to {currentComposition}
                  </Button>
                </>
              )}
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>
    </ExpandableSection>
  );
};

export default SchemaCompositionEditor;
