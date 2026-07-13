// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//
// Non-streaming chat delivery via polling — used when the Lambda Function URL
// streaming endpoint is unavailable (e.g. AWS GovCloud, where Lambda Function
// URLs do not exist, so VITE_STREAM_URL is empty).
//
// The chat processors persist ONLY the final assistant message to the
// ChatMessages table (there are no intermediate/streaming checkpoints), so this
// path gives a "spinner, then the full answer" experience rather than
// token-by-token streaming. The send-message mutation and the getChatMessages
// query both route through the existing Cognito-authed REST API (/op), so no
// Lambda Function URL is involved.
//
// Flow:
//   1. Caller sends the chat mutation (sendAgentChatMessage /
//      sendChatDocumentMessage) — this async-invokes the processor.
//   2. pollForAssistantReply() polls getChatMessages until a NEW assistant
//      message (newer than the just-sent user prompt) appears with
//      isProcessing=false, then returns it. Times out after maxWaitMs.
//

import { getChatMessages } from '../graphql/generated';

export interface PolledChatMessage {
  role: string;
  content: string;
  timestamp: string;
  isProcessing?: boolean | null;
  sessionId?: string | null;
  messageType?: string | null;
  toolMetadata?: unknown;
}

/**
 * Structural type for the REST client's `.graphql()` — kept loose (`any` args)
 * so the app's precisely-overloaded RestGraphqlClient is assignable here. The
 * response is narrowed to what we read (`data.getChatMessages`).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GraphqlClient = { graphql: (args: any) => Promise<any> };

interface PollOptions {
  /** Amplify-compatible client exposing `.graphql({ query, variables })`. */
  client: GraphqlClient;
  sessionId: string;
  /**
   * ISO-8601 timestamp of the user prompt just sent. Only assistant messages
   * strictly newer than this are considered the reply to this turn (so a stale
   * final message from a previous turn is not mistaken for the new one).
   */
  sinceTimestamp: string;
  /** Poll interval in ms (default 2000). */
  intervalMs?: number;
  /** Max total wait in ms before giving up (default 300000 = 5 min). */
  maxWaitMs?: number;
  /** Optional AbortSignal to cancel polling (e.g. component unmount / cancel). */
  signal?: AbortSignal;
}

const ASSISTANT_ROLE = 'assistant';

const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });

/**
 * Poll getChatMessages until the assistant's final reply to this turn is
 * persisted, and return it. Resolves with `null` on timeout.
 */
export const pollForAssistantReply = async ({
  client,
  sessionId,
  sinceTimestamp,
  intervalMs = 2000,
  maxWaitMs = 300000,
  signal,
}: PollOptions): Promise<PolledChatMessage | null> => {
  const deadline = Date.now() + maxWaitMs;

  while (Date.now() < deadline) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    let messages: PolledChatMessage[] = [];
    try {
      const response = await client.graphql({
        query: getChatMessages,
        variables: { sessionId },
      });
      messages = (response.data?.getChatMessages as PolledChatMessage[] | undefined) ?? [];
    } catch {
      // Transient read error — keep polling until the deadline.
      messages = [];
    }

    // The newest assistant message strictly newer than the sent prompt, and no
    // longer processing, is this turn's reply.
    const reply = messages
      .filter(
        (m) => m.role === ASSISTANT_ROLE && typeof m.timestamp === 'string' && m.timestamp > sinceTimestamp && m.isProcessing !== true,
      )
      .sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))[0];

    if (reply) return reply;

    await sleep(intervalMs, signal);
  }

  return null;
};
