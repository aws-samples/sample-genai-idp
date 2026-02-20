import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Container,
  SpaceBetween,
  Header,
  Button,
  Box,
  Alert,
  ColumnLayout,
  Modal,
  FormField,
  Input,
  Select,
  Textarea,
} from '@cloudscape-design/components';
import { useSchemaDesigner } from '../../hooks/useSchemaDesigner';
import { useSchemaValidation } from '../../hooks/useSchemaValidation';
import { useDebounce } from '../../hooks/useDebounce';
import { TYPE_OPTIONS, X_AWS_IDP_DOCUMENT_TYPE } from '../../constants/schemaConstants';
import SchemaCanvas from './SchemaCanvas';
import SchemaInspector from './SchemaInspector';
import SchemaPreviewTabs from './SchemaPreviewTabs';
import { formatTypeBadge, DocumentTypeBadge } from './utils/badgeHelpers';

interface SchemaClass {
  id: string;
  name: string;
  description?: string;
  attributes?: {
    properties?: Record<string, Record<string, unknown>>;
    required?: string[];
  };
  [key: string]: unknown;
}

interface ValidationError {
  path: string;
  message: string;
  keyword?: string;
  className?: string;
}

interface TypeOption {
  label: string;
  value: string;
}

interface SchemaBuilderProps {
  initialSchema?: SchemaClass[] | Record<string, unknown> | null;
  onChange?: ((schema: unknown, isDirty: boolean) => void) | null;
  onValidate?: ((isValid: boolean, errors: ValidationError[]) => void) | null;
  isRuleSchema?: boolean;
}

