// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Alert,
  ColumnLayout,
  StatusIndicator,
  ExpandableSection,
} from '@cloudscape-design/components';

interface Violation {
  field: string;
  message: string;
  possible_cause: string;
}

interface SchemaAnalysis {
  large_array_fields?: string[];
  max_min_items?: number;
  recommendation_strength?: string;
  recommendation_reason?: string;
}

interface OcrAnalysis {
  tables_detected?: number;
  estimated_row_count?: number;
  recommendation_strength?: string;
  recommendation_reason?: string;
}

interface ToolUsageDecision {
  expected?: boolean;
  actual?: boolean;
  mismatch?: boolean;
  explanation?: string;
}

interface CompletenessCheck {
  schema_constraints_met?: boolean;
  violations?: Violation[];
  summary?: string;
}

interface TableParsingStats {
  tables_parsed?: number;
  rows_parsed?: number;
  parse_success_rate?: number;
  avg_confidence?: number;
  warnings?: string[];
}

interface ValidationError {
  path?: string;
  validator?: string;
  message?: string;
}

interface ValidationInfo {
  valid?: boolean;
  error_count?: number;
  failed_fields?: string[];
  errors?: ValidationError[];
  check_formats?: boolean;
  fail_action?: string;
  escalated?: boolean;
  initial_error_count?: number;
  initial_failed_fields?: string[];
  escalation_model?: string;
  escalation_scope?: string;
  escalation_fields?: string[];
  resolved_by_escalation?: boolean;
}

interface PopulationCheck {
  fields_defined?: number;
  fields_populated?: number;
  population_ratio?: number;
  threshold?: number;
  below_threshold?: boolean;
  empty_fields?: string[];
}

interface ProcessingMetadata {
  extraction_method?: string;
  extraction_time_seconds?: number;
  parsing_succeeded?: boolean;
  extraction_model?: string;
  extraction_model_overridden?: boolean;
  schema_analysis?: SchemaAnalysis;
  ocr_analysis?: OcrAnalysis;
  tool_usage_decision?: ToolUsageDecision;
  completeness_check?: CompletenessCheck;
  table_parsing_tool_used?: boolean;
  table_parsing_stats?: TableParsingStats;
  validation?: ValidationInfo;
  population_check?: PopulationCheck;
}

interface ProcessingReportTabProps {
  metadata?: ProcessingMetadata;
  processingReport?: string;
}

