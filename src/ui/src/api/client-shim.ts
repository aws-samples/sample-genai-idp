// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// GraphQL-shaped client used across the UI. AWS AppSync has been removed; the
// app talks to an API Gateway HTTP API via the thin REST client. Call sites
// keep the historical shape:
//
//   import { generateClient } from '../api/client-shim';
//   const client = generateClient();
//   await client.graphql({ query, variables });
//
// `graphql()` POSTs queries/mutations to ${VITE_API_BASE_URL}/op/<field>;
// subscriptions are replaced by polling (see use-polling.ts) and the streaming
// chat client (stream-client.ts). Amplify is still used for Cognito auth only.
import { createRestClient } from './rest-client';

// Returns the REST client typed with the same `.graphql()` overloads the app
// used from the Amplify client, so call sites keep full result-type inference.
export const generateClient = () => createRestClient();

export default generateClient;
