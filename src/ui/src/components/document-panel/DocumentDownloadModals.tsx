// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import { Alert, Box, Button, Checkbox, Modal, ProgressBar, SpaceBetween } from '@cloudscape-design/components';
import type { ExportErrorEntry, ExportProgress } from './document-export';

interface DownloadOptionsModalProps {
  visible: boolean;
  includePageImages: boolean;
  includeSourceDocument: boolean;
  onIncludePageImagesChange: (value: boolean) => void;
  onIncludeSourceDocumentChange: (value: boolean) => void;
  onConfirm: () => void;
  onDismiss: () => void;
}

/** Shown only when the user selects "Download All"; toggles heavy optional assets. */
export const DownloadOptionsModal = ({
  visible,
  includePageImages,
  includeSourceDocument,
  onIncludePageImagesChange,
  onIncludeSourceDocumentChange,
  onConfirm,
  onDismiss,
}: DownloadOptionsModalProps): React.JSX.Element => (
  <Modal
    visible={visible}
    onDismiss={onDismiss}
    header="Download all document data"
    footer={
      <Box float="right">
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={onDismiss}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm}>
            Start download
          </Button>
        </SpaceBetween>
      </Box>
    }
  >
    <SpaceBetween size="s">
      <Box>
        Packages the document summary, section predictions, baselines (when available), per-page text, and confidence into a single ZIP
        archive. Folder structure mirrors the S3 buckets (<code>output/</code>, <code>baseline/</code>, <code>input/</code>).
      </Box>
      <Checkbox checked={includePageImages} onChange={({ detail }) => onIncludePageImagesChange(detail.checked)}>
        Include page images (can significantly increase archive size)
      </Checkbox>
      <Checkbox checked={includeSourceDocument} onChange={({ detail }) => onIncludeSourceDocumentChange(detail.checked)}>
        Include source document (original uploaded file from the input bucket)
      </Checkbox>
    </SpaceBetween>
  </Modal>
);

interface DownloadProgressModalProps {
  visible: boolean;
  progress: ExportProgress | null;
  errors: ExportErrorEntry[];
  isFinished: boolean;
  onCancel: () => void;
  onClose: () => void;
}

/** Long-running progress + error summary modal shown during exports. */
export const DownloadProgressModal = ({
  visible,
  progress,
  errors,
  isFinished,
  onCancel,
  onClose,
}: DownloadProgressModalProps): React.JSX.Element => {
  const total = progress?.total ?? 1;
  const completed = progress?.completed ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  return (
    <Modal
      visible={visible}
      onDismiss={isFinished ? onClose : undefined}
      header={isFinished ? 'Download complete' : 'Preparing download'}
      footer={
        <Box float="right">
          {isFinished ? (
            <Button variant="primary" onClick={onClose}>
              Close
            </Button>
          ) : (
            <Button variant="link" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </Box>
      }
    >
      <SpaceBetween size="s">
        <ProgressBar
          value={pct}
          additionalInfo={progress?.currentFile ?? ''}
          description={`${completed} of ${total} files processed`}
          label="Export progress"
        />
        {errors.length > 0 && (
          <Alert type="warning" header={`${errors.length} file(s) could not be included`}>
            <Box>
              These entries were skipped and recorded in the archive&apos;s <code>manifest.json</code>:
            </Box>
            <ul style={{ marginTop: '8px', maxHeight: '160px', overflow: 'auto' }}>
              {errors.slice(0, 25).map((e) => (
                <li key={`${e.path}-${e.message}`}>
                  <code>{e.path}</code>: {e.message}
                </li>
              ))}
              {errors.length > 25 && <li>…and {errors.length - 25} more</li>}
            </ul>
          </Alert>
        )}
      </SpaceBetween>
    </Modal>
  );
};
