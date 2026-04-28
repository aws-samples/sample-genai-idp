/**
 * IDPMonitor — Minimal AppSync HTTP client
 *
 * Sends a GraphQL query to an AppSync endpoint using either:
 *   - API_KEY auth (x-api-key header) — dev/testing default
 *   - IAM auth (AWS Signature v4) — not yet implemented, use Amplify for this
 *
 * This is a thin wrapper that avoids pulling Apollo Client / Amplify as a
 * hard dependency of the library build. Host apps that already use Apollo
 * can ignore this and use their own client — just use the exported query
 * strings directly from '../graphql/queries'.
 *
 * Usage:
 *   const data = await fetchAppSync<{ getMonitoringStatus: ... }>({
 *     url: 'https://<id>.appsync-api.<region>.amazonaws.com/graphql',
 *     apiKey: 'da2-xxxxx',
 *     query: GET_MONITORING_STATUS,
 *     variables: {},
 *   });
 */

export interface FetchAppSyncOptions {
  /** AppSync GraphQL endpoint URL */
  url: string;
  /** AppSync API Key (x-api-key auth). Leave empty to use Cognito JWT from Authorization header. */
  apiKey?: string;
  /** Cognito JWT access token (Authorization: Bearer). Used when apiKey is not provided. */
  accessToken?: string;
  /** GraphQL query string */
  query: string;
  /** GraphQL variables */
  variables?: Record<string, unknown>;
}

export class AppSyncError extends Error {
  public readonly errors: Array<{ message: string; errorType?: string }>;

  constructor(errors: Array<{ message: string; errorType?: string }>) {
    super(errors.map((e) => e.message).join('; '));
    this.name = 'AppSyncError';
    this.errors = errors;
  }
}

/**
 * Execute a GraphQL query against an AppSync endpoint.
 * Returns the `data` field from the response.
 * Throws AppSyncError if the response contains errors.
 */
export async function fetchAppSync<TData = unknown>(
  opts: FetchAppSyncOptions,
): Promise<TData> {
  const { url, apiKey, accessToken, query, variables = {} } = opts;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (apiKey) {
    headers['x-api-key'] = apiKey;
  } else if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query, variables }),
  });

  if (!response.ok) {
    throw new Error(
      `AppSync request failed: HTTP ${response.status} ${response.statusText}`,
    );
  }

  const json = (await response.json()) as {
    data?: TData;
    errors?: Array<{ message: string; errorType?: string }>;
  };

  if (json.errors && json.errors.length > 0) {
    throw new AppSyncError(json.errors);
  }

  if (!json.data) {
    throw new Error('AppSync response contained no data field');
  }

  return json.data;
}
