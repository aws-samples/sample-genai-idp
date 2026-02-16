// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { Authenticator } from '@aws-amplify/ui-react';

import { LOGIN_PATH, LOGOUT_PATH, REDIRECT_URL_PARAM } from './constants';

// this is set at build time depending on the AllowedSignUpEmailDomain CloudFormation parameter
const VITE_SHOULD_HIDE_SIGN_UP = import.meta.env.VITE_SHOULD_HIDE_SIGN_UP ?? 'true';

const AuthHeader = (): React.JSX.Element => (
  <h1 style={{ textAlign: 'center', margin: '2rem 0' }}>Welcome to GenAI Intelligent Document Processing!</h1>
);

interface UnauthRoutesProps {
  location: {
    pathname: string;
    search: string;
  };
}

const UnauthRoutes = ({ location }: UnauthRoutesProps): React.JSX.Element => (
  <Routes>
    <Route
      path={LOGIN_PATH}
      element={
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
          hideSignUp={VITE_SHOULD_HIDE_SIGN_UP === 'true'}
        />
      }
    />
    <Route path={LOGOUT_PATH} element={<Navigate to={LOGIN_PATH} replace />} />
    <Route
      path="*"
      element={
        <Navigate
          to={{
            pathname: LOGIN_PATH,
            search: `?${REDIRECT_URL_PARAM}=${location.pathname}${location.search}`,
          }}
          replace
        />
      }
    />
  </Routes>
);

export default UnauthRoutes;
