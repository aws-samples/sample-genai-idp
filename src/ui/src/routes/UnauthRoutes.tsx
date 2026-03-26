// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { Authenticator } from '@aws-amplify/ui-react';
import { signInWithRedirect } from 'aws-amplify/auth';

import { LOGIN_PATH, LOGOUT_PATH, REDIRECT_URL_PARAM } from './constants';

// this is set at build time depending on the AllowedSignUpEmailDomain CloudFormation parameter
const VITE_SHOULD_HIDE_SIGN_UP = import.meta.env.VITE_SHOULD_HIDE_SIGN_UP ?? 'true';
const VITE_EXTERNAL_IDP_NAME = import.meta.env.VITE_EXTERNAL_IDP_NAME ?? '';
const VITE_EXTERNAL_IDP_AUTO_LOGIN = import.meta.env.VITE_EXTERNAL_IDP_AUTO_LOGIN ?? 'false';

// Track whether auto-login redirect has been attempted to prevent loops
let autoLoginAttempted = false;

const AuthHeader = (): React.JSX.Element => (
  <h1 style={{ textAlign: 'center', margin: '2rem 0' }}>Welcome to GenAI Intelligent Document Processing!</h1>
);

const FederatedSignInButton = (): React.JSX.Element | null => {
  if (!VITE_EXTERNAL_IDP_NAME) return null;

  return (
    <div style={{ textAlign: 'center', margin: '1rem 0' }}>
      <button
        type="button"
        onClick={() => signInWithRedirect({ provider: { custom: VITE_EXTERNAL_IDP_NAME } })}
        style={{
          width: '100%',
          maxWidth: '400px',
          padding: '0.75rem 1rem',
          fontSize: '1rem',
          fontWeight: 500,
          color: '#fff',
          backgroundColor: '#0073bb',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
        }}
      >
        Sign in with {VITE_EXTERNAL_IDP_NAME}
      </button>
      <div style={{ margin: '1rem 0', color: '#666', fontSize: '0.875rem' }}>— or sign in with username —</div>
    </div>
  );
};

interface UnauthRoutesProps {
  location: {
    pathname: string;
    search: string;
  };
}

const AutoLoginOrAuthenticator = (): React.JSX.Element => {
  // Check if we returned from a failed federated login attempt or user explicitly signed out
  const hasError = window.location.href.includes('error=') || window.location.href.includes('errorMessage=');
  const userSignedOut = sessionStorage.getItem('idp_signed_out') === 'true';

  // Auto-redirect to external IdP if configured, not already attempted, no error, and user didn't just sign out
  if (VITE_EXTERNAL_IDP_NAME && VITE_EXTERNAL_IDP_AUTO_LOGIN === 'true' && !autoLoginAttempted && !hasError && !userSignedOut) {
    autoLoginAttempted = true;
    signInWithRedirect({ provider: { custom: VITE_EXTERNAL_IDP_NAME } });
    return <div style={{ textAlign: 'center', margin: '4rem 0' }}>Redirecting to {VITE_EXTERNAL_IDP_NAME}...</div>;
  }

  // Clear the signed-out flag once we show the login form (user can manually click the IdP button)
  if (userSignedOut) {
    sessionStorage.removeItem('idp_signed_out');
  }

  return (
    <Authenticator
      initialState="signIn"
      components={{
        Header: () => (
          <>
            <AuthHeader />
            <FederatedSignInButton />
          </>
        ),
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
  );
};

const UnauthRoutes = ({ location }: UnauthRoutesProps): React.JSX.Element => (
  <Routes>
    <Route path={LOGIN_PATH} element={<AutoLoginOrAuthenticator />} />
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
