// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * PromptPreview component for the Configuration page.
 *
 * Renders a preview of the actual prompts sent to the LLM for each processing step
 * (Classification, Extraction, Assessment, Summarization) with config-derived placeholders
 * filled in and document-specific placeholders shown as highlighted markers.
 *
 * This helps users understand what the LLM actually sees, enabling better optimization
 * of document class schemas and prompt templates.
 */

import React, { useState, useMemo, useCallback } from 'react';
import {
  Box,
  SpaceBetween,
  FormField,
  Select,
  Container,
  Header,
  ColumnLayout,
  Badge,
  Tabs,
  CopyToClipboard,
  Alert,
} from '@cloudscape-design/components';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ClassSchema {
  $id?: string;
  'x-aws-idp-document-type'?: string;
  type?: string;
  description?: string;
  properties?: Record<string, PropertySchema>;
  [key: string]: unknown;
}

interface PropertySchema {
  type?: string;
  description?: string;
  properties?: Record<string, PropertySchema>;
  items?: PropertySchema;
  [key: string]: unknown;
}

interface StepConfig {
  system_prompt?: string;
  task_prompt?: string;
  model?: string;
  [key: string]: unknown;
}

interface PromptPreviewProps {
  /** Merged configuration values (complete config: default + custom) */
  formValues: Record<string, unknown>;
}

// ─── Constants ───────────────────────────────────────────────────────────────

/** Processing steps available for prompt preview */
const STEPS = [
  { value: 'classification', label: 'Classification' },
  { value: 'extraction', label: 'Extraction' },
  { value: 'assessment', label: 'Assessment' },
  { value: 'summarization', label: 'Summarization' },
] as const;

type StepName = (typeof STEPS)[number]['value'];

/** Map of placeholder → human-readable description shown in preview */
const DOCUMENT_PLACEHOLDER_LABELS: Record<string, string> = {
  DOCUMENT_TEXT: '📄 [Document OCR text will be inserted here at runtime]',
  DOCUMENT_IMAGE: '🖼️ [Document page image(s) will be inserted here at runtime]',
  EXTRACTION_RESULTS: '📊 [Extraction results JSON will be inserted here at runtime]',
  OCR_TEXT_CONFIDENCE: '🔍 [OCR text with confidence scores will be inserted here at runtime]',
  EXPECTED_VALUE: '✅ [Expected value will be inserted here at runtime]',
  ACTUAL_VALUE: '📝 [Actual extracted value will be inserted here at runtime]',
  FEW_SHOT_EXAMPLES: '📚 [Few-shot examples from class configuration will be inserted here at runtime]',
};

// ─── Utility functions ───────────────────────────────────────────────────────

/**
 * Get the class identifier from a schema object.
 */
function getClassId(schema: ClassSchema): string {
  return schema.$id || schema['x-aws-idp-document-type'] || 'unknown';
}

/**
 * Clean JSON Schema by removing IDP custom fields (x-aws-idp-*) for display.
 * Mirrors the Python _clean_schema_for_prompt() logic in extraction/service.py.
 */
function cleanSchemaForPrompt(schema: Record<string, unknown>): Record<string, unknown> {
  const cleaned: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(schema)) {
    if (key.startsWith('x-aws-idp-')) continue;

    if (value && typeof value === 'object' && !Array.isArray(value)) {
      cleaned[key] = cleanSchemaForPrompt(value as Record<string, unknown>);
    } else if (Array.isArray(value)) {
      cleaned[key] = value.map((item) => (item && typeof item === 'object' ? cleanSchemaForPrompt(item as Record<string, unknown>) : item));
    } else {
      cleaned[key] = value;
    }
  }

  return cleaned;
}

/**
 * Format class names and descriptions for classification prompts.
 * Mirrors the Python _format_classes_list() logic in classification/service.py.
 */
function formatClassNamesAndDescriptions(classes: ClassSchema[]): string {
  return classes
    .map((cls) => {
      const name = getClassId(cls);
      const description = cls.description || '';
      return `${name}  \t[ ${description} ]`;
    })
    .join('\n');
}

