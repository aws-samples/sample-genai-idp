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
  Pagination,
  SegmentedControl,
  SpaceBetween,
  Spinner,
  StatusIndicator,
  TextFilter,
} from '@cloudscape-design/components';
import type { FlashbarProps } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getAnnotationQueue, claimReview, releaseReview, completeSectionReview } from '../../graphql/generated';
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

/** Rows per page in the queue rail. */
const QUEUE_ROWS_PER_PAGE = 20;

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
  const [isConfirming, setIsConfirming] = useState(false);
  const [isClaiming, setIsClaiming] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [queueFilter, setQueueFilter] = useState('');
  const [queuePage, setQueuePage] = useState(1);
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
   * Select a document for viewing. Deliberately does NOT claim it.
   *
   * Opening used to claim automatically, which meant browsing the queue silently
   * locked documents away from teammates — an annotator who clicked three
   * documents to see what was in them had taken all three. Viewing is free;
   * claiming is an explicit act.
   */
  const selectDocument = useCallback((item: QueueItem) => {
    setClaimWarning(null);
    setSelectedKey(item.objectKey);
  }, []);

  /** Take ownership so no one else edits this document at the same time. */
  const claimSelected = useCallback(async () => {
    if (!selected?.reviewObjectKey) return;
    setClaimWarning(null);
    setIsClaiming(true);
    try {
      await client.graphql({ query: claimReview, variables: { objectKey: selected.reviewObjectKey } });
      await loadQueue(true);
    } catch (err) {
      const message = String((err as { errors?: { message?: string }[] })?.errors?.[0]?.message ?? err);
      logger.warn('Could not claim document:', message);
      // Losing a race is normal in a shared queue, not an error state.
      setClaimWarning(
        message.includes('already claimed')
          ? `${selected.objectKey} was just claimed by someone else. Pick another document from the queue.`
          : `Could not claim ${selected.objectKey}: ${message}`,
      );
      await loadQueue(false);
    } finally {
      setIsClaiming(false);
    }
  }, [selected, loadQueue]);

  /**
   * Give a claim back without completing the review.
   *
   * Without this an abandoned claim was only ever released by the same annotator
   * finishing it, so a document someone opened and walked away from was stuck for
   * everyone else.
   */
  const releaseSelected = useCallback(async () => {
    if (!selected?.reviewObjectKey) return;
    setClaimWarning(null);
    setIsClaiming(true);
    try {
      await client.graphql({ query: releaseReview, variables: { objectKey: selected.reviewObjectKey } });
      await loadQueue(true);
    } catch (err) {
      logger.error('Could not release document:', err);
      const message = (err as { errors?: { message?: string }[] })?.errors?.[0]?.message;
      setClaimWarning(message || `Could not release ${selected.objectKey}.`);
    } finally {
      setIsClaiming(false);
    }
  }, [selected, loadQueue]);

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

  /**
   * Confirm the draft labels are already correct, with no edits.
   *
   * This is the common case in review and it needs to be a first-class action:
   * "no changes needed" is a *verdict*, not an absence of one. Submitting each
   * section unchanged through completeSectionReview records it as reviewed, tags
   * the labels reviewed-human so a later draft run cannot overwrite them, and —
   * because the curve reads an unchanged field as "the model was right" — teaches
   * the confidence curve the correct-at-this-confidence half of its signal, which
   * only ever arrives from a reviewer agreeing.
   */
  const handleConfirmCorrect = useCallback(async () => {
    if (!selected?.reviewObjectKey) return;
    setIsConfirming(true);
    setError(null);
    try {
      const sections = selected.sections ?? [];
      for (const section of sections) {
        // Sequential rather than parallel: these all mutate the same document
        // record, and the review API is not written for concurrent section
        // updates on one object.

        await client.graphql({
          query: completeSectionReview,
          variables: { objectKey: selected.reviewObjectKey, sectionId: section.sectionId },
        });
      }
      setFlashItems([
        {
          type: 'success',
          content: `${selected.objectKey} confirmed as correct and marked reviewed.`,
          dismissible: true,
          onDismiss: () => setFlashItems([]),
          id: 'annotation-confirmed',
        },
      ]);
      await advanceToNext();
    } catch (err) {
      logger.error('Error confirming labels:', err);
      const message = (err as { errors?: { message?: string }[] })?.errors?.[0]?.message;
      setError(message || 'Could not mark this document reviewed. Please try again.');
    } finally {
      setIsConfirming(false);
    }
  }, [selected, advanceToNext]);

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

  // Filter + paginate the rail. A 50-document queue in a fixed-height column is
  // unusable without them, and the queue is deliberately capped rather than
  // infinite so these bound what a reviewer scrolls.
  const filteredQueue = useMemo(() => {
    const all = queue?.documents ?? [];
    if (!queueFilter.trim()) return all;
    const needle = queueFilter.trim().toLowerCase();
    return all.filter((d) => d.objectKey.toLowerCase().includes(needle));
  }, [queue, queueFilter]);

  const queuePageCount = Math.max(1, Math.ceil(filteredQueue.length / QUEUE_ROWS_PER_PAGE));
  const pagedQueue = useMemo(() => {
    const start = (queuePage - 1) * QUEUE_ROWS_PER_PAGE;
    return filteredQueue.slice(start, start + QUEUE_ROWS_PER_PAGE);
  }, [filteredQueue, queuePage]);

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
          <Grid
            gridDefinition={
              railCollapsed
                ? [{ colspan: { default: 12, m: 1 } }, { colspan: { default: 12, m: 11 } }]
                : [{ colspan: { default: 12, m: 3 } }, { colspan: { default: 12, m: 9 } }]
            }
          >
            <Container
              header={
                <Header
                  variant="h3"
                  counter={railCollapsed ? undefined : `(${filteredQueue.length})`}
                  actions={
                    <Button
                      variant="inline-icon"
                      iconName={railCollapsed ? 'angle-right' : 'angle-left'}
                      ariaLabel={railCollapsed ? 'Expand review queue' : 'Collapse review queue'}
                      onClick={() => setRailCollapsed((v) => !v)}
                    />
                  }
                >
                  {railCollapsed ? '' : 'Review queue'}
                </Header>
              }
            >
              {railCollapsed ? (
                <Box fontSize="body-s" color="text-body-secondary" textAlign="center">
                  {filteredQueue.length}
                </Box>
              ) : (
                <SpaceBetween size="s">
                  <TextFilter
                    filteringText={queueFilter}
                    filteringPlaceholder="Find a document"
                    onChange={({ detail }) => {
                      setQueueFilter(detail.filteringText);
                      setQueuePage(1);
                    }}
                    countText={queueFilter ? `${filteredQueue.length} match${filteredQueue.length === 1 ? '' : 'es'}` : ''}
                  />
                  <Cards
                    items={pagedQueue}
                    trackBy="objectKey"
                    selectionType="single"
                    selectedItems={selected ? [selected] : []}
                    onSelectionChange={({ detail }) => {
                      const item = detail.selectedItems[0];
                      if (item) selectDocument(item);
                    }}
                    isItemDisabled={(item) => item.reviewed}
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
                            // No pipeline copy means nothing to claim — but the reason
                            // differs and the distinction matters. An unlabeled
                            // document needs a labeling run; authored ground truth
                            // needs nothing. Keying only on the missing review key
                            // labelled BOTH "Ground truth", which contradicted the
                            // "Unlabeled" badge right above it.
                            if (!item.reviewObjectKey) {
                              const isUnlabeled = !item.labelSource;
                              return (
                                <Box fontSize="body-s" color="text-body-secondary">
                                  {isUnlabeled ? 'Not labeled yet — generate draft labels first' : 'Ground truth — nothing to review'}
                                </Box>
                              );
                            }
                            return null;
                          },
                        },
                      ],
                    }}
                    cardsPerRow={[{ cards: 1 }]}
                    empty={<Box textAlign="center">No documents to review.</Box>}
                  />
                  {queuePageCount > 1 && (
                    <Pagination
                      currentPageIndex={queuePage}
                      pagesCount={queuePageCount}
                      onChange={({ detail }) => setQueuePage(detail.currentPageIndex)}
                    />
                  )}
                </SpaceBetween>
              )}
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
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={advanceToNext} disabled={isLoading}>
                      Skip to next document
                    </Button>
                    {/* Claiming is explicit: opening a document to look at it does
                        not lock it away from teammates. Release gives a claim back
                        without completing the review, so a document someone opened
                        and abandoned is not stuck for everyone else. */}
                    {selected.reviewObjectKey && !selected.claimedByMe && !selected.reviewed && (
                      <Button onClick={claimSelected} loading={isClaiming} disabled={isLoading || Boolean(selected.claimedBy)}>
                        {selected.claimedBy ? `Claimed by ${selected.claimedBy}` : 'Claim this document'}
                      </Button>
                    )}
                    {selected.claimedByMe && (
                      <Button onClick={releaseSelected} loading={isClaiming} disabled={isLoading}>
                        Release claim
                      </Button>
                    )}
                    {/* The common case: the draft labels are already right, so
                        there is nothing to edit. Without this the reviewer could
                        only "skip", which advances the cursor but never marks the
                        document reviewed — so a correct document could never be
                        completed and the queue never drained. */}
                    <Button
                      variant="primary"
                      onClick={handleConfirmCorrect}
                      loading={isConfirming}
                      disabled={isLoading || !selected.reviewObjectKey}
                    >
                      Labels are correct — mark reviewed
                    </Button>
                  </SpaceBetween>
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
