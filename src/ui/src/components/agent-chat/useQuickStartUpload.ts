// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useRef, useState } from 'react';
import { generateClient } from 'aws-amplify/api';
import JSZip from 'jszip';
import { ConsoleLogger } from 'aws-amplify/utils';
import { uploadMultiDocDiscoveryZip, startMultiDocDiscovery, onDiscoveryJobStatusChange } from '../../graphql/generated';

const logger = new ConsoleLogger('useQuickStartUpload');
const client = generateClient();

export interface QuickStartUploadStatus {
  jobId: string | null;
  status: string;
  currentStep?: string;
  totalDocuments?: number;
  clustersFound?: number;
  discoveredClasses?: string;
  reflectionReport?: string;
  errorMessage?: string;
}

export interface QuickStartUploadResult {
  jobId: string;
  classNames: string[];
  totalDocuments: number;
  clustersFound: number;
  configVersion: string;
}

interface UseQuickStartUploadArgs {
  onComplete?: (result: QuickStartUploadResult) => void;
  onError?: (message: string) => void;
}

const TERMINAL = ['COMPLETED', 'FAILED'];

const toZip = async (files: File[]): Promise<File> => {
  if (files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')) {
    return files[0];
  }
  const zip = new JSZip();
  files.forEach((file) => zip.file(file.name, file));
  const blob = await zip.generateAsync({ type: 'blob' });
  return new File([blob], `quick-start-${Date.now()}.zip`, { type: 'application/zip' });
};

const parseClassNames = (discoveredClasses?: string): string[] => {
  if (!discoveredClasses) return [];
  try {
    const parsed = JSON.parse(discoveredClasses);
    if (Array.isArray(parsed)) {
      return parsed.map((c) => c.classification || c.class_name || c.$id).filter(Boolean);
    }
  } catch {
    logger.warn('Could not parse discoveredClasses');
  }
  return [];
};

const useQuickStartUpload = ({ onComplete, onError }: UseQuickStartUploadArgs = {}) => {
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<QuickStartUploadStatus | null>(null);
  const subscriptionRef = useRef<{ unsubscribe: () => void } | null>(null);
  const configVersionRef = useRef<string>('');

  useEffect(
    () => () => {
      subscriptionRef.current?.unsubscribe();
    },
    [],
  );

  const subscribe = useCallback(
    (jobId: string) => {
      subscriptionRef.current?.unsubscribe();
      const observable = client.graphql({ query: onDiscoveryJobStatusChange, variables: { jobId } });
      subscriptionRef.current = (observable as unknown as { subscribe: (h: unknown) => { unsubscribe: () => void } }).subscribe({
        next: ({ data }: { data?: { onDiscoveryJobStatusChange?: QuickStartUploadStatus } }) => {
          const update = data?.onDiscoveryJobStatusChange;
          if (!update) return;
          setStatus((prev) => ({ ...(prev || { jobId, status: 'QUEUED' }), ...update }));
          if (TERMINAL.includes(update.status)) {
            subscriptionRef.current?.unsubscribe();
            subscriptionRef.current = null;
            if (update.status === 'COMPLETED') {
              onComplete?.({
                jobId,
                classNames: parseClassNames(update.discoveredClasses),
                totalDocuments: update.totalDocuments || 0,
                clustersFound: update.clustersFound || 0,
                configVersion: configVersionRef.current,
              });
            } else {
              onError?.(update.errorMessage || 'Document discovery failed');
            }
          }
        },
        error: (err: unknown) => {
          logger.error('Subscription error', err);
          onError?.('Lost connection to discovery job updates');
        },
      });
    },
    [onComplete, onError],
  );

  const startUpload = useCallback(
    async (files: File[], configVersion: string) => {
      if (!files.length) return;
      configVersionRef.current = configVersion;
      setUploading(true);
      setStatus({ jobId: null, status: 'PREPARING', currentStep: 'Packaging documents' });
      try {
        const zipFile = await toZip(files);

        const uploadResponse = await client.graphql({
          query: uploadMultiDocDiscoveryZip,
          variables: { fileName: zipFile.name, fileSize: zipFile.size, configVersion },
        });
        const uploadData = (uploadResponse as { data?: { uploadMultiDocDiscoveryZip?: { presignedUrl?: string; objectKey?: string } } })
          ?.data?.uploadMultiDocDiscoveryZip;
        if (!uploadData?.presignedUrl || !uploadData?.objectKey) {
          throw new Error('Failed to get an upload URL');
        }

        const presignedPost = JSON.parse(uploadData.presignedUrl) as { url: string; fields: Record<string, string> };
        const formData = new FormData();
        Object.entries(presignedPost.fields).forEach(([key, value]) => formData.append(key, value));
        formData.append('file', zipFile);
        const postResult = await fetch(presignedPost.url, { method: 'POST', body: formData });
        if (!postResult.ok) {
          throw new Error(`Upload failed: ${postResult.statusText}`);
        }

        const startResponse = await client.graphql({
          query: startMultiDocDiscovery,
          variables: {
            configVersion,
            zipFileName: zipFile.name,
            zipFileSize: zipFile.size,
            s3Prefix: uploadData.objectKey,
          },
        });
        const job = (startResponse as { data?: { startMultiDocDiscovery?: QuickStartUploadStatus } })?.data?.startMultiDocDiscovery;
        if (!job?.jobId) {
          throw new Error('Failed to start document discovery');
        }
        setStatus({ ...job });
        subscribe(job.jobId);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Upload failed';
        logger.error('startUpload failed', err);
        setStatus(null);
        onError?.(message);
      } finally {
        setUploading(false);
      }
    },
    [subscribe, onError],
  );

  const reset = useCallback(() => {
    subscriptionRef.current?.unsubscribe();
    subscriptionRef.current = null;
    setStatus(null);
  }, []);

  return { startUpload, uploading, status, reset };
};

export default useQuickStartUpload;
