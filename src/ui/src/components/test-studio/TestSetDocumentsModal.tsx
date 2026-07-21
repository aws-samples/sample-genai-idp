// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Box, SpaceBetween, Spinner, Alert, Grid, Button } from '@cloudscape-design/components';
import { generateClient } from '../../api/client-shim';
import { listBucketFiles } from '../../graphql/generated';
import useSettingsContext from '../../contexts/settings';
import FileViewer from '../document-viewer/FileViewer';
import { getErrorMessage } from '../../utils/errorUtils';

const client = generateClient();

interface TestSetDocumentsModalProps {
  visible: boolean;
  onDismiss: () => void;
  // The test set's ID — its folder in the test-set bucket is <id>/input/*.
  testSetId: string;
  // Display name (for the modal header); may differ from the ID.
  testSetName: string;
}

/**
 * Previews the documents in a test set (generated or uploaded) without running a
 * test execution. Lists the test set's input files from the test-set bucket and
 * renders the selected one with the shared FileViewer.
 */
const TestSetDocumentsModal = ({ visible, onDismiss, testSetId, testSetName }: TestSetDocumentsModalProps): React.JSX.Element => {
  const { settings } = useSettingsContext();
  const testSetBucket = (settings as Record<string, unknown>).TestSetBucket as string | undefined;
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!visible || !testSetId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setSelected(null);
    client
      .graphql({
        query: listBucketFiles,
        variables: { bucketType: 'testset', filePattern: `${testSetId}/input/*` },
      })
      .then((result) => {
        if (cancelled) return;
        const found = ((result.data.listBucketFiles || []) as (string | null)[]).filter((f): f is string => Boolean(f));
        setFiles(found);
        if (found.length > 0) setSelected(found[0]);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, testSetId]);

  const fileName = (key: string): string => key.split('/').pop() || key;

  const fileList = useMemo(
    () =>
      files.map((key) => (
        <Button key={key} variant={key === selected ? 'primary' : 'normal'} onClick={() => setSelected(key)} fullWidth>
          {fileName(key)}
        </Button>
      )),
    [files, selected],
  );

  return (
    <Modal visible={visible} onDismiss={onDismiss} header={`Documents in "${testSetName}"`} size="max">
      {loading ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : error ? (
        <Alert type="error" header="Could not load documents">
          {error}
        </Alert>
      ) : files.length === 0 ? (
        <Box color="text-body-secondary" padding="s">
          No documents found for this test set. If it was just generated and generation is still running, they will appear when it
          completes.
        </Box>
      ) : (
        <Grid gridDefinition={[{ colspan: 3 }, { colspan: 9 }]}>
          <SpaceBetween size="xs">
            <Box variant="small" color="text-body-secondary">
              {files.length} document(s)
            </Box>
            {fileList}
          </SpaceBetween>
          <Box>{selected && <FileViewer objectKey={selected} bucket={testSetBucket} />}</Box>
        </Grid>
      )}
    </Modal>
  );
};

export default TestSetDocumentsModal;
