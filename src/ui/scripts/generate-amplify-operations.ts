/**
 * Generate Amplify v6 branded string operations from .graphql files.
 *
 * Reads all .graphql files from src/graphql/operations/, matches them to
 * generated types from operation-types.ts, and outputs a single index.ts
 * file with branded casts for use with Amplify's generateClient().graphql().
 *
 * Run via: npm run generate-operations (or as part of npm run codegen)
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const OPERATIONS_DIR = path.resolve(__dirname, '../src/graphql/operations');
const OPERATION_TYPES_FILE = path.resolve(__dirname, '../src/graphql/generated/operation-types.ts');
const OUTPUT_FILE = path.resolve(__dirname, '../src/graphql/generated/index.ts');

interface OperationInfo {
  /** camelCase export name, e.g. "getDocument" */
  exportName: string;
  /** PascalCase operation name from the GraphQL text, e.g. "GetDocument" */
  operationName: string;
  /** "query" | "mutation" | "subscription" */
  operationType: 'query' | 'mutation' | 'subscription';
  /** Raw GraphQL text */
  graphqlText: string;
  /** The generated Variables type name, e.g. "GetDocumentQueryVariables" */
  variablesType: string | null;
  /** The generated Output type name, e.g. "GetDocumentQuery" */
  outputType: string | null;
}

/**
 * Extract the operation name and type from raw GraphQL text.
 * Matches patterns like: query GetDocument(...) { ... }
 */
function parseGraphQL(text: string, filePath?: string): { operationName: string; operationType: 'query' | 'mutation' | 'subscription' } | null {
  // Strip comment lines (lines starting with #) before parsing
  const strippedText = text.split('\n').filter(line => !line.trimStart().startsWith('#')).join('\n');
  const matches = [...strippedText.matchAll(/\b(query|mutation|subscription)\s+([A-Za-z_]\w*)/g)];
  if (matches.length > 1) {
    console.warn(`Warning: ${filePath ?? '<unknown>'} contains ${matches.length} operations; only the first will be used`);
  }
  if (matches.length === 0) return null;
  const [, operationType, operationName] = matches[0];
  return {
    operationType: operationType as 'query' | 'mutation' | 'subscription',
    operationName,
  };
}

/** Convert PascalCase to camelCase */
function toCamelCase(str: string): string {
  return str.charAt(0).toLowerCase() + str.slice(1);
}

/** Read all exported type names from operation-types.ts */
function readExportedTypes(filePath: string): Set<string> {
  const content = fs.readFileSync(filePath, 'utf-8');
  const types = new Set<string>();
  // Match: export type TypeName = ...
  const regex = /export\s+type\s+(\w+)\s*=/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    types.add(match[1]);
  }
  return types;
}

/** Recursively read all .graphql files from a directory */
function readGraphQLFiles(dir: string): { filePath: string; content: string }[] {
  const results: { filePath: string; content: string }[] = [];
  if (!fs.existsSync(dir)) return results;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...readGraphQLFiles(fullPath));
    } else if (entry.name.endsWith('.graphql')) {
      results.push({ filePath: fullPath, content: fs.readFileSync(fullPath, 'utf-8') });
    }
  }
  return results;
}

/**
 * For a given operation name and type, determine the codegen type names.
 *
 * GraphQL Codegen naming convention:
 * - Query "GetDocument" → types: GetDocumentQuery, GetDocumentQueryVariables
 * - Mutation "DeleteDocument" → types: DeleteDocumentMutation, DeleteDocumentMutationVariables
 * - Subscription "OnCreateDocument" → types: OnCreateDocumentSubscription, OnCreateDocumentSubscriptionVariables
 */
function inferTypeNames(
  operationName: string,
  operationType: 'query' | 'mutation' | 'subscription',
  availableTypes: Set<string>,
): { outputType: string | null; variablesType: string | null } {
  const suffix =
    operationType === 'query' ? 'Query' :
    operationType === 'mutation' ? 'Mutation' :
    'Subscription';

  const outputType = `${operationName}${suffix}`;
  const variablesType = `${operationName}${suffix}Variables`;

  return {
    outputType: availableTypes.has(outputType) ? outputType : null,
    variablesType: availableTypes.has(variablesType) ? variablesType : null,
  };
}

