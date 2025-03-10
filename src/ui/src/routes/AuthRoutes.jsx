// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { Logger } from 'aws-amplify';
import { Redirect, Route, Switch } from 'react-router-dom';

import { Button, useAuthenticator } from '@aws-amplify/ui-react';

import { SettingsContext } from '../contexts/settings';
import useParameterStore from '../hooks/use-parameter-store';
import useAppContext from '../contexts/app';

import DocumentsRoutes from './DocumentsRoutes';
import DocumentsQueryRoutes from './DocumentsQueryRoutes';

import { DOCUMENTS_PATH, DEFAULT_PATH, LOGIN_PATH, LOGOUT_PATH, DOCUMENTS_KB_QUERY_PATH } from './constants';

const logger = new Logger('AuthRoutes');

const AuthRoutes = ({ redirectParam }) => {
  const { currentCredentials } = useAppContext();
  const settings = useParameterStore(currentCredentials);
  const { signOut } = useAuthenticator();

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const settingsContextValue = {
    settings,
  };
  logger.debug('settingsContextValue', settingsContextValue);

  return (
    <SettingsContext.Provider value={settingsContextValue}>
      <Switch>
        <Route path={DOCUMENTS_PATH}>
          <DocumentsRoutes />
        </Route>
        <Route path={LOGIN_PATH}>
          <Redirect to={!redirectParam || redirectParam === LOGIN_PATH ? DEFAULT_PATH : `${redirectParam}`} />
        </Route>
        <Route path={LOGOUT_PATH}>
          <Button onClick={signOut}>Sign Out</Button>
        </Route>
        <Route path={DOCUMENTS_KB_QUERY_PATH}>
          <DocumentsQueryRoutes />
        </Route>
        <Route>
          <Redirect to={DEFAULT_PATH} />
        </Route>
      </Switch>
    </SettingsContext.Provider>
  );
};

AuthRoutes.propTypes = {
  redirectParam: PropTypes.string.isRequired,
};

export default AuthRoutes;
