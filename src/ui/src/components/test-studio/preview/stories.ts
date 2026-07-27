// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Story metadata for the ground-truth flow prototype. Each screen in the
// walkthrough carries its user story, design notes, build status, and feedback
// prompts so reviewers can react to the UX in place. Mirrors
// docs/proposals/ground-truth-hitl/user-flows.md.

export type StoryStatus = 'built' | 'backend-ready' | 'prototype' | 'proposed';

export interface Story {
  id: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  title: string;
  story: string;
  design: string[];
  status: StoryStatus;
  feedback: string[];
}

export const STORIES: Record<string, Story> = {
  queue: {
    id: 'queue',
    priority: 'P0',
    title: 'Annotator deep-link queue',
    story:
      'As an annotator, I want a link that drops me straight into my queue, with the most suspect documents first, so my time removes the most error.',
    design: [
      'The owner shares a direct URL; after login the annotator is IN the queue — no console navigation, no Document List.',
      'Queue is scoped to one test set, sorted lowest-confidence first; claiming locks a doc so annotators do not collide.',
      'The editor is the EXISTING review widget (page image, bounding boxes, Confidence Alerts Only filter) — reused unchanged. Only the queue, scoping, and progress are new.',
      'Save & next advances to the next lowest-confidence doc automatically.',
    ],
    status: 'prototype',
    feedback: [
      'Is the 3-column layout (queue / page / fields) right, or should the queue collapse?',
      'Is the target-accuracy banner useful to an annotator, or owner-only noise?',
      'What belongs on the queue chips besides confidence (vendor? alert count?)',
    ],
  },
  configure: {
    id: 'configure',
    priority: 'P0',
    title: 'Owner sets review effort',
    story:
      'As a config owner, I want to send a test set for review and choose how much effort to spend, so I get trustworthy labels without over-reviewing.',
    design: [
      'Three plain presets first; statistics are opt-in behind "Show the math".',
      'Target accuracy → estimated docs-to-review via a measured confidence-accuracy curve, with an error-burndown chart.',
      'Numbers are labeled rough estimates and self-correct as reviews come in.',
      'The shareable queue URL is issued from here after starting the workstream.',
    ],
    status: 'prototype',
    feedback: [
      'Are three presets the right default surface, or should target-accuracy be primary?',
      'Is the burndown chart understandable at a glance?',
    ],
  },
  'generate-labels': {
    id: 'generate-labels',
    priority: 'P0',
    title: 'Upload unlabeled → machine-drafted labels',
    story:
      'As a config owner, I want to upload unlabeled documents and have the system draft labels, so I do not have to label from scratch.',
    design: [
      'Closes today’s biggest gap: currently a test set cannot exist without labels.',
      'Generate draft labels runs the ACTIVE config by default — no config-binding step.',
      'Docs gain per-field confidence and sort worst-first; label source becomes Draft (machine).',
    ],
    status: 'backend-ready',
    feedback: [
      'Should generation be automatic on upload, or an explicit button as shown?',
      'Is "Draft (machine)" the right label-source vocabulary?',
    ],
  },
  publish: {
    id: 'publish',
    priority: 'P1',
    title: 'Publish an immutable golden version',
    story: 'As a config owner, I want to freeze reviewed labels as an immutable version, so evaluation has a stable reference.',
    design: [
      'One real decision: use the new version as the active reference (default yes).',
      'Freezing, per-field provenance, and unlocking scoring runs happen automatically — stated as info, not a checklist.',
      'Publishing before 100% reviewed is allowed; unreviewed fields keep machine labels, flagged as such.',
    ],
    status: 'built',
    feedback: ['Is partial-publish (time-boxed first pass) clear enough here?'],
  },
  fix: {
    id: 'fix',
    priority: 'P1',
    title: 'Solo fix — no team workflow',
    story: 'As a config owner working alone, I want to fix a few bad labels without setting up a team workflow.',
    design: [
      'Click any row on the detail page → the SAME existing editor opens for just that doc.',
      'Annotation is an opt-in, never a gate: no queue or team setup required.',
    ],
    status: 'prototype',
    feedback: ['Should solo-fix and the team queue look identical, or is the lighter frame here right?'],
  },
  executions: {
    id: 'executions',
    priority: 'P1',
    title: 'Runs pin the test-set version',
    story:
      'As an evaluator, I want every test run to record which test-set version it scored against, so comparisons never silently mix label changes with config changes.',
    design: [
      'Each run pins the set’s active reference version automatically — symmetric to the existing config-version pin.',
      'Comparisons are apples-to-apples only when BOTH configVersion and testSetVersion match; the UI flags mismatches.',
    ],
    status: 'built',
    feedback: ['Is a warning icon on mismatched comparisons enough, or should the UI block them?'],
  },
  list: {
    id: 'list',
    priority: 'P1',
    title: 'Manage many sets at a glance',
    story:
      'As a config owner, I want to see where each set came from and which version is trusted, so I can manage many sets without confusion.',
    design: [
      'One row per set: Stage (Draft → In review → Published), Source (Uploaded/Synthetic/Mixed), Version badge, Active reference.',
      'Label source is the trust model — machine-drafted ≠ human-verified ≠ synthetic; never colored the same.',
    ],
    status: 'built',
    feedback: ['Which columns earn their place? Anything missing (owner? last activity?)'],
  },
  'onramp-config': {
    id: 'onramp-config',
    priority: 'P2',
    title: 'Synthetic from an existing config',
    story: 'As a config owner, I want to generate a labeled test set from my existing config, so I can test it without sourcing documents.',
    design: [
      'Pick config version + document class + count; documents arrive already labeled, schema-matched exactly.',
      'Reuses the existing synthesis engine — this is wiring, not new generation code.',
    ],
    status: 'proposed',
    feedback: ['What generation knobs matter here (count, variety, quality threshold)?'],
  },
  'onramp-describe': {
    id: 'onramp-describe',
    priority: 'P2',
    title: 'Synthetic from a description',
    story:
      'As a config owner, I want to describe a document type in words and get a synthetic test set, so I can start with no config and no documents.',
    design: ['Cold-start path: authors a schema, creates a config version, generates labeled docs — all from a prompt.'],
    status: 'proposed',
    feedback: ['Should this also create the config version silently, or make that explicit?'],
  },
  'onramp-upload': {
    id: 'onramp-upload',
    priority: 'P2',
    title: 'Upload documents (labels auto-detected)',
    story: 'As a config owner, I want to upload documents — with or without labels — and have the system do the right thing.',
    design: [
      'One upload surface: labels are auto-detected (zip with input/ + baseline/, or bare docs).',
      'With labels → ready to publish. Without → Unlabeled, ready for Generate draft labels.',
    ],
    status: 'proposed',
    feedback: ['Is auto-detection trustworthy enough, or do users want an explicit choice?'],
  },
  manage: {
    id: 'manage',
    priority: 'P3',
    title: 'Add / remove documents',
    story: 'As a config owner, I want to add or remove documents, so a set can grow and shed bad samples without starting over.',
    design: [
      'Edits change the DRAFT only; published versions are untouched. Next publish cuts the next version, preserving lineage.',
      'Remove is backend-ready (API exists); add reuses the existing append paths.',
    ],
    status: 'backend-ready',
    feedback: ['Should removed docs be recoverable (soft-delete) within the draft?'],
  },
  merge: {
    id: 'merge',
    priority: 'P3',
    title: 'Merge test sets',
    story: 'As a config owner, I want to merge two test sets, so per-vendor sets can become one golden set.',
    design: [
      'Later phase. Merged set starts as a new draft with per-document provenance carried over.',
      'Open question: conflict resolution when the same doc exists in both with different labels.',
    ],
    status: 'proposed',
    feedback: ['How should label conflicts be resolved — newest wins, human-reviewed wins, or manual?'],
  },
  chooser: {
    id: 'chooser',
    priority: 'P2',
    title: 'New Test Set — four on-ramps',
    story: 'As a config owner, I want a single entry point that offers every way to create a test set.',
    design: [
      'Two groups: Generate synthetic (no documents needed) and Bring your documents.',
      '"From an existing config" is recommended — the fastest path when a schema is already locked.',
    ],
    status: 'prototype',
    feedback: ['Are four on-ramps too many choices up front?'],
  },
  detail: {
    id: 'detail',
    priority: 'P0',
    title: 'Test set detail — the hub',
    story: 'As a config owner, I want one page that shows a test set’s state and every next action.',
    design: [
      'Three-step guide (add docs → draft labels → publish); annotation is a clearly-separate opt-in.',
      'Docs table shows per-document confidence + label source; versions panel keeps versioning quiet but present.',
    ],
    status: 'prototype',
    feedback: ['Is "Set up team annotation" discoverable enough as the annotation entry point?'],
  },
};
