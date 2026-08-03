// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * AnnotationWorkspace — the scoped, worst-first annotation queue.
 * Route: /test-studio/sets/:testSetId/annotate
 *
 * This is where an annotator does their work, and for most of them it is the
 * only page they ever see ("one link, one queue"). The link is safe to share
 * because it only navigates: access is enforced server-side against the caller's
 * allowedTestSets on every operation, so a leaked URL grants nothing.
 *
 * Deliberately thin. The annotation surface IS the existing
 * GroundTruthVisualEditor — the same component the owner-facing document detail
 * page uses — and everything genuinely new here is the queue rail, the shared
 * progress banner, and "Save & next". Documents are ordered lowest-confidence
 * first so each review removes the most expected error.
 *
 * Saves route through completeSectionReview rather than the editor's default
 * direct-to-S3 write. That is what engages claim-to-lock, tags the label
 * reviewed-human so a later draft-labeling run won't overwrite it, records the
 * audit trail, and teaches the confidence curve the review-effort estimator
 * learns from.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  AppLayout,
  Badge,
  Box,
  BreadcrumbGroup,
  Button,
  Cards,
  Container,
  ContentLayout,
  CopyToClipboard,
  Flashbar,
  Grid,
  Header,
  ProgressBar,
  SegmentedControl,
  SpaceBetween,
  Spinner,
  StatusIndicator,
} from '@cloudscape-design/components';
import type { FlashbarProps } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getAnnotationQueue, claimReview, completeSectionReview } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import useUserRole from '../../hooks/use-user-role';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import FileViewer from '../document-viewer/FileViewer';
import GroundTruthVisualEditor from './GroundTruthVisualEditor';
import type { TestSetDocumentSectionRef } from './GroundTruthVisualEditor';
import { TEST_STUDIO_PATH, testSetDetailHref, testSetAnnotateHref } from '../../routes/constants';
import { renderConfidence, renderLabelSource } from './TestSetDetail';

const client = generateClient();
const logger = new ConsoleLogger('AnnotationWorkspace');

/** One document in the queue, as returned by getAnnotationQueue. */
export interface QueueItem {
  objectKey: string;
  inputKey: string;
  reviewObjectKey?: string | null;
  minConfidence?: number | null;
  confidenceThreshold?: number | null;
  labelSource?: string | null;
  sectionCount: number;
  sections?: TestSetDocumentSectionRef[] | null;
  claimedBy?: string | null;
  claimedByMe: boolean;
  reviewStatus?: string | null;
  reviewed: boolean;
  available: boolean;
}

interface QueueState {
  totalDocs: number;
  inspectedDocs?: number | null;
  reviewedDocs: number;
  remainingDocs: number;
  claimedByOthers: number;
  nextObjectKey?: string | null;
  labelJobStatus?: string | null;
  labelJobLabeled?: number | null;
  labelJobTotal?: number | null;
  documents: QueueItem[];
}

type DocView = 'ground-truth' | 'source';

const QUEUE_PAGE_SIZE = 100;

const LABEL_JOB_POLL_MS = 5000;

