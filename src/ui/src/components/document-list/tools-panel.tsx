// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel, Icon } from '@cloudscape-design/components';

const DOCS_BASE_URL = 'https://aws-solutions-library-samples.github.io/accelerated-intelligent-document-processing-on-aws';

const ToolsPanel = (): React.JSX.Element => (
  <HelpPanel
    header={<h2>Documents</h2>}
    footer={
      <div>
        <h3>
          Learn more <Icon name="external" />
        </h3>
        <ul>
          <li>
            <a href={`${DOCS_BASE_URL}/web-ui/`} target="_blank" rel="noopener noreferrer">
              Web UI
            </a>
          </li>
          <li>
            <a href={`${DOCS_BASE_URL}/human-review/`} target="_blank" rel="noopener noreferrer">
              Human Review
            </a>
          </li>
          <li>
            <a href={`${DOCS_BASE_URL}/monitoring/`} target="_blank" rel="noopener noreferrer">
              Monitoring
            </a>
          </li>
          <li>
            <a href={`${DOCS_BASE_URL}/circuit-breaker/`} target="_blank" rel="noopener noreferrer">
              Circuit Breaker
            </a>
          </li>
        </ul>
      </div>
    }
  >
    <div>
      <p>Track, search, filter, and manage all documents processed by the IDP system.</p>
      <h3>Features</h3>
      <ul>
        <li>View document processing status, classification, and confidence scores</li>
        <li>Filter by date range, status, document type, or any field using the search bar</li>
        <li>Select documents to reprocess, delete, or abort active workflows</li>
        <li>Claim or release documents for human review</li>
        <li>Export filtered results to Excel for offline analysis</li>
        <li>Drill down into individual documents for detailed inspection</li>
        <li>Monitor the circuit breaker status and (admins only) pause, resume, or probe document processing</li>
      </ul>
    </div>
  </HelpPanel>
);

export default ToolsPanel;
