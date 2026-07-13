// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi } from 'vitest';

import { pollForAssistantReply } from '../chat-poll';

// A fake graphql client whose getChatMessages returns a scripted sequence of
// responses across successive poll calls.
const clientReturning = (sequence: unknown[][]) => {
  let call = 0;
  return {
    graphql: vi.fn(async () => {
      const messages = sequence[Math.min(call, sequence.length - 1)];
      call += 1;
      return { data: { getChatMessages: messages } };
    }),
  };
};

const PROMPT_TS = '2026-07-13T10:00:00.000Z';

describe('pollForAssistantReply', () => {
  it('returns the assistant reply once it appears newer than the prompt', async () => {
    const client = clientReturning([
      // 1st poll: only the user message (no assistant yet).
      [{ role: 'user', content: 'hi', timestamp: '2026-07-13T10:00:00.100Z', isProcessing: false }],
      // 2nd poll: assistant final reply present.
      [
        { role: 'user', content: 'hi', timestamp: '2026-07-13T10:00:00.100Z', isProcessing: false },
        { role: 'assistant', content: 'hello!', timestamp: '2026-07-13T10:00:05.000Z', isProcessing: false },
      ],
    ]);

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      sinceTimestamp: PROMPT_TS,
      intervalMs: 1, // keep the test fast
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('hello!');
    expect(reply?.role).toBe('assistant');
    expect(client.graphql).toHaveBeenCalledTimes(2);
  });

  it('ignores a stale assistant message older than the prompt', async () => {
    const client = clientReturning([
      // Only a stale reply from a previous turn exists, then a fresh one lands.
      [{ role: 'assistant', content: 'old answer', timestamp: '2026-07-13T09:59:00.000Z', isProcessing: false }],
      [
        { role: 'assistant', content: 'old answer', timestamp: '2026-07-13T09:59:00.000Z', isProcessing: false },
        { role: 'assistant', content: 'new answer', timestamp: '2026-07-13T10:00:03.000Z', isProcessing: false },
      ],
    ]);

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      sinceTimestamp: PROMPT_TS,
      intervalMs: 1,
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('new answer');
  });

  it('does not return a still-processing assistant message', async () => {
    const client = clientReturning([
      [{ role: 'assistant', content: 'partial…', timestamp: '2026-07-13T10:00:02.000Z', isProcessing: true }],
      [{ role: 'assistant', content: 'done', timestamp: '2026-07-13T10:00:04.000Z', isProcessing: false }],
    ]);

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      sinceTimestamp: PROMPT_TS,
      intervalMs: 1,
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('done');
  });

  it('returns null on timeout when no reply appears', async () => {
    const client = clientReturning([[{ role: 'user', content: 'hi', timestamp: '2026-07-13T10:00:00.100Z' }]]);

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      sinceTimestamp: PROMPT_TS,
      intervalMs: 5,
      maxWaitMs: 20, // force a quick timeout
    });

    expect(reply).toBeNull();
  });

  it('keeps polling through a transient graphql error', async () => {
    let call = 0;
    const client = {
      graphql: vi.fn(async () => {
        call += 1;
        if (call === 1) throw new Error('network blip');
        return {
          data: {
            getChatMessages: [
              { role: 'assistant', content: 'recovered', timestamp: '2026-07-13T10:00:06.000Z', isProcessing: false },
            ],
          },
        };
      }),
    };

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      sinceTimestamp: PROMPT_TS,
      intervalMs: 1,
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('recovered');
    expect(client.graphql).toHaveBeenCalledTimes(2);
  });
});
