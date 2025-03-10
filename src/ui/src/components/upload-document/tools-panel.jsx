// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel } from '@awsui/components-react';

const header = <h2>Upload Documents</h2>;
const content = (
  <>
    <p>Upload documents to be processed by the GenAI IDP system.</p>
    <p>
      <strong>Supported formats:</strong> PDF, PNG, JPEG, TIFF, and other document formats supported by Textract.
    </p>
    <p>
      <strong>Prefix:</strong> Optionally add a prefix to organize your documents (e.g., &quot;invoices/&quot;,
      &quot;forms/2023/&quot;).
    </p>
    <p>
      After upload, documents will be automatically added to the processing queue and will appear in the Documents list
      when processing begins.
    </p>
  </>
);

const ToolsPanel = () => <HelpPanel header={header}>{content}</HelpPanel>;

export default ToolsPanel;
