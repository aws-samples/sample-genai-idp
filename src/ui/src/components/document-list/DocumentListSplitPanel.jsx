// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { SplitPanel } from '@awsui/components-react';

import useDocumentsContext from '../../contexts/documents';

import { getPanelContent, SPLIT_PANEL_I18NSTRINGS } from './documents-split-panel-config';

import '@awsui/global-styles/index.css';

const DocumentListSplitPanel = () => {
  const { selectedItems, setToolsOpen, getDocumentDetailsFromIds } = useDocumentsContext();

  const { header: panelHeader, body: panelBody } = getPanelContent(
    selectedItems,
    'multiple',
    setToolsOpen,
    getDocumentDetailsFromIds,
  );

  return (
    <SplitPanel header={panelHeader} i18nStrings={SPLIT_PANEL_I18NSTRINGS}>
      {panelBody}
    </SplitPanel>
  );
};

export default DocumentListSplitPanel;
