// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Extract a human-readable error message from whatever shape Amplify / AppSync
 * threw at us.
 *
 * Amplify's GraphQL client throws an object like:
 *
 *   { errors: [
 *       { message: "Not Authorized to access subscribeFeature on type Mutation",
 *         path: ["subscribeFeature"],
 *         ... },
 *       ...
 *     ],
 *     data: null,
 *   }
 *
 * Passing that through `String(e)` or `new Error(String(e))` yields the
 * useless string `"[object Object]"`, which is what users saw in red error
 * banners. This helper drills into the common shapes and returns a sensible
 * multi-line message; falls back to `JSON.stringify` as a last resort so the
 * UI never shows `[object Object]` again.
 */
export function extractGraphQLErrorMessage(err: unknown): string {
  // Native Error or anything with a usable .message
  if (err instanceof Error && err.message) {
    return err.message;
  }

  if (typeof err === 'string') {
    return err;
  }

  if (err && typeof err === 'object') {
    const anyErr = err as {
      errors?: Array<{ message?: string; errorType?: string; path?: unknown[] }>;
      message?: string;
    };

    // Amplify GraphQL error envelope — most common path.
    if (Array.isArray(anyErr.errors) && anyErr.errors.length > 0) {
      const messages = anyErr.errors.map((e) => e?.message).filter((m): m is string => typeof m === 'string' && m.length > 0);
      if (messages.length > 0) {
        return messages.join('\n');
      }
    }

    // Single-message fallback (e.g., a plain { message: '...' }).
    if (typeof anyErr.message === 'string' && anyErr.message.length > 0) {
      return anyErr.message;
    }

    // Last-resort JSON so the UI at least shows the shape rather than "[object Object]".
    try {
      return JSON.stringify(err);
    } catch {
      /* fall through */
    }
  }

  return 'Unknown error';
}
