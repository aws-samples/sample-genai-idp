// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel } from '@awsui/components-react';

const header = <h2>Document Knowledge Base Query</h2>;
const content = (
  <>
    <p>The Document Knowledge Base Query Tool allows you to query your document collection using natural language.</p>
    <p>
      <strong>Features:</strong>
    </p>
    <ul>
      <li>Ask questions about documents in your knowledge base</li>
      <li>Get responses with citations to source documents</li>
      <li>Follow document links to view original source material</li>
    </ul>
    <p>
      <strong>Tips:</strong>
    </p>
    <ul>
      <li>Be specific in your questions to get more accurate answers</li>
      <li>Questions are context-aware - you can ask follow-up questions</li>
      <li>Results are based on indexed document content</li>
    </ul>
  </>
);

const ToolsPanel = () => <HelpPanel header={header}>{content}</HelpPanel>;

export default ToolsPanel;
