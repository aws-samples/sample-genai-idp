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
  tool_usage_recommended?: boolean;
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
  rows_mapped?: number;
  invocation_count?: number;
  parse_success_rate?: number;
  avg_confidence?: number;
  confidence_available?: boolean;
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
  inferenceResult?: Record<string, unknown>;
}

// Count the items the extraction actually produced: total list rows across all
// array fields (e.g. holdings_positions) plus populated scalar fields. This is
// the authoritative result, distinct from the pre-flight OCR row estimate.
function summarizeResult(inferenceResult?: Record<string, unknown>): { listRows: number; scalarFields: number; listFields: string[] } {
  let listRows = 0;
  let scalarFields = 0;
  const listFields: string[] = [];
  if (inferenceResult && typeof inferenceResult === 'object') {
    Object.entries(inferenceResult).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        listRows += value.length;
        listFields.push(`${key} (${value.length})`);
      } else if (value !== null && value !== undefined && value !== '') {
        scalarFields += 1;
      }
    });
  }
  return { listRows, scalarFields, listFields };
}

function pct(n: number | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n)) return 'N/A';
  return `${Math.round(n * 100)}%`;
}

const ProcessingReportTab: React.FC<ProcessingReportTabProps> = ({ metadata, processingReport, inferenceResult }) => {
  if (!metadata) {
    return (
      <Box padding="l" textAlign="center" color="text-status-inactive">
        Processing report not available
      </Box>
    );
  }

  const isAgentic = (metadata.extraction_method || '').toLowerCase() === 'agentic';
  const succeeded = metadata.parsing_succeeded !== false;
  const validation = metadata.validation;
  const populationCheck = metadata.population_check;
  const completenessCheck = metadata.completeness_check || {};
  const stats = metadata.table_parsing_stats;
  const tableToolUsed = metadata.table_parsing_tool_used === true;

  const { listRows, scalarFields, listFields } = summarizeResult(inferenceResult);

  // ---- Build the list of issues to surface up top (plain language) ----
  const issues: { label: string; detail: string }[] = [];
  if (!succeeded) {
    issues.push({ label: 'Extraction failed', detail: 'The model output could not be parsed into the expected structure.' });
  }
  if (validation && validation.valid === false) {
    const fields = (validation.failed_fields || []).join(', ');
    issues.push({
      label: 'Schema validation failed',
      detail: `${validation.error_count || 0} field(s) did not satisfy the schema${fields ? `: ${fields}` : ''}${
        validation.escalated
          ? validation.resolved_by_escalation
            ? ' (resolved by escalation)'
            : ' (escalation attempted, still invalid)'
          : ''
      }.`,
    });
  }
  if (populationCheck?.below_threshold) {
    issues.push({
      label: 'Possible missing data',
      detail: `Only ${populationCheck.fields_populated}/${populationCheck.fields_defined} schema fields were populated (${pct(
        populationCheck.population_ratio,
      )}, below the ${pct(populationCheck.threshold)} threshold) — review for silent extraction loss.`,
    });
  }
  if (completenessCheck.schema_constraints_met === false && (completenessCheck.violations || []).length > 0) {
    issues.push({
      label: 'Completeness shortfall',
      detail: completenessCheck.summary || 'Some array fields have fewer items than the schema requires.',
    });
  }

  // Overall verdict
  const allClear = issues.length === 0 && succeeded;

  return (
    <SpaceBetween size="l">
      {/* ---- Outcome (top-line verdict) ---- */}
      <Container
        header={
          <Header
            variant="h2"
            description={`${isAgentic ? 'Agentic' : 'Standard'} extraction${
              metadata.extraction_time_seconds ? ` · ${metadata.extraction_time_seconds.toFixed(1)}s` : ''
            }`}
          >
            Extraction Outcome
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Box>
            <StatusIndicator type={allClear ? 'success' : succeeded ? 'warning' : 'error'}>
              {allClear ? 'Completed — no issues detected' : succeeded ? `Completed with ${issues.length} item(s) to review` : 'Failed'}
            </StatusIndicator>
          </Box>

          <ColumnLayout columns={4} variant="text-grid">
            {inferenceResult && (
              <div>
                <Box variant="awsui-key-label">Data extracted</Box>
                <Box>
                  {listRows > 0 ? `${listRows.toLocaleString()} row(s)` : `${scalarFields} field(s)`}
                  {listRows > 0 && scalarFields > 0 ? ` + ${scalarFields} field(s)` : ''}
                </Box>
              </div>
            )}
            <div>
              <Box variant="awsui-key-label">Schema validation</Box>
              <Box>
                {validation ? (
                  <StatusIndicator type={validation.valid ? 'success' : 'warning'}>
                    {validation.valid ? 'Valid' : `${validation.error_count || 0} issue(s)`}
                  </StatusIndicator>
                ) : (
                  <Box color="text-status-inactive">Not enabled</Box>
                )}
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Model</Box>
              <Box>
                {metadata.extraction_model || 'N/A'}
                {metadata.extraction_model_overridden ? ' (per-class)' : ''}
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Method</Box>
              <Box>
                {isAgentic ? 'Agentic' : 'Standard'}
                {isAgentic && tableToolUsed ? ' + table parser' : ''}
              </Box>
            </div>
          </ColumnLayout>

          {listFields.length > 0 && (
            <Box fontSize="body-s" color="text-status-inactive">
              Lists: {listFields.join(', ')}
            </Box>
          )}
        </SpaceBetween>
      </Container>

      {/* ---- Issues / all-clear ---- */}
      {issues.length > 0 ? (
        <Alert type={succeeded ? 'warning' : 'error'} header={`${issues.length} item(s) to review`}>
          <SpaceBetween size="xs">
            {issues.map((iss) => (
              <Box key={iss.label}>
                <strong>{iss.label}:</strong> {iss.detail}
              </Box>
            ))}
          </SpaceBetween>
        </Alert>
      ) : (
        <Alert type="success" header="No issues detected">
          Extraction completed and passed all enabled checks.
        </Alert>
      )}

      {/* ---- Details (collapsed by default) ---- */}
      <ExpandableSection variant="container" headerText="Details & diagnostics" defaultExpanded={issues.length > 0}>
        <SpaceBetween size="l">
          {/* Schema validation detail */}
          {validation && (
            <div>
              <Box variant="awsui-key-label">Schema Validation &amp; Escalation</Box>
              <ColumnLayout columns={3} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Result</Box>
                  <Box>
                    <StatusIndicator type={validation.valid ? 'success' : 'warning'}>
                      {validation.valid ? 'Valid' : `${validation.error_count || 0} violation(s)`}
                    </StatusIndicator>
                  </Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">On failure</Box>
                  <Box>{validation.fail_action || 'N/A'}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Format checks</Box>
                  <Box>{validation.check_formats ? 'On' : 'Off'}</Box>
                </div>
              </ColumnLayout>
              {validation.escalated && (
                <Box padding={{ top: 'xs' }} fontSize="body-s">
                  Escalated to <strong>{validation.escalation_model || 'stronger model'}</strong> (
                  {validation.escalation_scope === 'field-subset'
                    ? `fields: ${(validation.escalation_fields || []).join(', ') || 'none'}`
                    : 'full section'}
                  ) — {validation.resolved_by_escalation ? 'resolved' : 'still invalid'}
                  {validation.initial_error_count !== undefined
                    ? `; errors ${validation.initial_error_count} → ${validation.error_count || 0}`
                    : ''}
                  .
                </Box>
              )}
              {!validation.valid && validation.errors && validation.errors.length > 0 && (
                <Box padding={{ top: 'xs' }}>
                  <ExpandableSection headerText={`Violations (${validation.error_count || validation.errors.length})`}>
                    <SpaceBetween size="xxs">
                      {validation.errors.map((e) => (
                        <Box key={`verr-${e.path}-${e.validator}-${e.message}`} fontSize="body-s">
                          <strong>{e.path || '(root)'}</strong>: {e.message}
                        </Box>
                      ))}
                    </SpaceBetween>
                  </ExpandableSection>
                </Box>
              )}
            </div>
          )}

          {/* Field population */}
          {populationCheck && populationCheck.fields_defined !== undefined && (
            <div>
              <Box variant="awsui-key-label">Field Population (completeness heuristic)</Box>
              <Box>
                {populationCheck.fields_populated}/{populationCheck.fields_defined} fields populated (
                {pct(populationCheck.population_ratio)}) ·{' '}
                <StatusIndicator type={populationCheck.below_threshold ? 'warning' : 'success'}>
                  {populationCheck.below_threshold ? `below ${pct(populationCheck.threshold)} threshold` : 'OK'}
                </StatusIndicator>
              </Box>
              {populationCheck.empty_fields && populationCheck.empty_fields.length > 0 && (
                <Box padding={{ top: 'xs' }}>
                  <ExpandableSection headerText={`Empty fields (${populationCheck.empty_fields.length})`}>
                    <Box fontSize="body-s">{populationCheck.empty_fields.join(', ')}</Box>
                  </ExpandableSection>
                </Box>
              )}
            </div>
          )}

          {/* Table parsing */}
          {isAgentic && (metadata.ocr_analysis || stats) && (
            <div>
              <Box variant="awsui-key-label">Table Extraction</Box>
              <Box fontSize="body-s" padding={{ bottom: 'xs' }} color="text-body-secondary">
                {tableToolUsed
                  ? 'The deterministic table parser was used (parses tables from OCR text instead of having the model regenerate every row).'
                  : metadata.ocr_analysis?.tool_usage_recommended || metadata.ocr_analysis?.recommendation_strength === 'MANDATORY'
                    ? 'Large tables were detected but the deterministic table parser was not used for this section.'
                    : 'No large tables detected; the deterministic table parser was not needed.'}
              </Box>
              <ColumnLayout columns={3} variant="text-grid">
                {metadata.ocr_analysis?.estimated_row_count !== undefined && (
                  <div>
                    <Box variant="awsui-key-label">Table rows seen in OCR (estimate)</Box>
                    <Box>~{metadata.ocr_analysis.estimated_row_count.toLocaleString()}</Box>
                  </div>
                )}
                {stats && (
                  <>
                    <div>
                      <Box variant="awsui-key-label">Rows parsed by tool</Box>
                      <Box>{(stats.rows_parsed || 0).toLocaleString()}</Box>
                    </div>
                    <div>
                      <Box variant="awsui-key-label">Parse success rate</Box>
                      <Box>{stats.parse_success_rate !== undefined ? pct(stats.parse_success_rate) : 'N/A'}</Box>
                    </div>
                    {stats.confidence_available && stats.avg_confidence !== undefined && (
                      <div>
                        <Box variant="awsui-key-label">Avg OCR confidence</Box>
                        <Box>{stats.avg_confidence.toFixed(1)}%</Box>
                      </div>
                    )}
                  </>
                )}
              </ColumnLayout>
              {inferenceResult && listRows > 0 && metadata.ocr_analysis?.estimated_row_count !== undefined && (
                <Box padding={{ top: 'xs' }} fontSize="body-s" color="text-status-inactive">
                  The OCR estimate (~{metadata.ocr_analysis.estimated_row_count.toLocaleString()}) is a pre-extraction guess and may differ
                  from the {listRows.toLocaleString()} row(s) actually extracted (the authoritative count, shown in Document Data).
                </Box>
              )}
              {stats?.warnings && stats.warnings.length > 0 && (
                <Box padding={{ top: 'xs' }}>
                  <ExpandableSection headerText={`Parser warnings (${stats.warnings.length})`}>
                    <SpaceBetween size="xxs">
                      {stats.warnings.map((w) => (
                        <Box key={`warn-${w}`} fontSize="body-s">
                          • {w}
                        </Box>
                      ))}
                    </SpaceBetween>
                  </ExpandableSection>
                </Box>
              )}
            </div>
          )}

          {/* Completeness violations (minItems shortfalls) */}
          {completenessCheck.violations && completenessCheck.violations.length > 0 && (
            <div>
              <Box variant="awsui-key-label">Completeness Shortfalls</Box>
              <SpaceBetween size="xxs">
                {completenessCheck.violations.map((v) => (
                  <Box key={`cv-${v.field}`} fontSize="body-s">
                    <strong>{v.field}</strong>: {v.message}
                  </Box>
                ))}
              </SpaceBetween>
            </div>
          )}

          {/* Raw processing report text, if present */}
          {processingReport && (
            <ExpandableSection headerText="Raw processing report (text)">
              <Box padding="s" variant="code">
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{processingReport}</pre>
              </Box>
            </ExpandableSection>
          )}
        </SpaceBetween>
      </ExpandableSection>
    </SpaceBetween>
  );
};

export default ProcessingReportTab;
