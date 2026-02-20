// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState, useCallback, useRef } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import useAppContext from '../contexts/app';
import listDocumentsDateShard from '../graphql/queries/listDocumentsDateShard';
import listDocumentsDateHour from '../graphql/queries/listDocumentsDateHour';
import listDocumentsByDateRangeQuery from '../graphql/queries/listDocumentsByDateRange';
import getDocument from '../graphql/queries/getDocument';
import deleteDocument from '../graphql/queries/deleteDocument';
import reprocessDocument from '../graphql/queries/reprocessDocument';
import abortWorkflow from '../graphql/queries/abortWorkflow';
import onCreateDocument from '../graphql/queries/onCreateDocument';
import onUpdateDocument from '../graphql/queries/onUpdateDocument';
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

interface DocumentListItem {
  ObjectKey: string;
  PK?: string;
  SK?: string;
  [key: string]: unknown;
}

interface GraphQLSubscribable<T> {
  subscribe: (handlers: { next: (value: T) => void; error: (err: unknown) => void }) => GraphQLSubscriptionRef;
}

interface GetDocumentResult {
  data: { getDocument: Document | null };
}

interface ListDocumentsDateShardResult {
  data: { listDocumentsDateShard: { Documents: DocumentListItem[] } | null };
}

interface ListDocumentsDateHourResult {
  data: { listDocumentsDateHour: { Documents: DocumentListItem[] } | null };
}

interface ListDocumentsByDateRangeResult {
  data: { listDocumentsByDateRange: { Documents: DocumentListItem[]; nextToken?: string | null } | null };
}

interface AbortWorkflowResponse {
  success: boolean;
  abortedCount: number;
  failedCount: number;
  errors?: string[];
}