const ProcessingReportTab: React.FC<ProcessingReportTabProps> = ({ metadata, processingReport }) => {
  if (!metadata || !processingReport) {
    return (
      <Box padding="l" textAlign="center" color="text-status-inactive">
        Processing report not available
      </Box>
    );
  }

  const extractionMethod = metadata.extraction_method || 'unknown';
  const toolUsed = metadata.table_parsing_tool_used;
  const toolDecision = metadata.tool_usage_decision || {};
  const completenessCheck = metadata.completeness_check || {};
  const validation = metadata.validation;
  const populationCheck = metadata.population_check;
  const validationFailed = validation !== undefined && validation.valid === false;
  const populationLow = populationCheck?.below_threshold === true;
  const hasIssues = toolDecision.mismatch || !completenessCheck.schema_constraints_met || validationFailed || populationLow;

  return (
    <SpaceBetween size="l">
      {/* Alert banner for issues */}
      {hasIssues && (
        <Alert type="warning" header="Extraction Issues Detected">
          <SpaceBetween size="s">
            {toolDecision.mismatch && (
              <Box>
                <strong>Tool Usage Mismatch:</strong> {toolDecision.explanation}
              </Box>
            )}
            {!completenessCheck.schema_constraints_met && (
              <Box>
                <strong>Completeness Issue:</strong> {completenessCheck.summary}
              </Box>
            )}
            {validationFailed && (
              <Box>
                <strong>Schema Validation:</strong> {validation?.error_count || 0} constraint violation(s)
                {validation?.escalated ? ' (escalation attempted)' : ''} —{' '}
                {(validation?.failed_fields || []).join(', ') || 'see details below'}
              </Box>
            )}
            {populationLow && (
              <Box>
                <strong>Low Field Population:</strong> only {populationCheck?.fields_populated}/{populationCheck?.fields_defined} schema
                fields populated ({Math.round((populationCheck?.population_ratio || 0) * 100)}%) — possible silent extraction loss.
              </Box>
            )}
          </SpaceBetween>
        </Alert>
      )}

      {/* Overview */}
      <Container header={<Header variant="h2">Extraction Overview</Header>}>
        <ColumnLayout columns={3} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Method</Box>
            <Box>
              <StatusIndicator type="success">{extractionMethod.toUpperCase()}</StatusIndicator>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Processing Time</Box>
            <Box>{metadata.extraction_time_seconds?.toFixed(1) || 'N/A'}s</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Status</Box>
            <Box>
              <StatusIndicator type={metadata.parsing_succeeded ? 'success' : 'error'}>
                {metadata.parsing_succeeded ? 'SUCCESS' : 'FAILED'}
              </StatusIndicator>
            </Box>
          </div>
          {metadata.extraction_model && (
            <div>
              <Box variant="awsui-key-label">Model</Box>
              <Box>
                {metadata.extraction_model}
                {metadata.extraction_model_overridden ? ' (per-class override)' : ''}
              </Box>
            </div>
          )}
        </ColumnLayout>
      </Container>

      {/* Schema Analysis */}
      {metadata.schema_analysis && (
        <Container header={<Header variant="h3">Schema Analysis</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Large Array Fields</Box>
              <Box>
                {metadata.schema_analysis.large_array_fields?.length || 0}
                {metadata.schema_analysis.large_array_fields &&
                  metadata.schema_analysis.large_array_fields.length > 0 &&
                  ` (${metadata.schema_analysis.large_array_fields.join(', ')})`}
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Max minItems Constraint</Box>
              <Box>{metadata.schema_analysis.max_min_items || 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Tool Recommendation</Box>
              <Box>
                <StatusIndicator type={metadata.schema_analysis.recommendation_strength === 'MANDATORY' ? 'warning' : 'info'}>
                  {metadata.schema_analysis.recommendation_strength || 'N/A'}
                </StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Reason</Box>
              <Box fontSize="body-s">{metadata.schema_analysis.recommendation_reason || 'N/A'}</Box>
            </div>
          </ColumnLayout>
        </Container>
      )}

      {/* OCR Analysis */}
      {metadata.ocr_analysis && (
        <Container header={<Header variant="h3">OCR Table Detection</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Tables Detected</Box>
              <Box>{metadata.ocr_analysis.tables_detected || 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Estimated Rows</Box>
              <Box>{metadata.ocr_analysis.estimated_row_count || 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Tool Recommendation</Box>
              <Box>
                <StatusIndicator type={metadata.ocr_analysis.recommendation_strength === 'MANDATORY' ? 'warning' : 'info'}>
                  {metadata.ocr_analysis.recommendation_strength || 'N/A'}
                </StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Reason</Box>
              <Box fontSize="body-s">{metadata.ocr_analysis.recommendation_reason || 'N/A'}</Box>
            </div>
          </ColumnLayout>
        </Container>
      )}

      {/* Tool Usage Decision */}
      {extractionMethod === 'agentic' && toolDecision.expected !== undefined && (
        <Container
          header={
            <Header variant="h3" description="Whether the table parsing tool was used as expected">
              Table Parsing Tool Decision
            </Header>
          }
        >
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Expected</Box>
              <Box>
                <StatusIndicator type={toolDecision.expected ? 'success' : 'info'}>{toolDecision.expected ? 'YES' : 'NO'}</StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Actual</Box>
              <Box>
                <StatusIndicator type={toolUsed ? 'success' : 'warning'}>{toolUsed ? 'USED' : 'NOT USED'}</StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Match</Box>
              <Box>
                <StatusIndicator type={toolDecision.mismatch ? 'error' : 'success'}>
                  {toolDecision.mismatch ? 'MISMATCH' : 'MATCH'}
                </StatusIndicator>
              </Box>
            </div>
          </ColumnLayout>
          <Box padding={{ top: 's' }} fontSize="body-s">
            <strong>Explanation:</strong> {toolDecision.explanation || 'N/A'}
          </Box>
        </Container>
      )}

      {/* Completeness Check */}
      {completenessCheck.violations && completenessCheck.violations.length > 0 && (
        <Container header={<Header variant="h3">Completeness Validation</Header>}>
          <Alert type="error" header={completenessCheck.summary}>
            <SpaceBetween size="s">
              {(completenessCheck.violations as Violation[]).map((v) => (
                <Box key={`violation-${v.field}`}>
                  <strong>Field &quot;{v.field}&quot;:</strong> {v.message}
                  <br />
                  <Box fontSize="body-s" color="text-status-inactive">
                    Possible cause: {v.possible_cause}
                  </Box>
                </Box>
              ))}
            </SpaceBetween>
          </Alert>
        </Container>
      )}

      {/* Completeness Check - Success */}
      {completenessCheck.schema_constraints_met && (
        <Container header={<Header variant="h3">Completeness Validation</Header>}>
          <Alert type="success" header={completenessCheck.summary}>
            All required data was extracted successfully.
          </Alert>
        </Container>
      )}

      {/* Schema Validation & Escalation */}
      {validation !== undefined && (
        <Container
          header={
            <Header variant="h3" description="Full JSON-Schema validation of the extraction result">
              Schema Validation &amp; Escalation
            </Header>
          }
        >
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Result</Box>
              <Box>
                <StatusIndicator type={validation.valid ? 'success' : 'warning'}>
                  {validation.valid ? 'VALID' : `${validation.error_count || 0} VIOLATION(S)`}
                </StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Fail Action</Box>
              <Box>{(validation.fail_action || 'N/A').toUpperCase()}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Format Checks</Box>
              <Box>{validation.check_formats ? 'Enabled' : 'Disabled'}</Box>
            </div>
            {validation.escalated && (
              <>
                <div>
                  <Box variant="awsui-key-label">Escalation</Box>
                  <Box>
                    <StatusIndicator type={validation.resolved_by_escalation ? 'success' : 'warning'}>
                      {validation.resolved_by_escalation ? 'RESOLVED' : 'ATTEMPTED'}
                    </StatusIndicator>
                  </Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Escalation Model</Box>
                  <Box>{validation.escalation_model || 'N/A'}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Re-extracted Fields</Box>
                  <Box>
                    {validation.escalation_scope === 'field-subset'
                      ? (validation.escalation_fields || []).join(', ') || 'none'
                      : 'full section'}
                  </Box>
                </div>
              </>
            )}
          </ColumnLayout>

          {validation.escalated && validation.initial_error_count !== undefined && (
            <Box padding={{ top: 's' }} fontSize="body-s" color="text-status-inactive">
              Errors before escalation: {validation.initial_error_count} → after: {validation.error_count || 0}
            </Box>
          )}

          {!validation.valid && validation.errors && validation.errors.length > 0 && (
            <Box padding={{ top: 's' }}>
              <ExpandableSection headerText={`Violations (${validation.error_count || validation.errors.length})`}>
                <SpaceBetween size="xs">
                  {validation.errors.map((e) => (
                    <Box key={`verr-${e.path}-${e.validator}-${e.message}`} fontSize="body-s">
                      <strong>{e.path || '(root)'}</strong> [{e.validator}]: {e.message}
                    </Box>
                  ))}
                </SpaceBetween>
              </ExpandableSection>
            </Box>
          )}
        </Container>
      )}

      {/* Field Population (completeness heuristic) */}
      {populationCheck !== undefined && populationCheck.fields_defined !== undefined && (
        <Container
          header={
            <Header
              variant="h3"
              description="Fraction of schema-defined fields that came back populated (advisory — flags possible silent loss)"
            >
              Field Population
            </Header>
          }
        >
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Populated</Box>
              <Box>
                {populationCheck.fields_populated}/{populationCheck.fields_defined} (
                {Math.round((populationCheck.population_ratio || 0) * 100)}%)
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Threshold</Box>
              <Box>{Math.round((populationCheck.threshold || 0) * 100)}%</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Status</Box>
              <Box>
                <StatusIndicator type={populationCheck.below_threshold ? 'warning' : 'success'}>
                  {populationCheck.below_threshold ? 'BELOW THRESHOLD' : 'OK'}
                </StatusIndicator>
              </Box>
            </div>
          </ColumnLayout>
          {populationCheck.empty_fields && populationCheck.empty_fields.length > 0 && (
            <Box padding={{ top: 's' }}>
              <ExpandableSection headerText={`Empty fields (${populationCheck.empty_fields.length})`}>
                <SpaceBetween size="xs">
                  {populationCheck.empty_fields.map((f) => (
                    <Box key={`empty-${f}`} fontSize="body-s">
                      • {f}
                    </Box>
                  ))}
                </SpaceBetween>
              </ExpandableSection>
            </Box>
          )}
        </Container>
      )}

      {/* Table Parsing Stats */}
      {toolUsed && metadata.table_parsing_stats && (
        <Container header={<Header variant="h3">Table Parsing Results</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Tables Parsed</Box>
              <Box>{metadata.table_parsing_stats.tables_parsed || 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Total Rows Extracted</Box>
              <Box>{metadata.table_parsing_stats.rows_parsed || 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Parse Success Rate</Box>
              <Box>{((metadata.table_parsing_stats.parse_success_rate || 0) * 100).toFixed(1)}%</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Avg OCR Confidence</Box>
              <Box>{(metadata.table_parsing_stats.avg_confidence || 0).toFixed(1)}%</Box>
            </div>
          </ColumnLayout>

          {metadata.table_parsing_stats.warnings && metadata.table_parsing_stats.warnings.length > 0 && (
            <Box padding={{ top: 's' }}>
              <ExpandableSection headerText="Warnings">
                <SpaceBetween size="xs">
                  {(metadata.table_parsing_stats.warnings as string[]).map((w) => (
                    <Box key={`warning-${w}`} fontSize="body-s">
                      • {w}
                    </Box>
                  ))}
                </SpaceBetween>
              </ExpandableSection>
            </Box>
          )}
        </Container>
      )}

      {/* Full Text Report */}
      <ExpandableSection headerText="Full Processing Report (Text)" defaultExpanded={false}>
        <Box padding="s" variant="code">
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{processingReport}</pre>
        </Box>
      </ExpandableSection>
    </SpaceBetween>
  );
};

export default ProcessingReportTab;
