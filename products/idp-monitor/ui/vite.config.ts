// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { resolve } from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import dts from 'vite-plugin-dts';

export default defineConfig({
  plugins: [
    react(),
    dts({
      include: ['src'],
      outDir: 'dist',
      insertTypesEntry: true,
    }),
  ],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'IDPMonitorUI',
      // Produce two outputs:
      //   1. idp-monitor-ui.js     — ESM for library consumers (npm install)
      //   2. idp-monitor-ui.umd.js — UMD for runtime browser loading via
      //      dynamic import() from the Accelerator's S3/CloudFront origin.
      //      This file is what deploy.sh copies to /extensions/idp-monitor-ui.js
      //      on the Accelerator's S3 bucket.
      formats: ['es', 'umd'],
      fileName: (format) =>
        format === 'es' ? 'idp-monitor-ui.js' : 'idp-monitor-ui.umd.js',
    },
    rollupOptions: {
      // Externalize everything the host app (IDP Accelerator) already provides.
      // The Accelerator exposes these on window.__IDP_EXTENSIONS_DEPS__ so the
      // UMD bundle can reference them without bundling its own copies.
      external: [
        'react',
        'react-dom',
        'react/jsx-runtime',
        /^@cloudscape-design\/.*/,
      ],
      output: {
        // UMD globals — must match what the Accelerator exposes on window.
        // See genaiic-idp-monitor/src/ui/src/index.tsx and
        //     genaiic-idp-accelerator/src/ui/src/index.tsx where
        // window.__IDP_EXTENSIONS_DEPS__ is populated.
        globals: (id: string) => {
          if (id === 'react') return 'window.__IDP_EXTENSIONS_DEPS__.React';
          if (id === 'react-dom') return 'window.__IDP_EXTENSIONS_DEPS__.ReactDOM';
          if (id === 'react/jsx-runtime') return 'window.__IDP_EXTENSIONS_DEPS__.ReactJSXRuntime';
          if (id === '@cloudscape-design/collection-hooks') return 'window.__IDP_EXTENSIONS_DEPS__.CloudscapeCollectionHooks';
          // Per-component sub-path imports: @cloudscape-design/components/box → CloudscapeBox
          if (id.startsWith('@cloudscape-design/components/')) {
            const name = id.split('/').pop() ?? 'Component';
            const pascalName = name.charAt(0).toUpperCase() + name.slice(1).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
            return `window.__IDP_EXTENSIONS_DEPS__.Cloudscape${pascalName}`;
          }
          return id;
        },
      },
    },
    sourcemap: true,
    minify: false,
  },
  define: {
    // recharts (and its D3 deps) reference process.env.NODE_ENV at runtime.
    // Vite library builds do NOT inject process shims automatically, so we
    // must replace this at build time or the UMD bundle crashes in the browser
    // with "ReferenceError: process is not defined".
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
});
