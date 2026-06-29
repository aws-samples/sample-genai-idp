// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Transport shim for the GraphQL client. The app historically did:
//
//   import { generateClient } from 'aws-amplify/api';
//   const client = generateClient();
//
// To support replacing AppSync with an API Gateway HTTP API (for GovCloud /
// FedRAMP), call sites now import `generateClient` from THIS module instead.
// Behavior is selected at build time by VITE_API_TRANSPORT:
//
//   - 'appsync' (default): returns the real Amplify GraphQL client (unchanged).
//   - 'httpapi':           returns the thin REST client (POST /op/<field>),
//                          with subscriptions handled via polling elsewhere.
//
// Keeping the same `generateClient()` call shape means the ~50 call sites only
// change their import path, not their code.
import { generateClient as amplifyGenerateClient } from 'aws-amplify/api';

import { apiTransport } from '../aws-exports';
import { createRestClient } from './rest-client';

// Returns the Amplify GraphQL client under the default (appsync) transport, or
// the thin REST client under httpapi. The return type is inferred from the
// appsync branch so call sites keep full type inference (e.g. subscription
// `next` callbacks). The REST client implements the slice of the interface the
// app uses and is cast to that type at this boundary.
//
// NB: we intentionally do NOT annotate the return type with
// `ReturnType<typeof amplifyGenerateClient>` — that named alias triggers a
// TS2321 "excessive stack depth" error against Amplify's deeply-generic client
// type. Letting the appsync branch drive inference avoids the deep comparison.
export const generateClient = (...args: Parameters<typeof amplifyGenerateClient>) => {
  // Amplify's generateClient() only constructs a client object — it does not
  // connect or validate the AppSync endpoint until .graphql() is called. So we
  // can safely construct it in both modes; its value-derived type drives the
  // function's inferred return type, keeping full call-site typing (incl.
  // subscription `next` callbacks) without naming Amplify's deeply-generic
  // client type (which triggers TS2321). Under httpapi we return the REST
  // client at runtime instead, cast to the same type at this boundary.
  const amplifyClient = amplifyGenerateClient(...args);
  if (apiTransport === 'httpapi') {
    return createRestClient() as unknown as typeof amplifyClient;
  }
  return amplifyClient;
};

export default generateClient;
