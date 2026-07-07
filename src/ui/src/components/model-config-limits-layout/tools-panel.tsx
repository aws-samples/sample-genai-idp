// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel } from '@cloudscape-design/components';

const ToolsPanel = (): React.JSX.Element => (
  <HelpPanel header={<h2>Model Limits</h2>}>
    <div>
      <p>View and manage per-model token limits used when invoking Amazon Bedrock models.</p>
      <h3>Features</h3>
      <ul>
        <li>View the ordered list of model ID patterns and their max output/input token limits</li>
        <li>Edit limits, reorder entries, or add patterns for new models (Admin only)</li>
        <li>Edit the configuration in YAML or JSON using the built-in code editor</li>
        <li>Import and export the limit list as YAML or JSON files</li>
      </ul>
      <h3>How matching works</h3>
      <ul>
        <li>Each entry&apos;s pattern is a case-insensitive regular expression matched against the Bedrock model ID</li>
        <li>
          Entries are evaluated top to bottom — the <strong>first matching pattern wins</strong>
        </li>
        <li>Keep more specific patterns (e.g., long-context variants) above broader ones</li>
      </ul>
      <h3>Test a model ID</h3>
      <ul>
        <li>
          Use <strong>Test a model ID</strong> to check which entry a Bedrock model ID resolves to — pick a known model or type any ID,
          including future/unlisted ones
        </li>
        <li>It applies the same first-match logic as the runtime against the current (unsaved) list, and flags invalid patterns</li>
      </ul>
      <h3>Notes</h3>
      <ul>
        <li>Each pattern must be a valid regular expression, or the save is rejected</li>
        <li>
          Saving an <strong>empty list</strong> (deleting all rows) does not disable limits — it falls back to the built-in defaults, the
          same as &ldquo;Restore Defaults&rdquo;
        </li>
      </ul>
      <p>Saved changes are picked up by running document-processing workers within about a minute.</p>
    </div>
  </HelpPanel>
);

export default ToolsPanel;