const AnnotationWorkspace = (): React.JSX.Element => {
  const { testSetId } = useParams<{ testSetId: string }>();
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const { settings } = useSettingsContext();
  const { canAnnotate, isAnnotatorOnly, loading: roleLoading } = useUserRole();
  const testSetBucket = (settings as Record<string, unknown>).TestSetBucket as string | undefined;

  const [queue, setQueue] = useState<QueueState | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [claimWarning, setClaimWarning] = useState<string | null>(null);
  const [docView, setDocView] = useState<DocView>('ground-truth');
  const [flashItems, setFlashItems] = useState<FlashbarProps.MessageDefinition[]>([]);

  const loadQueue = useCallback(
    async (preserveSelection = true) => {
      if (!testSetId) return;
      setIsLoading(true);
      setError(null);
      try {
        const response = await client.graphql({
          query: getAnnotationQueue,
          variables: { testSetId, limit: QUEUE_PAGE_SIZE },
        });
        const data = response.data?.getAnnotationQueue as QueueState | null;
        if (!data) {
          setError('The annotation queue could not be loaded.');
          return;
        }
        setQueue(data);
        // Land on the first document the server says this caller can take,
        // unless we are already working one.
        setSelectedKey((current) => {
          if (preserveSelection && current && data.documents.some((d) => d.objectKey === current)) {
            return current;
          }
          return data.nextObjectKey ?? data.documents.find((d) => d.available)?.objectKey ?? null;
        });
      } catch (err) {
        logger.error('Error loading annotation queue:', err);
        // A scope denial is the expected failure for an unassigned annotator, so
        // say what to do about it rather than "please try again".
        const message = String((err as { errors?: { message?: string }[] })?.errors?.[0]?.message ?? err);
        setError(
          message.includes('Unauthorized')
            ? 'You are not assigned to this test set. Ask the person who shared this link to assign it to your account.'
            : 'Failed to load the annotation queue. Please try again.',
        );
      } finally {
        setIsLoading(false);
      }
    },
    [testSetId],
  );

  useEffect(() => {
    loadQueue(false);
  }, [loadQueue]);

  const labelJobRunning = queue?.labelJobStatus === 'RUNNING';
  const [pollTick, setPollTick] = useState(0);

  /**
   * Poll while draft labeling runs. Labels are harvested on read, so polling is
   * what advances the job — without this an annotator who opens the workspace
   * mid-run watches an empty queue that never fills, because the only other
   * poller is the owner-facing detail page they cannot open.
   *
   * Keyed on an explicit tick rather than the labeled count: a long run reports
   * the same count for minutes at a time, so depending on the count would stop
   * re-arming the timer and polling would die exactly when it is still needed.
   */
  useEffect(() => {
    if (!labelJobRunning) return undefined;
    const timer = setTimeout(async () => {
      await loadQueue(true);
      setPollTick((n) => n + 1);
    }, LABEL_JOB_POLL_MS);
    return () => clearTimeout(timer);
  }, [labelJobRunning, pollTick, loadQueue]);

  const selected = useMemo(() => queue?.documents.find((d) => d.objectKey === selectedKey) ?? null, [queue, selectedKey]);

  /**
   * Claim the document before editing, so two annotators can't unknowingly work
   * the same one. An already-claimed rejection is not an error state — surface it
   * and move on to the next available document.
   */
  const claimAndSelect = useCallback(
    async (item: QueueItem) => {
      setClaimWarning(null);
      setSelectedKey(item.objectKey);
      if (!item.reviewObjectKey || item.claimedByMe) return;
      try {
        await client.graphql({ query: claimReview, variables: { objectKey: item.reviewObjectKey } });
      } catch (err) {
        const message = String((err as { errors?: { message?: string }[] })?.errors?.[0]?.message ?? err);
        logger.warn('Could not claim document:', message);
        setClaimWarning(
          message.includes('already claimed')
            ? `${item.objectKey} was just claimed by someone else. Pick another document from the queue.`
            : `Could not claim ${item.objectKey}: ${message}`,
        );
        await loadQueue(false);
      }
    },
    [loadQueue],
  );

  // Claim whatever the queue landed us on.
  useEffect(() => {
    if (selected && !selected.claimedByMe && selected.available) {
      claimAndSelect(selected);
    }
    // Keyed on the object key only: re-running on every `selected` identity
    // change would re-claim the same document on each queue refresh.
  }, [selected, claimAndSelect]);

  /**
   * Persist a reviewed section through the review API. Replaces the editor's
   * default direct-S3 write so the save claims, tags the label reviewed-human,
   * records provenance, and feeds the confidence curve.
   */
  const handleSave = useCallback(
    async (sectionId: string, data: Record<string, unknown>) => {
      if (!selected?.reviewObjectKey) {
        throw new Error('This document has no review record yet — generate draft labels for the test set first.');
      }
      await client.graphql({
        query: completeSectionReview,
        variables: {
          objectKey: selected.reviewObjectKey,
          sectionId,
          editedData: JSON.stringify(data),
        },
      });
    },
    [selected],
  );

  const advanceToNext = useCallback(async () => {
    const current = selectedKey;
    await loadQueue(false);
    setQueue((data) => {
      if (data) {
        const next = data.documents.find((d) => d.available && d.objectKey !== current);
        setSelectedKey(next?.objectKey ?? null);
      }
      return data;
    });
  }, [loadQueue, selectedKey]);

  const handleSaved = useCallback(
    (baselineKey: string) => {
      setFlashItems([
        {
          type: 'success',
          content: `Saved. ${baselineKey.split('/').pop() ?? ''} is now marked reviewed.`,
          dismissible: true,
          onDismiss: () => setFlashItems([]),
          id: 'annotation-saved',
        },
      ]);
      advanceToNext();
    },
    [advanceToNext],
  );

  const progressPct = queue && queue.totalDocs > 0 ? Math.round((queue.reviewedDocs / queue.totalDocs) * 100) : 0;

  const content = (
    <ContentLayout
      header={
        <SpaceBetween size="xs">
          {/* Annotator-only users get no breadcrumb trail — the pages it links to
              are ones they cannot open. */}
          {!isAnnotatorOnly && (
            <BreadcrumbGroup
              items={[
                { text: 'Test Studio', href: `#${TEST_STUDIO_PATH}?tab=sets` },
                { text: testSetId ?? '', href: testSetDetailHref(testSetId ?? '') },
                { text: 'Annotate', href: '' },
              ]}
            />
          )}
          <Header
            variant="h1"
            description="Review the lowest-confidence documents first — each one you correct removes the most likely error."
            actions={
              !isAnnotatorOnly && (
                <CopyToClipboard
                  variant="button"
                  copyButtonText="Copy queue link"
                  textToCopy={`${window.location.origin}/${testSetAnnotateHref(testSetId ?? '')}`}
                  copySuccessText="Queue link copied — share it with an assigned annotator"
                  copyErrorText="Could not copy the queue link"
                />
              )
            }
          >
            Annotate: {testSetId}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {!testSetBucket && <Alert type="error">TestSetBucket is not configured in settings.</Alert>}
        {error && <Alert type="error">{error}</Alert>}
        {claimWarning && (
          <Alert type="warning" dismissible onDismiss={() => setClaimWarning(null)}>
            {claimWarning}
          </Alert>
        )}

        {queue && (
          <Container>
            <SpaceBetween size="s">
              <ProgressBar
                value={progressPct}
                label="Team progress"
                description="Shared across everyone annotating this test set"
                additionalInfo={
                  `${queue.reviewedDocs} of ${queue.totalDocs} documents reviewed` +
                  (queue.claimedByOthers > 0 ? ` · ${queue.claimedByOthers} in progress by others` : '')
                }
              />
              {/* Be explicit when the ranking covers only part of the set —
                  otherwise "worst-first" implies the whole set was ranked. */}
              {queue.inspectedDocs != null && queue.inspectedDocs < queue.totalDocs && (
                <Box fontSize="body-s" color="text-body-secondary">
                  Ordering covers the {queue.inspectedDocs} documents examined so far, not all {queue.totalDocs}.
                </Box>
              )}
            </SpaceBetween>
          </Container>
        )}

        {labelJobRunning && (
          <Alert type="info" header="Draft labeling in progress">
            <SpaceBetween size="xs">
              <Box>
                {queue?.labelJobLabeled ?? 0} of {queue?.labelJobTotal ?? 0} document(s) labeled. Documents appear in the queue as they
                finish — this page refreshes itself, no need to reload.
              </Box>
              {queue?.documents.length === 0 && (
                <Box fontSize="body-s" color="text-body-secondary">
                  Nothing to annotate yet. The first documents usually take a couple of minutes.
                </Box>
              )}
            </SpaceBetween>
          </Alert>
        )}

        {isLoading && !queue && (
          <Box textAlign="center" padding="xl">
            <Spinner /> Loading your queue…
          </Box>
        )}

        {queue && queue.documents.length === 0 && !error && !labelJobRunning && (
          <Alert type="success" header="Queue complete">
            Every document in this test set has been reviewed. Nothing left to annotate.
          </Alert>
        )}

        {queue && queue.documents.length > 0 && testSetBucket && (
          <Grid gridDefinition={[{ colspan: { default: 12, m: 3 } }, { colspan: { default: 12, m: 9 } }]}>
            <Container
              header={
                <Header variant="h3" counter={`(${queue.documents.length})`}>
                  Review queue
                </Header>
              }
            >
              <Cards
                items={queue.documents}
                trackBy="objectKey"
                selectionType="single"
                selectedItems={selected ? [selected] : []}
                onSelectionChange={({ detail }) => {
                  const item = detail.selectedItems[0];
                  if (item) claimAndSelect(item);
                }}
                isItemDisabled={(item) => !item.available}
                cardDefinition={{
                  header: (item) => (
                    <Box fontSize="body-s" fontWeight="bold">
                      {item.objectKey}
                    </Box>
                  ),
                  sections: [
                    {
                      id: 'meta',
                      content: (item) => (
                        <SpaceBetween direction="horizontal" size="xxs">
                          {renderConfidence(item.minConfidence, item.confidenceThreshold)}
                          {renderLabelSource(item.labelSource)}
                        </SpaceBetween>
                      ),
                    },
                    {
                      id: 'claim',
                      content: (item) => {
                        if (item.reviewed) return <StatusIndicator type="success">Reviewed</StatusIndicator>;
                        if (item.claimedByMe) return <Badge color="blue">You have this</Badge>;
                        if (item.claimedBy) return <StatusIndicator type="in-progress">{item.claimedBy}</StatusIndicator>;
                        return null;
                      },
                    },
                  ],
                }}
                cardsPerRow={[{ cards: 1 }]}
                empty={<Box textAlign="center">No documents to review.</Box>}
              />
            </Container>

            <SpaceBetween size="s">
              <SegmentedControl
                selectedId={docView}
                onChange={({ detail }) => setDocView(detail.selectedId as DocView)}
                options={[
                  { id: 'ground-truth', text: 'Annotate' },
                  { id: 'source', text: 'View source document' },
                ]}
              />
              {!selected && <Alert type="info">Choose a document from the queue to start.</Alert>}
              {selected && !selected.reviewObjectKey && (
                <Alert type="warning" header="Not ready to annotate">
                  This test set has no labeling run yet, so there is nothing to claim or review. Generate draft labels for the set first.
                </Alert>
              )}
              {selected && docView === 'source' && <FileViewer objectKey={selected.inputKey} bucket={testSetBucket} presignVia="server" />}
              {selected && docView === 'ground-truth' && (
                <GroundTruthVisualEditor
                  key={selected.objectKey}
                  bucket={testSetBucket}
                  inputKey={selected.inputKey}
                  objectKey={selected.objectKey}
                  sections={selected.sections ?? []}
                  isReadOnly={!canAnnotate || !selected.reviewObjectKey}
                  onSave={handleSave}
                  onSaved={handleSaved}
                  saveButtonText="Save & next in queue"
                />
              )}
              {selected && (
                <Box textAlign="right">
                  <Button onClick={advanceToNext} disabled={isLoading}>
                    Skip to next document
                  </Button>
                </Box>
              )}
            </SpaceBetween>
          </Grid>
        )}
      </SpaceBetween>
    </ContentLayout>
  );

  if (!roleLoading && !canAnnotate) {
    return (
      <AppLayout
        headerSelector="#top-navigation"
        ariaLabels={appLayoutLabels}
        navigation={<Navigation />}
        navigationOpen={navigationOpen}
        onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
        toolsHide
        content={
          <ContentLayout header={<Header variant="h1">Annotate</Header>}>
            <Alert type="error" header="Not available for your account">
              Ground-truth annotation requires an Annotator, Author or Admin role.
            </Alert>
          </ContentLayout>
        }
      />
    );
  }

  return (
    <AppLayout
      headerSelector="#top-navigation"
      ariaLabels={appLayoutLabels}
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      toolsHide
      notifications={<Flashbar items={flashItems} />}
      content={content}
    />
  );
};

export default AnnotationWorkspace;
