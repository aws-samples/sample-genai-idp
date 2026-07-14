// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Central definition of the public GitHub repository used for feedback and
 * issue reporting from the web UI. Previously the owner/repo slug and derived
 * URLs were repeated as string literals across several components (nav links,
 * tools panels, capacity-planning "Beta Feedback" alert). Import from here
 * instead so there is a single source of truth.
 *
 * Note: the canonical source lives in GitLab and is mirrored to this public
 * GitHub repo. User-facing feedback/issues are logged on GitHub (public).
 */
export const GITHUB_OWNER_REPO = 'aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws';

export const GITHUB_REPO_URL = `https://github.com/${GITHUB_OWNER_REPO}`;

/** Issues list. */
export const GITHUB_ISSUES_URL = `${GITHUB_REPO_URL}/issues`;

/** New-issue endpoint (append `?template=...&<field-id>=...` to prefill a form). */
export const GITHUB_NEW_ISSUE_URL = `${GITHUB_ISSUES_URL}/new`;

/** Issue-form template filenames (must match files in .github/ISSUE_TEMPLATE/). */
export const GITHUB_BUG_TEMPLATE = 'bug_report.yml';
export const GITHUB_FEATURE_TEMPLATE = 'feature_request.yml';

/** Published documentation site (GitHub Pages). */
export const DOCS_BASE_URL = `https://aws-solutions-library-samples.github.io/accelerated-intelligent-document-processing-on-aws`;
