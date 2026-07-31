// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// PROTOTYPE — clickable UX walkthrough of the ground-truth test-set flow,
// driven entirely by fixture data (fixtures.ts). Mounted at
// #/test-studio/preview so it renders on the live accelerator for UX review
// BEFORE full backend wiring. No AWS calls.
//
// Every screen is URL-addressable via ?step=<id> (which itself demos the P0
// "shareable deep-link queue" story) and carries an "About this screen" panel
// (stories.ts): the user story, design notes, build status, and feedback
// prompts — so reviewers can react to each requirement in place.
import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Box,
  Button,
  Cards,
  ColumnLayout,
  Container,
  CopyToClipboard,
  ExpandableSection,
  Header,
  Input,
  KeyValuePairs,
  Link,
  ProgressBar,
  RadioGroup,
  Select,
  Slider,
  SpaceBetween,
  Table,
  Textarea,
} from '@cloudscape-design/components';
import {
  PREVIEW_TEST_SETS,
  PREVIEW_DOCS,
  PREVIEW_QUEUE,
  PREVIEW_ESTIMATE,
  PREVIEW_BURNDOWN,
  PREVIEW_EFFORT_MODEL,
  PREVIEW_CONFIDENCE_DIST,
  PREVIEW_LOWEST_FIELDS,
  PREVIEW_HIGHEST_FIELDS,
  estimateForTarget,
  estimateAccuracyForReviewed,
  versionsFor,
  type PreviewTestSet,
  type LabelSource,
} from './fixtures';
import { STORIES, type Story, type StoryStatus } from './stories';
import MockVisualDocumentEditor from './MockVisualDocumentEditor';

type View =
  | 'list'
  | 'chooser'
  | 'detail'
  | 'configure'
  | 'annotate'
  | 'publish'
  | 'generate-labels'
  | 'fix'
  | 'executions'
  | 'onramp-config'
  | 'onramp-describe'
  | 'onramp-upload'
  | 'manage'
  | 'merge';

const VIEW_IDS: View[] = [
  'list',
  'chooser',
  'detail',
  'configure',
  'annotate',
  'publish',
  'generate-labels',
  'fix',
  'executions',
  'onramp-config',
  'onramp-describe',
  'onramp-upload',
  'manage',
  'merge',
];

const STATUS_BADGE: Record<StoryStatus, { color: 'green' | 'blue' | 'grey' | 'severity-medium'; text: string }> = {
  built: { color: 'green', text: 'Built & verified live' },
  'backend-ready': { color: 'blue', text: 'Backend built — UI is this prototype' },
  prototype: { color: 'severity-medium', text: 'Prototype (dummy data)' },
  proposed: { color: 'grey', text: 'Proposed' },
};

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

/** "About this screen": story, design notes, status, feedback prompts. */
const StoryPanel = ({ story }: { story: Story }): React.JSX.Element => {
  const status = STATUS_BADGE[story.status];
  return (
    <ExpandableSection
      variant="container"
      headerText={`About this screen — ${story.priority}: ${story.title}`}
      headerActions={<Badge color={status.color as never}>{status.text}</Badge>}
    >
      <SpaceBetween size="s">
        <Box variant="p">
          <em>“{story.story}”</em>
        </Box>
        <Box>
          <Box variant="awsui-key-label">How it works</Box>
          <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>
            {story.design.map((d) => (
              <li key={d} style={{ marginBottom: 4 }}>
                {d}
              </li>
            ))}
          </ul>
        </Box>
        <Box>
          <Box variant="awsui-key-label">Feedback wanted</Box>
          <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>
            {story.feedback.map((f) => (
              <li key={f} style={{ marginBottom: 4 }}>
                {f}
              </li>
            ))}
          </ul>
        </Box>
      </SpaceBetween>
    </ExpandableSection>
  );
};

// The demo tour: screens in the order that tells the story (mirrors the
// priority order in user-flows.md). The pager walks this sequence.
const TOUR: { id: View; label: string }[] = [
  { id: 'list', label: 'Test Sets' },
  { id: 'chooser', label: 'New Test Set' },
  { id: 'onramp-upload', label: 'Upload' },
  { id: 'generate-labels', label: 'Draft labels' },
  { id: 'detail', label: 'Detail hub' },
  { id: 'configure', label: 'Review effort' },
  { id: 'annotate', label: 'Annotate' },
  { id: 'publish', label: 'Publish' },
  { id: 'executions', label: 'Executions' },
  { id: 'manage', label: 'Manage docs' },
  { id: 'merge', label: 'Merge' },
  { id: 'onramp-config', label: 'Synthetic: config' },
  { id: 'onramp-describe', label: 'Synthetic: describe' },
  { id: 'fix', label: 'Solo fix' },
];

