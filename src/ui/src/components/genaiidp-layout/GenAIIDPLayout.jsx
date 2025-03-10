// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Switch, Route, useRouteMatch } from 'react-router-dom';
import { AppLayout, Flashbar } from '@awsui/components-react';

import { Logger } from 'aws-amplify';

import { DocumentsContext } from '../../contexts/documents';

import useNotifications from '../../hooks/use-notifications';
import useSplitPanel from '../../hooks/use-split-panel';
import useGraphQlApi from '../../hooks/use-graphql-api';

import DocumentList from '../document-list';
import DocumentDetails from '../document-details';
import DocumentsQueryLayout from '../document-kb-query-layout';
import UploadDocumentPanel from '../upload-document';
import { appLayoutLabels } from '../common/labels';

import Navigation from './navigation';
import Breadcrumbs from './breadcrumbs';
import ToolsPanel from './tools-panel';
import SplitPanel from './documents-split-panel';
import ConfigurationLayout from '../configuration-layout';

import { DOCUMENT_LIST_SHARDS_PER_DAY, PERIODS_TO_LOAD_STORAGE_KEY } from '../document-list/documents-table-config';
import { UPLOAD_DOCUMENT_PATH } from '../../routes/constants';

import useAppContext from '../../contexts/app';

const logger = new Logger('GenAIIDPLayout');

const GenAIIDPLayout = () => {
  const { navigationOpen, setNavigationOpen } = useAppContext();

  const { path } = useRouteMatch();
  logger.debug('path', path);

  const notifications = useNotifications();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);

  const getInitialPeriodsToLoad = () => {
    // default to 2 hours - half of one (4hr) shard period
    let periods = 0.5;
    try {
      const periodsFromStorage = Math.abs(JSON.parse(localStorage.getItem(PERIODS_TO_LOAD_STORAGE_KEY)));
      // prettier-ignore
      if (
        !Number.isFinite(periodsFromStorage)
        // load max of to 30 days
        || periodsFromStorage > DOCUMENT_LIST_SHARDS_PER_DAY * 30
      ) {
        logger.warn('invalid initialPeriodsToLoad value from local storage');
      } else {
        periods = (periodsFromStorage > 0) ? periodsFromStorage : periods;
        localStorage.setItem(PERIODS_TO_LOAD_STORAGE_KEY, JSON.stringify(periods));
      }
    } catch {
      logger.warn('failed to parse initialPeriodsToLoad from local storage');
    }

    return periods;
  };
  const initialPeriodsToLoad = getInitialPeriodsToLoad();

  const {
    documents,
    getDocumentDetailsFromIds,
    isDocumentsListLoading,
    periodsToLoad,
    setIsDocumentsListLoading,
    setPeriodsToLoad,
    deleteDocuments,
  } = useGraphQlApi({ initialPeriodsToLoad });

  // eslint-disable-next-line prettier/prettier
  const {
    splitPanelOpen,
    onSplitPanelToggle,
    splitPanelSize,
    onSplitPanelResize,
  } = useSplitPanel(selectedItems);

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const documentsContextValue = {
    documents,
    getDocumentDetailsFromIds,
    isDocumentsListLoading,
    selectedItems,
    setIsDocumentsListLoading,
    setPeriodsToLoad,
    setToolsOpen,
    setSelectedItems,
    periodsToLoad,
    toolsOpen,
    deleteDocuments,
  };

  return (
    <DocumentsContext.Provider value={documentsContextValue}>
      <AppLayout
        headerSelector="#top-navigation"
        navigation={<Navigation />}
        navigationOpen={navigationOpen}
        onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
        breadcrumbs={<Breadcrumbs />}
        notifications={<Flashbar items={notifications} />}
        tools={<ToolsPanel />}
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
        splitPanelOpen={splitPanelOpen}
        onSplitPanelToggle={onSplitPanelToggle}
        splitPanelSize={splitPanelSize}
        onSplitPanelResize={onSplitPanelResize}
        splitPanel={<SplitPanel />}
        content={
          <Switch>
            <Route exact path={path}>
              <DocumentList />
            </Route>
            <Route path={`${path}/query`}>
              <DocumentsQueryLayout />
            </Route>
            <Route path={`${path}/config`}>
              <ConfigurationLayout />
            </Route>
            <Route path={UPLOAD_DOCUMENT_PATH}>
              <UploadDocumentPanel />
            </Route>
            <Route path={`${path}/:objectKey`}>
              <DocumentDetails />
            </Route>
          </Switch>
        }
        ariaLabels={appLayoutLabels}
      />
    </DocumentsContext.Provider>
  );
};

export default GenAIIDPLayout;
