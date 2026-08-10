// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * GroundTruthVisualEditor — edit a test set document's ground truth beside its
 * page images (Document Details' Visual Editor, recomposed for test sets).
 *
 * Left: page images rendered client-side from the source doc (no processed
 * page images exist for test set docs — see useTestDocPages). Right: tabs with
 * a visual form over the baseline's `inference_result` (plus document class /
 * page indices) and a raw JSON editor. Bounding boxes appear when the baseline
 * carries `explainability_info` geometry (i.e. it was minted via Copy to
 * Baseline from a processed doc); hand-built baselines simply have no boxes.
 *
 * Saves write the whole section result.json back to its TestSetBucket
 * baseline key via the uploadDocument presigned POST (Admin/Author only),
 * appending an _editHistory entry for provenance like VisualEditorModal does.
 */

import React, { useState, useEffect, useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  FormField,
  Header,
  Input,
  Select,
  SegmentedControl,
  SpaceBetween,
  Spinner,
  Tabs,
} from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getFilePresignedUrl, uploadDocument } from '../../graphql/generated';
import useAppContext from '../../contexts/app';
import PageImageViewer from '../common/PageImageViewer';
import FormFieldRenderer from '../document-viewer/FormFieldRenderer';
import JSONEditorTab from '../document-viewer/JSONEditorTab';
import useTestDocPages from '../../hooks/use-test-doc-pages';

const client = generateClient();
const logger = new ConsoleLogger('GroundTruthVisualEditor');

export interface TestSetDocumentSectionRef {
  sectionId: string;
  baselineKey: string;
}

interface GroundTruthVisualEditorProps {
  bucket: string;
  inputKey: string;
  objectKey: string;
  sections: TestSetDocumentSectionRef[];
  isReadOnly: boolean;
  /** Called after a successful save (e.g. to show a flash message). */
  onSaved?: (baselineKey: string) => void;
  /**
   * Optional replacement for how a save is persisted.
   *
   * By default the editor writes the baseline object straight to S3 via a
   * presigned POST. That is right for an owner editing ground truth directly, but
   * it bypasses the HITL review API — so it never claims a lock, never tags the
   * label `reviewed-human`, and never feeds the confidence curve that the
   * review-effort estimator learns from.
   *
   * The annotation workspace supplies this to route saves through
   * `completeSectionReview` instead, which engages all of the above. When absent
   * the direct-S3 path is unchanged, so existing callers keep their behaviour.
   */
  onSave?: (sectionId: string, data: Record<string, unknown>) => Promise<void>;
  /** Label for the save button (the queue uses "Save & next in queue"). */
  saveButtonText?: string;
}

const getSectionLabel = (sectionId: string, data: Record<string, unknown> | null): string => {
  const docClass = (data?.document_class as Record<string, unknown> | undefined)?.type;
  return docClass ? `Section ${sectionId} (${String(docClass)})` : `Section ${sectionId}`;
};

