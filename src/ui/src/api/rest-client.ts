// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Thin REST client that replaces AWS AppSync (GraphQL over Amplify) for
// UI<->backend queries and mutations. AppSync is unavailable in GovCloud and
// not FedRAMP-compliant; this client talks to an API Gateway HTTP API instead.
//
// It deliberately mimics the small slice of the Amplify `generateClient()` API
// the app uses, so call sites stay unchanged:
//
//   const client = generateClient();
//   const res = await client.graphql({ query: listDocuments, variables });
//   res.data.listDocuments  // <- same shape as Amplify returns
//
// Queries/mutations are POSTed to `${apiBaseUrl}/op/<fieldName>` with the
// Cognito id token as the Authorization header. The HTTP API JWT authorizer
// validates the token; the dispatcher Lambda routes by field name.
//
// Subscriptions have no transport here (the HTTP API uses polling instead).
// `graphql()` on a subscription returns an inert subscription object so any
// not-yet-migrated call site fails safe (logs once) rather than throwing.
import { fetchAuthSession } from 'aws-amplify/auth';
import { ConsoleLogger } from 'aws-amplify/utils';

import { apiBaseUrl } from '../aws-exports';

const logger = new ConsoleLogger('restClient');

// Match the operation kind + field name from a generated GraphQL op string.
//   "  query ListDocuments($x: Int) {\n  listDocuments(...) { ... } }"
// -> kind = "query", field = "listDocuments"
const OP_RE = /\b(query|mutation|subscription)\s+\w+\s*(?:\([^)]*\))?\s*\{\s*([A-Za-z_][A-Za-z0-9_]*)/;

const fieldCache = new Map<string, { kind: string; field: string }>();

interface ParsedOp {
  kind: string;
  field: string;
}

const parseOperation = (query: string): ParsedOp => {
  const cached = fieldCache.get(query);
  if (cached) return cached;
  const m = OP_RE.exec(query);
  if (!m) {
    throw new Error('restClient: could not parse operation from query string');
  }
  const parsed = { kind: m[1], field: m[2] };
  fieldCache.set(query, parsed);
  return parsed;
};

const getIdToken = async (): Promise<string> => {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) {
    throw new Error('restClient: no Cognito id token available');
  }
  return token;
};

// Shape returned to callers — mirrors Amplify's { data, errors }.
interface GraphqlResult<T = unknown> {
  data: T;
  errors?: { message?: string; errorType?: string }[];
}

interface GraphqlRequest {
  query: string;
  variables?: Record<string, unknown>;
  authMode?: string;
}

// Inert subscription returned for subscription operations (polling replaces
// real-time push under the HTTP API transport).
const inertSubscription = (field: string) => ({
  subscribe: () => {
    logger.warn(`restClient: subscription '${field}' is a no-op under httpapi transport (use polling)`);
    return { unsubscribe: () => {} };
  },
});

const doGraphql = async ({ query, variables }: GraphqlRequest): Promise<GraphqlResult> => {
  const { kind, field } = parseOperation(query);

  if (kind === 'subscription') {
    return inertSubscription(field) as unknown as GraphqlResult;
  }

  if (!apiBaseUrl) {
    throw new Error('restClient: VITE_API_BASE_URL is not configured');
  }

  const token = await getIdToken();
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/op/${field}`, {
      method: 'POST',
      headers: {
        Authorization: token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ arguments: variables ?? {} }),
    });
  } catch (e) {
    // Network error — surface in the same { errors: [...] } shape callers parse.
    const message = e instanceof Error ? e.message : String(e);
    throw { errors: [{ message, errorType: 'NetworkError' }] };
  }

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    // Dispatcher returns { errors: [{ message, errorType }] }; pass it through
    // so existing error handling (gqlError.errors[0]) keeps working.
    if (body && typeof body === 'object' && 'errors' in body) {
      throw body;
    }
    throw {
      errors: [{ message: `Request failed (${response.status})`, errorType: 'HttpError' }],
    };
  }

  // Success: wrap under the field name to match Amplify's res.data.<field>.
  return { data: { [field]: body } };
};

// The object returned by our generateClient() replacement. Only `.graphql()`
// is implemented because that is all the app uses from the Amplify client.
export interface RestGraphqlClient {
  graphql: (req: GraphqlRequest) => Promise<GraphqlResult>;
}

export const createRestClient = (): RestGraphqlClient => ({
  graphql: doGraphql,
});

export default createRestClient;
