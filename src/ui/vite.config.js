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
      output: {
        // Manual chunking for better code splitting
        manualChunks: {
          'aws-amplify': ['aws-amplify', '@aws-amplify/ui-react'],
          'aws-sdk': [
            '@aws-sdk/client-s3',
            '@aws-sdk/client-ssm',
            '@aws-sdk/client-cognito-identity',
            '@aws-sdk/s3-request-presigner',
          ],
          'cloudscape': ['@cloudscape-design/components', '@cloudscape-design/global-styles'],
          'chart': ['chart.js', 'react-chartjs-2'],
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
  },

  // Define global constants
  define: {
    // Ensure process.env is available for compatibility
    'process.env': {},
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

  // CSS configuration
  css: {
    modules: {
      localsConvention: 'camelCase',
    },
  },
}));