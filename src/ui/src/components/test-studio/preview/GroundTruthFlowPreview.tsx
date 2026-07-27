// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// PROTOTYPE — clickable UX walkthrough of the ground-truth test-set flow,
// driven entirely by fixture data (see fixtures.ts). Mounted at
// #/test-studio/preview so it renders on the live accelerator for UX review
// BEFORE full backend wiring. No AWS calls. Real Cloudscape components so it
// looks and feels native. Swap fixtures for real hooks once the UX is locked.
import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Cards,
  ColumnLayout,
  Container,
  Header,
  KeyValuePairs,
  Link,
  ProgressBar,
  SpaceBetween,
  Table,
} from '@cloudscape-design/components';
import {
  PREVIEW_TEST_SETS,
  PREVIEW_DOCS,
  PREVIEW_QUEUE,
  PREVIEW_FIELDS,
  PREVIEW_ESTIMATE,
  PREVIEW_BURNDOWN,
  type PreviewTestSet,
  type LabelSource,
} from './fixtures';

type View = 'list' | 'chooser' | 'detail' | 'configure' | 'annotate' | 'publish';

const sourceBadge = (s: PreviewTestSet['source']): React.JSX.Element => {
  const color = s === 'Synthetic' ? 'grey' : s === 'Mixed' ? 'blue' : 'green';
  return <Badge color={color}>{s}</Badge>;
};

const stageBadge = (s: PreviewTestSet['stage']): React.JSX.Element => {
  if (s === 'published') return <Badge color="green">Published</Badge>;
  if (s === 'in-review') return <Badge color="blue">In review</Badge>;
  return <Badge color="grey">Draft</Badge>;
};

const labelSourceBadge = (s: LabelSource): React.JSX.Element => {
  switch (s) {
    case 'synthetic':
      return <Badge color="grey">Synthetic</Badge>;
    case 'draft-machine':
      return <Badge color="blue">Draft (machine)</Badge>;
    case 'reviewed-human':
      return <Badge color="green">✓ Reviewed (human)</Badge>;
    case 'uploaded':
      return <Badge color="green">Uploaded</Badge>;
    default:
      return <Badge color="grey">Unlabeled</Badge>;
  }
};

const confidenceBadge = (c: number | null): React.JSX.Element => {
  if (c === null) return <Box color="text-status-inactive">n/a</Box>;
  const color = c < 0.7 ? 'red' : c < 0.9 ? 'severity-medium' : 'green';
  return <Badge color={color as never}>{c.toFixed(2)}</Badge>;
};

