import React, { useState } from 'react';
import { Alert, Box, Button, Container, ExpandableSection, FormField, Header, Input, SpaceBetween } from '@cloudscape-design/components';
import { X_AWS_IDP_PAGE_CONTENT_REGEX } from '../../../constants/schemaConstants';

export interface PageTypeEntry {
  id?: string;
  name: string;
  description?: string;
  [X_AWS_IDP_PAGE_CONTENT_REGEX]?: string;
}

interface PageTypesEditorProps {
  pageTypes?: PageTypeEntry[];
  onChange: (pageTypes: PageTypeEntry[]) => void;
}

/**
 * PageTypesEditor
 *
 * Edits the `x-aws-idp-page-types` array on a class. Each entry declares a
 * named page sub-type plus a regex used to detect the page from per-page OCR
 * text. Page-type names declared here are referenced by properties via
 * `x-aws-idp-source-page-types` to mark them as MISSING when the page is
 * absent from the section.
 */
const PageTypesEditor = ({ pageTypes = [], onChange }: PageTypesEditorProps): React.JSX.Element => {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const handleAdd = (): void => {
    const next: PageTypeEntry = {
      id: crypto.randomUUID(),
      name: `PageType${pageTypes.length + 1}`,
      description: '',
      [X_AWS_IDP_PAGE_CONTENT_REGEX]: '',
    };
    onChange([...pageTypes, next]);
    setExpanded({ ...expanded, [pageTypes.length]: true });
  };

  const handleUpdate = (index: number, field: keyof PageTypeEntry | string, value: string): void => {
    const updated = [...pageTypes];
    updated[index] = { ...updated[index], [field]: value };
    onChange(updated);
  };

  const handleDelete = (index: number): void => {
    onChange(pageTypes.filter((_, i) => i !== index));
    const next = { ...expanded };
    delete next[index];
    setExpanded(next);
  };

  const toggle = (index: number): void => {
    setExpanded({ ...expanded, [index]: !expanded[index] });
  };

  return (
    <SpaceBetween size="m">
      <Box>
        <SpaceBetween size="xs">
          <Header
            {...({ variant: 'h4' } as Record<string, unknown>)}
            description="Declare page sub-types this class can include. Each entry's regex is matched against per-page OCR text to detect which pages were submitted. Properties can declare 'Source Page Types' referencing names defined here."
            actions={
              <Button iconName="add-plus" onClick={handleAdd}>
                Add Page Type
              </Button>
            }
          >
            Page Types ({pageTypes.length})
          </Header>

          {pageTypes.length === 0 && (
            <Alert type="info" header="No page types defined">
              Add page types when this class can be submitted with optional sub-sections (e.g. an &quot;International Transfers&quot;
              supplement that may be omitted). When defined, properties that source from absent page types are marked as MISSING in
              extraction output instead of being silently empty.
            </Alert>
          )}
        </SpaceBetween>
      </Box>

      {pageTypes.map((entry, index) => {
        const stableKey = entry.id || `page-type-${index}`;
        return (
          <ExpandableSection
            key={stableKey}
            headerText={entry.name || `Page Type ${index + 1}`}
            expanded={expanded[index] || false}
            onChange={() => toggle(index)}
            headerActions={
              <Button
                iconName="remove"
                variant="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(index);
                }}
              />
            }
          >
            <Container>
              <SpaceBetween size="m">
                <FormField
                  label="Name"
                  description="Identifier referenced by properties' Source Page Types. Must be unique within this class."
                >
                  <Input
                    value={entry.name || ''}
                    onChange={({ detail }) => handleUpdate(index, 'name', detail.value)}
                    placeholder="e.g., AccountSummary, TransactionsWorksheet"
                  />
                </FormField>

                <FormField label="Description (Optional)" description="Human-readable note describing this page sub-type.">
                  <Input
                    value={entry.description || ''}
                    onChange={({ detail }) => handleUpdate(index, 'description', detail.value)}
                    placeholder="e.g., First page with account holder + summary"
                  />
                </FormField>

                <FormField
                  label="Page Content Regex"
                  description="Regex matched against per-page OCR text. First match wins. Use case-insensitive flags like (?i) when needed."
                >
                  <Input
                    value={(entry[X_AWS_IDP_PAGE_CONTENT_REGEX] as string) || ''}
                    onChange={({ detail }) => handleUpdate(index, X_AWS_IDP_PAGE_CONTENT_REGEX, detail.value)}
                    placeholder="e.g., (?i)account summary"
                  />
                </FormField>
              </SpaceBetween>
            </Container>
          </ExpandableSection>
        );
      })}
    </SpaceBetween>
  );
};

export default PageTypesEditor;
