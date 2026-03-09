// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState, useCallback, useRef } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import useAppContext from '../contexts/app';
import {
  listDocuments,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  getDocumentCount,
  getDocument,
  deleteDocument,
  reprocessDocument,
  abortWorkflow,
  onCreateDocument,
  onUpdateDocument,
} from '../graphql/generated';
import { DOCUMENT_LIST_SHARDS_PER_DAY } from '../components/document-list/documents-table-config';
import { Document } from '../types/documents';

const client = generateClient();

const logger = new ConsoleLogger('useGraphQlApi');

interface DateRange {
  startDateTime: string;
  endDateTime: string;
}

interface UseGraphQlApiParams {
  initialPeriodsToLoad?: number;
}

interface UseGraphQlApiReturn {
  documents: Document[];
  isDocumentsListLoading: boolean;
  hasListBeenLoaded: boolean;
  getDocumentDetailsFromIds: (objectKeys: string[]) => Promise<Document[]>;
  setIsDocumentsListLoading: React.Dispatch<React.SetStateAction<boolean>>;
  setPeriodsToLoad: React.Dispatch<React.SetStateAction<number>>;
  periodsToLoad: number;
  customDateRange: DateRange | null;
  setCustomDateRange: React.Dispatch<React.SetStateAction<DateRange | null>>;
  deleteDocuments: (objectKeys: string[]) => Promise<unknown>;
  reprocessDocuments: (objectKeys: string[], version?: string) => Promise<unknown>;
  abortWorkflows: (objectKeys: string[]) => Promise<unknown>;
}

