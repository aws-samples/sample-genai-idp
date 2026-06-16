// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Renders backend markdown through the HOST's SafeMarkdown component.
 *
 * The rule-validation consolidated summary is markdown with embedded HTML
 * (a `<style>` block, `<colgroup>`/`<col>`, styled `<span>` color tags, and
 * GFM tables) AND document-derived content. The host exposes its
 * XSS-sanitizing renderer (rehype-raw + rehype-sanitize allow-list) on
 * `window.IdpFeatureHost.SafeMarkdown` so features render it through the same
 * vetted pipeline instead of bundling their own (unsanitized) markdown
 * renderer. See src/ui/src/components/feature-page/feature-host-globals.ts and
 * src/ui/src/components/common/SafeMarkdown.tsx.
 *
 * If the host is older and doesn't expose SafeMarkdown, we fall back to
 * preformatted text — readable, and never executes embedded HTML.
 */

import React from 'react';
import { Box } from '@cloudscape-design/components';

type SafeMarkdownComponent = React.ComponentType<{ children: string }>;

interface HostNamespace {
  SafeMarkdown?: SafeMarkdownComponent;
}

function getHostSafeMarkdown(): SafeMarkdownComponent | null {
  if (typeof window === 'undefined') return null;
  const host = (window as unknown as { IdpFeatureHost?: HostNamespace })
    .IdpFeatureHost;
  return host?.SafeMarkdown ?? null;
}

const PreFallback: React.FC<{ children: string }> = ({ children }) => (
  <Box variant="code">
    <pre
      style={{
        whiteSpace: 'pre-wrap',
        maxHeight: 480,
        overflow: 'auto',
        margin: 0,
      }}
    >
      {children}
    </pre>
  </Box>
);

const HostMarkdown: React.FC<{ children: string }> = ({ children }) => {
  const SafeMarkdown = getHostSafeMarkdown();
  if (!SafeMarkdown) {
    return <PreFallback>{children}</PreFallback>;
  }
  return <SafeMarkdown>{children}</SafeMarkdown>;
};

export default HostMarkdown;
