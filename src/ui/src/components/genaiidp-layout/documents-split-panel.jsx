// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { Logger } from 'aws-amplify';

import { DOCUMENTS_PATH } from '../../routes/constants';

import DocumentListSplitPanel from '../document-list/DocumentListSplitPanel';

const logger = new Logger('CallsSplitPanel');

const CallsSplitPanel = () => {
  const { path } = useRouteMatch();
  logger.debug('path', path);
  return (
    <Switch>
      <Route exact path={DOCUMENTS_PATH}>
        <DocumentListSplitPanel />
      </Route>
    </Switch>
  );
};

export default CallsSplitPanel;
