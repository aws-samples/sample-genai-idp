// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Extracts the human-readable Markdown findings text from a Troubleshoot agent
 * job result so it can be pre-filled into a GitHub issue. Mirrors the parsing
 * that AgentResultDisplay does for the `text` responseType: the result may be a
 * double-encoded JSON string and/or wrapped in a `.result` property (from
 * DynamoDB), and the text lives in `textData.content` or `content`.
 *
 * Returns an empty string when the result is missing or is a non-text response
 * (e.g. a plot or table), in which case callers should omit the findings block.
 */
const safeJsonParse = (data: unknown): unknown => {
  if (data === null || data === undefined) return data;
  if (typeof data === 'object') return data;
  if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data);
      if (typeof parsed === 'string') {
        try {
          return JSON.parse(parsed);
        } catch {
          return parsed;
        }
      }
      return parsed;
    } catch {
      return data;
    }
  }
  return data;
};

export const extractFindingsText = (result: string | Record<string, unknown> | null | undefined): string => {
  if (!result) return '';

  let parsed = safeJsonParse(result) as Record<string, unknown> | string;

  if (parsed && typeof parsed === 'object' && 'result' in parsed && parsed.result) {
    parsed = safeJsonParse(parsed.result) as Record<string, unknown> | string;
  }

  // Plain string result — treat as the findings text directly.
  if (typeof parsed === 'string') return parsed.trim();

  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>;
    // Only surface text responses; plots/tables have no meaningful text body.
    if (obj.responseType && obj.responseType !== 'text') return '';
    const textData = (obj.textData || obj) as Record<string, unknown>;
    const content = textData.content;
    if (typeof content === 'string') return content.trim();
  }

  return '';
};

export default extractFindingsText;
