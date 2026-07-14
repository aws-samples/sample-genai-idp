// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Builds GitHub "new issue" URLs that pre-fill our issue-*form* fields.
 *
 * Mechanism: GitHub issue forms (`.github/ISSUE_TEMPLATE/*.yml`) are pre-filled
 * by passing `?template=<file>.yml&<field-id>=<value>` query params, where each
 * `<field-id>` matches an `id:` in the YAML form. (This is different from the
 * legacy `?body=` mechanism used by Markdown templates — for forms, `body=` is
 * ignored.) Dropdown fields cannot be pre-filled via URL, so every field we
 * want to auto-populate is a text `input`/`textarea` in the YAML.
 *
 * Field-prefill only takes effect once the `.yml` templates exist on the
 * repository's default branch on GitHub. Until then these links still open the
 * new-issue form; they just don't populate. Nothing is ever submitted
 * automatically — the user always reviews the rendered form first.
 */
import { GITHUB_NEW_ISSUE_URL, GITHUB_BUG_TEMPLATE, GITHUB_FEATURE_TEMPLATE } from '../constants/github';

export interface DeploymentContext {
  /** settings.Version (e.g. "0.6.0.dev25"). */
  version?: string;
  /** VITE_AWS_REGION (e.g. "us-west-2"). */
  region?: string;
  /** settings.StackName. */
  stackName?: string;
  /** settings.IDPPattern — mapped to a friendly processing-mode label. */
  pattern?: string;
  /** settings.BuildDateTime. */
  buildDateTime?: string;
}

/** Optional per-document context, only used by the Troubleshoot flow. */
export interface DocumentContext {
  objectKey?: string;
  objectStatus?: string;
  configVersion?: string;
  executionArn?: string;
  /** Job error message when the troubleshoot job failed. */
  jobError?: string;
  /** Markdown findings text from the Troubleshoot agent result. */
  findings?: string;
}

/**
 * Map the raw IDPPattern setting to the user-facing processing-mode label used
 * in the bug form. IDPPattern values look like "Pattern2 - ..." historically;
 * the unified stack reports BDA vs Pipeline mode.
 */
const toProcessingMode = (pattern?: string): string => {
  if (!pattern) return '';
  const p = pattern.toLowerCase();
  if (p.includes('bda') || p.includes('pattern1')) return 'BDA mode';
  if (p.includes('pipeline') || p.includes('pattern2')) return 'Pipeline mode';
  return pattern;
};

/**
 * Human-readable environment block shared by all issue bodies. Rendered as
 * Markdown so it reads cleanly in the "Version / Build" style summary field.
 */
export const buildEnvironmentSummary = (ctx: DeploymentContext): string => {
  const lines: string[] = [];
  if (ctx.version) lines.push(`Version: ${ctx.version}`);
  if (ctx.buildDateTime) lines.push(`Build: ${ctx.buildDateTime}`);
  if (ctx.stackName) lines.push(`Stack: ${ctx.stackName}`);
  return lines.join('\n');
};

/**
 * Compose the Markdown block that pre-fills the bug form's "Troubleshoot agent
 * output" field, including a redaction reminder and the captured findings.
 */
const buildTroubleshootField = (doc: DocumentContext): string => {
  const parts: string[] = [];
  const meta: string[] = [];
  if (doc.objectKey) meta.push(`- Document: ${doc.objectKey}`);
  if (doc.objectStatus) meta.push(`- Status: ${doc.objectStatus}`);
  if (doc.configVersion) meta.push(`- Config version: ${doc.configVersion}`);
  if (doc.executionArn) meta.push(`- Execution ARN: ${doc.executionArn}`);
  if (meta.length) parts.push(meta.join('\n'));
  if (doc.jobError) parts.push(`Job error:\n\n\`\`\`\n${doc.jobError}\n\`\`\``);
  if (doc.findings) parts.push(`Findings:\n\n${doc.findings}`);
  return parts.join('\n\n');
};

// GitHub rejects/ truncates extremely long URLs. Keep the whole URL well under
// the ~8 KB practical ceiling by capping the largest single field.
const MAX_FIELD_CHARS = 6000;
const TRUNCATION_NOTE = '\n\n…(truncated — use "Copy full details" in the app and paste the rest here)';

const capField = (value: string): string =>
  value.length > MAX_FIELD_CHARS ? value.slice(0, MAX_FIELD_CHARS - TRUNCATION_NOTE.length) + TRUNCATION_NOTE : value;

const encode = (params: Record<string, string | undefined>): string => {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') usp.append(k, capField(v));
  });
  return usp.toString();
};

/** Build a URL for the bug-report issue form, pre-filling environment fields. */
export const buildBugReportUrl = (ctx: DeploymentContext, doc?: DocumentContext): string => {
  const params: Record<string, string | undefined> = {
    template: GITHUB_BUG_TEMPLATE,
    region: ctx.region,
    mode: toProcessingMode(ctx.pattern),
    version: buildEnvironmentSummary(ctx),
  };
  if (doc) {
    params.title = doc.objectKey ? `[Bug]: Issue processing ${doc.objectKey}` : undefined;
    params.troubleshoot = buildTroubleshootField(doc);
  }
  return `${GITHUB_NEW_ISSUE_URL}?${encode(params)}`;
};

/** Build a URL for the feature-request issue form, pre-filling environment. */
export const buildFeatureRequestUrl = (ctx: DeploymentContext): string => {
  const params: Record<string, string | undefined> = {
    template: GITHUB_FEATURE_TEMPLATE,
    version: buildEnvironmentSummary(ctx),
  };
  return `${GITHUB_NEW_ISSUE_URL}?${encode(params)}`;
};

/**
 * Plain-text block for the "Copy full details" affordance on the troubleshoot
 * flow — includes everything (environment + document + full findings), since
 * the URL-based prefill is length-capped.
 */
export const buildFullDetailsText = (ctx: DeploymentContext, doc: DocumentContext): string => {
  const sections: string[] = [];
  sections.push(
    [
      '## Environment',
      buildEnvironmentSummary(ctx),
      ctx.region ? `Region: ${ctx.region}` : '',
      `Processing mode: ${toProcessingMode(ctx.pattern)}`,
    ]
      .filter(Boolean)
      .join('\n'),
  );
  const docBlock = buildTroubleshootField(doc);
  if (docBlock) sections.push(`## Troubleshoot agent output\n${docBlock}`);
  sections.push('> ⚠️ Please review and redact any sensitive document data before submitting.');
  return sections.join('\n\n');
};
