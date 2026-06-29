/* eslint-disable */
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// The values in this file are generated in CodeBuild
// You can also create a .env.local file during development
// https://create-react-app.dev/docs/adding-custom-environment-variables/

const {
  VITE_USER_POOL_ID,
  VITE_USER_POOL_CLIENT_ID,
  VITE_IDENTITY_POOL_ID,
  VITE_APPSYNC_GRAPHQL_URL,
  // API transport selection ('appsync' | 'httpapi') and the HTTP API / Lambda
  // streaming endpoints. Populated when ApiTransport=httpapi; the thin REST
  // client (src/api/) reads these. Empty/undefined when using AppSync.
  VITE_API_TRANSPORT,
  VITE_API_BASE_URL,
  VITE_STREAM_URL,
  VITE_AWS_REGION,
  VITE_COGNITO_DOMAIN,
  VITE_EXTERNAL_IDP_NAME,
  VITE_EXTERNAL_IDP_AUTO_LOGIN,
  VITE_CLOUDFRONT_DOMAIN,
} = import.meta.env;

// Transport mode for UI<->backend communication. 'httpapi' routes
// queries/mutations through the thin REST client and uses polling + Lambda
// streaming; anything else (default) uses AppSync GraphQL via Amplify.
export const apiTransport = VITE_API_TRANSPORT || 'appsync';
export const apiBaseUrl = VITE_API_BASE_URL || '';
export const streamUrl = VITE_STREAM_URL || '';
export const awsRegion = VITE_AWS_REGION;

// Build OAuth config only when an external IdP is configured.
// Cognito matches redirect_uri case-sensitively against its registered
// callback/logout URLs, but browsers normalize the host portion of a URL
// to lowercase. Lowercasing the full URL keeps Amplify's request aligned
// with what the browser actually presents (ALB DNS names embed the stack
// name and can otherwise be mixed-case).
const redirectUrl = (VITE_CLOUDFRONT_DOMAIN || window.location.origin + '/').toLowerCase();
const oauthConfig =
  VITE_EXTERNAL_IDP_NAME && VITE_COGNITO_DOMAIN
    ? {
        domain: VITE_COGNITO_DOMAIN,
        scope: ['openid', 'email', 'phone', 'profile'],
        redirectSignIn: redirectUrl,
        redirectSignOut: redirectUrl,
        responseType: 'code',
      }
    : {};

const awsmobile = {
  aws_project_region: VITE_AWS_REGION,
  aws_cognito_identity_pool_id: VITE_IDENTITY_POOL_ID,
  aws_cognito_region: VITE_AWS_REGION,
  aws_user_pools_id: VITE_USER_POOL_ID,
  aws_user_pools_web_client_id: VITE_USER_POOL_CLIENT_ID,
  oauth: oauthConfig,
  aws_cognito_login_mechanisms: ['PREFERRED_USERNAME'],
  aws_cognito_signup_attributes: ['EMAIL'],
  aws_cognito_mfa_configuration: 'OFF',
  aws_cognito_mfa_types: ['SMS'],
  aws_cognito_password_protection_settings: {
    passwordPolicyMinLength: 8,
    passwordPolicyCharacters: [],
  },
  aws_cognito_verification_mechanisms: ['EMAIL'],
  aws_appsync_graphqlEndpoint: VITE_APPSYNC_GRAPHQL_URL,
  aws_appsync_region: VITE_AWS_REGION,
  aws_appsync_authenticationType: 'AMAZON_COGNITO_USER_POOLS',
};

export default awsmobile;
