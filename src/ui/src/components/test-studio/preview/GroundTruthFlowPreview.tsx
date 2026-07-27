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
  ExpandableSection,
  Header,
  Input,
  KeyValuePairs,
  Link,
  ProgressBar,
  Select,
  SpaceBetween,
  Table,
  Textarea,
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
import { STORIES, type Story, type StoryStatus } from './stories';

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

const GroundTruthFlowPreview = (): React.JSX.Element => {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlStep = searchParams.get('step') as View | null;
  const view: View = urlStep && VIEW_IDS.includes(urlStep) ? urlStep : 'list';
  const [selected, setSelected] = useState<PreviewTestSet>(PREVIEW_TEST_SETS[0]);
  const [reviewMode, setReviewMode] = useState<'lowest' | 'all' | 'accept'>('lowest');
  const [queueIdx, setQueueIdx] = useState(0);
  const [labelsGenerated, setLabelsGenerated] = useState(false);

  const go = (v: View): void => {
    setSearchParams(v === 'list' ? {} : { step: v });
  };

  const shareUrl = (v: View): string => {
    const base = window.location.href.split('?')[0].split('#')[0];
    return `${base}#/test-studio/preview?step=${v}`;
  };

  const banner = (
    <Alert type="info" header="Prototype — dummy data. Every screen is URL-addressable via ?step=…">
      A clickable UX walkthrough of the proposed ground-truth test-set flow (no backend). Each screen explains its user story under “About
      this screen” and lists the feedback we want. Current step: <strong>{view}</strong>.{' '}
      {view !== 'list' && <Link onFollow={() => go('list')}>← back to Test Sets</Link>}
    </Alert>
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
              header: 'Version',
              cell: (t) =>
                t.activeReference ? <Badge color="blue">{`v${t.activeReference}`}</Badge> : <Box color="text-status-inactive">draft</Box>,
            },
            { id: 'ref', header: 'Active reference', cell: (t) => (t.activeReference ? `v${t.activeReference}` : '—') },
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
                title: 'From an existing config ✦ recommended',
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
                  ⚡ Generate draft labels
                </Button>
              ) : (
                <Button variant="primary" onClick={() => go('detail')}>
                  Continue to test set →
                </Button>
              )
            }
          >
            Q3 Invoice spot-check — draft labels
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
            <Alert type="success">Draft labels generated with the active config (invoice-v4). Sorted worst-confidence first.</Alert>
            <Table
              variant="borderless"
              items={PREVIEW_QUEUE}
              columnDefinitions={[
                { id: 'name', header: 'Document', cell: (d) => d.name },
                { id: 'conf', header: 'Confidence', cell: (d) => confidenceBadge(d.minConfidence) },
                { id: 'src', header: 'Label source', cell: () => <Badge color="blue">Draft (machine)</Badge> },
              ]}
            />
          </SpaceBetween>
        )}
      </Container>
    </SpaceBetween>
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
            <strong>Three steps:</strong> ① Add documents ✓ · ② Generate draft labels · ③ Publish a version. Annotation is an optional
            refinement, not a gate.
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
            <Button variant="primary" onClick={() => go('generate-labels')}>
              ⚡ Generate draft labels
            </Button>
            <Button onClick={() => go('configure')}>Set up team annotation →</Button>
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
    </SpaceBetween>
  );

  // ---- CONFIGURE (P0 #2) --------------------------------------------------------
  const configureView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.configure} />
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
                ['lowest', 'Review the lowest-confidence docs', 'Focus human effort where the model is least sure. (recommended)'],
                ['all', 'Review everything', 'Every document gets human eyes. Highest confidence; most effort.'],
                ['accept', 'Accept machine labels as-is', 'No human review — publish draft labels directly.'],
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

          <ExpandableSection headerText="Show the math — target a specific label accuracy">
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
            actions={<Badge color="severity-medium">⏱ ends Fri 5:00 PM · 1d 4h left</Badge>}
          >
            Annotate: {selected.name}
          </Header>
        }
      >
        <Alert type="info">
          <strong>Target 99% accuracy — review the {PREVIEW_ESTIMATE.docsToReview} lowest-confidence docs.</strong> Est. current{' '}
          {PREVIEW_ESTIMATE.currentAccuracy}% · progress {queueIdx + 1} / {PREVIEW_QUEUE.length} · you arrived via the shared queue link.
        </Alert>
      </Container>

      <ColumnLayout columns={3}>
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
                else go('publish');
              }}
            >
              Save &amp; next in queue →
            </Button>
          </SpaceBetween>
        </Container>
      </ColumnLayout>
    </SpaceBetween>
  );

  // ---- SOLO FIX (P1 #5) ---------------------------------------------------------------
  const fixView = (
    <SpaceBetween size="m">
      <StoryPanel story={STORIES.fix} />
      <Container
        header={
          <Header variant="h2" description="Existing review editor, opened for one document — no queue, no team setup.">
            Fix labels: INV_air_products_0012.pdf
          </Header>
        }
      >
        <ColumnLayout columns={2}>
          <Box>
            <div
              style={{
                background: '#f7f8f9',
                border: '1px solid #e9ebed',
                borderRadius: 8,
                height: 240,
                padding: 16,
                fontFamily: 'monospace',
                fontSize: 11,
                color: '#3a3f47',
              }}
            >
              <div style={{ fontWeight: 700 }}>AIR PRODUCTS AND CHEMICALS, INC.</div>
              <div>INVOICE No. A-4471-X6</div>
              <div style={{ marginTop: 16, color: '#8d6605' }}>[existing widget]</div>
            </div>
          </Box>
          <SpaceBetween size="s">
            {PREVIEW_FIELDS.slice(0, 2).map((f) => (
              <Container key={f.name} variant="stacked">
                <SpaceBetween size="xxs">
                  <Box>
                    <strong>{f.name}</strong> {confidenceBadge(f.confidence)}
                  </Box>
                  <input defaultValue={f.value} style={{ width: '100%', padding: 6, border: '1px solid #c6c6cd', borderRadius: 6 }} />
                </SpaceBetween>
              </Container>
            ))}
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => go('detail')}>Cancel</Button>
              <Button variant="primary" onClick={() => go('detail')}>
                Save &amp; return
              </Button>
            </SpaceBetween>
          </SpaceBetween>
        </ColumnLayout>
      </Container>
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
            <Button onClick={() => go('detail')}>Back</Button>
            <Button variant="primary" onClick={() => go('list')}>
              Publish v1 &amp; set baseline
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