// Stamped at build time by Vite so a stale cached bundle is self-evident.
const BUILD_STAMP = new Date(document.lastModified || Date.now()).toLocaleString();

const GroundTruthFlowPreview = (): React.JSX.Element => {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlStep = searchParams.get('step') as View | null;
  const view: View = urlStep && VIEW_IDS.includes(urlStep) ? urlStep : 'list';
  const [selected, setSelected] = useState<PreviewTestSet>(PREVIEW_TEST_SETS[0]);
  const [reviewMode, setReviewMode] = useState<'lowest' | 'all' | 'accept'>('lowest');
  const [queueIdx, setQueueIdx] = useState(0);
  const [labelsGenerated, setLabelsGenerated] = useState(false);
  const [targetAccuracy, setTargetAccuracy] = useState(PREVIEW_ESTIMATE.target);
  const estimate = estimateForTarget(targetAccuracy);
  const [viewingDoc, setViewingDoc] = useState<string | null>(null);
  const [publishSetActive, setPublishSetActive] = useState(true);

  const go = (v: View): void => {
    setSearchParams(v === 'list' ? {} : { step: v });
  };

  const shareUrl = (v: View): string => {
    const base = window.location.href.split('?')[0].split('#')[0];
    return `${base}#/test-studio/preview?step=${v}`;
  };

  const tourIdx = TOUR.findIndex((t) => t.id === view);
  const prevStop = tourIdx > 0 ? TOUR[tourIdx - 1] : null;
  const nextStop = tourIdx >= 0 && tourIdx < TOUR.length - 1 ? TOUR[tourIdx + 1] : null;

  // Compact tour bar: prototype notice + prev/next traversal + build stamp.
  const banner = (
    <Container disableContentPaddings>
      <Box padding={{ horizontal: 'm', vertical: 'xs' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            <Badge color="severity-medium">Prototype — dummy data</Badge>
            <Box variant="span" fontSize="body-s" color="text-body-secondary">
              Tour {tourIdx >= 0 ? tourIdx + 1 : '–'} of {TOUR.length}: <strong>{TOUR[tourIdx]?.label ?? view}</strong>
            </Box>
          </SpaceBetween>
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            {prevStop && <Button onClick={() => go(prevStop.id)}>‹ {prevStop.label}</Button>}
            {nextStop && (
              <Button variant="primary" onClick={() => go(nextStop.id)}>
                Next: {nextStop.label} ›
              </Button>
            )}
            {view !== 'list' && (
              <Button variant="link" onClick={() => go('list')}>
                Start over
              </Button>
            )}
            <Box variant="span" fontSize="body-s" color="text-status-inactive">
              build {BUILD_STAMP}
            </Box>
          </SpaceBetween>
        </div>
      </Box>
    </Container>
  );

  // ---- LIST (P1: manage many sets at a glance) ---------------------------
  const listView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.list} />
      <Container
        header={
          <Header
            variant="h2"
            description="A test set is a versioned collection of documents and their reviewed ground-truth labels."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => go('executions')}>Test Executions</Button>
                <Button variant="primary" onClick={() => go('chooser')}>
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
                      go('detail');
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
              header: 'Active version',
              cell: (t) =>
                t.activeReference ? (
                  <SpaceBetween direction="horizontal" size="xxs">
                    <Badge color="blue">{`v${t.activeReference}`}</Badge>
                    {t.latestVersion && t.latestVersion > t.activeReference && (
                      <Box fontSize="body-s" color="text-body-secondary">
                        (latest v{t.latestVersion})
                      </Box>
                    )}
                  </SpaceBetween>
                ) : (
                  <Box color="text-status-inactive">— not published</Box>
                ),
            },
          ]}
        />
      </Container>
    </SpaceBetween>
  );

  // ---- CHOOSER (P2 umbrella) ---------------------------------------------
  const chooserView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.chooser} />
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
              header: (item) => <Link onFollow={() => go(item.step as View)}>{item.title}</Link>,
              sections: [
                { id: 'desc', content: (item) => <Box color="text-body-secondary">{item.desc}</Box> },
                { id: 'out', content: (item) => <Badge color="grey">{item.out}</Badge> },
              ],
            }}
            cardsPerRow={[{ cards: 2 }]}
            items={[
              {
                title: 'From an existing config — recommended',
                step: 'onramp-config',
                desc: 'Pick a config version + document class; generate synthetic, labeled documents that match its schema exactly — no prompt.',
                out: '→ Synthetic labeled set · schema-matched',
              },
              {
                title: 'Describe it',
                step: 'onramp-describe',
                desc: 'No config yet? Describe the document type; we author a schema, then generate synthetic labeled documents.',
                out: '→ Synthetic labeled set · from a prompt',
              },
            ]}
          />
          <Box variant="h3">Bring your documents</Box>
          <Cards
            cardDefinition={{
              header: (item) => <Link onFollow={() => go(item.step as View)}>{item.title}</Link>,
              sections: [
                { id: 'desc', content: (item) => <Box color="text-body-secondary">{item.desc}</Box> },
                { id: 'out', content: (item) => <Badge color={item.color as never}>{item.out}</Badge> },
              ],
            }}
            cardsPerRow={[{ cards: 2 }]}
            items={[
              {
                title: 'Upload documents (labels auto-detected)',
                step: 'onramp-upload',
                desc: 'One upload surface. With labels → ready to publish. Without → generate draft labels next.',
                out: '→ Labeled, or Draft (machine) next',
                color: 'blue',
              },
            ]}
          />
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- ON-RAMP: from config (P2) ------------------------------------------
  const onrampConfigView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES['onramp-config']} />
      <Container header={<Header variant="h2">Generate from an existing config</Header>}>
        <SpaceBetween size="m">
          <ColumnLayout columns={3}>
            <Box>
              <Box variant="awsui-key-label">Config version</Box>
              <Select selectedOption={{ label: 'invoice-v4 (active)', value: 'invoice-v4' }} options={[]} onChange={() => {}} />
            </Box>
            <Box>
              <Box variant="awsui-key-label">Document class</Box>
              <Select selectedOption={{ label: 'Invoice', value: 'invoice' }} options={[]} onChange={() => {}} />
            </Box>
            <Box>
              <Box variant="awsui-key-label">Documents to generate</Box>
              <Input value="25" onChange={() => {}} />
            </Box>
          </ColumnLayout>
          <Alert type="info">
            Labels are generated with the documents and match the config schema exactly — the set is publishable immediately.
          </Alert>
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('chooser')}>Back</Button>
            <Button
              variant="primary"
              onClick={() => {
                setSelected(PREVIEW_TEST_SETS[2]);
                go('detail');
              }}
            >
              Generate synthetic test set
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- ON-RAMP: describe it (P2) -------------------------------------------
  const onrampDescribeView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES['onramp-describe']} />
      <Container header={<Header variant="h2">Describe the document type</Header>}>
        <SpaceBetween size="m">
          <Textarea value="Vendor invoices with line items, tax, PO number, and payment terms." onChange={() => {}} rows={3} />
          <Alert type="info">
            A schema is authored from the description, a config version is created, and labeled documents are generated.
          </Alert>
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('chooser')}>Back</Button>
            <Button
              variant="primary"
              onClick={() => {
                setSelected(PREVIEW_TEST_SETS[2]);
                go('detail');
              }}
            >
              Author schema &amp; generate
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- ON-RAMP: upload (P2) --------------------------------------------------
  const onrampUploadView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES['onramp-upload']} />
      <Container header={<Header variant="h2">Upload documents</Header>}>
        <SpaceBetween size="m">
          <Box padding="xl" textAlign="center" color="text-body-secondary">
            <div style={{ border: '2px dashed #c6c6cd', borderRadius: 12, padding: 40 }}>
              Drop a zip or files here — labels are auto-detected (input/ + baseline/ folders, or bare documents)
            </div>
          </Box>
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('chooser')}>Back</Button>
            <Button
              variant="primary"
              onClick={() => {
                setSelected(PREVIEW_TEST_SETS[3]);
                setLabelsGenerated(false);
                go('generate-labels');
              }}
            >
              Upload (no labels detected) →
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- GENERATE DRAFT LABELS (P0 #3) ----------------------------------------
  const generateLabelsView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES['generate-labels']} />
      <Container
        header={
          <Header
            variant="h2"
            description="No labels were detected. Run the active config to draft them."
            actions={
              !labelsGenerated ? (
                <Button variant="primary" onClick={() => setLabelsGenerated(true)}>
                  Generate draft labels
                </Button>
              ) : (
                <Button variant="primary" onClick={() => go('detail')}>
                  Continue to test set →
                </Button>
              )
            }
          >
            {selected.name} — draft labels
          </Header>
        }
      >
        {!labelsGenerated ? (
          <Table
            variant="borderless"
            items={PREVIEW_DOCS.slice(0, 4)}
            columnDefinitions={[
              { id: 'name', header: 'Document', cell: (d) => d.name },
              { id: 'conf', header: 'Confidence', cell: () => <Box color="text-status-inactive">—</Box> },
              { id: 'src', header: 'Label source', cell: () => <Badge color="grey">Unlabeled</Badge> },
            ]}
          />
        ) : (
          <SpaceBetween size="s">
            <Alert type="success">
              Draft labels generated with the active config (invoice-v4). Sorted worst-confidence first — click a document to view it with
              its labels.
            </Alert>
            <Table
              variant="borderless"
              items={PREVIEW_QUEUE}
              columnDefinitions={[
                {
                  id: 'name',
                  header: 'Document',
                  cell: (d) => <Link onFollow={() => setViewingDoc(d.name)}>{d.name}</Link>,
                },
                { id: 'conf', header: 'Confidence', cell: (d) => confidenceBadge(d.minConfidence) },
                { id: 'src', header: 'Label source', cell: () => <Badge color="blue">Draft (machine)</Badge> },
              ]}
            />
          </SpaceBetween>
        )}
      </Container>

      {/* Post-generation confidence summary: distribution + extremes + est. accuracy */}
      {labelsGenerated && (
        <ColumnLayout columns={2}>
          <Container
            header={
              <Header variant="h3" description="Per-field confidence across all generated labels">
                Confidence distribution
              </Header>
            }
          >
            <SpaceBetween size="s">
              <KeyValuePairs
                columns={2}
                items={[
                  { label: 'Est. accuracy of draft labels', value: `≈${PREVIEW_ESTIMATE.currentAccuracy}%` },
                  {
                    label: 'Fields below threshold (0.8)',
                    value: `${PREVIEW_CONFIDENCE_DIST.filter((b) => b.low).reduce((s, b) => s + b.fields, 0)} of ${PREVIEW_CONFIDENCE_DIST.reduce((s, b) => s + b.fields, 0)}`,
                  },
                ]}
              />
              <SpaceBetween size="xxs">
                {PREVIEW_CONFIDENCE_DIST.map((b) => (
                  <div key={b.bucket} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 72, fontSize: 12, color: '#5f6b7a' }}>{b.bucket}</span>
                    <div
                      style={{
                        background: b.low ? '#d91515' : '#037f0c',
                        opacity: b.low ? 0.8 : 0.75,
                        height: 12,
                        borderRadius: 3,
                        width: `${b.fields * 1.6}px`,
                      }}
                    />
                    <span style={{ fontSize: 12 }}>
                      {b.fields} fields{b.low ? ' · needs review' : ''}
                    </span>
                  </div>
                ))}
              </SpaceBetween>
              <Box fontSize="body-s" color="text-body-secondary">
                Red buckets fall below the review threshold — these drive the review queue and the effort estimate.
              </Box>
            </SpaceBetween>
          </Container>

          <Container header={<Header variant="h3">Extremes — where to look first</Header>}>
            <SpaceBetween size="s">
              <Box>
                <Box variant="awsui-key-label">Lowest-confidence fields</Box>
                <SpaceBetween size="xxs">
                  {PREVIEW_LOWEST_FIELDS.map((f) => (
                    <div key={`${f.doc}-${f.field}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 13 }}>
                        <strong>{f.field}</strong>{' '}
                        <Box variant="span" fontSize="body-s" color="text-body-secondary">
                          · {f.doc}
                        </Box>
                      </span>
                      {confidenceBadge(f.confidence)}
                    </div>
                  ))}
                </SpaceBetween>
              </Box>
              <Box>
                <Box variant="awsui-key-label">Highest-confidence fields</Box>
                <SpaceBetween size="xxs">
                  {PREVIEW_HIGHEST_FIELDS.map((f) => (
                    <div key={`${f.doc}-${f.field}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ fontSize: 13 }}>
                        <strong>{f.field}</strong>{' '}
                        <Box variant="span" fontSize="body-s" color="text-body-secondary">
                          · {f.doc}
                        </Box>
                      </span>
                      {confidenceBadge(f.confidence)}
                    </div>
                  ))}
                </SpaceBetween>
              </Box>
            </SpaceBetween>
          </Container>
        </ColumnLayout>
      )}

      {labelsGenerated && viewingDoc && <MockVisualDocumentEditor docName={viewingDoc} filter="all" onClose={() => setViewingDoc(null)} />}
    </SpaceBetween>
  );

  // Version history — the immutable published versions of the selected set.
  // Backed by getTestSetVersions on the real page; fixtures here.
  const versions = versionsFor(selected.id);
  const versionHistoryPanel = (
    <Container
      header={
        <Header
          variant="h2"
          counter={versions.length ? `(${versions.length})` : undefined}
          description="Every publish freezes an immutable snapshot. Scoring runs pin one of these versions so label changes never masquerade as config changes."
        >
          Version history
        </Header>
      }
    >
      {versions.length === 0 ? (
        <Box color="text-body-secondary" padding={{ vertical: 's' }}>
          No published versions yet. Publish the draft to cut <strong>v1</strong> and set the evaluation baseline.
        </Box>
      ) : (
        <Table
          variant="borderless"
          items={[...versions].sort((a, b) => b.version - a.version)}
          columnDefinitions={[
            {
              id: 'version',
              header: 'Version',
              cell: (v) => (
                <SpaceBetween direction="horizontal" size="xs">
                  <Badge color="blue">{`v${v.version}`}</Badge>
                  {v.isActiveReference && <Badge color="green">active reference</Badge>}
                </SpaceBetween>
              ),
            },
            { id: 'label', header: 'Label', cell: (v) => v.label },
            { id: 'docs', header: 'Docs', cell: (v) => v.fileCount },
            {
              id: 'coverage',
              header: 'Review coverage',
              cell: (v) =>
                v.reviewedPct >= 100 ? (
                  <Badge color="green">100% reviewed</Badge>
                ) : (
                  <Box color="text-status-warning">{v.reviewedPct}% reviewed</Box>
                ),
            },
            { id: 'config', header: 'Config version', cell: (v) => v.configVersion },
            { id: 'by', header: 'Published by', cell: (v) => v.createdBy },
            { id: 'at', header: 'Published', cell: (v) => new Date(v.createdAt).toLocaleDateString() },
          ]}
        />
      )}
    </Container>
  );

  // ---- DETAIL HUB (P0) --------------------------------------------------------
  const detailView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.detail} />
      <Container
        header={
          <Header
            variant="h1"
            description={`${selected.docs} documents · bound config: ${selected.boundConfig}`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => go('manage')}>Manage documents</Button>
                <Button onClick={() => go('publish')}>Publish version</Button>
              </SpaceBetween>
            }
          >
            {selected.name} {stageBadge(selected.stage)}
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Alert type="info">
            <strong>Three steps:</strong> ① Add documents {'✓'} · ② Generate draft labels{' '}
            {selected.stage !== 'draft' || selected.boundConfig !== '—' ? '✓' : ''} · ③ Publish a version{' '}
            {selected.stage === 'published' ? '✓' : ''}. Annotation is an optional refinement, not a gate.
          </Alert>
          <KeyValuePairs
            columns={3}
            items={[
              { label: 'Lifecycle stage', value: stageBadge(selected.stage) },
              { label: 'Source', value: sourceBadge(selected.source) },
              { label: 'Active reference', value: selected.activeReference ? `v${selected.activeReference}` : 'none yet' },
            ]}
          />
          {/* Primary action follows the lifecycle stage */}
          <SpaceBetween direction="horizontal" size="xs">
            {selected.stage === 'draft' && (
              <Button variant="primary" onClick={() => go('generate-labels')}>
                Generate draft labels
              </Button>
            )}
            {selected.stage === 'in-review' && (
              <Button variant="primary" onClick={() => go('annotate')}>
                Open annotation queue ({selected.reviewedPct ?? 0}% reviewed)
              </Button>
            )}
            {selected.stage === 'published' && (
              <Button variant="primary" onClick={() => go('executions')}>
                Start test run
              </Button>
            )}
            <Button onClick={() => go('configure')}>Set up team annotation</Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>

      <Container
        header={
          <Header variant="h2" description="Click a row to fix labels solo (no team workflow). Sorted worst-confidence first.">
            Documents (5 shown)
          </Header>
        }
      >
        <Table
          variant="borderless"
          items={PREVIEW_DOCS}
          columnDefinitions={[
            { id: 'name', header: 'Document', cell: (d) => <Link onFollow={() => go('fix')}>{d.name}</Link> },
            { id: 'vendor', header: 'Vendor / cluster', cell: (d) => d.vendor },
            { id: 'conf', header: 'Confidence', cell: (d) => confidenceBadge(d.minConfidence) },
            { id: 'src', header: 'Label source', cell: (d) => labelSourceBadge(d.labelSource) },
          ]}
        />
      </Container>

      {versionHistoryPanel}
    </SpaceBetween>
  );

  // ---- CONFIGURE (P0 #2) --------------------------------------------------------
  const configureView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.configure} />
      <Container
        header={
          <Header variant="h2" description="Choose how much human review this set gets; we estimate the effort.">
            Set up annotation — {selected.name}
          </Header>
        }
      >
        <SpaceBetween size="l">
          <Box>
            <Box variant="awsui-key-label">Review depth</Box>
            <RadioGroup
              value={reviewMode}
              onChange={({ detail }) => setReviewMode(detail.value as 'lowest' | 'all' | 'accept')}
              items={[
                {
                  value: 'lowest',
                  label: 'Review the lowest-confidence documents (recommended)',
                  description: 'Focus human effort where the model is least sure.',
                },
                {
                  value: 'all',
                  label: 'Review everything',
                  description: 'Every document gets human eyes. Highest trust, most effort.',
                },
                {
                  value: 'accept',
                  label: 'Accept machine labels as-is',
                  description: 'No human review — publish the draft labels directly.',
                },
              ]}
            />
          </Box>

          <ExpandableSection headerText="Show the math — target a specific label accuracy">
            <SpaceBetween size="m">
              {/* Interactive: slide the desired accuracy; everything recomputes. */}
              <Box>
                <Box variant="awsui-key-label">Target label accuracy: {targetAccuracy.toFixed(1)}%</Box>
                <Slider
                  value={targetAccuracy}
                  onChange={({ detail }) => setTargetAccuracy(detail.value)}
                  min={95}
                  max={99.8}
                  step={0.1}
                  ariaLabel="Target label accuracy"
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#5f6b7a' }}>
                  <span>95% — accept most machine labels</span>
                  <span>99.8% — review nearly everything</span>
                </div>
              </Box>
              <KeyValuePairs
                columns={4}
                items={[
                  { label: 'Est. current accuracy', value: `≈${PREVIEW_ESTIMATE.currentAccuracy}%` },
                  { label: 'Docs to review', value: `≈${estimate.docs} / ${PREVIEW_ESTIMATE.totalDocs}` },
                  {
                    label: 'Est. review time',
                    value: `≈${estimate.minutes >= 60 ? `${(estimate.minutes / 60).toFixed(1)} hrs` : `${estimate.minutes} min`}`,
                  },
                  { label: 'Implied confidence cutoff', value: `≈${estimate.cutoff.toFixed(2)}` },
                ]}
              />
              <Box fontSize="body-s" color="text-body-secondary">
                Time model: ~{PREVIEW_EFFORT_MODEL.secondsPerField}s per flagged field × {PREVIEW_EFFORT_MODEL.avgFieldsPerDoc} fields + ~
                {PREVIEW_EFFORT_MODEL.secondsPerPage}s per page × {PREVIEW_EFFORT_MODEL.avgPagesPerDoc} pages per document.
              </Box>
              <Box>
                <Box variant="awsui-key-label">
                  Error burndown — blue bars are reviewed by humans; grey bars are auto-accepted beyond the cutoff
                </Box>
                <SpaceBetween size="xxs">
                  {PREVIEW_BURNDOWN.map((p) => {
                    const reviewed = p.reviewed <= estimate.docs;
                    return (
                      <div key={p.reviewed} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 70, fontSize: 12, color: '#5f6b7a' }}>{p.reviewed} docs</span>
                        <div
                          style={{
                            background: reviewed ? '#006ce0' : '#c6c6cd',
                            height: 10,
                            borderRadius: 3,
                            width: `${p.residualError * 40}px`,
                          }}
                        />
                        <span style={{ fontSize: 12, color: reviewed ? undefined : '#5f6b7a' }}>
                          {p.residualError}%{reviewed ? '' : ' · auto-accepted'}
                        </span>
                      </div>
                    );
                  })}
                  {/* cutoff marker */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
                    <span style={{ width: 70 }} />
                    <div style={{ borderTop: '2px dashed #8d6605', flexBasis: 240 }} />
                    <span style={{ fontSize: 12, color: '#8d6605', fontWeight: 700 }}>
                      cutoff: review {estimate.docs} docs → target {targetAccuracy.toFixed(1)}% met
                    </span>
                  </div>
                </SpaceBetween>
              </Box>
              <Alert type="info">
                Rough estimate — based on a prior confidence–accuracy curve, not yet measured on this set. Self-corrects as your team
                reviews.
              </Alert>
            </SpaceBetween>
          </ExpandableSection>

          <Alert type="info" header="Share this with your annotators">
            After starting, annotators go straight to the queue via a direct link — no console navigation:
            <Box variant="code" margin={{ top: 'xs' }}>
              {shareUrl('annotate')}
            </Box>
          </Alert>

          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('detail')}>Cancel</Button>
            <Button variant="primary" onClick={() => go('annotate')}>
              Start workstream → open annotation queue
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- ANNOTATE (P0 #1) ------------------------------------------------------------
  const current = PREVIEW_QUEUE[Math.min(queueIdx, PREVIEW_QUEUE.length - 1)];
  const annotateView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.queue} />
      <Container
        header={
          <Header
            variant="h2"
            description="You are assigned to this test set. Work the queue lowest-confidence first."
            actions={
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Badge color="blue">Ends Fri 5:00 PM · 1d 4h left</Badge>
                <CopyToClipboard
                  variant="button"
                  copyButtonText="Copy queue link"
                  textToCopy={shareUrl('annotate')}
                  copySuccessText="Queue link copied — share it with annotators"
                  copyErrorText="Could not copy the queue link"
                />
              </SpaceBetween>
            }
          >
            Annotate: {selected.name}
          </Header>
        }
      >
        <SpaceBetween size="s">
          <Alert type="info">
            <strong>
              Target 99% accuracy — review the {PREVIEW_ESTIMATE.docsToReview} lowest-confidence docs ({PREVIEW_QUEUE.length} shown in this
              sample).
            </strong>{' '}
            Est. current label accuracy {PREVIEW_ESTIMATE.currentAccuracy}%.
          </Alert>
          <ProgressBar
            value={Math.round(((queueIdx + 1) / PREVIEW_QUEUE.length) * 100)}
            label="Queue progress"
            additionalInfo={`${queueIdx + 1} of ${PREVIEW_QUEUE.length} documents reviewed`}
          />
        </SpaceBetween>
      </Container>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* The ONLY new UI: the scoped, confidence-ordered queue rail. */}
        <div style={{ flex: '0 0 280px' }}>
          <Container
            header={
              <Header variant="h3" description="new — lowest confidence first, claim to lock">
                Review queue
              </Header>
            }
          >
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
        </div>

        {/* Everything else IS the existing Visual Document Editor, unchanged.
            'Next Section' is relabeled by the queue wrapper to advance the queue. */}
        <div style={{ flex: 1 }}>
          <MockVisualDocumentEditor
            docName={current?.name ?? ''}
            filter="alerts"
            onNext={() => {
              if (queueIdx < PREVIEW_QUEUE.length - 1) setQueueIdx(queueIdx + 1);
              else go('publish');
            }}
            nextLabel="Save & next in queue →"
          />
        </div>
      </div>
    </SpaceBetween>
  );

  // ---- SOLO FIX (P1 #5) — the existing editor, opened for one doc ------------
  const fixView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.fix} />
      <MockVisualDocumentEditor docName="INV_air_products_0012.pdf" filter="alerts" onClose={() => go('detail')} />
    </SpaceBetween>
  );

  // ---- EXECUTIONS (P1 #6) --------------------------------------------------------------
  const executionsView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.executions} />
      <Container header={<Header variant="h2">Test Executions</Header>}>
        <Table
          variant="borderless"
          items={[
            { run: 'Vendor-Invoices-20260727-1', config: 'invoice-v4', tsv: 'v1', acc: '96.1%', ok: true },
            { run: 'Vendor-Invoices-20260726-2', config: 'invoice-v5-rc', tsv: 'v1', acc: '97.0%', ok: true },
            { run: 'Vendor-Invoices-20260901-1', config: 'invoice-v5-rc', tsv: 'v2', acc: '95.2%', ok: false },
          ]}
          columnDefinitions={[
            { id: 'run', header: 'Test run', cell: (r) => r.run },
            { id: 'config', header: 'Config version', cell: (r) => <Box variant="code">{r.config}</Box> },
            {
              id: 'tsv',
              header: 'Test set version',
              cell: (r) => <Badge color="blue">{r.tsv}</Badge>,
            },
            { id: 'acc', header: 'Accuracy', cell: (r) => r.acc },
            {
              id: 'cmp',
              header: 'Comparable?',
              cell: (r) =>
                r.ok ? (
                  <Box color="text-status-success">✓ same test-set version</Box>
                ) : (
                  <Box color="text-status-warning">⚠ different test-set version — labels changed, not just the config</Box>
                ),
            },
          ]}
        />
      </Container>
    </SpaceBetween>
  );

  // ---- MANAGE (P3 #11) --------------------------------------------------------------------
  const manageView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.manage} />
      <Container
        header={
          <Header
            variant="h2"
            description="Edits change the draft only; published versions are untouched."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => go('chooser')}>Add documents ▾</Button>
                <Button>Remove selected (2)</Button>
                <Button onClick={() => go('merge')}>Merge with another set…</Button>
              </SpaceBetween>
            }
          >
            Manage documents — {selected.name}
          </Header>
        }
      >
        <Table
          variant="borderless"
          selectionType="multi"
          selectedItems={PREVIEW_DOCS.slice(0, 2)}
          onSelectionChange={() => {}}
          items={PREVIEW_DOCS}
          columnDefinitions={[
            { id: 'name', header: 'Document', cell: (d) => d.name },
            { id: 'conf', header: 'Confidence', cell: (d) => confidenceBadge(d.minConfidence) },
            { id: 'src', header: 'Label source', cell: (d) => labelSourceBadge(d.labelSource) },
          ]}
        />
      </Container>
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => go('detail')}>← Back to test set</Button>
      </SpaceBetween>
    </SpaceBetween>
  );

  // ---- MERGE (P3 #12) ------------------------------------------------------------------------
  const mergeView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.merge} />
      <Container header={<Header variant="h2">Merge test sets</Header>}>
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <Box>
              <Box variant="awsui-key-label">Source A</Box>
              <Select selectedOption={{ label: 'Vendor Invoices — Golden (120 docs)', value: 'a' }} options={[]} onChange={() => {}} />
            </Box>
            <Box>
              <Box variant="awsui-key-label">Source B</Box>
              <Select selectedOption={{ label: 'Q3 Invoice spot-check (40 docs)', value: 'b' }} options={[]} onChange={() => {}} />
            </Box>
          </ColumnLayout>
          <Alert type="warning" header="3 documents exist in both sets with different labels">
            Choose conflict resolution: <strong>human-reviewed wins</strong> (default) · newest wins · resolve manually.
          </Alert>
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('manage')}>Cancel</Button>
            <Button variant="primary" onClick={() => go('detail')}>
              Merge into new draft (157 docs)
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  // ---- PUBLISH (P1 #4) --------------------------------------------------------------------------
  const publishView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.publish} />
      <Container
        header={
          <Header variant="h2" description="Freeze the reviewed labels into an immutable version and set it as the evaluation baseline.">
            Publish golden version — {selected.name}
          </Header>
        }
      >
        <SpaceBetween size="l">
          {(() => {
            const pct = selected.reviewedPct ?? 65;
            const reviewed = Math.round(selected.docs * (pct / 100));
            const estAccuracy = estimateAccuracyForReviewed(reviewed, selected.docs);
            return (
              <>
                <KeyValuePairs
                  columns={4}
                  items={[
                    { label: 'New version', value: `v${(selected.latestVersion ?? 0) + 1} (from draft)` },
                    { label: 'Documents', value: String(selected.docs) },
                    // Derived from the selected set so the arithmetic always holds
                    { label: 'Reviewed (human)', value: String(reviewed) },
                    { label: 'Draft (machine)', value: String(selected.docs - reviewed) },
                  ]}
                />
                <Alert type={estAccuracy >= 99 ? 'success' : 'info'}>
                  <strong>Estimated label accuracy at this version: ~{estAccuracy}%</strong> — based on {reviewed} of {selected.docs}{' '}
                  documents human-reviewed (lowest-confidence first). Reviewing more of the flagged docs raises this; the estimate
                  self-corrects as scoring runs measure the version against real predictions.
                </Alert>
              </>
            );
          })()}
          <Box>
            <Box variant="awsui-key-label">Use v{(selected.latestVersion ?? 0) + 1} as the active reference?</Box>
            <RadioGroup
              value={publishSetActive ? 'yes' : 'no'}
              onChange={({ detail }) => setPublishSetActive(detail.value === 'yes')}
              items={[
                {
                  value: 'yes',
                  label: `Yes — future scoring runs compare against v${(selected.latestVersion ?? 0) + 1} (recommended)`,
                },
                {
                  value: 'no',
                  label: `Not yet — just save v${(selected.latestVersion ?? 0) + 1}`,
                },
              ]}
            />
          </Box>
          <ProgressBar
            value={selected.reviewedPct ?? 65}
            label="Human review coverage"
            description="Publishing is allowed before 100% — unreviewed fields keep machine labels, flagged as such. Provenance is recorded per field."
          />
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => go('detail')}>Cancel</Button>
            <Button variant="primary" onClick={() => go('list')}>
              {publishSetActive
                ? `Publish v${(selected.latestVersion ?? 0) + 1} & set as baseline`
                : `Publish v${(selected.latestVersion ?? 0) + 1}`}
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );

  const views: Record<View, React.JSX.Element> = {
    list: listView,
    chooser: chooserView,
    detail: detailView,
    configure: configureView,
    annotate: annotateView,
    publish: publishView,
    'generate-labels': generateLabelsView,
    fix: fixView,
    executions: executionsView,
    'onramp-config': onrampConfigView,
    'onramp-describe': onrampDescribeView,
    'onramp-upload': onrampUploadView,
    manage: manageView,
    merge: mergeView,
  };

  return (
    <Box padding={{ horizontal: 'l', vertical: 'l' }}>
      <SpaceBetween size="l">
        {banner}
        {views[view]}
      </SpaceBetween>
    </Box>
  );
};

export default GroundTruthFlowPreview;
