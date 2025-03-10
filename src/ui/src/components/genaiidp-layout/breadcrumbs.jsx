// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Switch, useRouteMatch } from 'react-router-dom';

import DocumentListBreadCrumbs from '../document-list/breadcrumbs';
import DocumentDetailsBreadCrumbs from '../document-details/breadcrumbs';
import ConfigurationBreadCrumbs from '../configuration-layout/breadcrumbs';
import UploadDocumentBreadCrumbs from '../upload-document/breadcrumbs';
import { UPLOAD_DOCUMENT_PATH } from '../../routes/constants';

const Breadcrumbs = () => {
  const { path } = useRouteMatch();

  return (
    <Switch>
      <Route exact path={path}>
        <DocumentListBreadCrumbs />
      </Route>
      <Route path={`${path}/config`}>
        <ConfigurationBreadCrumbs />
      </Route>
      <Route path={UPLOAD_DOCUMENT_PATH}>
        <UploadDocumentBreadCrumbs />
      </Route>
      <Route path={`${path}/:objectKey`}>
        <DocumentDetailsBreadCrumbs />
      </Route>
    </Switch>
  );
};

export default Breadcrumbs;
