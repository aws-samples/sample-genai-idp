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
import { useParams } from 'react-router-dom';
import {
  Alert,
  AppLayout,
  Box,
  BreadcrumbGroup,
  Button,
  ContentLayout,
  Header,
  Link,
  Pagination,
  SpaceBetween,
  Table,
  TextFilter,
} from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getTestSetDocuments } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import { TEST_STUDIO_PATH, testSetDocumentHref } from '../../routes/constants';
import TestDocThumbnail from './TestDocThumbnail';
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
}

export const formatSize = (size?: number | null): string => {
  if (size === null || size === undefined) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const TestSetDetail = (): React.JSX.Element => {
  const { testSetId } = useParams<{ testSetId: string }>();
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

  const filteredDocs = filterText ? documents.filter((d) => d.objectKey.toLowerCase().includes(filterText.toLowerCase())) : documents;

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

            <Table
              header={
                <Header
                  counter={`(${filteredDocs.length})`}
                  actions={
                    <Button iconName="refresh" onClick={() => fetchPage(currentPageIndex, pageTokens)} disabled={isLoading}>
                      Refresh
                    </Button>
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
              items={filteredDocs}
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
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default TestSetDetail;
