// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { SplitPanel } from '@cloudscape-design/components';

import useDocumentsContext from '../../contexts/documents';

import { getPanelContent, SPLIT_PANEL_I18NSTRINGS } from './documents-split-panel-config';
import type { MappedDocument } from './documents-table-config';

import '@cloudscape-design/global-styles/index.css';

const DocumentListSplitPanel = (): React.JSX.Element => {
  const { selectedItems, setToolsOpen, getDocumentDetailsFromIds } = useDocumentsContext();

  const { header: panelHeader, body: panelBody } = getPanelContent(
    selectedItems as unknown as MappedDocument[],
    'multiple',
    setToolsOpen as (open: boolean) => void,
    getDocumentDetailsFromIds as (ids: string[]) => Promise<unknown>,
  );

  return (
    <SplitPanel header={panelHeader} i18nStrings={SPLIT_PANEL_I18NSTRINGS}>
      {panelBody}
    </SplitPanel>
  );
};

export default DocumentListSplitPanel;
