// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Faithful stand-in for the EXISTING Visual Document Editor modal
// (src/components/document-viewer/VisualEditorModal.tsx) for the fixture-driven
// prototype. Mirrors the real widget's structure exactly — title, tabs
// (Visual Editor / JSON Editor / Revision History / Processing Report), the
// Document Pages pane with zoom/pan, the Document Data pane with Expand All /
// Collapse All / "Confidence Alerts Only", per-field Confidence/Threshold +
// editable Predicted value, and the Section / Previous / Next footer.
//
// IN THE REAL IMPLEMENTATION THIS COMPONENT IS NOT BUILT: these screens open
// the actual VisualEditorModal unchanged. This file exists only so the
// prototype can show that experience with dummy data.
import React from 'react';
import { Badge, Box, Button, Container, Header, SpaceBetween } from '@cloudscape-design/components';
import { PREVIEW_FIELDS } from './fixtures';

interface Props {
  docName: string;
  /** Show all fields or only the sub-threshold ones (mirrors the real filter). */
  filter?: 'alerts' | 'all';
  onPrev?: () => void;
  onNext?: () => void;
  nextLabel?: string;
  onClose?: () => void;
}

const MockVisualDocumentEditor = ({
  docName,
  filter = 'alerts',
  onPrev,
  onNext,
  nextLabel = 'Next Section ›',
  onClose,
}: Props): React.JSX.Element => {
  const fields = filter === 'alerts' ? PREVIEW_FIELDS.filter((f) => f.confidence < f.threshold + 0.02) : PREVIEW_FIELDS;
  return (
    <Container
      header={
        <Header variant="h2" actions={<Badge color="grey">existing widget — reused unchanged</Badge>}>
          Visual Document Editor
        </Header>
      }
    >
      <SpaceBetween size="m">
        {/* Tabs exactly as the real modal presents them */}
        <div style={{ display: 'flex', gap: 24, borderBottom: '1px solid #e9ebed', paddingBottom: 0 }}>
          {['Visual Editor', 'JSON Editor', 'Revision History', 'Processing Report'].map((t, i) => (
            <span
              key={t}
              style={{
                padding: '6px 2px 10px',
                fontWeight: i === 0 ? 700 : 400,
                color: i === 0 ? '#006ce0' : '#5f6b7a',
                borderBottom: i === 0 ? '2px solid #006ce0' : '2px solid transparent',
                fontSize: 14,
              }}
            >
              {t}
            </span>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 18 }}>
          {/* Document Pages (left) */}
          <div style={{ flex: 1.1 }}>
            <Box variant="h4">Document Pages (1)</Box>
            <div
              style={{
                border: '1px solid #e9ebed',
                borderRadius: 8,
                background: '#f7f8f9',
                height: 340,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <div
                style={{
                  background: '#fff',
                  width: '74%',
                  height: '86%',
                  boxShadow: '0 1px 6px rgba(0,0,0,.15)',
                  padding: 12,
                  fontFamily: 'monospace',
                  fontSize: 9,
                  color: '#3a3f47',
                  lineHeight: 1.8,
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 11 }}>AIR PRODUCTS AND CHEMICALS, INC.</div>
                <div>
                  INVOICE No. <span style={{ outline: '2px solid #d91515', background: '#fde7e7', padding: '0 2px' }}>A-4471-X6</span>
                </div>
                <div>
                  PO: <span style={{ outline: '2px solid #e5931a', background: '#fff6df', padding: '0 2px' }}>4500-7789-02</span>
                </div>
                <div>
                  Tax: <span style={{ outline: '2px solid #e5931a', background: '#fff6df', padding: '0 2px' }}>$50.49</span> · Total:
                  $662.49
                </div>
                <div style={{ marginTop: 12, color: '#8d6605' }}>[{docName} — page image + bounding boxes]</div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 13, color: '#5f6b7a' }}>
              <span>‹ › Page 1 of 1</span>
              <span>
                <strong>Zoom:</strong> − 100% + &nbsp; <strong>Pan:</strong> ← → ↑ ↓ ↺
              </span>
            </div>
          </div>

          {/* Document Data (right) */}
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Box variant="h4">Document Data</Box>
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link">+ Expand All</Button>
                <Button variant="inline-link">− Collapse All</Button>
                <Button variant="inline-link">{filter === 'alerts' ? 'Confidence Alerts Only ▾' : 'Show All ▾'}</Button>
              </SpaceBetween>
            </div>
            <div style={{ border: '1px solid #e9ebed', borderRadius: 8, padding: '4px 14px 12px', maxHeight: 340, overflow: 'auto' }}>
              <Box variant="h5">▾ Document Data</Box>
              {fields.map((f) => (
                <div key={f.name} style={{ padding: '8px 0' }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{f.name}:</div>
                  <div style={{ fontSize: 12, color: f.confidence < f.threshold ? '#d91515' : '#5f6b7a', margin: '2px 0' }}>
                    Confidence: {(f.confidence * 100).toFixed(1)}% / Threshold: {(f.threshold * 100).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: 12, color: '#5f6b7a', margin: '2px 0' }}>Predicted:</div>
                  <input
                    defaultValue={f.value}
                    aria-label={`${f.name} predicted value`}
                    style={{
                      width: '100%',
                      padding: '7px 10px',
                      background: '#eef0f2',
                      border: '1px solid #e9ebed',
                      borderRadius: 6,
                      fontSize: 13,
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer exactly as the real modal: Section/Type + nav */}
        <div
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #e9ebed', paddingTop: 12 }}
        >
          <Box fontSize="body-s">
            <strong>Section:</strong> 2 &nbsp; <strong>Type:</strong> Invoice
          </Box>
          <SpaceBetween direction="horizontal" size="xs">
            {onPrev && <Button onClick={onPrev}>‹ Previous Section</Button>}
            {onNext && (
              <Button variant="primary" onClick={onNext}>
                {nextLabel}
              </Button>
            )}
            {onClose && <Button onClick={onClose}>Close</Button>}
          </SpaceBetween>
        </div>
      </SpaceBetween>
    </Container>
  );
};

export default MockVisualDocumentEditor;
