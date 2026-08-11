// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * TestSetDetail — list a test set's documents (route: /test-studio/sets/:testSetId).
 *
 * Mirrors the Document List -> Document Details structure of the main app:
 * each row links to the TestSetDocumentDetail page, with per-row quick
 * actions ("View Source" / "Ground Truth") that deep-link straight to the
 * corresponding view on that page.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  AppLayout,
  Badge,
  Box,
  BreadcrumbGroup,
  Button,
  ContentLayout,
  Header,
  Link,
  Pagination,
  Popover,
  SpaceBetween,
  StatusIndicator,
  Table,
  TextFilter,
} from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getTestSetDocuments, generateDraftLabels, getDraftLabelJob } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import { TEST_STUDIO_PATH, testSetDocumentHref, testSetAnnotateHref } from '../../routes/constants';
import TestDocThumbnail from './TestDocThumbnail';
import ReviewEffortModal from './ReviewEffortModal';
import GenerateDraftLabelsModal from './GenerateDraftLabelsModal';
import type { TestSetDocumentSectionRef } from './GroundTruthVisualEditor';

const client = generateClient();
const logger = new ConsoleLogger('TestSetDetail');

const PAGE_SIZE = 50;

export interface TestSetDocumentItem {
  objectKey: string;
  inputKey: string;
  size?: number | null;
  lastModified?: string | null;
  sections: TestSetDocumentSectionRef[];
  labelSource?: string | null;
  minConfidence?: number | null;
  confidenceThreshold?: number | null;
  alertCount?: number | null;
  fieldCount?: number | null;
}

/**
 * Label provenance is the trust axis of the whole review loop, so machine-drafted
 * labels must never look like human-verified ones. One vocabulary, used here and
 * anywhere else labels surface.
 */
export const LABEL_SOURCE_BADGES: Record<string, { color: 'blue' | 'green' | 'grey' | 'severity-neutral'; text: string }> = {
  'draft-machine': { color: 'blue', text: 'Draft (machine)' },
  'reviewed-human': { color: 'green', text: 'Reviewed (human)' },
  synthetic: { color: 'grey', text: 'Synthetic' },
  uploaded: { color: 'grey', text: 'Uploaded' },
};

export const renderLabelSource = (labelSource?: string | null): React.JSX.Element => {
  if (!labelSource) return <Badge color="severity-neutral">Unlabeled</Badge>;
  const badge = LABEL_SOURCE_BADGES[labelSource];
  return badge ? <Badge color={badge.color}>{badge.text}</Badge> : <Badge color="grey">{labelSource}</Badge>;
};

/**
 * Confidence as a percentage, colored against the *configured* alert threshold:
 * red below it, amber within 10 points above it, otherwise plain. Hardcoded bands
 * would contradict the assessment config — with a 0.8 threshold a 0.85 field is
 * passing, and with a 0.9 threshold it is failing. Falls back to 80% only when
 * the result carries no threshold at all.
 */
const DEFAULT_CONFIDENCE_THRESHOLD_PCT = 80;
const NEAR_THRESHOLD_MARGIN_PCT = 10;

export const renderConfidence = (value?: number | null, threshold?: number | null): React.JSX.Element | string => {
  if (value === null || value === undefined) return '-';
  const pct = value <= 1 ? value * 100 : value;
  const rawThreshold = threshold ?? null;
  const thresholdPct = rawThreshold === null ? DEFAULT_CONFIDENCE_THRESHOLD_PCT : rawThreshold <= 1 ? rawThreshold * 100 : rawThreshold;
  const below = pct < thresholdPct;
  const near = !below && pct < thresholdPct + NEAR_THRESHOLD_MARGIN_PCT;
  const color = below ? 'text-status-error' : near ? 'text-status-warning' : 'text-status-success';
  return (
    <Box color={color} fontWeight={below ? 'bold' : 'normal'}>
      {pct.toFixed(1)}%
    </Box>
  );
};

