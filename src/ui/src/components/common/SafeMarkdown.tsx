// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * SafeMarkdown — a drop-in replacement for ReactMarkdown + rehype-raw that
 * sanitizes rendered HTML against an allow-list schema.
 *
 * Why: the backend deliberately emits rich markdown containing a small set
 * of HTML constructs (`<details>/<summary>`, custom `<documentid>` anchors,
 * `<br>`, styled `<p>` for whitespace preservation, tables). Some of that
 * markdown embeds user-document-derived content (OCR text, KB snippets,
 * LLM answers) which could carry attacker-controlled HTML — for example,
 * a malicious PDF containing `<img src=x onerror=…>` in its OCR output.
 *
 * Rendering that content with just `rehype-raw` was exploitable as stored
 * XSS. Pairing `rehype-raw` with `rehype-sanitize` keeps the legitimate
 * HTML working while stripping event handlers, `<script>`, `<iframe>`,
 * `javascript:` URLs, and other active-content vectors.
 *
 * The schema is an extension of `rehype-sanitize`'s `defaultSchema`:
 *   - Allow `<details>` and `<summary>` (used by KB query "Context")
 *   - Allow the custom `<documentid>` tag (mapped to a React component
 *     via the `components` prop at call sites)
 *   - Allow a narrow `style` attribute on `<p>` so backend-emitted
 *     `style="white-space: pre-line"` continues to work. (We intend to
 *     migrate this to a CSS class in a follow-up so CSP can eventually
 *     drop 'unsafe-inline' from style-src.)
 *   - Allow `href` URL schemes restricted to http/https/mailto plus
 *     relative URLs (anchor references used for bounding-box overlays
 *     and navigation to document pages).
 */

import React from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import type { PluggableList } from 'unified';

/**
 * Allow-list schema. We start from `defaultSchema` (which already covers
 * common markdown-to-HTML elements safely) and extend it in a minimal
 * targeted way. We do NOT allow event handlers (on*) — rehype-sanitize
 * strips those by default and we inherit that.
 */
const safeSchema = {
  ...defaultSchema,
  // Retain the default URL scheme allow-list, adding `mailto`.
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto'],
    src: ['http', 'https', 'data'], // `data:` only for images inlined by the backend
    cite: ['http', 'https'],
  },
  // Allow the small set of tags the backend uses beyond defaults.
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    'details',
    'summary',
    // Custom tag emitted by query_knowledgebase_resolver; mapped to a
    // CustomLink React component in DocumentsQueryLayout.tsx via the
    // `components` prop.
    'documentid',
  ],
  // Extend per-tag attribute allow-lists. defaultSchema already permits
  // a safe set for most tags. We add:
  //   - style on <p> for `white-space: pre-line` use (temporary)
  //   - href on <documentid> so CustomLink can read it
  //   - className wherever we expect syntax-highlighted code
  attributes: {
    ...defaultSchema.attributes,
    p: [...(defaultSchema.attributes?.p ?? []), ['style', /^white-space:\s*pre-line;?$/i]],
    documentid: ['href', 'title', 'className'],
    code: [...(defaultSchema.attributes?.code ?? []), 'className'],
    span: [...(defaultSchema.attributes?.span ?? []), 'className', 'style'],
    div: [...(defaultSchema.attributes?.div ?? []), 'className'],
    a: [...(defaultSchema.attributes?.a ?? []), 'target', 'rel'],
    img: [...(defaultSchema.attributes?.img ?? []), 'alt', 'width', 'height'],
    // details/summary have no attributes of interest beyond the tag itself.
    details: [...(defaultSchema.attributes?.['*'] ?? []), 'open'],
    summary: defaultSchema.attributes?.['*'] ?? [],
  },
  // Allow class names starting with `hljs-`, `language-`, or `md-` (used
  // in our custom evaluation reports). defaultSchema permits `className`
  // on many elements but restricts allowed class tokens; here we keep
  // its default behavior and rely on the per-element attribute list
  // above to include `className`.
} as const;

export interface SafeMarkdownProps {
  children: string;
  /**
   * Optional custom components mapping, forwarded to ReactMarkdown's
   * `components` prop. Use this to intercept `documentid` etc.
   */
  components?: Components;
  /**
   * Optional additional remark plugins. remark-gfm is always enabled.
   */
  extraRemarkPlugins?: PluggableList;
  /**
   * Optional additional rehype plugins. rehype-raw (parse) + rehype-sanitize
   * (sanitize) are always enabled; anything provided here runs after them.
   */
  extraRehypePlugins?: PluggableList;
  className?: string;
}

/**
 * Renders `children` as markdown, parsing any embedded raw HTML via
 * rehype-raw and then sanitizing the result against `safeSchema`.
 *
 * Intended to replace bare `<ReactMarkdown remarkPlugins={[remarkGfm]}
 * rehypePlugins={[rehypeRaw]}>` usages across the UI.
 */
const SafeMarkdown: React.FC<SafeMarkdownProps> = ({
  children,
  components,
  extraRemarkPlugins = [],
  extraRehypePlugins = [],
  className,
}) => {
  const content = children ?? '';
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, ...extraRemarkPlugins]}
      // IMPORTANT: rehype-raw MUST run before rehype-sanitize so the raw
      // HTML nodes are materialized as HAST elements before we sanitize.
      rehypePlugins={[rehypeRaw, [rehypeSanitize, safeSchema], ...extraRehypePlugins]}
      components={components}
      {...(className ? ({ className } as Record<string, unknown>) : {})}
    >
      {content}
    </ReactMarkdown>
  );
};

export default SafeMarkdown;
