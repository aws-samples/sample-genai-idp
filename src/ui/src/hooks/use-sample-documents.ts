// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';
import { listSampleDocuments as listSampleDocumentsOp, uploadSampleDocument as uploadSampleDocumentOp } from '../graphql/generated';

export interface SampleDocument {
  id: string;
  name: string;
  description?: string | null;
  s3Key: string;
  kind: string;
  fileCount?: number | null;
  /** Associated config_library/unified preset folder, or null when unassociated. */
  configId?: string | null;
}

interface UseSampleDocumentsReturn {
  loading: boolean;
  error: string | null;
  listSamples: () => Promise<SampleDocument[]>;
  uploadSample: (sampleId: string, prefix: string, version?: string) => Promise<{ success: boolean; objectKeys: string[]; error?: string }>;
}

const client = generateClient();
const logger = new ConsoleLogger('useSampleDocuments');

const useSampleDocuments = (): UseSampleDocumentsReturn => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listSamples = async (): Promise<SampleDocument[]> => {
    setLoading(true);
    setError(null);

    try {
      const result = await client.graphql({ query: listSampleDocumentsOp });
      const response = result.data.listSampleDocuments;

      if (!response?.success) {
        throw new Error(response?.error || 'Failed to list sample documents');
      }

      return (response.samples?.filter((s): s is NonNullable<typeof s> => s !== null) ?? []) as SampleDocument[];
    } catch (err: unknown) {
      logger.error('Error listing sample documents:', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return [];
    } finally {
      setLoading(false);
    }
  };

  const uploadSample = async (
    sampleId: string,
    prefix: string,
    version?: string,
  ): Promise<{ success: boolean; objectKeys: string[]; error?: string }> => {
    setLoading(true);
    setError(null);

    try {
      const result = await client.graphql({
        query: uploadSampleDocumentOp,
        variables: { sampleId, prefix: prefix || '', version },
      });
      const response = result.data.uploadSampleDocument;

      if (!response?.success) {
        throw new Error(response?.error || 'Failed to upload sample document');
      }

      return {
        success: true,
        objectKeys: (response.objectKeys?.filter((k): k is string => !!k) ?? []) as string[],
      };
    } catch (err: unknown) {
      logger.error('Error uploading sample document:', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return { success: false, objectKeys: [], error: message };
    } finally {
      setLoading(false);
    }
  };

  return { loading, error, listSamples, uploadSample };
};

export default useSampleDocuments;