/**
 * How many fields need a human, as a count rather than a score.
 *
 * This is the same signal human review uses in the Document List: a field below
 * its configured threshold is an alert, and whether it missed by 2 points or 40
 * does not change that somebody has to look at it. A count also describes the
 * work in the way an annotator meets it — eight weak fields is eight things to
 * check — where a single lowest score does not. The score is still available in
 * the popover, since the calibration curve is built on it.
 */
export const renderAlertCount = (
  alertCount?: number | null,
  fieldCount?: number | null,
  minConfidence?: number | null,
  threshold?: number | null,
): React.JSX.Element | string => {
  if (alertCount === null || alertCount === undefined) return '-';
  const detail = (
    <SpaceBetween size="xxs">
      <Box variant="span">
        Lowest field confidence: {minConfidence === null || minConfidence === undefined ? '-' : renderConfidence(minConfidence, threshold)}
      </Box>
      <Box variant="span" fontSize="body-s" color="text-body-secondary">
        {threshold === null || threshold === undefined
          ? 'Alerts count fields below the default 80% threshold.'
          : `Alerts count fields below their configured threshold (${((threshold <= 1 ? threshold * 100 : threshold) as number).toFixed(0)}%).`}
      </Box>
    </SpaceBetween>
  );
  return (
    <Popover dismissButton={false} position="top" size="medium" triggerType="custom" content={detail}>
      <Box color={alertCount > 0 ? 'text-status-error' : 'text-status-success'} fontWeight={alertCount > 0 ? 'bold' : 'normal'}>
        {alertCount === 0 ? `None of ${fieldCount ?? 0} fields` : `${alertCount} of ${fieldCount ?? 0} fields`}
      </Box>
    </Popover>
  );
};

/**
 * Where this document stands in the review loop — as distinct from the model's
 * confidence, which review never changes.
 */
export const renderReviewState = (labelSource?: string | null): React.JSX.Element => {
  if (labelSource === 'reviewed-human') {
    return <StatusIndicator type="success">Reviewed</StatusIndicator>;
  }
  if (labelSource === 'draft-machine') {
    return <StatusIndicator type="pending">Awaiting review</StatusIndicator>;
  }
  if (!labelSource) {
    return <StatusIndicator type="info">Unlabeled</StatusIndicator>;
  }
  // Uploaded or generated ground truth: authored, so there is nothing to review.
  return <StatusIndicator type="success">Ground truth</StatusIndicator>;
};