interface GraphQLSubscriptionRef {
  unsubscribe: () => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
interface DocumentListItem {
  ObjectKey: string;
  PK?: string;
  SK?: string;
  [key: string]: unknown;
}

/**
 * Calculate the date range for a relative time period.
 * periodsToLoad represents the number of shard periods (each 4 hours).
 */
const getDateRangeForPeriod = (periodsToLoad: number): DateRange => {
  const now = new Date();
  const hoursInShard = 24 / DOCUMENT_LIST_SHARDS_PER_DAY;
  const hoursBack = periodsToLoad * hoursInShard;
  const startDate = new Date(now.getTime() - hoursBack * 3600 * 1000);
  return {
    startDateTime: startDate.toISOString(),
    endDateTime: now.toISOString(),
  };
};

const useGraphQlApi = ({ initialPeriodsToLoad = DOCUMENT_LIST_SHARDS_PER_DAY * 2 }: UseGraphQlApiParams = {}): UseGraphQlApiReturn => {
  const [periodsToLoad, setPeriodsToLoad] = useState<number>(initialPeriodsToLoad);
  const [isDocumentsListLoading, setIsDocumentsListLoading] = useState<boolean>(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [customDateRange, setCustomDateRange] = useState<DateRange | null>(null);
  const { setErrorMessage } = useAppContext();

  const subscriptionsRef = useRef<{
    onCreate: GraphQLSubscriptionRef | null;
    onUpdate: GraphQLSubscriptionRef | null;
  }>({ onCreate: null, onUpdate: null });

  // Ref to track customDateRange in subscription callbacks (closures capture stale state)
  const customDateRangeRef = useRef<DateRange | null>(customDateRange);
  useEffect(() => {
    customDateRangeRef.current = customDateRange;
  }, [customDateRange]);

  /**
   * Check if a document falls within the active date range filter.
   */
  const isDocumentInActiveRange = useCallback(
    (doc: Document): boolean => {
      const range = customDateRangeRef.current || getDateRangeForPeriod(periodsToLoad);
      const docTime = doc?.InitialEventTime || doc?.QueuedTime;
      if (!docTime) return false;
      return docTime >= range.startDateTime && docTime <= range.endDateTime;
    },
    [periodsToLoad],
  );

  const setDocumentsDeduped = useCallback((documentValues: Document[]): void => {
    setDocuments((currentDocuments) => {
      const documentValuesdocumentIds = documentValues.map((c) => c.ObjectKey);
      const filteredCurrentDocuments = currentDocuments.filter((c) => !documentValuesdocumentIds.includes(c.ObjectKey));
      const allDocuments = [...filteredCurrentDocuments, ...documentValues];
      const deduplicatedByObjectKey = Object.values(
        allDocuments.reduce((acc: Record<string, Document>, doc) => {
          const existing = acc[doc.ObjectKey];
          if (!existing) {
            acc[doc.ObjectKey] = doc;
          } else {
            const existingTime = existing.CompletionTime || existing.InitialEventTime || '0';
            const newTime = doc.CompletionTime || doc.InitialEventTime || '0';
            if (newTime > existingTime) {
              acc[doc.ObjectKey] = doc;
            }
          }
          return acc;
        }, {}),
      );
      return deduplicatedByObjectKey;
    });
  }, []);

  /**
   * Fetch full document details for specific documents by ObjectKey.
   * Used only when navigating to document detail view, NOT for list loading.
   */
  const getDocumentDetailsFromIds = useCallback(
    async (objectKeys: string[]): Promise<Document[]> => {
      logger.debug('getDocumentDetailsFromIds', objectKeys);
      const getDocumentPromises = objectKeys.map((objectKey) => client.graphql({ query: getDocument, variables: { objectKey } }));
      const getDocumentResolutions = await Promise.allSettled(getDocumentPromises);

      type GetDocumentResolved = Awaited<(typeof getDocumentPromises)[number]>;

      const documentValues = getDocumentResolutions
        .filter((r) => r.status === 'fulfilled')
        .map((r) => (r as PromiseFulfilledResult<GetDocumentResolved>).value?.data?.getDocument)
        .filter((doc): doc is NonNullable<typeof doc> => doc != null) as Document[];

      return documentValues;
    },
    [setErrorMessage],
  );

  // ── Subscriptions ──────────────────────────────────────────────────────
  // Subscriptions use the event data directly — NO getDocument calls needed.
  // The onUpdateDocument subscription includes all Document fields.
  // The onCreateDocument subscription only has ObjectKey, so we add a minimal
  // placeholder that will be updated by the next onUpdateDocument event.

  useEffect(() => {
    if (subscriptionsRef.current.onCreate) return undefined;

    logger.debug('onCreateDocument subscription');
    const subscription = client.graphql({ query: onCreateDocument }).subscribe({
      next: (message) => {
        const objectKey = message.data?.onCreateDocument?.ObjectKey || '';
        if (objectKey) {
          // Create a minimal placeholder document from the subscription event.
          // It will be enriched by the next onUpdateDocument subscription event.
          const placeholderDoc = {
            ObjectKey: objectKey,
            PK: `doc#${objectKey}`,
            SK: 'none',
            ObjectStatus: 'QUEUED',
            InitialEventTime: new Date().toISOString(),
          } as unknown as Document;

          if (isDocumentInActiveRange(placeholderDoc)) {
            setDocumentsDeduped([placeholderDoc]);
            logger.debug(`Subscription: added new document placeholder ${objectKey}`);
          }
        }
      },
      error: (error: unknown) => {
        logger.error('onCreateDocument subscription error:', error);
        setErrorMessage('document list network subscription failed - please reload the page');
      },
    });

    subscriptionsRef.current.onCreate = subscription;
    return () => {
      if (subscriptionsRef.current.onCreate) {
        subscriptionsRef.current.onCreate.unsubscribe();
        subscriptionsRef.current.onCreate = null;
      }
    };
  }, [setDocumentsDeduped, setErrorMessage, isDocumentInActiveRange]);

  useEffect(() => {
    if (subscriptionsRef.current.onUpdate) return undefined;

    logger.debug('onUpdateDocument subscription setup');
    const subscription = client.graphql({ query: onUpdateDocument }).subscribe({
      next: (message) => {
        // Use the subscription event data directly — it already includes all Document fields.
        // No need to call getDocument for each update!
        const documentUpdateEvent = message.data?.onUpdateDocument;
        if (documentUpdateEvent?.ObjectKey) {
          const doc = documentUpdateEvent as unknown as Document;
          if (isDocumentInActiveRange(doc)) {
            setDocumentsDeduped([doc]);
          }
        }
      },
      error: (error: unknown) => {
        logger.error('onUpdateDocument subscription error:', error);
        setErrorMessage('document update network request failed - please reload the page');
      },
    });

    subscriptionsRef.current.onUpdate = subscription;
    return () => {
      if (subscriptionsRef.current.onUpdate) {
        subscriptionsRef.current.onUpdate.unsubscribe();
        subscriptionsRef.current.onUpdate = null;
      }
    };
  }, [setDocumentsDeduped, setErrorMessage, isDocumentInActiveRange]);

  // ── Document Loading (GSI-based, paginated with cap) ────────────────

  // Track whether the initial list load has been explicitly requested.
  // This prevents listDocuments from firing on mount when the user is on
  // a non-list page (e.g., document details, config). The DocumentList
  // component triggers the initial load by calling setIsDocumentsListLoading(true).
  const hasListBeenRequestedRef = useRef<boolean>(false);

  /**
   * Fetch documents for a date range using the GSI-based listDocuments query.
   * Paginates through results up to MAX_DOCUMENTS_TO_LOAD to avoid excessive API calls.
   * The GSI query returns document list fields directly (no getDocument calls needed).
   */
  const sendSetDocumentsForDateRange = async (dateRange: DateRange): Promise<void> => {
    try {
      logger.info('Fetching documents via GSI', dateRange);
      let totalLoaded = 0;
      let currentToken: string | null = null;

      do {
        const variables: Record<string, unknown> = {
          startDateTime: dateRange.startDateTime,
          endDateTime: dateRange.endDateTime,
          limit: 200,
        };
        if (currentToken) {
          variables.nextToken = currentToken;
        }

        const response = await client.graphql({
          query: listDocuments,
          variables,
        });

        const result = response.data?.listDocuments;
        const pageDocs = (result?.Documents ?? []) as unknown as Document[];
        currentToken = result?.nextToken ?? null;
        totalLoaded += pageDocs.length;

        // Render incrementally — show each page as it arrives
        if (pageDocs.length > 0) {
          setDocumentsDeduped(pageDocs as unknown as Document[]);
        }

        // Stop loading spinner after first page so user sees results immediately
        if (totalLoaded === pageDocs.length) {
          setIsDocumentsListLoading(false);
        }

        logger.debug(`Fetched ${pageDocs.length} documents (total: ${totalLoaded}), hasMore=${!!currentToken}`);
      } while (currentToken);

      logger.info(`Total documents loaded: ${totalLoaded}`);
      setIsDocumentsListLoading(false);
    } catch (error: unknown) {
      setIsDocumentsListLoading(false);
      // Extract meaningful error message from GraphQL/Lambda errors
      const gqlError = error as { errors?: { message?: string; errorType?: string }[] };
      const firstError = gqlError?.errors?.[0];
      const detail = firstError?.message || (error instanceof Error ? error.message : 'Unknown error');
      const errorType = firstError?.errorType ? ` (${firstError.errorType})` : '';
      setErrorMessage(`Failed to list documents${errorType}: ${detail}`);
      logger.error('Error fetching documents', error);
    }
  };

  useEffect(() => {
    if (isDocumentsListLoading) {
      // Mark that the list has been requested at least once. This allows
      // the periodsToLoad watcher to auto-reload on subsequent changes.
      hasListBeenRequestedRef.current = true;
      logger.debug('document list is loading');
      setTimeout(() => {
        setDocuments([]);
        const dateRange = customDateRange || getDateRangeForPeriod(periodsToLoad);
        sendSetDocumentsForDateRange(dateRange);
      }, 1);
    }
  }, [isDocumentsListLoading]);

  useEffect(() => {
    logger.debug('list period changed', periodsToLoad);
    if (!customDateRange && hasListBeenRequestedRef.current) {
      // Only auto-reload when the period changes AFTER the first load was requested
      setIsDocumentsListLoading(true);
    }
  }, [periodsToLoad]);

  useEffect(() => {
    if (customDateRange) {
      logger.debug('custom date range changed', customDateRange);
      setIsDocumentsListLoading(true);
    }
  }, [customDateRange]);

  // ── Mutations ──────────────────────────────────────────────────────────

  const deleteDocuments = async (objectKeys: string[]): Promise<unknown> => {
    try {
      const result = await client.graphql({ query: deleteDocument, variables: { objectKeys } });
      setIsDocumentsListLoading(true);
      return result.data.deleteDocument;
    } catch (error) {
      setErrorMessage('Failed to delete document(s) - please try again later');
      logger.error('Error deleting documents', error);
      return false;
    }
  };

  const reprocessDocuments = async (objectKeys: string[], version?: string): Promise<unknown> => {
    try {
      const variables: { objectKeys: string[]; version?: string } = { objectKeys };
      if (version) variables.version = version;
      const result = await client.graphql({ query: reprocessDocument, variables });
      setIsDocumentsListLoading(true);
      return result.data.reprocessDocument;
    } catch (error) {
      setErrorMessage('Failed to reprocess document(s) - please try again later');
      logger.error('Error reprocessing documents', error);
      return false;
    }
  };

  const abortWorkflows = async (objectKeys: string[]): Promise<unknown> => {
    try {
      const result = await client.graphql({ query: abortWorkflow, variables: { objectKeys } });
      const response = result.data.abortWorkflow;
      setIsDocumentsListLoading(true);

      if ((response.failedCount ?? 0) > 0 && (response.abortedCount ?? 0) > 0) {
        setErrorMessage(`Aborted ${response.abortedCount ?? 0} document(s), but ${response.failedCount ?? 0} failed`);
      } else if ((response.failedCount ?? 0) > 0 && response.abortedCount === 0) {
        setErrorMessage(`Failed to abort document(s): ${response.errors?.join(', ') || 'Unknown error'}`);
      }

      return response;
    } catch (error: unknown) {
      setErrorMessage('Failed to abort workflow(s) - please try again later');
      logger.error('Error aborting workflows', error);
      return {
        success: false,
        abortedCount: 0,
        failedCount: objectKeys.length,
        errors: [error instanceof Error ? error.message : String(error)],
      };
    }
  };

  return {
    documents,
    isDocumentsListLoading,
    hasListBeenLoaded: hasListBeenRequestedRef.current,
    getDocumentDetailsFromIds,
    setIsDocumentsListLoading,
    setPeriodsToLoad,
    periodsToLoad,
    customDateRange,
    setCustomDateRange,
    deleteDocuments,
    reprocessDocuments,
    abortWorkflows,
  };
};

export default useGraphQlApi;