function main(): void {
  // 1. Read available generated types
  if (!fs.existsSync(OPERATION_TYPES_FILE)) {
    console.error(`ERROR: ${OPERATION_TYPES_FILE} not found. Run graphql-codegen first.`);
    process.exit(1);
  }
  const availableTypes = readExportedTypes(OPERATION_TYPES_FILE);

  // 2. Read all .graphql files
  const graphqlFiles = readGraphQLFiles(OPERATIONS_DIR);
  if (graphqlFiles.length === 0) {
    console.error(`ERROR: No .graphql files found in ${OPERATIONS_DIR}`);
    process.exit(1);
  }

  // 3. Parse each file and build operation info
  const operations: OperationInfo[] = [];
  const errors: string[] = [];

  for (const { filePath, content } of graphqlFiles) {
    const parsed = parseGraphQL(content, filePath);
    if (!parsed) {
      errors.push(`WARNING: Could not parse operation from ${path.relative(OPERATIONS_DIR, filePath)}`);
      continue;
    }

    const { operationName, operationType } = parsed;
    const { outputType, variablesType } = inferTypeNames(operationName, operationType, availableTypes);

    if (!outputType) {
      errors.push(`WARNING: No generated type found for ${operationName} (expected ${operationName}${operationType === 'query' ? 'Query' : operationType === 'mutation' ? 'Mutation' : 'Subscription'})`);
      continue;
    }

    operations.push({
      exportName: toCamelCase(operationName),
      operationName,
      operationType,
      graphqlText: content.trim(),
      variablesType,
      outputType,
    });
  }

  if (operations.length === 0) {
    console.error('ERROR: No valid operations could be parsed from .graphql files');
    process.exit(1);
  }

  // Log warnings
  for (const error of errors) {
    console.warn(error);
  }

  // Sort operations alphabetically for stable output
  operations.sort((a, b) => a.exportName.localeCompare(b.exportName));

  // 4. Collect all type imports
  const typeImports: string[] = [];
  for (const op of operations) {
    if (op.outputType) typeImports.push(op.outputType);
    if (op.variablesType) typeImports.push(op.variablesType);
  }
  typeImports.sort();

  // Determine which branded type imports we need
  const needsGeneratedQuery = operations.some((op) => op.operationType === 'query');
  const needsGeneratedMutation = operations.some((op) => op.operationType === 'mutation');
  const needsGeneratedSubscription = operations.some((op) => op.operationType === 'subscription');

  const amplifyImports: string[] = [];
  if (needsGeneratedQuery) amplifyImports.push('GeneratedQuery');
  if (needsGeneratedMutation) amplifyImports.push('GeneratedMutation');
  if (needsGeneratedSubscription) amplifyImports.push('GeneratedSubscription');

  // 5. Generate output
  const lines: string[] = [
    '/* eslint-disable */',
    '// This file is auto-generated by npm run codegen. Do not edit manually.',
    '',
    `import type { ${amplifyImports.join(', ')} } from '@aws-amplify/api-graphql';`,
    `import type { ${typeImports.join(', ')} } from './operation-types';`,
    '',
  ];

  for (const op of operations) {
    const brandedType =
      op.operationType === 'query' ? 'GeneratedQuery' :
      op.operationType === 'mutation' ? 'GeneratedMutation' :
      'GeneratedSubscription';

    const variablesPart = op.variablesType || 'never';
    const outputPart = op.outputType;

    // Indent the GraphQL text by 2 spaces for readability
    const indentedText = op.graphqlText
      .split('\n')
      .map((line) => `  ${line}`)
      .join('\n');

    lines.push(`export const ${op.exportName} = /* GraphQL */ \``);
    lines.push(indentedText);
    lines.push(`\` as ${brandedType}<${variablesPart}, ${outputPart}>;`);
    lines.push('');
  }

  // Ensure output directory exists
  const outputDir = path.dirname(OUTPUT_FILE);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  fs.writeFileSync(OUTPUT_FILE, lines.join('\n'), 'utf-8');
  console.log(`Generated ${operations.length} branded operations in ${path.relative(process.cwd(), OUTPUT_FILE)}`);

  if (errors.length > 0) {
    console.warn(`${errors.length} warning(s) encountered — see above.`);
  }
}

main();
