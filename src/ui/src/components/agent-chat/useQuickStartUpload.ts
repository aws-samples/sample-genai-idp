// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useRef, useState } from 'react';
import JSZip from 'jszip';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { uploadMultiDocDiscoveryZip, startMultiDocDiscovery, listDiscoveryJobs, uploadDiscoveryDocument } from '../../graphql/generated';

const logger = new ConsoleLogger('useQuickStartUpload');
const client = generateClient();

const POLL_INTERVAL_MS = 5000;

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
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const configVersionRef = useRef<string>('');

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // AppSync subscriptions were removed with the REST migration, so status is
  // tracked by polling listDiscoveryJobs and matching our jobId, mirroring
  // MultiDocDiscoveryPanel.
  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      const poll = async () => {
        try {
          const resp = await client.graphql({ query: listDiscoveryJobs });
          const jobs =
            (resp as { data?: { listDiscoveryJobs?: { DiscoveryJobs?: (QuickStartUploadStatus & { jobId: string })[] } } })?.data
              ?.listDiscoveryJobs?.DiscoveryJobs || [];
          const update = jobs.find((j) => j.jobId === jobId);
          if (!update) return;
          setStatus((prev) => ({ ...(prev || { jobId, status: 'QUEUED' }), ...update }));
          if (TERMINAL.includes(update.status)) {
            stopPolling();
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
        } catch (err) {
          logger.error('Discovery status poll failed', err);
        }
      };
      pollTimerRef.current = setInterval(poll, POLL_INTERVAL_MS);
      void poll();
    },
    [onComplete, onError, stopPolling],
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
        startPolling(job.jobId);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Upload failed';
        logger.error('startUpload failed', err);
        setStatus(null);
        onError?.(message);
      } finally {
        setUploading(false);
      }
    },
    [startPolling, onError],
  );

  const reset = useCallback(() => {
    stopPolling();
    setStatus(null);
  }, [stopPolling]);

  return { startUpload, uploading, status, reset };
};

export default useQuickStartUpload;
