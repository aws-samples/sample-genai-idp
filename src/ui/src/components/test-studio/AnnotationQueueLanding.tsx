// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * AnnotationQueueLanding — where an annotator assigned to more than one test set
 * chooses which queue to work. Route: /test-studio/annotate
 *
 * A single-set annotator never sees this: the navigation links them straight into
 * their queue ("one link, one queue"). It also handles the two states that would
 * otherwise dead-end an annotator with no explanation — scope not yet resolved,
 * and no sets assigned at all.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Alert,
  AppLayout,
  Badge,
  Box,
  Cards,
  ContentLayout,
  Header,
  Link,
  ProgressBar,
  SpaceBetween,
  Spinner,
  StatusIndicator,
} from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getAnnotationQueue } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import useUserRole from '../../hooks/use-user-role';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import { testSetAnnotateHref } from '../../routes/constants';

const client = generateClient();
const logger = new ConsoleLogger('AnnotationQueueLanding');

interface QueueSummary {
  totalDocs: number;
  reviewedDocs: number;
  remainingDocs: number;
  claimedByOthers: number;
  labelJobStatus?: string | null;
  hasReviewableWork: boolean;
}

const AnnotationQueueLanding = (): React.JSX.Element => {
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const { allowedTestSets, canAnnotate, loading } = useUserRole();

  const sets = allowedTestSets ?? [];

  /**
   * Per-set progress, so choosing a queue is not blind.
   *
   * A card showing only the set id gives an annotator with several assignments no
   * way to tell which needs attention — or that a set has no labels yet and would
   * dead-end them on arrival. getAnnotationQueue already returns shared progress
   * and label-job state, and Annotators are permitted to call it.
   */
  const [summaries, setSummaries] = useState<Record<string, QueueSummary>>({});

  const loadSummaries = useCallback(async (ids: string[]) => {
    await Promise.all(
      ids.map(async (id) => {
        try {
          const response = await client.graphql({
            query: getAnnotationQueue,
            // A single row is enough: the counts are set-level, and pulling the
            // whole queue for every assigned set would be wasteful here.
            variables: { testSetId: id, limit: 1 },
          });
          const q = response.data?.getAnnotationQueue;
          if (!q) return;
          setSummaries((prev) => ({
            ...prev,
            [id]: {
              totalDocs: q.totalDocs ?? 0,
              reviewedDocs: q.reviewedDocs ?? 0,
              remainingDocs: q.remainingDocs ?? 0,
              claimedByOthers: q.claimedByOthers ?? 0,
              labelJobStatus: q.labelJobStatus,
              hasReviewableWork: Boolean(q.documents?.some((d) => d?.reviewObjectKey)),
            },
          }));
        } catch (err) {
          // A summary that fails to load leaves the card usable — the link still
          // works, it just shows no progress.
          logger.debug(`Could not load queue summary for ${id}:`, err);
        }
      }),
    );
  }, []);

  useEffect(() => {
    if (sets.length > 0) loadSummaries(sets);
    // Keyed on the joined ids so a scope change refetches, but an identical
    // array identity on re-render does not.
  }, [sets.join(','), loadSummaries]);

  return (
    <AppLayout
      headerSelector="#top-navigation"
      ariaLabels={appLayoutLabels}
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      toolsHide
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="The test sets you have been assigned to annotate">
              My annotation queues
            </Header>
          }
        >
          <SpaceBetween size="l">
            {loading && (
              <Box textAlign="center" padding="xl">
                <Spinner /> Loading your assignments…
              </Box>
            )}

            {!loading && !canAnnotate && (
              <Alert type="error" header="Not available for your account">
                Ground-truth annotation requires an Annotator, Author or Admin role.
              </Alert>
            )}

            {/* An annotator with no assigned set is denied every set server-side,
                so say who can fix it rather than showing an empty list. */}
            {!loading && canAnnotate && sets.length === 0 && (
              <Alert type="info" header="No test sets assigned yet">
                Your account has no test sets assigned, so there is nothing to annotate. Ask an administrator to assign you a test set —
                they can do this from User Management.
              </Alert>
            )}

            {!loading && sets.length > 0 && (
              <Cards
                items={sets.map((id) => ({ id }))}
                trackBy="id"
                cardDefinition={{
                  header: (item) => <Link href={testSetAnnotateHref(item.id)}>{item.id}</Link>,
                  sections: [
                    {
                      id: 'state',
                      content: (item) => {
                        const summary = summaries[item.id];
                        if (!summary)
                          return (
                            <Box fontSize="body-s" color="text-body-secondary">
                              Loading…
                            </Box>
                          );
                        if (summary.labelJobStatus === 'RUNNING') {
                          return <StatusIndicator type="in-progress">Labeling in progress</StatusIndicator>;
                        }
                        // Say so here rather than letting them arrive at a queue
                        // that cannot be worked.
                        if (!summary.hasReviewableWork) {
                          return <Badge color="severity-neutral">Needs labeling first</Badge>;
                        }
                        if (summary.remainingDocs === 0) {
                          return <StatusIndicator type="success">All reviewed</StatusIndicator>;
                        }
                        return <Badge color="blue">Draft labels ready</Badge>;
                      },
                    },
                    {
                      id: 'progress',
                      content: (item) => {
                        const summary = summaries[item.id];
                        if (!summary || summary.totalDocs === 0) return null;
                        const pct = Math.round((summary.reviewedDocs / summary.totalDocs) * 100);
                        return (
                          <ProgressBar
                            value={pct}
                            additionalInfo={
                              `${summary.reviewedDocs} of ${summary.totalDocs} reviewed` +
                              (summary.claimedByOthers > 0 ? ` · ${summary.claimedByOthers} in progress by others` : '')
                            }
                          />
                        );
                      },
                    },
                    {
                      id: 'action',
                      content: (item) => <Link href={testSetAnnotateHref(item.id)}>Open queue — most confidence alerts first</Link>,
                    },
                  ],
                }}
                cardsPerRow={[{ cards: 1 }, { minWidth: 600, cards: 2 }]}
              />
            )}
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default AnnotationQueueLanding;
