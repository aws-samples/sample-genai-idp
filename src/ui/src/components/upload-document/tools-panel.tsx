// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel } from '@cloudscape-design/components';
import { SUPPORTED_UPLOAD_FORMATS_LABEL } from '../common/constants';

const header = <h2>Upload Documents</h2>;
const content = (
  <>
    <p>Upload documents to be processed by the GenAI IDP system.</p>
    <p>{SUPPORTED_UPLOAD_FORMATS_LABEL}</p>
    <p>
      <strong>Prefix:</strong> Optionally add a prefix to organize your documents (e.g., &quot;invoices/&quot;, &quot;forms/2023/&quot;).
    </p>
    <p>
      After upload, documents will be automatically added to the processing queue and will appear in the Documents list when processing
      begins.
    </p>
  </>
);

const ToolsPanel = (): React.JSX.Element => <HelpPanel header={header}>{content}</HelpPanel>;

export default ToolsPanel;
