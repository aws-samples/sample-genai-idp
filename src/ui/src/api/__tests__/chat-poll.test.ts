// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi } from 'vitest';

import { pollForAssistantReply, fetchAssistantKeys } from '../chat-poll';

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

const noKeys = new Set<string>();

describe('fetchAssistantKeys', () => {
  it('captures a baseline of existing assistant messages', async () => {
    const client = clientReturning([
      [
        { role: 'user', content: 'hi', timestamp: '2026-07-13T10:00:00.000Z' },
        { role: 'assistant', content: 'prior answer', timestamp: '2026-07-13T09:59:00.000Z', isProcessing: false },
      ],
    ]);
    const keys = await fetchAssistantKeys(client, 's1');
    expect(keys.size).toBe(1);
    // A message with the same key would be treated as "already seen".
    expect(keys.has('2026-07-13T09:59:00.000Z|12')).toBe(true);
  });

  it('returns an empty set if the read fails', async () => {
    const client = { graphql: vi.fn(async () => Promise.reject(new Error('boom'))) };
    const keys = await fetchAssistantKeys(client, 's1');
    expect(keys.size).toBe(0);
  });
});

describe('pollForAssistantReply', () => {
  it('returns the new assistant reply not present in the baseline', async () => {
    const client = clientReturning([
      // 1st poll: only the user message.
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
      knownAssistantKeys: noKeys,
      intervalMs: 1,
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('hello!');
    expect(client.graphql).toHaveBeenCalledTimes(2);
  });

  it('ignores a pre-existing (baselined) assistant message and waits for the new one', async () => {
    const stale = { role: 'assistant', content: 'old answer', timestamp: '2026-07-13T09:59:00.000Z', isProcessing: false };
    const known = new Set<string>([`${stale.timestamp}|${stale.content.length}`]);
    const client = clientReturning([
      [stale], // only the baselined reply exists — must NOT be returned
      [stale, { role: 'assistant', content: 'new answer', timestamp: '2026-07-13T10:00:03.000Z', isProcessing: false }],
    ]);

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      knownAssistantKeys: known,
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
      knownAssistantKeys: noKeys,
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
      knownAssistantKeys: noKeys,
      intervalMs: 5,
      maxWaitMs: 20,
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
            getChatMessages: [{ role: 'assistant', content: 'recovered', timestamp: '2026-07-13T10:00:06.000Z', isProcessing: false }],
          },
        };
      }),
    };

    const reply = await pollForAssistantReply({
      client,
      sessionId: 's1',
      knownAssistantKeys: noKeys,
      intervalMs: 1,
      maxWaitMs: 5000,
    });

    expect(reply?.content).toBe('recovered');
    expect(client.graphql).toHaveBeenCalledTimes(2);
  });

  it('surfaces an auth/authorization error immediately instead of polling to timeout', async () => {
    const client = {
      graphql: vi.fn(async () => Promise.reject({ errors: [{ errorType: 'Unauthorized', message: 'session not found' }] })),
    };

    await expect(
      pollForAssistantReply({
        client,
        sessionId: 's1',
        knownAssistantKeys: noKeys,
        intervalMs: 1,
        maxWaitMs: 5000,
      }),
    ).rejects.toBeTruthy();
    // Only one call — it did not retry the auth failure.
    expect(client.graphql).toHaveBeenCalledTimes(1);
  });

  it('throws AbortError when the signal is already aborted', async () => {
    const client = clientReturning([[]]);
    const controller = new AbortController();
    controller.abort();

    await expect(
      pollForAssistantReply({
        client,
        sessionId: 's1',
        knownAssistantKeys: noKeys,
        intervalMs: 1,
        maxWaitMs: 5000,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});