const GroundTruthVisualEditor = ({
  bucket,
  inputKey,
  objectKey,
  sections,
  isReadOnly,
  onSaved,
  onSave,
  saveButtonText,
}: GroundTruthVisualEditorProps): React.JSX.Element => {
  const { user } = useAppContext();
  const { pages, isLoading: pagesLoading, error: pagesError, previewUnavailable } = useTestDocPages(bucket, inputKey);

  const [selectedSectionId, setSelectedSectionId] = useState<string>(sections[0]?.sectionId ?? '1');
  const [localData, setLocalData] = useState<Record<string, unknown> | null>(null);
  const [originalJson, setOriginalJson] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeFieldGeometry, setActiveFieldGeometry] = useState<Record<string, unknown> | null>(null);
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(new Set());
  // Same filter the HITL review editor offers. On a document with 169 fields the
  // handful below threshold are what a reviewer is actually there for, and
  // scrolling to find them is most of the work.
  const [filterMode, setFilterMode] = useState<SelectProps.Option>({ label: 'Show all fields', value: 'none' });
  const [activeTabId, setActiveTabId] = useState('visual');

  const selectedSection = sections.find((s) => s.sectionId === selectedSectionId) ?? sections[0];

  // Reset to the first section when switching documents.
  useEffect(() => {
    setSelectedSectionId(sections[0]?.sectionId ?? '1');
  }, [inputKey, sections]);

  // Load the selected section's baseline result.json. Bytes are fetched
  // straight from S3 via a server-issued presigned URL (same rationale as
  // JSONViewer: no Lambda 6MB cap, and the resolver's bucket allow-list
  // covers the TestSetBucket).
  useEffect(() => {
    if (!selectedSection) {
      setLocalData(null);
      setOriginalJson(null);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      setError(null);
      setActiveFieldGeometry(null);
      try {
        const s3Uri = `s3://${bucket}/${selectedSection.baselineKey}`;
        const response = await client.graphql({
          query: getFilePresignedUrl,
          variables: { s3Uri },
        });
        const presignedUrl = response.data?.getFilePresignedUrl?.presignedUrl;
        if (!presignedUrl) throw new Error('No presigned URL returned by server');
        const s3Response = await fetch(presignedUrl);
        if (!s3Response.ok) throw new Error(`S3 fetch failed: ${s3Response.status}`);
        const text = await s3Response.text();
        if (cancelled) return;
        setLocalData(JSON.parse(text));
        setOriginalJson(text);
      } catch (err) {
        logger.error('Error loading baseline:', err);
        if (!cancelled) setError(`Failed to load ground truth: ${(err as Error).message}`);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [bucket, selectedSection?.baselineKey]);

  const hasChanges = useMemo(() => {
    if (!localData || originalJson === null) return false;
    try {
      return JSON.stringify(localData) !== JSON.stringify(JSON.parse(originalJson));
    } catch {
      return true;
    }
  }, [localData, originalJson]);

  // Warn on tab close with unsaved edits.
  useEffect(() => {
    if (!hasChanges) return undefined;
    const beforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [hasChanges]);

  const explainabilityInfo = (localData?.explainability_info as Record<string, unknown> | Record<string, unknown>[] | null) ?? null;
  const inferenceResult =
    (localData?.inference_result as Record<string, unknown> | undefined) ??
    (localData?.inferenceResult as Record<string, unknown> | undefined) ??
    null;

  // Packet-splitting baselines carry the section's document-absolute page
  // indices (0-based). Use them to restrict the image pane to this section's
  // pages; otherwise show the whole document.
  const splitPageIndices = (localData?.split_document as Record<string, unknown> | undefined)?.page_indices as number[] | undefined;
  const sectionPages = useMemo(() => {
    if (!splitPageIndices?.length || pages.length === 0) return pages;
    return splitPageIndices.map((idx) => pages[idx]).filter(Boolean);
  }, [pages, splitPageIndices]);
  const pageIds = useMemo(() => sectionPages.map((p) => p.Id), [sectionPages]);

  const documentClassType = (localData?.document_class as Record<string, unknown> | undefined)?.type as string | undefined;

  const updateInferenceResult = (newValue: Record<string, unknown>) => {
    if (isReadOnly || !localData) return;
    const updated = { ...localData };
    if (updated.inference_result !== undefined) {
      updated.inference_result = newValue;
    } else if (updated.inferenceResult !== undefined) {
      updated.inferenceResult = newValue;
    } else {
      updated.inference_result = newValue;
    }
    setLocalData(updated);
  };

  const updateDocumentClass = (newType: string) => {
    if (isReadOnly || !localData) return;
    const docClass = { ...((localData.document_class as Record<string, unknown>) ?? {}), type: newType };
    setLocalData({ ...localData, document_class: docClass });
  };

  const handleSave = async () => {
    if (!selectedSection || !localData) return;
    setIsSaving(true);
    setError(null);
    try {
      // Append an edit-history entry (same provenance convention as
      // VisualEditorModal) so GT edits are auditable in the file itself.
      const dataToSave: Record<string, unknown> = { ...localData };
      const editHistory = (dataToSave._editHistory as unknown[]) || [];
      editHistory.push({
        timestamp: new Date().toISOString(),
        editedBy: (user as { username?: string } | undefined)?.username || 'unknown',
        source: 'test-set-ground-truth-editor',
      });
      dataToSave._editHistory = editHistory;
      const editedContent = JSON.stringify(dataToSave, null, 2);

      const fullPath = selectedSection.baselineKey;

      // Caller-supplied persistence (the annotation workspace routes through the
      // review API so the save claims, tags and teaches the confidence curve).
      if (onSave) {
        await onSave(selectedSection.sectionId, dataToSave);
        setLocalData(dataToSave);
        setOriginalJson(editedContent);
        logger.info('Saved ground truth via caller-supplied handler for', fullPath);
        if (onSaved) onSaved(fullPath);
        return;
      }

      const fileName = fullPath.split('/').pop() ?? fullPath;
      const prefix = fullPath.substring(0, fullPath.lastIndexOf('/'));

      const response = await client.graphql({
        query: uploadDocument,
        variables: { fileName, contentType: 'application/json', prefix, bucket },
      });
      const { presignedUrl, usePostMethod } = response.data.uploadDocument;
      if (usePostMethod?.toLowerCase() !== 'true') {
        throw new Error('Server returned PUT method which is not supported');
      }
      const presignedPostData = JSON.parse(presignedUrl);
      const formData = new FormData();
      Object.entries(presignedPostData.fields as Record<string, string>).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append('file', new Blob([editedContent], { type: 'application/json' }), fileName);
      const uploadResponse = await fetch(presignedPostData.url, { method: 'POST', body: formData });
      if (!uploadResponse.ok) {
        const errorText = await uploadResponse.text().catch(() => 'Could not read error response');
        throw new Error(`Upload failed: ${errorText}`);
      }

      setLocalData(dataToSave);
      setOriginalJson(editedContent);
      logger.info('Saved ground truth to', fullPath);
      if (onSaved) onSaved(fullPath);
    } catch (err) {
      logger.error('Error saving ground truth:', err);
      setError(`Failed to save: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDiscard = () => {
    if (originalJson !== null) {
      setLocalData(JSON.parse(originalJson));
    }
  };

  const handleFieldFocus = (geometry: Record<string, unknown> | null) => {
    setActiveFieldGeometry(geometry ?? null);
  };

  const handleToggleCollapse = (pathKey: string) => {
    setCollapsedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(pathKey)) next.delete(pathKey);
      else next.add(pathKey);
      return next;
    });
  };

  const handleSectionChange = (sectionId: string) => {
    if (hasChanges && !window.confirm('You have unsaved ground truth changes. Discard them and switch sections?')) {
      return;
    }
    setSelectedSectionId(sectionId);
  };

  if (sections.length === 0) {
    return <Alert type="warning">No ground truth (baseline) sections found for {objectKey}.</Alert>;
  }

  return (
    <SpaceBetween size="s">
      <Header
        variant="h3"
        actions={
          !isReadOnly && (
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={handleDiscard} disabled={!hasChanges || isSaving}>
                Discard changes
              </Button>
              <Button variant="primary" onClick={handleSave} loading={isSaving} disabled={!hasChanges}>
                {saveButtonText ?? 'Save changes'}
              </Button>
            </SpaceBetween>
          )
        }
      >
        Ground truth — {objectKey}
      </Header>

      {sections.length > 1 && (
        <SegmentedControl
          selectedId={selectedSectionId}
          onChange={({ detail }) => handleSectionChange(detail.selectedId)}
          options={sections.map((s) => ({
            id: s.sectionId,
            text: s.sectionId === selectedSectionId ? getSectionLabel(s.sectionId, localData) : `Section ${s.sectionId}`,
          }))}
        />
      )}

      {error && <Alert type="error">{error}</Alert>}
      {!explainabilityInfo && localData && (
        <Alert type="info">No field geometry available for this baseline — bounding-box highlighting is disabled.</Alert>
      )}

      <div style={{ display: 'flex', gap: '16px', alignItems: 'stretch' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {pagesLoading && (
            <Box textAlign="center" padding="xl">
              <Spinner /> Rendering document pages…
            </Box>
          )}
          {previewUnavailable && (
            <Alert type="info">
              Preview is not available for TIFF documents — use View Source Document to download. Ground truth editing still works.
            </Alert>
          )}
          {pagesError && <Alert type="error">{pagesError}</Alert>}
          {!pagesLoading && sectionPages.length > 0 && (
            <PageImageViewer pageIds={pageIds} documentPages={sectionPages} activeFieldGeometry={activeFieldGeometry} />
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0, maxHeight: '760px', overflowY: 'auto' }}>
          {isLoading && (
            <Box textAlign="center" padding="xl">
              <Spinner /> Loading ground truth…
            </Box>
          )}
          {!isLoading && localData && (
            <Tabs
              activeTabId={activeTabId}
              onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
              tabs={[
                {
                  id: 'visual',
                  label: 'Visual Editor',
                  content: (
                    <SpaceBetween size="s">
                      {documentClassType !== undefined && (
                        <FormField label="Document class" description="Expected classification for this section">
                          <Input
                            value={documentClassType ?? ''}
                            onChange={({ detail }) => updateDocumentClass(detail.value)}
                            disabled={isReadOnly}
                          />
                        </FormField>
                      )}
                      {splitPageIndices !== undefined && (
                        <FormField label="Page indices" description="0-based pages of this section within the document (read-only)">
                          <Input value={JSON.stringify(splitPageIndices)} disabled />
                        </FormField>
                      )}
                      {inferenceResult ? (
                        <>
                          <FormField label="Fields to show">
                            <Select
                              selectedOption={filterMode}
                              onChange={({ detail }) => setFilterMode(detail.selectedOption)}
                              options={[
                                { label: 'Show all fields', value: 'none' },
                                { label: 'Confidence alerts only', value: 'confidence-alerts' },
                              ]}
                            />
                          </FormField>
                          <FormFieldRenderer
                            fieldKey="Document Data"
                            value={inferenceResult}
                            onChange={updateInferenceResult}
                            isReadOnly={isReadOnly}
                            onFieldFocus={handleFieldFocus}
                            onFieldDoubleClick={handleFieldFocus}
                            path={[]}
                            explainabilityInfo={explainabilityInfo}
                            collapsedPaths={collapsedPaths}
                            onToggleCollapse={handleToggleCollapse}
                            filterMode={filterMode.value}
                            displayPath={[]}
                          />
                        </>
                      ) : (
                        <Alert type="warning">This baseline has no inference_result — use the JSON editor tab.</Alert>
                      )}
                    </SpaceBetween>
                  ),
                },
                {
                  id: 'json',
                  label: 'JSON Editor',
                  content: (
                    <JSONEditorTab
                      predictionData={localData}
                      baselineData={null}
                      isReadOnly={isReadOnly}
                      onPredictionChange={(data) => setLocalData(data)}
                      showBaseline={false}
                      isBaselineAvailable={false}
                      loadingEvaluation={false}
                    />
                  ),
                },
              ]}
            />
          )}
        </div>
      </div>
    </SpaceBetween>
  );
};

export default GroundTruthVisualEditor;
