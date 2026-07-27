// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Dummy data for the Ground-Truth flow PROTOTYPE. This drives a clickable UX
// walkthrough on the live accelerator so the flow can be reviewed and iterated
// before committing to full backend wiring. NONE of this hits AWS — it is
// static fixture data. Swap these for the real hooks/resolvers once the UX is
// locked. See src/components/test-studio/preview/.

export type LabelSource = 'synthetic' | 'uploaded' | 'draft-machine' | 'reviewed-human' | 'unlabeled';
export type Stage = 'draft' | 'in-review' | 'published';

export interface PreviewTestSet {
  id: string;
  name: string;
  description: string;
  docs: number;
  source: 'Uploaded' | 'Synthetic' | 'Mixed';
  stage: Stage;
  latestVersion: number | null;
  activeReference: number | null;
  boundConfig: string;
  reviewedPct?: number; // for in-review sets
}

export interface PreviewDoc {
  name: string;
  vendor: string;
  minConfidence: number | null; // null when unlabeled
  labelSource: LabelSource;
  reviewer?: string;
}

export interface PreviewField {
  name: string;
  value: string;
  confidence: number;
  threshold: number;
}

export const PREVIEW_TEST_SETS: PreviewTestSet[] = [
  {
    id: 'vendor-invoices-golden',
    name: 'Vendor Invoices — Golden',
    description: 'Invoices sampled across 8 vendors × 5 product types.',
    docs: 120,
    source: 'Mixed',
    stage: 'in-review',
    latestVersion: null,
    activeReference: null,
    boundConfig: 'invoice-v4',
    reviewedPct: 65,
  },
  {
    id: 'confbench',
    name: 'ConfBench',
    description: 'Variations from two unique document IDs in ConfBench.',
    docs: 39,
    source: 'Uploaded',
    stage: 'published',
    latestVersion: 2,
    activeReference: 2,
    boundConfig: 'confbench-cfg',
  },
  {
    id: 'fake-w2',
    name: 'Fake-W2-Tax-Forms',
    description: '2,000 synthetic US W-2 tax forms with 45-field ground truth.',
    docs: 2000,
    source: 'Synthetic',
    stage: 'published',
    latestVersion: 1,
    activeReference: 1,
    boundConfig: 'fake-w2',
  },
  {
    id: 'q3-spot-check',
    name: 'Q3 Invoice spot-check',
    description: '40 documents for a quick config test.',
    docs: 40,
    source: 'Uploaded',
    stage: 'draft',
    latestVersion: null,
    activeReference: null,
    boundConfig: 'active (invoice-v4)',
  },
  {
    id: 'realkie-fcc',
    name: 'RealKIE-FCC',
    description: 'FCC invoices, just uploaded — no labels yet.',
    docs: 75,
    source: 'Uploaded',
    stage: 'draft',
    latestVersion: null,
    activeReference: null,
    boundConfig: '—',
  },
];

export const PREVIEW_DOCS: PreviewDoc[] = [
  { name: 'INV_air_products_0012.pdf', vendor: 'Air Products', minConfidence: 0.61, labelSource: 'draft-machine', reviewer: 'reviewer-a' },
  { name: 'INV_welding_5583.pdf', vendor: 'Welding supply', minConfidence: 0.78, labelSource: 'draft-machine' },
  { name: 'INV_industrial_gas_781.pdf', vendor: 'Industrial gas', minConfidence: 0.81, labelSource: 'draft-machine' },
  { name: 'INV_sand_221.pdf', vendor: 'Sand / aggregate', minConfidence: 0.94, labelSource: 'reviewed-human', reviewer: 'reviewer-b' },
  { name: 'SYN_invoice_air_0007.pdf', vendor: 'Air Products (synthetic)', minConfidence: null, labelSource: 'synthetic' },
];

// Confidence-ordered review queue (lowest first) for the annotation workspace.
export const PREVIEW_QUEUE: PreviewDoc[] = PREVIEW_DOCS.filter((d) => d.minConfidence !== null).sort(
  (a, b) => (a.minConfidence as number) - (b.minConfidence as number),
);

// Fields for the currently-open document in the annotation workspace, mirroring
// the existing Visual Document Editor's confidence-alert view.
export const PREVIEW_FIELDS: PreviewField[] = [
  { name: 'Invoice Number', value: 'A-4471-X6', confidence: 0.61, threshold: 0.8 },
  { name: 'PO Number', value: '4500-7789-02', confidence: 0.78, threshold: 0.8 },
  { name: 'Tax Amount', value: '$50.49', confidence: 0.81, threshold: 0.8 },
];

// Error-burndown series for the target-accuracy estimator (residual error % vs
// docs reviewed, lowest-confidence first).
export const PREVIEW_BURNDOWN: { reviewed: number; residualError: number }[] = [
  { reviewed: 0, residualError: 5.8 },
  { reviewed: 15, residualError: 3.9 },
  { reviewed: 30, residualError: 2.6 },
  { reviewed: 45, residualError: 1.7 },
  { reviewed: 62, residualError: 1.0 },
  { reviewed: 90, residualError: 0.5 },
  { reviewed: 120, residualError: 0.2 },
];

export const PREVIEW_ESTIMATE = {
  currentAccuracy: 94.2,
  target: 99.0,
  docsToReview: 62,
  totalDocs: 120,
  estEffortHours: 4.3,
  impliedCutoff: 0.88,
};
