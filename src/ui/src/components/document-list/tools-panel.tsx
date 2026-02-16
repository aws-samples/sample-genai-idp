// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { HelpPanel } from '@cloudscape-design/components';

const header = <h2>Documents</h2>;
const content = (
  <>
    <p>View a list of documents and related information.</p>
    <p>Use the search bar to filter on any field.</p>
    <p>To drill down even further into the details, select an individual document.</p>
  </>
);

const ToolsPanel = (): React.JSX.Element => <HelpPanel header={header}>{content}</HelpPanel>;

export default ToolsPanel;
