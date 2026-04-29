// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import svgr from 'vite-plugin-svgr';
import { resolve } from 'path';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    react({
      // Use automatic JSX runtime (React 17+)
      jsxRuntime: 'automatic',
      // Include all JavaScript files for JSX transformation
      include: '**/*.{js,jsx,ts,tsx}',
    }),

    // Enable SVG import as React components
    svgr(),
  ],

  // Ensure all .js and .jsx files are treated as JSX
  esbuild: {
    jsx: 'automatic',
  },

  // Development server configuration
  server: {
    port: 3000,
    open: true,
    // Enable CORS for AWS Amplify
    cors: true,
  },

  // Build configuration
  build: {
    outDir: 'build',
    sourcemap: mode === 'development' ? 'inline' : false,
    // Increase chunk size warning limit (suppressed for enterprise internal tool)
    chunkSizeWarningLimit: 3000,
    rollupOptions: {
      // NOTE: @idp-accelerator/idp-monitor-ui is intentionally NOT marked external
      // in this repo (genaiic-idp-monitor). The package is always installed here
      // via "file:../../products/idp-monitor/ui" and must be bundled so that the
      // dynamic import() in MonitoringShell.tsx resolves successfully at runtime.
      // (In the open-source genaiic-idp-accelerator repo the package is marked
      // external because it may not be installed there.)
      output: {
        // Manual chunking for better code splitting
        manualChunks: {
          'aws-amplify': ['aws-amplify', '@aws-amplify/ui-react'],
          'aws-sdk': ['@aws-sdk/client-s3', '@aws-sdk/client-ssm', '@aws-sdk/client-cognito-identity', '@aws-sdk/s3-request-presigner'],
          cloudscape: ['@cloudscape-design/components', '@cloudscape-design/global-styles'],
          chart: ['chart.js', 'react-chartjs-2'],
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
    // Configure target to ensure JSX is handled
    target: 'esnext',
  },

  // Resolve configuration
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
    // Ensure proper module resolution
    extensions: ['.mjs', '.ts', '.tsx', '.js', '.jsx', '.json'],
    // Deduplicate React — prevents "Cannot read properties of null (reading 'useEffect')"
    // when @idp-accelerator/idp-monitor-ui is bundled inline (its recharts dependency
    // would otherwise pull in a second React instance at runtime).
    dedupe: ['react', 'react-dom', 'react/jsx-runtime', '@cloudscape-design/components'],
  },

  // Define global constants
  define: {
    // Ensure process.env is available for compatibility
    'process.env': {},
    // IDPMonitor AppSync endpoint — injected at build time via environment variables.
    // Set VITE_IDP_MONITOR_API_URL and VITE_IDP_MONITOR_API_KEY in your build environment
    // (CodeBuild env vars, .env.local, etc.) when deploying the IDPMonitor stack.
    // If not set, useMonitoringStatus returns "not_deployed" and the monitoring activation
    // page is shown. The dashboard becomes available once the stack is deployed and the
    // UI is rebuilt with these variables populated.
    __IDP_MONITOR_API_URL__: JSON.stringify(process.env.VITE_IDP_MONITOR_API_URL ?? ''),
    __IDP_MONITOR_API_KEY__: JSON.stringify(process.env.VITE_IDP_MONITOR_API_KEY ?? ''),
    __IDP_MONITOR_MOCK__: JSON.stringify(process.env.VITE_IDP_MONITOR_MOCK ?? ''),
  },

  // Optimize dependencies
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'aws-amplify',
      '@aws-amplify/ui-react',
      '@cloudscape-design/components',
      '@cloudscape-design/global-styles',
    ],
    exclude: ['@aws-sdk/signature-v4-multi-region'],
    esbuildOptions: {
      loader: {
        '.js': 'jsx',
      },
      // Suppress source map warnings for dependencies
      sourcemap: false,
    },
  },

  // Suppress source map warnings in development
  ...(mode === 'development' && {
    logLevel: 'info',
    clearScreen: false,
  }),

  // Test configuration (vitest)
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },

  // CSS configuration
  css: {
    modules: {
      localsConvention: 'camelCase',
    },
  },
}));