const SchemaBuilder = ({
  initialSchema = null,
  onChange = null,
  onValidate = null,
  isRuleSchema = false,
}: SchemaBuilderProps): React.JSX.Element => {
  const {
    classes,
    selectedClassId,
    setSelectedClassId,
    selectedAttributeId,
    setSelectedAttributeId,
    isDirty,
    addClass,
    updateClass,
    removeClass,
    addAttribute,
    updateAttribute,
    renameAttribute,
    removeAttribute,
    reorderAttributes,
    exportSchema,
    getSelectedClass,
    getSelectedAttribute,
    clearAllClasses,
  } = useSchemaDesigner(initialSchema || [], isRuleSchema);

  const { validateSchema } = useSchemaValidation();

  const [showPreview, setShowPreview] = useState(false);
  const [showAddClassModal, setShowAddClassModal] = useState(false);
  const [showAddAttributeModal, setShowAddAttributeModal] = useState(false);
  const [newClassName, setNewClassName] = useState('');
  const [newClassDescription, setNewClassDescription] = useState('');
  const [newAttributeName, setNewAttributeName] = useState('');
  const [newAttributeType, setNewAttributeType] = useState<TypeOption>({ label: 'String', value: 'string' });
  const [newAttributeDescription, setNewAttributeDescription] = useState('');
  const [newAttributeReferenceClass, setNewAttributeReferenceClass] = useState<TypeOption | null>(null);
  const [showEditClassModal, setShowEditClassModal] = useState(false);
  const [editingClass, setEditingClass] = useState<SchemaClass | null>(null);
  const [showDeleteConfirmModal, setShowDeleteConfirmModal] = useState(false);
  const [classToDelete, setClassToDelete] = useState<SchemaClass | null>(null);
  const [showWipeAllModal, setShowWipeAllModal] = useState(false);
  const [aggregatedValidationErrors, setAggregatedValidationErrors] = useState<ValidationError[]>([]);
  const lastExportedSchemaRef = useRef<string | null>(null);
  const lastValidationResultRef = useRef<string | null>(null);

  // Debounce classes changes to reduce validation frequency
  const debouncedClasses = useDebounce(classes, 300);

  // Memoize the exported schema to avoid recalculating on every render
  const currentSchema = useMemo(() => exportSchema(), [exportSchema]);

  useEffect(() => {
    if (onChange) {
      const schemaString = JSON.stringify(currentSchema);
      if (schemaString !== lastExportedSchemaRef.current) {
        lastExportedSchemaRef.current = schemaString;
        onChange(currentSchema, isDirty);
      }
    }
  }, [currentSchema, isDirty, onChange]);

  useEffect(() => {
    if (onValidate && debouncedClasses.length > 0) {
      const allErrors: ValidationError[] = [];
      let allValid = true;

      debouncedClasses.forEach((cls) => {
        const result = validateSchema(cls);
        if (!result.valid) {
          allValid = false;
          allErrors.push(...result.errors.map((err: ValidationError) => ({ ...err, className: cls.name })));
        }
      });

      const validationResult = JSON.stringify({ allValid, allErrors });
      if (validationResult !== lastValidationResultRef.current) {
        lastValidationResultRef.current = validationResult;
        setAggregatedValidationErrors(allErrors);
        onValidate(allValid, allErrors);
      }
    } else if (onValidate && debouncedClasses.length === 0) {
      if (lastValidationResultRef.current !== null) {
        lastValidationResultRef.current = null;
        setAggregatedValidationErrors([]);
        onValidate(true, []);
      }
    }
  }, [debouncedClasses, onValidate, validateSchema]);

  const handleAddClass = (): void => {
    setShowAddClassModal(true);
  };

  const handleAddAttribute = (): void => {
    if (!selectedClassId) {
      alert('Please select a class first');
      return;
    }
    setShowAddAttributeModal(true);
  };

  const handleConfirmAddClass = (): void => {
    if (newClassName.trim()) {
      addClass(newClassName.trim(), newClassDescription.trim() || undefined);
      setNewClassName('');
      setNewClassDescription('');
      setShowAddClassModal(false);
    }
  };

  const handleConfirmAddAttribute = (): void => {
    if (newAttributeName.trim() && newAttributeType.value) {
      const attrName = newAttributeName.trim();
      addAttribute(selectedClassId, attrName, newAttributeType.value);

      const updates: Record<string, unknown> = {};
      if (newAttributeDescription.trim()) {
        updates.description = newAttributeDescription.trim();
      }

      // If object or array and a reference class is selected, add $ref
      if (newAttributeReferenceClass && newAttributeReferenceClass.value) {
        if (newAttributeType.value === 'object') {
          updates.$ref = `#/$defs/${newAttributeReferenceClass.value}`;
          // Remove schema keywords that conflict with $ref
          updates.type = undefined;
          updates.properties = undefined;
          updates.required = undefined;
        } else if (newAttributeType.value === 'array') {
          updates.items = { $ref: `#/$defs/${newAttributeReferenceClass.value}` };
        }
      }

      if (Object.keys(updates).length > 0) {
        updateAttribute(selectedClassId, attrName, updates);
      }

      setNewAttributeName('');
      setNewAttributeType({ label: 'String', value: 'string' });
      setNewAttributeDescription('');
      setNewAttributeReferenceClass(null);
      setShowAddAttributeModal(false);
    }
  };

  // Use TYPE_OPTIONS from constants, filtering to commonly used types
  const attributeTypeOptions = TYPE_OPTIONS.filter((opt) => ['string', 'number', 'boolean', 'object', 'array'].includes(opt.value));

  const handleEditClass = (cls: SchemaClass): void => {
    setEditingClass(cls);
    setNewClassName(cls.name);
    setNewClassDescription(cls.description || '');
    setShowEditClassModal(true);
  };

  const handleConfirmEditClass = (): void => {
    if (editingClass && newClassName.trim()) {
      updateClass(editingClass.id, {
        name: newClassName.trim(),
        description: newClassDescription.trim() || undefined,
      });
      setEditingClass(null);
      setNewClassName('');
      setNewClassDescription('');
      setShowEditClassModal(false);
    }
  };

  const handleWipeAll = (): void => {
    setShowWipeAllModal(true);
  };

  const handleConfirmWipeAll = (): void => {
    clearAllClasses();
    setShowWipeAllModal(false);
  };

  const docTypeCount = classes.filter((c) => c[X_AWS_IDP_DOCUMENT_TYPE]).length;
  const _sharedCount = classes.filter((c) => !c[X_AWS_IDP_DOCUMENT_TYPE]).length;

  // Dynamic labels based on schema type
  const typeLabel = isRuleSchema ? 'rule' : 'document';
  const _typeLabelPlural = isRuleSchema ? 'rules' : 'documents';
  const TypeLabel = isRuleSchema ? 'Rule' : 'Document';
  const TypesLabel = isRuleSchema ? 'Rules' : 'Documents';
  const _classLabel = isRuleSchema ? 'Rule Class' : 'Class';
  const classesLabel = isRuleSchema ? 'Rule Classes' : 'Classes';
  const _attributeLabel = isRuleSchema ? 'Rule' : 'Attribute';
  const attributesLabel = isRuleSchema ? 'Rules' : 'Attributes';
  const sharedLabel = isRuleSchema ? 'Recommendation Options' : 'Shared Classes';

  return (
    <>
      {/* Floating breadcrumb bar showing current selection - fixed to viewport */}
      {(selectedClassId || selectedAttributeId) && (
        <div
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 1000,
            backgroundColor: '#ffffff',
            borderBottom: '2px solid #0972d3',
            padding: '12px 20px',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
            marginBottom: '16px',
          }}
        >
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            {selectedClassId && (
              <>
                <Box fontSize="body-m" fontWeight="bold">
                  {getSelectedClass()?.name || 'Unknown Class'}
                </Box>
                {getSelectedClass()?.[X_AWS_IDP_DOCUMENT_TYPE] && <DocumentTypeBadge isRuleSchema={isRuleSchema} />}
              </>
            )}
            {selectedAttributeId && (
              <>
                <Box fontSize="body-s" color="text-body-secondary">
                  ›
                </Box>
                <Box fontSize="body-m" color="text-label">
                  {selectedAttributeId}
                </Box>
                {getSelectedAttribute() && formatTypeBadge(getSelectedAttribute())}
              </>
            )}
            <Box {...({ flex: '1' } as Record<string, unknown>)} />
            <Button
              variant="inline-link"
              iconName="close"
              onClick={() => {
                setSelectedAttributeId(null);
                if (!selectedAttributeId) {
                  setSelectedClassId(null);
                }
              }}
              ariaLabel="Clear selection"
            >
              {selectedAttributeId ? 'Deselect attribute' : 'Deselect class'}
            </Button>
          </SpaceBetween>
        </div>
      )}

      <SpaceBetween size="l">
        {aggregatedValidationErrors.length > 0 && (
          <Alert type="error" dismissible onDismiss={() => setAggregatedValidationErrors([])} header="Schema Validation Errors">
            <ul>
              {aggregatedValidationErrors.map((error) => (
                <li key={`${error.className || 'unknown'}-${error.path}-${error.message}-${error.keyword || ''}`}>
                  {error.className && <strong>{error.className}</strong>} {error.path}: {error.message}
                </li>
              ))}
            </ul>
          </Alert>
        )}

        <div style={{ maxHeight: 'calc(100vh - 200px)', overflow: 'auto' }}>
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <Box>
                    <SpaceBetween direction="horizontal" size="xs">
                      <Button onClick={handleAddClass} iconName="add-plus">
                        {isRuleSchema ? 'Add Rule Class' : 'Add Class'}
                      </Button>
                      <Button onClick={handleAddAttribute} disabled={!selectedClassId} iconName="add-plus">
                        {isRuleSchema ? 'Add Rule' : 'Add Attribute'}
                      </Button>
                      <Button onClick={() => setShowPreview(!showPreview)} iconName={showPreview ? 'view-vertical' : 'view-horizontal'}>
                        {showPreview ? 'Hide' : 'Show'} Preview
                      </Button>
                      <Button
                        onClick={() => {
                          const schema = exportSchema();
                          const blob = new Blob([JSON.stringify(schema, null, 2)], { type: 'application/json' });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement('a');
                          a.href = url;
                          a.download = `schema-${Date.now()}.json`;
                          a.click();
                          URL.revokeObjectURL(url);
                        }}
                        iconName="download"
                        disabled={classes.length === 0}
                      >
                        Export
                      </Button>
                      <Button onClick={handleWipeAll} iconName="remove" disabled={classes.length === 0}>
                        Wipe All
                      </Button>
                    </SpaceBetween>
                  </Box>
                }
                description="Build JSON Schema Draft 2020-12 compliant extraction schemas with advanced features"
              >
                Schema Builder
              </Header>
            }
          >
            <ColumnLayout columns={showPreview ? 2 : 3} variant="text-grid" minColumnWidth={300}>
              <Box>
                <SpaceBetween size="m">
                  <Header variant="h3">
                    {classesLabel} ({docTypeCount} {typeLabel} {docTypeCount === 1 ? 'type' : 'types'})
                  </Header>

                  {classes.filter((c) => c[X_AWS_IDP_DOCUMENT_TYPE]).length === 0 && (
                    <Alert type="warning" header={`No ${TypesLabel} Types`}>
                      No classes are marked as {typeLabel} types. Mark at least one class as a {typeLabel} type to generate {typeLabel}{' '}
                      schemas.
                    </Alert>
                  )}

                  <Box>
                    {!isRuleSchema && <Header {...({ variant: 'h4' } as Record<string, unknown>)}>{TypesLabel} Types</Header>}
                    <SpaceBetween size="s">
                      {classes.filter((c) => c[X_AWS_IDP_DOCUMENT_TYPE]).length === 0 && (
                        <Box fontSize="body-s" color="text-body-secondary" padding="s">
                          No {typeLabel} types yet. Add a class and mark it as a {typeLabel} type.
                        </Box>
                      )}
                      {classes
                        .filter((cls) => cls[X_AWS_IDP_DOCUMENT_TYPE])
                        .map((cls) => (
                          <Container key={cls.id} disableContentPaddings={false}>
                            <div
                              role="button"
                              tabIndex={0}
                              onClick={() => setSelectedClassId(cls.id)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  setSelectedClassId(cls.id);
                                }
                              }}
                              style={{
                                cursor: 'pointer',
                                padding: '12px',
                                borderRadius: '8px',
                                border: selectedClassId === cls.id ? '2px solid #0972d3' : '2px solid transparent',
                                backgroundColor: selectedClassId === cls.id ? '#e8f4fd' : 'transparent',
                                transition: 'all 0.2s ease',
                              }}
                            >
                              <SpaceBetween size="xs">
                                <Box>
                                  <SpaceBetween direction="horizontal" size="s" alignItems="center">
                                    <DocumentTypeBadge isRuleSchema={isRuleSchema} />
                                    <Box fontWeight="bold">{cls.name}</Box>
                                    <Box float="right">
                                      <SpaceBetween direction="horizontal" size="xs">
                                        <Button
                                          variant="icon"
                                          iconName="edit"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleEditClass(cls);
                                          }}
                                          ariaLabel={`Edit ${cls.name}`}
                                        />
                                        <Button
                                          variant="icon"
                                          iconName="close"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setClassToDelete(cls);
                                            setShowDeleteConfirmModal(true);
                                          }}
                                          ariaLabel={`Delete ${cls.name}`}
                                        />
                                      </SpaceBetween>
                                    </Box>
                                  </SpaceBetween>
                                </Box>
                                {cls.description && (
                                  <Box fontSize="body-s" color="text-body-secondary">
                                    {cls.description}
                                  </Box>
                                )}
                                <Box fontSize="body-s" color="text-body-secondary">
                                  {Object.keys(cls.attributes?.properties || {}).length}{' '}
                                  {isRuleSchema ? attributesLabel.toLowerCase() : 'attribute(s)'}
                                </Box>
                              </SpaceBetween>
                            </div>
                          </Container>
                        ))}
                    </SpaceBetween>
                  </Box>

                  {!isRuleSchema && (
                    <Box>
                      <Header {...({ variant: 'h4' } as Record<string, unknown>)}>{sharedLabel}</Header>
                      <SpaceBetween size="s">
                        {classes.filter((c) => !c[X_AWS_IDP_DOCUMENT_TYPE]).length === 0 && (
                          <Box fontSize="body-s" color="text-body-secondary" padding="s">
                            No shared classes. Shared classes can be referenced by {typeLabel} types via $ref.
                          </Box>
                        )}
                        {classes
                          .filter((cls) => !cls[X_AWS_IDP_DOCUMENT_TYPE])
                          .map((cls) => (
                            <Container key={cls.id} disableContentPaddings={false}>
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => setSelectedClassId(cls.id)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    setSelectedClassId(cls.id);
                                  }
                                }}
                                style={{
                                  cursor: 'pointer',
                                  padding: '12px',
                                  borderRadius: '8px',
                                  border: selectedClassId === cls.id ? '2px solid #0972d3' : '2px solid transparent',
                                  backgroundColor: selectedClassId === cls.id ? '#e8f4fd' : 'transparent',
                                  transition: 'all 0.2s ease',
                                }}
                              >
                                <SpaceBetween size="xs">
                                  <Box>
                                    <SpaceBetween direction="horizontal" size="s" alignItems="center">
                                      <Box fontWeight="bold">{cls.name}</Box>
                                      <Box float="right">
                                        <SpaceBetween direction="horizontal" size="xs">
                                          <Button
                                            variant="icon"
                                            iconName="edit"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleEditClass(cls);
                                            }}
                                            ariaLabel={`Edit ${cls.name}`}
                                          />
                                          <Button
                                            variant="icon"
                                            iconName="close"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              setClassToDelete(cls);
                                              setShowDeleteConfirmModal(true);
                                            }}
                                            ariaLabel={`Delete ${cls.name}`}
                                          />
                                        </SpaceBetween>
                                      </Box>
                                    </SpaceBetween>
                                  </Box>
                                  {cls.description && (
                                    <Box fontSize="body-s" color="text-body-secondary">
                                      {cls.description}
                                    </Box>
                                  )}
                                  <Box fontSize="body-s" color="text-body-secondary">
                                    {Object.keys(cls.attributes?.properties || {}).length} attribute(s)
                                  </Box>
                                </SpaceBetween>
                              </div>
                            </Container>
                          ))}
                      </SpaceBetween>
                    </Box>
                  )}
                </SpaceBetween>
              </Box>

              {!showPreview && (
                <>
                  <SchemaCanvas
                    selectedClass={getSelectedClass()}
                    selectedAttributeId={selectedAttributeId}
                    onSelectAttribute={setSelectedAttributeId}
                    onUpdateAttribute={(name, updates) => updateAttribute(selectedClassId, name, updates)}
                    onRemoveAttribute={(name) => removeAttribute(selectedClassId, name)}
                    onReorder={(oldIndex, newIndex) => reorderAttributes(selectedClassId, oldIndex, newIndex)}
                    onNavigateToClass={(classId) => {
                      setSelectedClassId(classId);
                      setSelectedAttributeId(null);
                    }}
                    onNavigateToAttribute={(classId, attributeName) => {
                      setSelectedClassId(classId);
                      setSelectedAttributeId(attributeName);
                    }}
                    availableClasses={classes}
                    isRuleSchema={isRuleSchema}
                  />

                  <SchemaInspector
                    selectedClass={getSelectedClass()}
                    selectedAttribute={getSelectedAttribute()}
                    selectedAttributeName={selectedAttributeId}
                    onUpdate={(updates) => updateAttribute(selectedClassId, selectedAttributeId, updates)}
                    onUpdateClass={(updates) => updateClass(selectedClassId, updates)}
                    onRenameAttribute={(newName) => renameAttribute(selectedClassId, selectedAttributeId, newName)}
                    availableClasses={classes}
                    isRequired={getSelectedClass()?.attributes?.required?.includes(selectedAttributeId) || false}
                    isRuleSchema={isRuleSchema}
                    onToggleRequired={(checked) => {
                      const selectedClass = getSelectedClass();
                      if (!selectedClass || !selectedClass.attributes) return;

                      const currentRequired = selectedClass.attributes.required || [];
                      let newRequired: string[];

                      if (checked) {
                        if (!currentRequired.includes(selectedAttributeId)) {
                          newRequired = [...currentRequired, selectedAttributeId];
                        } else {
                          return; // Already required
                        }
                      } else {
                        newRequired = currentRequired.filter((name) => name !== selectedAttributeId);
                      }

                      // Only update the required field, not the entire attributes object
                      // This ensures immer properly tracks the change and creates new references
                      updateClass(selectedClassId, {
                        attributes: {
                          required: newRequired,
                        },
                      });
                    }}
                    onNavigateToClass={(classId) => {
                      setSelectedClassId(classId);
                      setSelectedAttributeId(null);
                    }}
                    onNavigateToAttribute={(classId, attributeName) => {
                      setSelectedClassId(classId);
                      setSelectedAttributeId(attributeName);
                    }}
                  />
                </>
              )}

              {showPreview && <SchemaPreviewTabs classes={classes} selectedClassId={selectedClassId} exportedSchemas={currentSchema} />}
            </ColumnLayout>
          </Container>
        </div>

        <Modal
          visible={showAddClassModal}
          onDismiss={() => {
            setShowAddClassModal(false);
            setNewClassName('');
            setNewClassDescription('');
          }}
          header={isRuleSchema ? 'Add Rule Class' : 'Add Class'}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="link"
                  onClick={() => {
                    setShowAddClassModal(false);
                    setNewClassName('');
                    setNewClassDescription('');
                  }}
                >
                  Cancel
                </Button>
                <Button variant="primary" onClick={handleConfirmAddClass} disabled={!newClassName.trim()}>
                  {isRuleSchema ? 'Add Rule Class' : 'Add Class'}
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <FormField
              label={isRuleSchema ? 'Rule Class Name' : 'Class Name'}
              description={`A unique name for this ${isRuleSchema ? 'rule' : 'extraction'} class`}
            >
              <Input
                value={newClassName}
                onChange={({ detail }) => setNewClassName(detail.value)}
                placeholder={isRuleSchema ? 'e.g., ComplianceRules, SafetyChecks' : 'e.g., Invoice, Customer, Address'}
              />
            </FormField>
            <FormField label="Description (Optional)" description="Describe what this class represents">
              <Textarea
                value={newClassDescription}
                onChange={({ detail }) => setNewClassDescription(detail.value)}
                placeholder="e.g., Invoice document with line items"
                rows={3}
              />
            </FormField>
          </SpaceBetween>
        </Modal>

        <Modal
          visible={showAddAttributeModal}
          onDismiss={() => {
            setShowAddAttributeModal(false);
            setNewAttributeName('');
            setNewAttributeType({ label: 'String', value: 'string' });
            setNewAttributeDescription('');
            setNewAttributeReferenceClass(null);
          }}
          header={isRuleSchema ? 'Add Rule' : 'Add Attribute'}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="link"
                  onClick={() => {
                    setShowAddAttributeModal(false);
                    setNewAttributeName('');
                    setNewAttributeType({ label: 'String', value: 'string' });
                    setNewAttributeDescription('');
                    setNewAttributeReferenceClass(null);
                  }}
                >
                  Cancel
                </Button>
                <Button variant="primary" onClick={handleConfirmAddAttribute} disabled={!newAttributeName.trim()}>
                  {isRuleSchema ? 'Add Rule' : 'Add Attribute'}
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <FormField
              label={isRuleSchema ? 'Rule Name' : 'Attribute Name'}
              description={isRuleSchema ? 'The rule name' : 'The field name to extract from documents'}
            >
              <Input
                value={newAttributeName}
                onChange={({ detail }) => setNewAttributeName(detail.value)}
                placeholder={isRuleSchema ? 'e.g., checkCompliance, validateSafety' : 'e.g., invoiceNumber, customerName, total'}
              />
            </FormField>
            <FormField
              label={isRuleSchema ? 'Rule Output Data Type' : 'Attribute Type'}
              description={isRuleSchema ? 'The type of data this rule validates' : 'The type of data this field contains'}
            >
              <Select
                selectedOption={newAttributeType}
                onChange={({ detail }) => setNewAttributeType(detail.selectedOption as TypeOption)}
                options={attributeTypeOptions}
              />
            </FormField>
            <FormField label="Description (Optional)" description="Describe what this field contains">
              <Textarea
                value={newAttributeDescription}
                onChange={({ detail }) => setNewAttributeDescription(detail.value)}
                placeholder="e.g., The unique invoice number for this document"
                rows={3}
              />
            </FormField>

            {(newAttributeType.value === 'object' || newAttributeType.value === 'array') && classes.length > 1 && (
              <FormField
                label={newAttributeType.value === 'object' ? 'Object Type' : 'Array Item Type'}
                description={
                  newAttributeType.value === 'object'
                    ? 'Define the structure: reference an existing class or create inline properties'
                    : 'What type of items will this array contain? Reference a class to create a list of ' +
                      'complex objects (e.g., list of persons)'
                }
                info={
                  newAttributeType.value === 'array' ? (
                    <Box>Example: If you have a &quot;person&quot; class, select it here to create an array of person objects</Box>
                  ) : undefined
                }
              >
                <Select
                  selectedOption={newAttributeReferenceClass}
                  onChange={({ detail }) => setNewAttributeReferenceClass(detail.selectedOption as TypeOption)}
                  options={[
                    {
                      label: newAttributeType.value === 'object' ? '⚙️ Inline properties' : '📝 Simple values (string)',
                      value: '',
                      description:
                        newAttributeType.value === 'object' ? 'Define properties directly in this object' : 'Array of simple strings',
                    },
                    ...classes
                      .filter((cls) => cls.id !== selectedClassId)
                      .map((cls) => ({
                        label: `🔗 ${cls.name}`,
                        value: cls.name,
                        description: cls.description || `Reference the ${cls.name} class`,
                      })),
                  ]}
                  placeholder={
                    newAttributeType.value === 'array'
                      ? 'e.g., select "person" to create list of persons'
                      : 'Select a class or define inline'
                  }
                />
              </FormField>
            )}
          </SpaceBetween>
        </Modal>

        <Modal
          visible={showEditClassModal}
          onDismiss={() => {
            setShowEditClassModal(false);
            setEditingClass(null);
            setNewClassName('');
            setNewClassDescription('');
          }}
          header="Edit Class"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="link"
                  onClick={() => {
                    setShowEditClassModal(false);
                    setEditingClass(null);
                    setNewClassName('');
                    setNewClassDescription('');
                  }}
                >
                  Cancel
                </Button>
                <Button variant="primary" onClick={handleConfirmEditClass} disabled={!newClassName.trim()}>
                  Save Changes
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <FormField label="Class Name" description="A unique name for this extraction class">
              <Input
                value={newClassName}
                onChange={({ detail }) => setNewClassName(detail.value)}
                placeholder="e.g., Invoice, Customer, Address"
              />
            </FormField>
            <FormField label="Description (Optional)" description="Describe what this class represents">
              <Textarea
                value={newClassDescription}
                onChange={({ detail }) => setNewClassDescription(detail.value)}
                placeholder="e.g., Invoice document with line items"
                rows={3}
              />
            </FormField>
          </SpaceBetween>
        </Modal>

        <Modal
          visible={showDeleteConfirmModal}
          onDismiss={() => {
            setShowDeleteConfirmModal(false);
            setClassToDelete(null);
          }}
          header="Delete Class"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="link"
                  onClick={() => {
                    setShowDeleteConfirmModal(false);
                    setClassToDelete(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    if (classToDelete) {
                      removeClass(classToDelete.id);
                    }
                    setShowDeleteConfirmModal(false);
                    setClassToDelete(null);
                  }}
                >
                  Delete
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <Alert type="warning">
              Are you sure you want to delete the class <strong>{classToDelete?.name}</strong>? This action cannot be undone.
            </Alert>
            {classToDelete && Object.keys(classToDelete.attributes?.properties || {}).length > 0 && (
              <Alert type="info">
                This class has {Object.keys(classToDelete.attributes!.properties!).length} attribute(s) that will also be deleted.
              </Alert>
            )}
          </SpaceBetween>
        </Modal>

        <Modal
          visible={showWipeAllModal}
          onDismiss={() => setShowWipeAllModal(false)}
          header={`Wipe All ${TypeLabel} Classes`}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="link" onClick={() => setShowWipeAllModal(false)}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={handleConfirmWipeAll}>
                  Wipe All
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <Alert type="error">
              Are you sure you want to delete{' '}
              <strong>
                all {classes.length} {typeLabel} class(es)
              </strong>
              ? This action cannot be undone.
            </Alert>
            <Box variant="p">
              All {typeLabel} classes and their attributes will be permanently removed.
              {!isRuleSchema && ' You will need to recreate them or use the discovery feature to regenerate your schema.'}
            </Box>
          </SpaceBetween>
        </Modal>
      </SpaceBetween>
    </>
  );
};

export default SchemaBuilder;
