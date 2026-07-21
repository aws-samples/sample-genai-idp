// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * TestSetDetail — browse a test set's documents and their ground truth.
 * Route: /test-studio/sets/:testSetId
 *
 * Paginated document table (getTestSetDocuments) on top; selecting a document
 * opens a detail area beneath with two views:
 *   - View Source Document (FileViewer against the TestSetBucket, server-side
 *     presigning — the identity-pool role cannot read that bucket)
 *   - Ground Truth editor (GroundTruthVisualEditor: page images + GT form)
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
  Flashbar,
  Header,
  Pagination,
  SegmentedControl,
  SpaceBetween,
  Table,
  TextFilter,
} from '@cloudscape-design/components';
import type { FlashbarProps } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getTestSetDocuments } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import useUserRole from '../../hooks/use-user-role';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import FileViewer from '../document-viewer/FileViewer';
import GroundTruthVisualEditor, { TestSetDocumentSectionRef } from './GroundTruthVisualEditor';
import { TEST_STUDIO_PATH } from '../../routes/constants';

const client = generateClient();
const logger = new ConsoleLogger('TestSetDetail');

const PAGE_SIZE = 50;

interface TestSetDocumentItem {
  objectKey: string;
  inputKey: string;
  size?: number | null;
  lastModified?: string | null;
  sections: TestSetDocumentSectionRef[];
}

const formatSize = (size?: number | null): string => {
  if (size === null || size === undefined) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const TestSetDetail = (): React.JSX.Element => {
  const { testSetId } = useParams<{ testSetId: string }>();
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const { settings } = useSettingsContext();
  const { canWrite } = useUserRole();
  const testSetBucket = (settings as Record<string, unknown>).TestSetBucket as string | undefined;

  const [documents, setDocuments] = useState<TestSetDocumentItem[]>([]);
  // Server pagination: pageTokens[i] is the nextToken that fetches page i+1.
  const [pageTokens, setPageTokens] = useState<(string | null)[]>([null]);
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [selectedDoc, setSelectedDoc] = useState<TestSetDocumentItem | null>(null);
  const [docView, setDocView] = useState<'ground-truth' | 'source'>('ground-truth');
  const [flashItems, setFlashItems] = useState<FlashbarProps.MessageDefinition[]>([]);

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
        const docs = (page?.documents ?? []) as TestSetDocumentItem[];
        setDocuments(docs);
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
    setSelectedDoc(null);
    setPageTokens([null]);
    setCurrentPageIndex(1);
    fetchPage(1, [null]);
  }, [testSetId, fetchPage]);

  const handlePageChange = (pageIndex: number) => {
    setCurrentPageIndex(pageIndex);
    setSelectedDoc(null);
    fetchPage(pageIndex, pageTokens);
  };

  const filteredDocs = filterText ? documents.filter((d) => d.objectKey.toLowerCase().includes(filterText.toLowerCase())) : documents;

  const selectedIndex = selectedDoc ? filteredDocs.findIndex((d) => d.inputKey === selectedDoc.inputKey) : -1;

  const navigateDoc = (delta: number) => {
    const nextIndex = selectedIndex + delta;
    if (nextIndex >= 0 && nextIndex < filteredDocs.length) {
      setSelectedDoc(filteredDocs[nextIndex]);
    }
  };

  const handleSaved = (baselineKey: string) => {
    setFlashItems([
      {
        type: 'success',
        content: `Ground truth saved to ${baselineKey}`,
        dismissible: true,
        onDismiss: () => setFlashItems([]),
        id: 'gt-saved',
      },
    ]);
  };

  return (
    <AppLayout
      headerSelector="#top-navigation"
      ariaLabels={appLayoutLabels}
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      toolsHide
      notifications={<Flashbar items={flashItems} />}
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
            {!testSetBucket && <Alert type="error">TestSetBucket is not configured in settings.</Alert>}
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
                  id: 'objectKey',
                  header: 'Document',
                  cell: (item: TestSetDocumentItem) => item.objectKey,
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
              selectionType="single"
              selectedItems={selectedDoc ? [selectedDoc] : []}
              onSelectionChange={({ detail }) => setSelectedDoc((detail.selectedItems[0] as TestSetDocumentItem) ?? null)}
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

            {selectedDoc && testSetBucket && (
              <SpaceBetween size="s">
                <Header
                  variant="h2"
                  actions={
                    <SpaceBetween direction="horizontal" size="xs">
                      <Button iconName="angle-left" onClick={() => navigateDoc(-1)} disabled={selectedIndex <= 0}>
                        Previous
                      </Button>
                      <Button
                        iconName="angle-right"
                        iconAlign="right"
                        onClick={() => navigateDoc(1)}
                        disabled={selectedIndex < 0 || selectedIndex >= filteredDocs.length - 1}
                      >
                        Next
                      </Button>
                    </SpaceBetween>
                  }
                >
                  {selectedDoc.objectKey}
                </Header>
                <SegmentedControl
                  selectedId={docView}
                  onChange={({ detail }) => setDocView(detail.selectedId as 'ground-truth' | 'source')}
                  options={[
                    { id: 'ground-truth', text: canWrite ? 'Edit Ground Truth' : 'View Ground Truth' },
                    { id: 'source', text: 'View Source Document' },
                  ]}
                />
                {docView === 'source' ? (
                  <FileViewer objectKey={selectedDoc.inputKey} bucket={testSetBucket} presignVia="server" />
                ) : (
                  <GroundTruthVisualEditor
                    key={selectedDoc.inputKey}
                    bucket={testSetBucket}
                    inputKey={selectedDoc.inputKey}
                    objectKey={selectedDoc.objectKey}
                    sections={selectedDoc.sections}
                    isReadOnly={!canWrite}
                    onSaved={handleSaved}
                  />
                )}
              </SpaceBetween>
            )}
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default TestSetDetail;
