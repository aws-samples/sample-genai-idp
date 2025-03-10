// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { Redirect, Route, Switch } from 'react-router-dom';

import { Authenticator } from '@aws-amplify/ui-react';

import { LOGIN_PATH, LOGOUT_PATH, REDIRECT_URL_PARAM } from './constants';

// this is set at build time depending on the AllowedSignUpEmailDomain CloudFormation parameter
const { REACT_APP_SHOULD_HIDE_SIGN_UP = 'true' } = process.env;

const AuthHeader = () => (
  <h1 style={{ textAlign: 'center', margin: '2rem 0' }}>Welcome to GenAI Intelligent Document Processing!</h1>
);

const UnauthRoutes = ({ location }) => (
  <Switch>
    <Route path={LOGIN_PATH}>
      <Authenticator
        initialState="signIn"
        components={{
          Header: AuthHeader,
        }}
        services={{
          async validateCustomSignUp(formData) {
            if (formData.email) {
              return undefined;
            }
            return {
              email: 'Email is required',
            };
          },
        }}
        signUpAttributes={['email']}
        hideSignUp={REACT_APP_SHOULD_HIDE_SIGN_UP === 'true'}
      />
    </Route>
    <Route path={LOGOUT_PATH}>
      <Redirect to={LOGIN_PATH} />
    </Route>
    <Route>
      <Redirect
        to={{
          pathname: LOGIN_PATH,
          search: `?${REDIRECT_URL_PARAM}=${location.pathname}${location.search}`,
        }}
      />
    </Route>
  </Switch>
);

UnauthRoutes.propTypes = {
  location: PropTypes.shape({
    pathname: PropTypes.string,
    search: PropTypes.string,
  }).isRequired,
};

export default UnauthRoutes;