/**
 * Format a class schema as cleaned JSON for extraction/assessment prompts.
 * Mirrors the Python _format_schema_for_prompt() logic in extraction/service.py.
 */
function formatSchemaForPrompt(schema: ClassSchema): string {
  const cleaned = cleanSchemaForPrompt(schema as Record<string, unknown>);
  return JSON.stringify(cleaned, null, 2);
}

/**
 * Estimate token count from text (rough approximation: ~4 chars per token for English).
 */
function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}

/** Delimiters used to mark config-substituted values for highlighting */
const CONFIG_START = '\u00AB'; // «
const CONFIG_END = '\u00BB'; // »

/**
 * Fill config-derived placeholders in a prompt template and mark document-specific ones.
 *
 * Config-derived placeholders (filled with actual values and wrapped in « » markers):
 *   - {CLASS_NAMES_AND_DESCRIPTIONS} → formatted class list
 *   - {ATTRIBUTE_NAMES_AND_DESCRIPTIONS} → cleaned JSON schema
 *   - {DOCUMENT_CLASS} → selected class name
 *
 * Document-specific placeholders (replaced with descriptive markers):
 *   - {DOCUMENT_TEXT}, {DOCUMENT_IMAGE}, {EXTRACTION_RESULTS}, etc.
 *
 * Also strips <<CACHEPOINT>> markers for clean display.
 */
function renderPrompt(template: string, configSubstitutions: Record<string, string>): string {
  if (!template) return '';

  let result = template;

  // Fill config-derived placeholders, wrapping substituted values in markers for highlighting
  for (const [key, value] of Object.entries(configSubstitutions)) {
    result = result.replace(new RegExp(`\\{${key}\\}`, 'g'), `${CONFIG_START}${value}${CONFIG_END}`);
  }

  // Replace document-specific placeholders with descriptive markers
  for (const [placeholder, label] of Object.entries(DOCUMENT_PLACEHOLDER_LABELS)) {
    result = result.replace(new RegExp(`\\{${placeholder}\\}`, 'g'), label);
  }

  // Strip <<CACHEPOINT>> markers
  result = result.replace(/<<CACHEPOINT>>/g, '');

  // Clean up excessive blank lines
  result = result.replace(/\n{3,}/g, '\n\n');

  return result.trim();
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const promptPreviewStyles = `
  .prompt-preview-content {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-wrap: break-word;
    background-color: #fafafa;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px;
    min-height: 200px;
    height: 50vh;
    overflow-y: auto;
    overflow-x: auto;
    color: #1a1a1a;
    resize: vertical;
  }

  .prompt-preview-content .runtime-placeholder {
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 4px;
    padding: 2px 6px;
    font-style: italic;
    color: #856404;
    display: inline;
  }

  .prompt-preview-content .config-value {
    background-color: #d4edda;
    border: 1px solid #28a745;
    border-radius: 4px;
    padding: 2px 6px;
    color: #155724;
  }

  .prompt-stats-row {
    display: flex;
    gap: 16px;
    align-items: center;
    flex-wrap: wrap;
  }

  .prompt-stat-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #545b64;
  }
`;

// ─── Sub-components ──────────────────────────────────────────────────────────

/**
 * Renders a prompt template with syntax highlighting for placeholders.
 * Config-derived values are shown in green, runtime placeholders in yellow.
 */
const HighlightedPrompt = ({ text }: { text: string }): React.JSX.Element => {
  if (!text) {
    return (
      <Box color="text-body-secondary">
        <span style={{ fontStyle: 'italic' }}>No prompt template configured for this step.</span>
      </Box>
    );
  }

  // Parse text into segments: plain text, runtime placeholders (yellow), and config values (green)
  // Config values are wrapped in « » markers by renderPrompt()
  // Runtime placeholders start with emoji prefixes (📄, 🖼️, etc.)
  const segments: React.ReactNode[] = [];
  let keyCounter = 0;

  // Combined regex: match either config-value markers «...» or runtime placeholder markers
  const combinedRegex = /(\u00AB[\s\S]*?\u00BB)|((?:📄|🖼️|📊|🔍|✅|📝|📚)\s*\[.*?\])/gu;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = combinedRegex.exec(text)) !== null) {
    // Add plain text before this match
    if (match.index > lastIndex) {
      segments.push(text.substring(lastIndex, match.index));
    }

    if (match[1]) {
      // Config-substituted value (green) — strip the « » delimiters
      const configContent = match[1].substring(1, match[1].length - 1);
      segments.push(
        <span key={`cv-${keyCounter++}`} className="config-value">
          {configContent}
        </span>,
      );
    } else if (match[2]) {
      // Runtime placeholder (yellow)
      segments.push(
        <span key={`ph-${keyCounter++}`} className="runtime-placeholder">
          {match[2]}
        </span>,
      );
    }

    lastIndex = match.index + match[0].length;
  }

  // Add any remaining plain text after the last match
  if (lastIndex < text.length) {
    segments.push(text.substring(lastIndex));
  }

  return <div className="prompt-preview-content">{segments}</div>;
};

