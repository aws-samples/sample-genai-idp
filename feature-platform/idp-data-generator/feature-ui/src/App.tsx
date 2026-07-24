// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Box, Container, Header, SpaceBetween, Link } from '@cloudscape-design/components';

import type { FeatureContext } from './types';

declare const __FEATURE_VERSION__: string;

// Host Test Studio hash route. Test Sets is the default tab there, where the
// "Generate Test Set" action lives.
const TEST_STUDIO_HASH = '#/test-studio';

// Upstream SEED generator documentation.
const SEED_DOCS_URL = 'https://awslabs.github.io/synthetically_engineered_evaluation_data';

/**
 * Test Set Generator feature page.
 *
 * Generation is driven from the host's Test Studio (Test Sets → Generate
 * Synthetic Data), which offers dependent version/class dropdowns backed by the
 * host configuration. This page is just a landing card that points there — the
 * host modal is the single source of truth, so we don't duplicate the form (or
 * proxy host config listing) inside the sandboxed feature bundle.
 */
const App: React.FC<FeatureContext> = ({ installedVersion }) => (
  <Container
    header={
      <Header variant="h1" description={`Generate labeled synthetic test sets · v${installedVersion || __FEATURE_VERSION__}`}>
        Test Set Generator
      </Header>
    }
  >
    <SpaceBetween size="m">
      <Box variant="p">
        This extension adds synthetic test-set generation to the accelerator. Generate labeled documents (PDF +
        ground-truth JSON) from a plain-language description or an existing configuration version.
      </Box>
      <Box variant="p">
        Start a generation from <strong>Test Studio → Test Sets → Generate Test Set</strong>. The resulting test
        set appears in the Test Sets list when the background job completes.
      </Box>
      <Link href={TEST_STUDIO_HASH}>Go to Test Studio → Test Sets</Link>
      <Link href={SEED_DOCS_URL} external externalIconAriaLabel="Opens in a new tab">
        SEED generator documentation
      </Link>
    </SpaceBetween>
  </Container>
);

export default App;
