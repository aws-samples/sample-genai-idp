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
      formats: ['es', 'umd'],
      fileName: (format) =>
        format === 'es' ? 'idp-monitor-ui.js' : 'idp-monitor-ui.umd.cjs',
    },
    rollupOptions: {
      // Externalize everything the host app already provides
      external: [
        'react',
        'react-dom',
        'react/jsx-runtime',
        /^@cloudscape-design\/.*/,
      ],
      output: {
        globals: (id: string) => {
          if (id === 'react') return 'React';
          if (id === 'react-dom') return 'ReactDOM';
          if (id === 'react/jsx-runtime') return 'ReactJSXRuntime';
          if (id === '@cloudscape-design/collection-hooks') return 'CloudscapeCollectionHooks';
          // Per-component sub-path imports: @cloudscape-design/components/box → CloudscapeBox
          if (id.startsWith('@cloudscape-design/components/')) {
            const name = id.split('/').pop() ?? 'Component';
            return 'Cloudscape' + name.charAt(0).toUpperCase() + name.slice(1).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
          }
          return id;
        },
      },
    },
    sourcemap: true,
    minify: false,
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
});