const GroundTruthFlowPreview = (): React.JSX.Element => {
  const [view, setView] = useState<View>('list');
  const [selected, setSelected] = useState<PreviewTestSet>(PREVIEW_TEST_SETS[0]);
  const [reviewMode, setReviewMode] = useState<'lowest' | 'all' | 'accept'>('lowest');
  const [showMath, setShowMath] = useState(false);
  const [queueIdx, setQueueIdx] = useState(0);

  const banner = (
    <Alert type="info" header="Prototype — dummy data">
      This is a clickable UX walkthrough of the proposed ground-truth test-set flow, driven by fixture data (no backend). Use it to review
      and refine the experience before we wire it up. Current step: <strong>{view}</strong>.{' '}
      {view !== 'list' && <Link onFollow={() => setView('list')}>← back to Test Sets</Link>}
    </Alert>
  );

  // ---- LIST -------------------------------------------------------------
  const listView = (
    <Container
      header={
        <Header
          variant="h2"
          description="A test set is a versioned collection of documents and their reviewed ground-truth labels."
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button>Refresh</Button>
              <Button variant="primary" onClick={() => setView('chooser')}>
                New Test Set
              </Button>
            </SpaceBetween>
          }
        >
          Test Sets ({PREVIEW_TEST_SETS.length})
        </Header>
      }
    >
      <Table
        variant="borderless"
        items={PREVIEW_TEST_SETS}
        columnDefinitions={[
          {
            id: 'name',
            header: 'Name',
            cell: (t) => (
              <SpaceBetween size="xxs">
                <Link
                  onFollow={() => {
                    setSelected(t);
                    setView('detail');
                  }}
                >
                  <strong>{t.name}</strong>
                </Link>
                <Box fontSize="body-s" color="text-body-secondary">
                  {t.description}
                </Box>
              </SpaceBetween>
            ),
          },
          {
            id: 'stage',
            header: 'Stage',
            cell: (t) => (
              <SpaceBetween size="xxs">
                {stageBadge(t.stage)}
                {t.stage === 'in-review' && (
                  <Box fontSize="body-s" color="text-body-secondary">
                    {t.reviewedPct}% reviewed
                  </Box>
                )}
              </SpaceBetween>
            ),
          },
          { id: 'docs', header: 'Docs', cell: (t) => t.docs },
          { id: 'source', header: 'Source', cell: (t) => sourceBadge(t.source) },
          {
            id: 'version',
            header: 'Version',
            cell: (t) =>
              t.activeReference ? <Badge color="blue">{`v${t.activeReference}`}</Badge> : <Box color="text-status-inactive">draft</Box>,
          },
          { id: 'ref', header: 'Active reference', cell: (t) => (t.activeReference ? `v${t.activeReference}` : '—') },
        ]}
      />
    </Container>
  );

  // ---- CHOOSER (4 on-ramps) --------------------------------------------
  const chooserView = (
    <Container
      header={
        <Header variant="h2" description="Get labeled documents to score a config against. Generate them, or bring your own.">
          New Test Set
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Box variant="h3">Generate synthetic (no documents needed)</Box>
        <Cards
          cardDefinition={{
            header: (item) => (
              <Link
                onFollow={() => {
                  setSelected(PREVIEW_TEST_SETS[3]);
                  setView('detail');
                }}
              >
                {item.title}
              </Link>
            ),
            sections: [
              { id: 'desc', content: (item) => <Box color="text-body-secondary">{item.desc}</Box> },
              { id: 'out', content: (item) => <Badge color="grey">{item.out}</Badge> },
            ],
          }}
          cardsPerRow={[{ cards: 2 }]}
          items={[
            {
              title: 'From an existing config ✦ recommended',
              desc: 'Pick a config version + document class; generate synthetic, labeled documents that match its schema exactly — no prompt. Best for testing a config you already have.',
              out: '→ Synthetic labeled set · schema-matched',
            },
            {
              title: 'Describe it',
              desc: 'No config yet? Describe the document type; we author a schema, then generate synthetic labeled documents. Cold-start path.',
              out: '→ Synthetic labeled set · from a prompt',
            },
          ]}
        />
        <Box variant="h3">Bring your documents</Box>
        <Cards
          cardDefinition={{
            header: (item) => (
              <Link
                onFollow={() => {
                  setSelected(PREVIEW_TEST_SETS[3]);
                  setView('detail');
                }}
              >
                {item.title}
              </Link>
            ),
            sections: [
              { id: 'desc', content: (item) => <Box color="text-body-secondary">{item.desc}</Box> },
              { id: 'out', content: (item) => <Badge color={item.color as never}>{item.out}</Badge> },
            ],
          }}
          cardsPerRow={[{ cards: 2 }]}
          items={[
            {
              title: 'Upload labeled docs',
              desc: 'You have documents and ground-truth labels (auto-detected on upload).',
              out: '→ Ready to publish',
              color: 'green',
            },
            {
              title: 'Upload documents only',
              desc: 'Real documents, no labels. Upload, then Generate draft labels by running the active config.',
              out: '→ Draft (machine) labels',
              color: 'blue',
            },
          ]}
        />
      </SpaceBetween>
    </Container>
  );

  // ---- DETAIL HUB -------------------------------------------------------
  const detailView = (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h1"
            description={`${selected.docs} documents · bound config: ${selected.boundConfig}`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button>Versions</Button>
                <Button onClick={() => setView('publish')}>Publish version</Button>
              </SpaceBetween>
            }
          >
            {selected.name} {stageBadge(selected.stage)}
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Alert type="info">
            <strong>Three steps:</strong> ① Add documents ✓ · ② Generate draft labels · ③ Publish a version. Optionally fix the
            lowest-confidence rows before publishing.
          </Alert>
          <ColumnLayout columns={2} variant="text-grid">
            <KeyValuePairs
              columns={1}
              items={[
                { label: 'Lifecycle stage', value: stageBadge(selected.stage) },
                { label: 'Documents', value: String(selected.docs) },
                { label: 'Source', value: sourceBadge(selected.source) },
              ]}
            />
            <KeyValuePairs
              columns={1}
              items={[
                { label: 'Bound config', value: selected.boundConfig },
                { label: 'Published version', value: selected.activeReference ? `v${selected.activeReference}` : 'none yet' },
                { label: 'Active reference', value: selected.activeReference ? `v${selected.activeReference}` : 'none yet' },
              ]}
            />
          </ColumnLayout>
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="primary">⚡ Generate draft labels</Button>
            <Button onClick={() => setView('configure')}>Set up team annotation →</Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>

      <Container
        header={
          <Header variant="h2" description="Click a row to view or fix labels. Sorted worst-confidence first.">
            Documents ({PREVIEW_DOCS.length} shown)
          </Header>
        }
      >
        <Table
          variant="borderless"
          items={PREVIEW_DOCS}
          columnDefinitions={[
            { id: 'name', header: 'Document', cell: (d) => <Link onFollow={() => setView('annotate')}>{d.name}</Link> },
            { id: 'vendor', header: 'Vendor / cluster', cell: (d) => d.vendor },
            { id: 'conf', header: 'Confidence', cell: (d) => confidenceBadge(d.minConfidence) },
            { id: 'src', header: 'Label source', cell: (d) => labelSourceBadge(d.labelSource) },
          ]}
        />
      </Container>
    </SpaceBetween>
  );

  // ---- CONFIGURE ANNOTATION EFFORT -------------------------------------
  const configureView = (
    <Container
      header={
        <Header variant="h2" description="Set how good the golden dataset needs to be; we estimate the minimum review effort.">
          Configure team annotation — {selected.name}
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Box variant="h3">How much should annotators review?</Box>
        <SpaceBetween size="xs">
          {(
            [
              [
                'lowest',
                'Review the lowest-confidence docs',
                'Focus human effort where the model is least sure. Highest accuracy gain per hour. (recommended)',
              ],
              ['all', 'Review everything', 'Every document gets human eyes. Highest confidence; most effort.'],
              ['accept', 'Accept machine labels as-is', 'No human review — publish draft labels directly. Fastest; lowest trust.'],
            ] as const
          ).map(([id, title, desc]) => (
            <Box key={id} padding="s">
              <div style={{ display: 'flex', gap: 8 }}>
                <input type="radio" aria-label={title} checked={reviewMode === id} onChange={() => setReviewMode(id)} />
                <span>
                  <strong>{title}</strong>
                  <br />
                  <Box variant="span" color="text-body-secondary" fontSize="body-s">
                    {desc}
                  </Box>
                </span>
              </div>
            </Box>
          ))}
        </SpaceBetween>

        <Link onFollow={() => setShowMath((v) => !v)}>{showMath ? '▾' : '▸'} Show the math — target a specific label accuracy</Link>
        {showMath && (
          <Container variant="stacked">
            <SpaceBetween size="m">
              <KeyValuePairs
                columns={4}
                items={[
                  { label: 'Est. current accuracy', value: `≈${PREVIEW_ESTIMATE.currentAccuracy}%` },
                  { label: 'Target', value: `${PREVIEW_ESTIMATE.target}%` },
                  { label: 'Docs to review', value: `≈${PREVIEW_ESTIMATE.docsToReview} / ${PREVIEW_ESTIMATE.totalDocs}` },
                  { label: 'Implied cutoff', value: `≈${PREVIEW_ESTIMATE.impliedCutoff}` },
                ]}
              />
              <Box>
                <Box variant="awsui-key-label">Error burndown (residual error % as lowest-confidence docs are reviewed)</Box>
                {/* Simple inline bar chart from fixture series */}
                <SpaceBetween size="xxs">
                  {PREVIEW_BURNDOWN.map((p) => (
                    <div key={p.reviewed} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 70, fontSize: 12, color: '#5f6b7a' }}>{p.reviewed} docs</span>
                      <div style={{ background: '#006ce0', height: 10, borderRadius: 3, width: `${p.residualError * 40}px` }} />
                      <span style={{ fontSize: 12 }}>{p.residualError}%</span>
                    </div>
                  ))}
                </SpaceBetween>
              </Box>
              <Alert type="warning">
                Rough estimate — based on a prior confidence–accuracy curve, not yet measured on this set. Self-corrects as your team
                reviews.
              </Alert>
            </SpaceBetween>
          </Container>
        )}

        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setView('detail')}>Cancel</Button>
          <Button variant="primary" onClick={() => setView('annotate')}>
            Continue → open annotation queue
          </Button>
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );

  // ---- ANNOTATION WORKSPACE --------------------------------------------
  const current = PREVIEW_QUEUE[Math.min(queueIdx, PREVIEW_QUEUE.length - 1)];
  const annotateView = (
    <SpaceBetween size="m">
      <Container
        header={
          <Header
            variant="h2"
            description="You are assigned to this test set. Work the queue lowest-confidence first."
            actions={<Badge color="severity-medium">⏱ ends Fri 5:00 PM · 1d 4h left</Badge>}
          >
            Annotate: {selected.name}
          </Header>
        }
      >
        <Alert type="info">
          <strong>Target 99% accuracy — review the {PREVIEW_ESTIMATE.docsToReview} lowest-confidence docs.</strong> Est. current{' '}
          {PREVIEW_ESTIMATE.currentAccuracy}% · progress {queueIdx + 1} / {PREVIEW_QUEUE.length}.
        </Alert>
      </Container>

      <ColumnLayout columns={3}>
        {/* Queue */}
        <Container header={<Header variant="h3">Review queue</Header>}>
          <SpaceBetween size="xs">
            {PREVIEW_QUEUE.map((d, i) => (
              <Box key={d.name} padding="xs">
                <Link onFollow={() => setQueueIdx(i)}>
                  <strong style={{ color: i === queueIdx ? '#006ce0' : undefined }}>{d.name}</strong>
                </Link>
                <div>
                  <Box variant="span" fontSize="body-s" color="text-body-secondary">
                    {d.vendor} ·{' '}
                  </Box>
                  {confidenceBadge(d.minConfidence)}
                </div>
              </Box>
            ))}
          </SpaceBetween>
        </Container>

        {/* Existing widget stand-in: page + fields (labeled as reused) */}
        <Container
          header={
            <Header variant="h3" description="Existing Visual Document Editor — reused unchanged">
              {current?.name}
            </Header>
          }
        >
          <Box>
            <div
              style={{
                background: '#f7f8f9',
                border: '1px solid #e9ebed',
                borderRadius: 8,
                height: 260,
                padding: 16,
                fontFamily: 'monospace',
                fontSize: 11,
                color: '#3a3f47',
              }}
            >
              <div style={{ fontFamily: 'inherit', fontWeight: 700 }}>AIR PRODUCTS AND CHEMICALS, INC.</div>
              <div>INVOICE No. A-4471-X6</div>
              <div>PO: 4500-7789-02</div>
              <div>Tax: $50.49 · Total: $662.49</div>
              <div style={{ marginTop: 16, color: '#8d6605' }}>[page image + bounding boxes — existing widget]</div>
            </div>
          </Box>
        </Container>

        {/* Field review */}
        <Container
          header={
            <Header variant="h3" description="Confidence Alerts Only (existing filter)">
              Fields to review
            </Header>
          }
        >
          <SpaceBetween size="s">
            {PREVIEW_FIELDS.map((f) => (
              <Container key={f.name} variant="stacked">
                <SpaceBetween size="xxs">
                  <Box>
                    <strong>{f.name}</strong> {confidenceBadge(f.confidence)}
                  </Box>
                  <Box fontSize="body-s" color="text-body-secondary">
                    Confidence {(f.confidence * 100).toFixed(0)}% / threshold {(f.threshold * 100).toFixed(0)}%
                  </Box>
                  <input defaultValue={f.value} style={{ width: '100%', padding: 6, border: '1px solid #c6c6cd', borderRadius: 6 }} />
                </SpaceBetween>
              </Container>
            ))}
            <Button
              variant="primary"
              onClick={() => {
                if (queueIdx < PREVIEW_QUEUE.length - 1) setQueueIdx(queueIdx + 1);
                else setView('publish');
              }}
            >
              Save &amp; next in queue →
            </Button>
          </SpaceBetween>
        </Container>
      </ColumnLayout>
    </SpaceBetween>
  );

  // ---- PUBLISH ----------------------------------------------------------
  const publishView = (
    <Container
      header={
        <Header variant="h2" description="Freeze the reviewed labels into an immutable version and set it as the evaluation baseline.">
          Publish golden version — {selected.name}
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Alert type="success">Annotation complete for this walkthrough. Publishing freezes an immutable version.</Alert>
        <KeyValuePairs
          columns={4}
          items={[
            { label: 'New version', value: 'v1 (from draft)' },
            { label: 'Documents', value: String(selected.docs) },
            { label: 'Reviewed (human)', value: '78' },
            { label: 'Draft (machine)', value: '42' },
          ]}
        />
        <Box>
          <Box variant="awsui-key-label">Use v1 as the active reference?</Box>
          <SpaceBetween size="xxs">
            <label>
              <input type="radio" defaultChecked name="ref" /> Yes — future scoring runs compare against v1 (recommended)
            </label>
            <label>
              <input type="radio" name="ref" /> Not yet — just save v1
            </label>
          </SpaceBetween>
        </Box>
        <ProgressBar
          value={100}
          label="Golden dataset readiness"
          description="Publishing records per-field provenance and unlocks scoring runs."
        />
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setView('detail')}>Back</Button>
          <Button variant="primary" onClick={() => setView('list')}>
            Publish v1 &amp; set baseline
          </Button>
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );

  const views: Record<View, React.JSX.Element> = {
    list: listView,
    chooser: chooserView,
    detail: detailView,
    configure: configureView,
    annotate: annotateView,
    publish: publishView,
  };

  return (
    <ContentWrap>
      <SpaceBetween size="l">
        {banner}
        {views[view]}
      </SpaceBetween>
    </ContentWrap>
  );
};

// Thin content wrapper for consistent padding when mounted stand-alone.
const ContentWrap = ({ children }: { children: React.ReactNode }): React.JSX.Element => (
  <Box padding={{ horizontal: 'l', vertical: 'l' }}>{children}</Box>
);

export default GroundTruthFlowPreview;