export const formatSize = (size?: number | null): string => {
  if (size === null || size === undefined) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const TestSetDetail = (): React.JSX.Element => {
  const { testSetId } = useParams<{ testSetId: string }>();
  const navigate = useNavigate();
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const { settings } = useSettingsContext();
  const testSetBucket = (settings as Record<string, unknown>).TestSetBucket as string | undefined;

  const [documents, setDocuments] = useState<TestSetDocumentItem[]>([]);
  // Server pagination: pageTokens[i] is the nextToken that fetches page i+1.
  const [pageTokens, setPageTokens] = useState<(string | null)[]>([null]);
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [labelJob, setLabelJob] = useState<{
    jobId: string;
    status: string;
    total: number;
    labeled: number;
    skippedAlreadyLabeled?: number | null;
  } | null>(null);
  const [isStartingLabels, setIsStartingLabels] = useState(false);
  const [showEffortModal, setShowEffortModal] = useState(false);
  const [showLabelModal, setShowLabelModal] = useState(false);
  // Default to worst-first once any document carries confidence — the whole point
  // of draft labels is to review the least trustworthy ones first.
  const [worstFirst, setWorstFirst] = useState(true);

  const fetchPage = useCallback(
    async (pageIndex: number, tokens: (string | null)[]) => {
      if (!testSetId) return;
      setIsLoading(true);
      setError(null);
      try {
        const response = await client.graphql({
          query: getTestSetDocuments,
          variables: {
            testSetId,
            limit: PAGE_SIZE,
            nextToken: tokens[pageIndex - 1] ?? undefined,
          },
        });
        const page = response.data?.getTestSetDocuments;
        setDocuments((page?.documents ?? []) as TestSetDocumentItem[]);
        setHasMore(Boolean(page?.nextToken));
        setPageTokens((prev) => {
          const next = [...prev];
          next[pageIndex] = page?.nextToken ?? null;
          return next;
        });
        // Resume polling a job this session did not start. Harvesting happens on
        // read, so a job only progresses while something polls it — a refresh
        // mid-run otherwise left it RUNNING forever and the Test Sets list
        // reported "Labeling" indefinitely.
        if (page?.activeLabelJobId) {
          setLabelJob((current) =>
            current?.jobId === page.activeLabelJobId
              ? current
              : { jobId: page.activeLabelJobId as string, status: 'RUNNING', total: 0, labeled: 0 },
          );
        }
      } catch (err) {
        logger.error('Error loading test set documents:', err);
        setError('Failed to load test set documents. Please try again.');
      } finally {
        setIsLoading(false);
      }
    },
    [testSetId],
  );

  useEffect(() => {
    setPageTokens([null]);
    setCurrentPageIndex(1);
    fetchPage(1, [null]);
  }, [testSetId, fetchPage]);

  const handlePageChange = (pageIndex: number) => {
    setCurrentPageIndex(pageIndex);
    fetchPage(pageIndex, pageTokens);
  };

  const handleGenerateDraftLabels = async (configVersion?: string, objectKeys?: string[]) => {
    if (!testSetId) return;
    setIsStartingLabels(true);
    setError(null);
    try {
      const response = await client.graphql({
        query: generateDraftLabels,
        variables: { input: { testSetId, configVersion, objectKeys } },
      });
      const job = response.data?.generateDraftLabels;
      if (job) {
        setLabelJob({
          jobId: job.jobId,
          status: job.status,
          total: job.total ?? 0,
          labeled: job.labeled ?? 0,
          skippedAlreadyLabeled: job.skippedAlreadyLabeled ?? 0,
        });
        setShowLabelModal(false);
      }
    } catch (err) {
      logger.error('Error starting draft labeling:', err);
      // Surface the server's message. Several are deliberate and actionable —
      // "every document already has ground truth, run a test instead" tells the
      // owner what to do, whereas "please try again" is advice that cannot work.
      const message = (err as { errors?: { message?: string }[] })?.errors?.[0]?.message;
      setError(message || 'Failed to start draft labeling. Please try again.');
    } finally {
      setIsStartingLabels(false);
    }
  };

  /**
   * Poll the labeling job while it runs. The resolver harvests finished
   * documents on read, so polling is what advances the job — and each tick also
   * refreshes the table so labels appear as they land.
   *
   * Keyed on an explicit tick, and deliberately NOT on fetchPage/pageTokens. A
   * tick calls fetchPage, which sets pageTokens; depending on those meant the
   * effect tore itself down and re-armed mid-flight, so any tick that refreshed
   * the table cancelled its own successor. Observed live: polling stopped ~30s
   * into a run and the banner sat at "0 of 3" indefinitely while the documents
   * had in fact all finished — the job only looked stuck because nothing was
   * driving the harvest.
   */
  const [labelPollTick, setLabelPollTick] = useState(0);
  const [documentsStale, setDocumentsStale] = useState(false);
  const jobId = labelJob?.jobId;
  const jobRunning = labelJob?.status === 'RUNNING';

  useEffect(() => {
    if (!testSetId || !jobId || !jobRunning) return undefined;
    const timer = setTimeout(async () => {
      try {
        const response = await client.graphql({
          query: getDraftLabelJob,
          variables: { testSetId, jobId },
        });
        const job = response.data?.getDraftLabelJob;
        if (job) {
          setLabelJob({
            jobId: job.jobId,
            status: job.status,
            total: job.total ?? 0,
            labeled: job.labeled ?? 0,
            skippedAlreadyLabeled: job.skippedAlreadyLabeled ?? 0,
          });
          setDocumentsStale(true);
          if (job.status === 'FAILED') {
            setError(job.error ? `Draft labeling failed: ${job.error}` : 'Draft labeling failed.');
          }
        }
      } catch (err) {
        logger.error('Error polling draft label job:', err);
      } finally {
        setLabelPollTick((n) => n + 1);
      }
    }, 5000);
    return () => clearTimeout(timer);
  }, [testSetId, jobId, jobRunning, labelPollTick]);

  // Refresh the table in a separate effect so the poll loop never depends on
  // fetchPage — the dependency that was killing it.
  useEffect(() => {
    if (!documentsStale) return;
    setDocumentsStale(false);
    fetchPage(currentPageIndex, pageTokens);
  }, [documentsStale, currentPageIndex, pageTokens, fetchPage]);

  const filteredDocs = filterText ? documents.filter((d) => d.objectKey.toLowerCase().includes(filterText.toLowerCase())) : documents;

  const hasConfidence = documents.some((d) => d.minConfidence !== null && d.minConfidence !== undefined);
  // Sort in place on the current page: pagination is server-side and opaque, so
  // this orders what the reviewer can actually see rather than implying a
  // set-wide ranking it can't deliver.
  const visibleDocs =
    worstFirst && hasConfidence
      ? [...filteredDocs].sort((a, b) => {
          const av = a.minConfidence ?? Number.POSITIVE_INFINITY;
          const bv = b.minConfidence ?? Number.POSITIVE_INFINITY;
          return av - bv;
        })
      : filteredDocs;

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
            <SpaceBetween size="xs">
              <BreadcrumbGroup
                items={[
                  { text: 'Test Studio', href: `#${TEST_STUDIO_PATH}?tab=sets` },
                  { text: testSetId ?? '', href: '' },
                ]}
              />
              <Header variant="h1" description="Browse this test set's documents and view or edit their ground truth">
                Test Set: {testSetId}
              </Header>
            </SpaceBetween>
          }
        >
          <SpaceBetween size="l">
            {error && <Alert type="error">{error}</Alert>}

            {labelJob && labelJob.status === 'RUNNING' && (
              <Alert type="info">
                <StatusIndicator type="in-progress">
                  Draft labeling in progress — {labelJob.labeled} of {labelJob.total} document(s) labeled. Labels appear here as they
                  complete.
                  {labelJob.skippedAlreadyLabeled
                    ? ` Skipping ${labelJob.skippedAlreadyLabeled} document(s) that already have ground truth.`
                    : ''}
                </StatusIndicator>
              </Alert>
            )}

            {labelJob && labelJob.status === 'COMPLETED' && (
              <Alert type="success" dismissible onDismiss={() => setLabelJob(null)}>
                Draft labeling complete — {labelJob.labeled} document(s) labeled
                {labelJob.skippedAlreadyLabeled ? `, ${labelJob.skippedAlreadyLabeled} skipped (already had ground truth)` : ''}. Review the
                documents with the most confidence alerts first, then publish a version to freeze them as ground truth.
              </Alert>
            )}

            <Table
              header={
                <Header
                  counter={`(${filteredDocs.length})`}
                  description={
                    hasConfidence ? 'Confidence is the lowest per-field score in each document — review the weakest first.' : undefined
                  }
                  actions={
                    <SpaceBetween direction="horizontal" size="xs">
                      {hasConfidence && (
                        <Button onClick={() => setWorstFirst((prev) => !prev)}>{worstFirst ? 'Sort by name' : 'Sort worst-first'}</Button>
                      )}
                      <Button
                        iconName="gen-ai"
                        onClick={() => setShowLabelModal(true)}
                        loading={isStartingLabels}
                        disabled={isLoading || labelJob?.status === 'RUNNING'}
                      >
                        Generate draft labels
                      </Button>
                      {/* Owners reach the worst-first queue from here rather than
                          hand-building the URL; it is also the link they share
                          with an assigned annotator. Routed through the effort
                          estimate so the decision "how much to review" is made
                          before committing a team, not discovered mid-queue. */}
                      <Button onClick={() => setShowEffortModal(true)} iconName="user-profile">
                        Annotate
                      </Button>
                      <Button iconName="refresh" onClick={() => fetchPage(currentPageIndex, pageTokens)} disabled={isLoading}>
                        Refresh
                      </Button>
                    </SpaceBetween>
                  }
                >
                  Documents
                </Header>
              }
              columnDefinitions={[
                {
                  id: 'thumbnail',
                  header: 'Preview',
                  cell: (item: TestSetDocumentItem) =>
                    testSetBucket ? <TestDocThumbnail bucket={testSetBucket} inputKey={item.inputKey} /> : null,
                  width: 130,
                },
                {
                  id: 'objectKey',
                  header: 'Document',
                  cell: (item: TestSetDocumentItem) => (
                    <Link href={testSetDocumentHref(testSetId ?? '', item.objectKey)}>{item.objectKey}</Link>
                  ),
                  sortingField: 'objectKey',
                },
                {
                  id: 'labelSource',
                  header: 'Labels',
                  cell: (item: TestSetDocumentItem) => renderLabelSource(item.labelSource),
                  sortingField: 'labelSource',
                },
                {
                  id: 'alertCount',
                  // What the rest of the product shows for human review: the number
                  // of fields below their threshold, not a score. A bare percentage
                  // invited reading 28% as "this document is 28% good" when the
                  // other 30 fields were above 0.99 — and it said nothing about how
                  // much work the document actually is. The score lives in the
                  // cell's popover.
                  header: 'Confidence alerts',
                  cell: (item: TestSetDocumentItem) =>
                    renderAlertCount(item.alertCount, item.fieldCount, item.minConfidence, item.confidenceThreshold),
                  sortingField: 'alertCount',
                },
                {
                  id: 'reviewState',
                  // The column that MOVES as annotation progresses. Confidence
                  // alerts come from the model's own assessment and deliberately do
                  // not change when a human reviews — so without this there was
                  // nothing on screen reflecting review effort.
                  header: 'Review state',
                  cell: (item: TestSetDocumentItem) => renderReviewState(item.labelSource),
                  sortingField: 'labelSource',
                },
                {
                  id: 'size',
                  header: 'Size',
                  cell: (item: TestSetDocumentItem) => formatSize(item.size),
                },
                {
                  id: 'lastModified',
                  header: 'Last modified',
                  cell: (item: TestSetDocumentItem) => (item.lastModified ? new Date(item.lastModified).toLocaleString() : '-'),
                },
                {
                  id: 'sections',
                  header: 'GT sections',
                  cell: (item: TestSetDocumentItem) => item.sections.length,
                },
              ]}
              items={visibleDocs}
              loading={isLoading}
              loadingText="Loading documents"
              trackBy="inputKey"
              filter={
                <TextFilter
                  filteringText={filterText}
                  filteringPlaceholder="Find documents on this page"
                  onChange={({ detail }) => setFilterText(detail.filteringText)}
                />
              }
              pagination={
                <Pagination
                  currentPageIndex={currentPageIndex}
                  pagesCount={hasMore ? currentPageIndex + 1 : currentPageIndex}
                  openEnd={hasMore}
                  onChange={({ detail }) => handlePageChange(detail.currentPageIndex)}
                />
              }
              empty={
                <Box textAlign="center" color="inherit">
                  <b>No documents</b>
                  <Box variant="p" color="inherit">
                    This test set has no documents{filterText ? ' matching the filter' : ''}.
                  </Box>
                </Box>
              }
            />

            <GenerateDraftLabelsModal
              visible={showLabelModal}
              testSetId={testSetId ?? ''}
              documents={documents}
              submitting={isStartingLabels}
              onDismiss={() => setShowLabelModal(false)}
              onSubmit={handleGenerateDraftLabels}
            />

            <ReviewEffortModal
              visible={showEffortModal}
              testSetId={testSetId ?? ''}
              onDismiss={() => setShowEffortModal(false)}
              onContinue={() => {
                setShowEffortModal(false);
                navigate(testSetAnnotateHref(testSetId ?? '').replace(/^#/, ''));
              }}
            />
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default TestSetDetail;