/**
 * Stats bar showing token estimates and model info.
 */
const PromptStats = ({
  systemPrompt,
  taskPrompt,
  model,
}: {
  systemPrompt: string;
  taskPrompt: string;
  model: string;
}): React.JSX.Element => {
  const systemTokens = estimateTokens(systemPrompt);
  const taskTokens = estimateTokens(taskPrompt);
  const totalTokens = systemTokens + taskTokens;

  return (
    <div className="prompt-stats-row">
      <div className="prompt-stat-item">
        <Badge color="blue">Model</Badge>
        <span>{model || 'Not configured'}</span>
      </div>
      <div className="prompt-stat-item">
        <Badge color="grey">System</Badge>
        <span>~{systemTokens.toLocaleString()} tokens</span>
      </div>
      <div className="prompt-stat-item">
        <Badge color="grey">Task</Badge>
        <span>~{taskTokens.toLocaleString()} tokens</span>
      </div>
      <div className="prompt-stat-item">
        <Badge color="green">Total (est.)</Badge>
        <span>~{totalTokens.toLocaleString()} tokens</span>
      </div>
      <div className="prompt-stat-item" style={{ marginLeft: 'auto', fontSize: '12px', color: '#888' }}>
        Token estimates exclude document content and images
      </div>
    </div>
  );
};

// ─── Main Component ──────────────────────────────────────────────────────────

