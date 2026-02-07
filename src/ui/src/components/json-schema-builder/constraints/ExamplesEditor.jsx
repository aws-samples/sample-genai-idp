import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  Box,
  SpaceBetween,
  Header,
  FormField,
  Input,
  Textarea,
  Button,
  ExpandableSection,
  Alert,
  Container,
  ColumnLayout,
} from '@cloudscape-design/components';

/**
 * ExamplesEditor Component
 *
 * Manages few-shot examples for classification and extraction.
 * Examples are stored in the x-aws-idp-examples array with:
 * - name: Example identifier
 * - classPrompt: Classification prompt (used by classification service)
 * - attributesPrompt: Extraction prompt (used by extraction service)
 * - imagePath: S3 path or local path to example image(s)
 */
const ExamplesEditor = ({ examples = [], onChange }) => {
  const [expandedSections, setExpandedSections] = useState({});

  const handleAddExample = () => {
    const newExample = {
      id: crypto.randomUUID(),
      name: `Example ${examples.length + 1}`,
      classPrompt: '',
      attributesPrompt: '',
      imagePath: '',
    };
    onChange([...examples, newExample]);
    // Auto-expand the new example
    setExpandedSections({
      ...expandedSections,
      [examples.length]: true,
    });
  };

  const handleUpdateExample = (index, field, value) => {
    const updated = [...examples];
    updated[index] = {
      ...updated[index],
      [field]: value,
    };
    onChange(updated);
  };

  const handleDeleteExample = (index) => {
    const updated = examples.filter((_, i) => i !== index);
    onChange(updated);
    // Clean up expanded state
    const newExpanded = { ...expandedSections };
    delete newExpanded[index];
    setExpandedSections(newExpanded);
  };

  const toggleSection = (index) => {
    setExpandedSections({
      ...expandedSections,
      [index]: !expandedSections[index],
    });
  };

  return (
    <SpaceBetween size="m">
      <Box>
        <SpaceBetween size="xs">
          <Header
            variant="h4"
            description="Add few-shot examples to improve classification and extraction accuracy"
            actions={
              <Button iconName="add-plus" onClick={handleAddExample}>
                Add Example
              </Button>
            }
          >
            Few-Shot Examples ({examples.length})
          </Header>

          {examples.length === 0 && (
            <Alert type="info" header="No examples defined">
              Add examples to provide the model with sample inputs and expected outputs. Examples help improve accuracy for both
              classification and extraction tasks.
            </Alert>
          )}
        </SpaceBetween>
      </Box>

      {examples.map((example, index) => {
        // Use stable ID as key to prevent focus loss on content changes
        const stableKey = example.id || `example-${index}`;
        return (
          <ExpandableSection
            key={stableKey}
            headerText={example.name || `Example ${index + 1}`}
            expanded={expandedSections[index] || false}
            onChange={() => toggleSection(index)}
            headerActions={
              <Button
                iconName="remove"
                variant="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteExample(index);
                }}
              />
            }
          >
            <Container>
              <SpaceBetween size="m">
                <FormField label="Example Name" description="Unique identifier for this example">
                  <Input
                    value={example.name || ''}
                    onChange={({ detail }) => handleUpdateExample(index, 'name', detail.value)}
                    placeholder="e.g., Invoice Example 1"
                  />
                </FormField>

                <FormField
                  label="Classification Prompt (classPrompt)"
                  description="Used by classification service to identify document type. Describe what makes this example match this class."
                  stretch
                >
                  <Textarea
                    value={example.classPrompt || ''}
                    onChange={({ detail }) => handleUpdateExample(index, 'classPrompt', detail.value)}
                    placeholder="This is an example of the class 'Invoice'. Key characteristics: Has invoice number, date, line items, and total amount."
                    rows={4}
                  />
                </FormField>

                <FormField
                  label="Extraction Prompt (attributesPrompt)"
                  description="Used by extraction service to extract field values. Show expected output format and values."
                  stretch
                >
                  <Textarea
                    value={example.attributesPrompt || ''}
                    onChange={({ detail }) => handleUpdateExample(index, 'attributesPrompt', detail.value)}
                    placeholder={`Expected attributes are:\n{\n  "invoiceNumber": "INV-2024-001",\n  "date": "2024-01-15",\n  "total": 1250.00\n}`}
                    rows={8}
                  />
                </FormField>

                <FormField
                  label="Image Path (imagePath)"
                  description="S3 URI (s3://bucket/path) or local path to example image. Supports directories for multiple images."
                  stretch
                >
                  <Input
                    value={example.imagePath || ''}
                    onChange={({ detail }) => handleUpdateExample(index, 'imagePath', detail.value)}
                    placeholder="s3://my-bucket/examples/invoice-1.png or config_library/examples/"
                  />
                </FormField>

                <Alert type="info">
                  <ColumnLayout columns={2} variant="text-grid">
                    <div>
                      <Box variant="strong">Classification Service</Box>
                      <Box variant="p">
                        Uses <code>classPrompt</code> and <code>imagePath</code>
                      </Box>
                    </div>
                    <div>
                      <Box variant="strong">Extraction Service</Box>
                      <Box variant="p">
                        Uses <code>attributesPrompt</code> and <code>imagePath</code>
                      </Box>
                    </div>
                  </ColumnLayout>
                </Alert>
              </SpaceBetween>
            </Container>
          </ExpandableSection>
        );
      })}
    </SpaceBetween>
  );
};

ExamplesEditor.propTypes = {
  examples: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string,
      classPrompt: PropTypes.string,
      attributesPrompt: PropTypes.string,
      imagePath: PropTypes.string,
    }),
  ),
  onChange: PropTypes.func.isRequired,
};

export default ExamplesEditor;
