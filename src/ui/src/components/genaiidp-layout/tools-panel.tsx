// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes } from 'react-router-dom';

import DocumentListToolsPanel from '../document-list/tools-panel';
import DocumentDetailsToolsPanel from '../document-details/tools-panel';
import ConfigurationToolsPanel from '../configuration-layout/tools-panel';
import UploadDocumentToolsPanel from '../upload-document/tools-panel';
import DocumentsQueryToolsPanel from '../document-kb-query-layout/tools-panel';

const ToolsPanel = (): React.JSX.Element => {
  return (
    <Routes>
      <Route index element={<DocumentListToolsPanel />} />
      <Route path="config" element={<ConfigurationToolsPanel />} />
      <Route path="upload" element={<UploadDocumentToolsPanel />} />
      <Route path="query" element={<DocumentsQueryToolsPanel />} />
      <Route path=":objectKey" element={<DocumentDetailsToolsPanel />} />
    </Routes>
  );
};

export default ToolsPanel;