const PromptPreview = ({ formValues }: PromptPreviewProps): React.JSX.Element => {
  const [selectedStep, setSelectedStep] = useState<StepName>('classification');
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);

  // Extract classes from config
  const classes = useMemo((): ClassSchema[] => {
    const raw = formValues?.classes;
    if (!Array.isArray(raw)) return [];
    return raw as ClassSchema[];
  }, [formValues?.classes]);

  // Build class options for the dropdown
  const classOptions = useMemo(
    () =>
      classes.map((cls) => ({
        value: getClassId(cls),
        label: `${getClassId(cls)}${cls.description ? ` — ${cls.description.substring(0, 60)}` : ''}`,
      })),
    [classes],
  );

  // Auto-select first class when classes change or class selection is cleared
  React.useEffect(() => {
    if (classes.length > 0 && !selectedClassId) {
      setSelectedClassId(getClassId(classes[0]));
    } else if (classes.length === 0) {
      setSelectedClassId(null);
    }
  }, [classes, selectedClassId]);

  // Get the step config (system_prompt, task_prompt, model)
  const stepConfig = useMemo((): StepConfig => {
    const cfg = formValues?.[selectedStep];
    if (!cfg || typeof cfg !== 'object') return {};
    return cfg as StepConfig;
  }, [formValues, selectedStep]);

  // Whether this step needs a class selection
  const needsClassSelection = selectedStep === 'extraction' || selectedStep === 'assessment';

  // Get selected class schema
  const selectedClass = useMemo((): ClassSchema | null => {
    if (!selectedClassId) return null;
    return classes.find((cls) => getClassId(cls) === selectedClassId) || null;
  }, [classes, selectedClassId]);

  // Build config-derived substitutions based on the selected step
  const buildSubstitutions = useCallback((): Record<string, string> => {
    const subs: Record<string, string> = {};

    switch (selectedStep) {
      case 'classification':
        subs.CLASS_NAMES_AND_DESCRIPTIONS = formatClassNamesAndDescriptions(classes);
        break;

      case 'extraction':
        if (selectedClass) {
          subs.DOCUMENT_CLASS = getClassId(selectedClass);
          subs.ATTRIBUTE_NAMES_AND_DESCRIPTIONS = formatSchemaForPrompt(selectedClass);
        } else {
          subs.DOCUMENT_CLASS = '[No class selected]';
          subs.ATTRIBUTE_NAMES_AND_DESCRIPTIONS = '[No class selected]';
        }
        break;

      case 'assessment':
        if (selectedClass) {
          subs.DOCUMENT_CLASS = getClassId(selectedClass);
          subs.ATTRIBUTE_NAMES_AND_DESCRIPTIONS = formatSchemaForPrompt(selectedClass);
        } else {
          subs.DOCUMENT_CLASS = '[No class selected]';
          subs.ATTRIBUTE_NAMES_AND_DESCRIPTIONS = '[No class selected]';
        }
        break;

      case 'summarization':
        // Summarization only has document-specific placeholders
        break;
    }

    return subs;
  }, [selectedStep, classes, selectedClass]);

  // Render the prompts
  const { renderedSystemPrompt, renderedTaskPrompt, rawSystemPrompt, rawTaskPrompt } = useMemo(() => {
    const subs = buildSubstitutions();
    const sysTemplate = stepConfig.system_prompt || '';
    const taskTemplate = stepConfig.task_prompt || '';

    return {
      renderedSystemPrompt: renderPrompt(sysTemplate, subs),
      renderedTaskPrompt: renderPrompt(taskTemplate, subs),
      rawSystemPrompt: sysTemplate,
      rawTaskPrompt: taskTemplate,
    };
  }, [stepConfig, buildSubstitutions]);

  return (
    <SpaceBetween size="m">
      <style>{promptPreviewStyles}</style>

      {/* Controls row */}
      <Container>
        <ColumnLayout columns={needsClassSelection ? 2 : 1}>
          <FormField label="Processing Step" description="Select a pipeline step to preview its prompts">
            <Select
              selectedOption={STEPS.find((s) => s.value === selectedStep) || null}
              onChange={({ detail }) => setSelectedStep(detail.selectedOption.value as StepName)}
              options={[...STEPS]}
            />
          </FormField>

          {needsClassSelection && (
            <FormField label="Document Class" description="Select a class to see how its schema appears in the prompt">
              <Select
                selectedOption={classOptions.find((o) => o.value === selectedClassId) || null}
                onChange={({ detail }) => setSelectedClassId(detail.selectedOption.value ?? null)}
                options={classOptions}
                placeholder="Select a document class..."
                empty="No document classes configured"
              />
            </FormField>
          )}
        </ColumnLayout>
      </Container>

      {/* Info about what's shown */}
      <Alert type="info" header="About Prompt Preview">
        <SpaceBetween size="xxs">
          <span>
            This preview shows the actual prompts sent to the LLM.{' '}
            <span style={{ backgroundColor: '#d4edda', border: '1px solid #28a745', padding: '1px 4px', borderRadius: '3px' }}>
              Green highlighted text
            </span>{' '}
            shows configuration-derived values (class names, attribute schemas) substituted from your config.{' '}
            <span style={{ backgroundColor: '#fff3cd', border: '1px solid #ffc107', padding: '1px 4px', borderRadius: '3px' }}>
              Yellow highlighted text
            </span>{' '}
            indicates runtime placeholders filled with actual document content during processing.
          </span>
        </SpaceBetween>
      </Alert>

      {/* Stats bar */}
      <PromptStats systemPrompt={renderedSystemPrompt} taskPrompt={renderedTaskPrompt} model={stepConfig.model || ''} />

      {/* Prompt display */}
      <Tabs
        tabs={[
          {
            id: 'task',
            label: `Task Prompt (~${estimateTokens(renderedTaskPrompt).toLocaleString()} tokens)`,
            content: (
              <SpaceBetween size="s">
                <Box float="right">
                  <CopyToClipboard
                    copyButtonAriaLabel="Copy task prompt"
                    copySuccessText="Task prompt copied"
                    copyErrorText="Failed to copy"
                    textToCopy={renderedTaskPrompt}
                    variant="icon"
                  />
                </Box>
                <HighlightedPrompt text={renderedTaskPrompt} />
              </SpaceBetween>
            ),
          },
          {
            id: 'system',
            label: `System Prompt (~${estimateTokens(renderedSystemPrompt).toLocaleString()} tokens)`,
            content: (
              <SpaceBetween size="s">
                <Box float="right">
                  <CopyToClipboard
                    copyButtonAriaLabel="Copy system prompt"
                    copySuccessText="System prompt copied"
                    copyErrorText="Failed to copy"
                    textToCopy={renderedSystemPrompt}
                    variant="icon"
                  />
                </Box>
                <HighlightedPrompt text={renderedSystemPrompt} />
              </SpaceBetween>
            ),
          },
          {
            id: 'raw-task',
            label: 'Raw Task Template',
            content: (
              <SpaceBetween size="s">
                <Box float="right">
                  <CopyToClipboard
                    copyButtonAriaLabel="Copy raw task template"
                    copySuccessText="Raw template copied"
                    copyErrorText="Failed to copy"
                    textToCopy={rawTaskPrompt}
                    variant="icon"
                  />
                </Box>
                <div className="prompt-preview-content" style={{ color: '#555' }}>
                  {rawTaskPrompt || (
                    <Box color="text-body-secondary">
                      <span style={{ fontStyle: 'italic' }}>No task prompt template configured.</span>
                    </Box>
                  )}
                </div>
              </SpaceBetween>
            ),
          },
          {
            id: 'raw-system',
            label: 'Raw System Template',
            content: (
              <SpaceBetween size="s">
                <Box float="right">
                  <CopyToClipboard
                    copyButtonAriaLabel="Copy raw system template"
                    copySuccessText="Raw template copied"
                    copyErrorText="Failed to copy"
                    textToCopy={rawSystemPrompt}
                    variant="icon"
                  />
                </Box>
                <div className="prompt-preview-content" style={{ color: '#555' }}>
                  {rawSystemPrompt || (
                    <Box color="text-body-secondary">
                      <span style={{ fontStyle: 'italic' }}>No system prompt template configured.</span>
                    </Box>
                  )}
                </div>
              </SpaceBetween>
            ),
          },
        ]}
      />

      {/* Legend */}
      {needsClassSelection && selectedClass && (
        <Container header={<Header variant="h3">Substitution Details</Header>}>
          <SpaceBetween size="s">
            <Box variant="h4">
              {'{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}'} → Cleaned JSON Schema for &quot;{getClassId(selectedClass)}&quot;
            </Box>
            <Box variant="small" color="text-body-secondary">
              This is the cleaned version of the class JSON Schema (with x-aws-idp-* custom fields removed) that gets inserted into the
              prompt. This is what the LLM sees when extracting/assessing attributes.
            </Box>
            <div className="prompt-preview-content" style={{ height: '300px', fontSize: '12px' }}>
              {formatSchemaForPrompt(selectedClass)}
            </div>
          </SpaceBetween>
        </Container>
      )}

      {selectedStep === 'classification' && classes.length > 0 && (
        <Container header={<Header variant="h3">Substitution Details</Header>}>
          <SpaceBetween size="s">
            <Box variant="h4">{'{CLASS_NAMES_AND_DESCRIPTIONS}'} → Formatted Class List</Box>
            <Box variant="small" color="text-body-secondary">
              This is the class list with descriptions that gets inserted into the classification prompt. The LLM uses this to classify
              document pages.
            </Box>
            <div className="prompt-preview-content" style={{ height: '200px', fontSize: '12px' }}>
              {formatClassNamesAndDescriptions(classes)}
            </div>
          </SpaceBetween>
        </Container>
      )}
    </SpaceBetween>
  );
};

export default PromptPreview;