const useGraphQlApi = ({ initialPeriodsToLoad = DOCUMENT_LIST_SHARDS_PER_DAY * 2 }: UseGraphQlApiParams = {}): UseGraphQlApiReturn => {
  const [periodsToLoad, setPeriodsToLoad] = useState<number>(initialPeriodsToLoad);
  const [isDocumentsListLoading, setIsDocumentsListLoading] = useState<boolean>(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [customDateRange, setCustomDateRange] = useState<DateRange | null>(null); // { startDateTime, endDateTime }
  const [_dateRangeNextToken, _setDateRangeNextToken] = useState<string | null>(null);
  const { setErrorMessage } = useAppContext()!;

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
   * For relative periods (no customDateRange), always returns true.
   * For custom date ranges, checks the document's InitialEventTime or QueuedTime.
   */
  const isDocumentInActiveRange = useCallback((doc: Document): boolean => {
    const range = customDateRangeRef.current;
    if (!range) return true; // No custom range = relative period, always accept

    const docTime = doc?.InitialEventTime || doc?.QueuedTime;
    if (!docTime) return false; // No timestamp = can't verify, exclude

    return docTime >= range.startDateTime && docTime <= range.endDateTime;
  }, []);

  const setDocumentsDeduped = useCallback((documentValues: Document[]): void => {
    logger.debug('setDocumentsDeduped called with:', documentValues);
    setDocuments((currentDocuments) => {
      const documentValuesdocumentIds = documentValues.map((c) => c.ObjectKey);

      // Remove old entries with matching ObjectKeys
      const filteredCurrentDocuments = currentDocuments.filter((c) => !documentValuesdocumentIds.includes(c.ObjectKey));

      // Add new entries with PK/SK preserved
      const newDocuments = documentValues.map((document) => ({
        ...document,
        ListPK: document.ListPK || currentDocuments.find((c) => c.ObjectKey === document.ObjectKey)?.ListPK,
        ListSK: document.ListSK || currentDocuments.find((c) => c.ObjectKey === document.ObjectKey)?.ListSK,
      }));

      // Combine and deduplicate by ObjectKey, keeping only the latest entry per ObjectKey
      const allDocuments = [...filteredCurrentDocuments, ...newDocuments];
      const deduplicatedByObjectKey = Object.values(
        allDocuments.reduce((acc: Record<string, Document>, doc) => {
          const existing = acc[doc.ObjectKey];
          // Keep the document with the most recent CompletionTime or InitialEventTime
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

  const getDocumentDetailsFromIds = useCallback(
    async (objectKeys: string[]): Promise<Document[]> => {
      // prettier-ignore
      logger.debug('getDocumentDetailsFromIds', objectKeys);
      const getDocumentPromises = objectKeys.map((objectKey) =>
        client.graphql({ query: getDocument as unknown as string, variables: { objectKey } }),
      );
      const getDocumentResolutions = await Promise.allSettled(getDocumentPromises);

      // Separate rejected promises from null/undefined results
      const getDocumentRejected = getDocumentResolutions.filter((r) => r.status === 'rejected');
      const fulfilledResults = getDocumentResolutions.filter((r) => r.status === 'fulfilled');
      const getDocumentNull = fulfilledResults
        .map((r, idx) => ({ doc: (r as PromiseFulfilledResult<GetDocumentResult>).value?.data?.getDocument, key: objectKeys[idx] }))
        .filter((item) => !item.doc)
        .map((item) => item.key);

      // Log partial failures but NEVER show error banner for individual document failures
      if (getDocumentRejected.length > 0) {
        logger.warn(`Failed to load ${getDocumentRejected.length} of ${objectKeys.length} document(s) due to query rejection`);
        logger.debug('Rejected promises:', getDocumentRejected);
      }
      if (getDocumentNull.length > 0) {
        logger.warn(`${getDocumentNull.length} of ${objectKeys.length} document(s) not found (returned null):`, getDocumentNull);
        logger.warn('These documents have list entries but no corresponding document records - possible orphaned list entries');
      }

      // Filter out null/undefined documents to prevent downstream errors
      const documentValues = getDocumentResolutions
        .filter((r) => r.status === 'fulfilled')
        .map((r) => (r as PromiseFulfilledResult<GetDocumentResult>).value?.data?.getDocument)
        .filter((doc: Document | null): doc is Document => doc != null);

      logger.debug(`Successfully loaded ${documentValues.length} of ${objectKeys.length} requested documents`);
      return documentValues;
    },
    [setErrorMessage],
  );

  useEffect(() => {
    if (subscriptionsRef.current.onCreate) {
      logger.debug('onCreateDocument subscription already exists, skipping');
      return undefined;
    }

    logger.debug('onCreateDocument subscription');
    interface OnCreateSubscriptionData {
      data: { onCreateDocument: { ObjectKey: string } };
    }
    const subscription = (
      client.graphql({
        query: onCreateDocument as unknown as string,
      }) as unknown as GraphQLSubscribable<OnCreateSubscriptionData>
    ).subscribe({
      next: async (subscriptionData: OnCreateSubscriptionData) => {
        logger.debug('document list subscription update', subscriptionData);
        const data = subscriptionData?.data;
        const objectKey = data?.onCreateDocument?.ObjectKey || '';
        if (objectKey) {
          try {
            const documentValues = await getDocumentDetailsFromIds([objectKey]);
            if (documentValues && documentValues.length > 0) {
              // Filter: only add documents that fall within the active date range
              const inRangeDocuments = documentValues.filter(isDocumentInActiveRange);
              if (inRangeDocuments.length > 0) {
                setDocumentsDeduped(inRangeDocuments);
              } else {
                logger.debug(`Subscription: new document ${objectKey} outside active date range, skipping`);
              }
            }
          } catch (error) {
            logger.error('Error processing onCreateDocument subscription:', error);
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
      logger.debug('onCreateDocument subscription cleanup');
      if (subscriptionsRef.current.onCreate) {
        subscriptionsRef.current.onCreate.unsubscribe();
        subscriptionsRef.current.onCreate = null;
      }
    };
  }, [getDocumentDetailsFromIds, setDocumentsDeduped, setErrorMessage]);

  useEffect(() => {
    if (subscriptionsRef.current.onUpdate) {
      logger.debug('onUpdateDocument subscription already exists, skipping');
      return undefined;
    }

    logger.debug('onUpdateDocument subscription setup');
    interface OnUpdateSubscriptionData {
      data: { onUpdateDocument: Document };
    }
    const subscription = (
      client.graphql({
        query: onUpdateDocument as unknown as string,
      }) as unknown as GraphQLSubscribable<OnUpdateSubscriptionData>
    ).subscribe({
      next: async (subscriptionData: OnUpdateSubscriptionData) => {
        logger.debug('document update subscription received', subscriptionData);
        const data = subscriptionData?.data;
        const documentUpdateEvent = data?.onUpdateDocument;
        if (documentUpdateEvent?.ObjectKey) {
          // Fetch full document details to ensure we have complete data
          try {
            const documentValues = await getDocumentDetailsFromIds([documentUpdateEvent.ObjectKey]);
            if (documentValues && documentValues.length > 0) {
              // For updates: only add if document is already in the list OR falls within the active range
              // This ensures in-range docs get updates, but out-of-range new docs don't sneak in
              const filteredValues = documentValues.filter((doc) => {
                if (isDocumentInActiveRange(doc)) return true;
                // Check if this document is already displayed (allow status updates for existing docs)
                return false;
              });
              if (filteredValues.length > 0) {
                setDocumentsDeduped(filteredValues);
              } else {
                logger.debug(`Subscription: updated document ${documentUpdateEvent.ObjectKey} outside active date range, skipping`);
              }
            }
          } catch (error) {
            logger.error('Error fetching document details after update:', error);
            // Fallback to subscription data if fetch fails - still apply range filter
            if (isDocumentInActiveRange(documentUpdateEvent)) {
              setDocumentsDeduped([documentUpdateEvent]);
            }
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
      logger.debug('onUpdateDocument subscription cleanup');
      if (subscriptionsRef.current.onUpdate) {
        subscriptionsRef.current.onUpdate.unsubscribe();
        subscriptionsRef.current.onUpdate = null;
      }
    };
  }, [setDocumentsDeduped, setErrorMessage, getDocumentDetailsFromIds]);

  const listDocumentIdsByDateShards = async ({ date, shards }: { date: string; shards: number[] }): Promise<DocumentListItem[]> => {
    const listDocumentsDateShardPromises = shards.map((i) => {
      logger.debug('sending list document date shard', date, i);
      return client.graphql({ query: listDocumentsDateShard as unknown as string, variables: { date, shard: i } });
    });
    const listDocumentsDateShardResolutions = await Promise.allSettled(listDocumentsDateShardPromises);

    const listRejected = listDocumentsDateShardResolutions.filter((r) => r.status === 'rejected');
    if (listRejected.length) {
      setErrorMessage('failed to list documents - please try again later');
      logger.error('list document promises rejected', listRejected);
    }
    const documentData = listDocumentsDateShardResolutions
      .filter((r) => r.status === 'fulfilled')
      .map((r) => (r as PromiseFulfilledResult<ListDocumentsDateShardResult>).value?.data?.listDocumentsDateShard?.Documents || [])
      .reduce((pv: DocumentListItem[], cv: DocumentListItem[]) => [...cv, ...pv], []);

    return documentData;
  };

  const listDocumentIdsByDateHours = async ({ date, hours }: { date: string; hours: number[] }): Promise<DocumentListItem[]> => {
    const listDocumentsDateHourPromises = hours.map((i) => {
      logger.debug('sending list document date hour', date, i);
      return client.graphql({ query: listDocumentsDateHour as unknown as string, variables: { date, hour: i } });
    });
    const listDocumentsDateHourResolutions = await Promise.allSettled(listDocumentsDateHourPromises);

    const listRejected = listDocumentsDateHourResolutions.filter((r) => r.status === 'rejected');
    if (listRejected.length) {
      setErrorMessage('failed to list documents - please try again later');
      logger.error('list document promises rejected', listRejected);
    }

    const documentData = listDocumentsDateHourResolutions
      .filter((r) => r.status === 'fulfilled')
      .map((r) => (r as PromiseFulfilledResult<ListDocumentsDateHourResult>).value?.data?.listDocumentsDateHour?.Documents || [])
      .reduce((pv: DocumentListItem[], cv: DocumentListItem[]) => [...cv, ...pv], []);

    return documentData;
  };

  const sendSetDocumentsForDateRange = async (dateRange: DateRange, nextToken: string | null = null): Promise<void> => {
    // Server-side paginated query for custom date ranges
    try {
      logger.info('Fetching documents by date range', dateRange);
      const allDocuments: DocumentListItem[] = [];
      let currentToken = nextToken;

      // Fetch all pages (server-side pagination)
      do {
        const response = await client.graphql({
          query: listDocumentsByDateRangeQuery as unknown as string,
          variables: {
            startDateTime: dateRange.startDateTime,
            endDateTime: dateRange.endDateTime,
            limit: 200,
            nextToken: currentToken,
          },
        });

        const result = (response as ListDocumentsByDateRangeResult)?.data?.listDocumentsByDateRange;
        if (result?.Documents) {
          allDocuments.push(...result.Documents);
        }
        currentToken = result?.nextToken ?? null;
        logger.debug(`Fetched ${result?.Documents?.length || 0} documents, hasMore=${!!currentToken}`);
      } while (currentToken);

      logger.info(`Total documents fetched for date range: ${allDocuments.length}`);

      // Transform to match existing document format expected by the UI
      const documentValues = allDocuments.map((doc: DocumentListItem) => ({
        ...doc,
        ListPK: (doc.ListPK as string) || (doc.PK as string),
        ListSK: (doc.ListSK as string) || (doc.SK as string),
      }));

      setDocumentsDeduped(documentValues as Document[]);
      setIsDocumentsListLoading(false);
    } catch (error) {
      setIsDocumentsListLoading(false);
      setErrorMessage('Failed to list documents for date range - please try again later');
      logger.error('Error fetching documents by date range', error);
    }
  };

  const sendSetDocumentsForPeriod = async (): Promise<void> => {
    // XXX this logic should be moved to the API
    try {
      const now = new Date();

      // array of arrays containing date / shard pairs relative to current UTC time
      // e.g. 2 periods to on load 2021-01-01T:20:00:00.000Z ->
      // [ [ '2021-01-01', 3 ], [ '2021-01-01', 4 ] ]
      const hoursInShard = 24 / DOCUMENT_LIST_SHARDS_PER_DAY;
      const dateShardPairs = [...Array(Math.floor(periodsToLoad)).keys()].map((p) => {
        const deltaInHours = p * hoursInShard;
        const relativeDate = new Date(now.getTime() - deltaInHours * 3600 * 1000);

        const relativeDateString = relativeDate.toISOString().split('T')[0];
        const shard = Math.floor(relativeDate.getUTCHours() / hoursInShard);

        return [relativeDateString, shard] as [string, number];
      });

      // reduce array of date/shard pairs into object of shards by date
      // e.g. [ [ '2021-01-01', 3 ], [ '2021-01-01', 4 ] ] -> { '2021-01-01': [ 3, 4 ] }
      const dateShards = dateShardPairs.reduce((p: Record<string, number[]>, c) => ({ ...p, [c[0]]: [...(p[c[0]] || []), c[1]] }), {});
      logger.debug('document list date shards', dateShards);

      // parallelizes listDocuments and getDocumentDetails
      // alternatively we could implement it by sending multiple graphql queries in 1 request
      const documentDataDateShardPromises = Object.keys(dateShards).map(
        // pretttier-ignore
        async (d) => listDocumentIdsByDateShards({ date: d, shards: dateShards[d] }),
      );

      // get document Ids by hour on residual hours outside of the lower shard date/hour boundary
      // or just last n hours when periodsToLoad is less than 1 shard period
      let baseDate;
      let residualHours;
      if (periodsToLoad < 1) {
        baseDate = new Date(now);
        const numHours = Math.floor(periodsToLoad * hoursInShard);
        residualHours = [...Array(numHours).keys()].map((h) => (((baseDate.getUTCHours() - h) % 24) + 24) % 24);
      } else {
        baseDate = new Date(now.getTime() - periodsToLoad * hoursInShard * 3600 * 1000);
        const residualBaseHour = baseDate.getUTCHours() % hoursInShard;
        residualHours = [...Array(hoursInShard - residualBaseHour).keys()].map((h) => (baseDate.getUTCHours() + h) % 24);
      }
      const baseDateString = baseDate.toISOString().split('T')[0];

      const residualDateHours = { date: baseDateString, hours: residualHours };
      logger.debug('document list date hours', residualDateHours);

      const documentDataDateHourPromise = listDocumentIdsByDateHours(residualDateHours);

      const documentDataPromises = [...documentDataDateShardPromises, documentDataDateHourPromise];
      const documentDetailsPromises = documentDataPromises.map(async (documentDataPromise) => {
        const documentData = await documentDataPromise;
        const objectKeys = documentData.map((item: DocumentListItem) => item.ObjectKey);
        const documentDetails = await getDocumentDetailsFromIds(objectKeys);

        // Log orphaned list entries with full PK/SK details for debugging
        const retrievedKeys = new Set(documentDetails.map((d) => d.ObjectKey));
        const missingDocs = documentData.filter((item: DocumentListItem) => !retrievedKeys.has(item.ObjectKey));
        if (missingDocs.length > 0) {
          missingDocs.forEach((item: DocumentListItem) => {
            logger.warn(`Orphaned list entry detected:`);
            logger.warn(`  - List entry: PK="${item.PK}", SK="${item.SK}"`);
            logger.warn(`  - Expected doc entry: PK="doc#${item.ObjectKey}", SK="none"`);
            logger.warn(`  - ObjectKey: "${item.ObjectKey}"`);
          });
        }

        // Merge document details with PK and SK, filtering out nulls to prevent shard-level failures
        return documentDetails
          .filter((detail) => detail != null)
          .map((detail) => {
            const matchingData = documentData.find((item: DocumentListItem) => item.ObjectKey === detail.ObjectKey);
            return { ...detail, ListPK: matchingData?.PK, ListSK: matchingData?.SK };
          });
      });

      const documentValuesPromises = documentDetailsPromises.map(async (documentValuesPromise) => {
        const documentValues = await documentValuesPromise;
        logger.debug('documentValues', documentValues);
        return documentValues;
      });

      const getDocumentsPromiseResolutions = await Promise.allSettled(documentValuesPromises);
      logger.debug('getDocumentsPromiseResolutions', getDocumentsPromiseResolutions);
      const documentValuesReduced = getDocumentsPromiseResolutions
        .filter((r) => r.status === 'fulfilled')
        .map((r) => (r as PromiseFulfilledResult<Document[]>).value)
        .reduce((previous, current) => [...previous, ...current], []);
      logger.debug('documentValuesReduced', documentValuesReduced);
      setDocumentsDeduped(documentValuesReduced);
      setIsDocumentsListLoading(false);
      const getDocumentsRejected = getDocumentsPromiseResolutions.filter((r) => r.status === 'rejected');
      // Only show error banner if ALL shard queries failed
      if (getDocumentsRejected.length === documentDataPromises.length) {
        setErrorMessage('failed to get document details - please try again later');
        logger.error('All shard queries rejected', getDocumentsRejected);
      } else if (getDocumentsRejected.length > 0) {
        // Partial failure - log but don't show error banner
        logger.warn(`${getDocumentsRejected.length} of ${documentDataPromises.length} shard queries failed`);
        logger.debug('Rejected shard queries:', getDocumentsRejected);
      }
    } catch (error) {
      setIsDocumentsListLoading(false);
      setErrorMessage('failed to list Documents - please try again later');
      logger.error('error obtaining document list', error);
    }
  };

  useEffect(() => {
    if (isDocumentsListLoading) {
      logger.debug('document list is loading');
      // send in a timeout to avoid blocking rendering
      setTimeout(() => {
        setDocuments([]);
        if (customDateRange) {
          // Use server-side paginated query for custom date ranges
          sendSetDocumentsForDateRange(customDateRange);
        } else {
          // Use existing shard-based client-side mechanism for relative periods
          sendSetDocumentsForPeriod();
        }
      }, 1);
    }
  }, [isDocumentsListLoading]);

  useEffect(() => {
    logger.debug('list period changed', periodsToLoad);
    if (!customDateRange) {
      setIsDocumentsListLoading(true);
    }
  }, [periodsToLoad]);

  useEffect(() => {
    if (customDateRange) {
      logger.debug('custom date range changed', customDateRange);
      setIsDocumentsListLoading(true);
    }
  }, [customDateRange]);

  const deleteDocuments = async (objectKeys: string[]): Promise<unknown> => {
    try {
      logger.debug('Deleting documents', objectKeys);
      const result = await client.graphql({ query: deleteDocument as unknown as string, variables: { objectKeys } });
      logger.debug('Delete documents result', result);

      // Refresh the document list after deletion
      setIsDocumentsListLoading(true);

      return (result as { data: { deleteDocument: unknown } }).data.deleteDocument;
    } catch (error) {
      setErrorMessage('Failed to delete document(s) - please try again later');
      logger.error('Error deleting documents', error);
      return false;
    }
  };

  const reprocessDocuments = async (objectKeys: string[], version?: string): Promise<unknown> => {
    try {
      logger.debug('Reprocessing documents', objectKeys, 'with version', version);
      const variables: { objectKeys: string[]; version?: string } = { objectKeys };
      if (version) {
        variables.version = version;
      }
      const result = await client.graphql({ query: reprocessDocument as unknown as string, variables });
      logger.debug('Reprocess documents result', result);
      // Refresh the document list after reprocessing
      setIsDocumentsListLoading(true);
      return (result as { data: { reprocessDocument: unknown } }).data.reprocessDocument;
    } catch (error) {
      setErrorMessage('Failed to reprocess document(s) - please try again later');
      logger.error('Error reprocessing documents', error);
      return false;
    }
  };

  const abortWorkflows = async (objectKeys: string[]): Promise<unknown> => {
    try {
      logger.debug('Aborting workflows for documents', objectKeys);
      const result = await client.graphql({ query: abortWorkflow as unknown as string, variables: { objectKeys } });
      logger.debug('Abort workflows result', result);
      const response = (result as { data: { abortWorkflow: AbortWorkflowResponse } }).data.abortWorkflow;

      // Refresh the document list after aborting
      setIsDocumentsListLoading(true);

      // Show error message if some aborts failed but not all
      if (response.failedCount > 0 && response.abortedCount > 0) {
        setErrorMessage(`Aborted ${response.abortedCount} document(s), but ${response.failedCount} failed`);
      } else if (response.failedCount > 0 && response.abortedCount === 0) {
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
