# Frontend UI Development — GenAI IDP Accelerator

## Stack
- **Framework**: React 18.3 + TypeScript 5.9 (strict mode)
- **UI Library**: Cloudscape Design System v3 (`@cloudscape-design/components`)
- **Bundler**: Vite 7.3 with `@vitejs/plugin-react` (automatic JSX)
- **Auth**: AWS Amplify v6 + Cognito (`@aws-amplify/ui-react`)
- **API**: AppSync GraphQL with generated types (via `codegen.config.mjs`)
- **Router**: react-router-dom v6 (HashRouter)
- **State**: React Context + `immer` (NO Redux)
- **Node**: `>=22.12.0`, npm `>=10.0.0`
- **Module**: ESM (`"type": "module"`)
- **Test**: Vitest + jsdom

## Path Alias
`@/` → `./src/` (configured in both `tsconfig.json` and `vite.config.js`)
```tsx
import { useAppContext } from '@/contexts/app';
```

## Component Pattern (MUST follow)
Arrow function components are ENFORCED by ESLint:
```tsx
import React, { useState, useEffect, useMemo } from 'react';
import { Table, Pagination, TextFilter, Box, SpaceBetween } from '@cloudscape-design/components';
import { useCollection } from '@cloudscape-design/collection-hooks';
import { ConsoleLogger } from 'aws-amplify/utils';

const logger = new ConsoleLogger('MyComponent');

const MyComponent = (): React.JSX.Element => {
  // 1. Hooks (context, state, refs, navigation)
  const { user } = useAppContext();
  const [data, setData] = useState<MyType[]>([]);
  const navigate = useNavigate();

  // 2. Effects
  useEffect(() => {
    // ...
  }, []);

  // 3. Memos / derived state
  const filtered = useMemo(() => data.filter(...), [data]);

  // 4. Handlers
  const handleClick = () => { ... };

  // 5. Render
  return (
    <SpaceBetween size="l">
      <Table items={filtered} ... />
    </SpaceBetween>
  );
};

export default MyComponent;
```

## Directory Structure
```
src/ui/src/
├── App.tsx              # Root: ThemeProvider > Authenticator.Provider > AppContent
├── index.tsx            # Entry point
├── components/          # 27 feature directories + common/
│   ├── common/          # Shared (tables, modals, labels, download helpers)
│   ├── agent-chat/
│   ├── document-list/
│   ├── document-details/
│   ├── configuration-layout/
│   ├── json-schema-builder/
│   ├── test-studio/
│   └── ...
├── contexts/            # React Context providers
│   ├── app.ts           # AppContext (auth, config, navigation)
│   ├── agentChat.tsx
│   ├── analytics.tsx
│   ├── documents.ts
│   └── settings.ts
├── hooks/               # 17 custom hooks (use-kebab-case.ts for new ones)
├── routes/              # Route definitions (AuthRoutes, UnauthRoutes, etc.)
├── graphql/             # Generated GraphQL types — DO NOT EDIT manually
├── types/               # TypeScript type definitions
├── utils/               # Utility functions
├── constants/           # App constants
└── data/                # Static data (e.g., standard-classes.json)
```

## Context Pattern
```tsx
// Definition (contexts/app.ts)
export interface AppContextValue {
  authState: string;
  awsConfig: Record<string, unknown> | undefined;
  user: AuthUser | undefined;
}
export const AppContext = createContext<AppContextValue | null>(null);
const useAppContext = (): AppContextValue => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppContext must be used within AppContext.Provider');
  return ctx;
};
export default useAppContext;
```

## Auth Pattern
```tsx
import { useAuthenticator } from '@aws-amplify/ui-react';
import { fetchAuthSession } from 'aws-amplify/auth';

const { user, signOut } = useAuthenticator();
const session = await fetchAuthSession();
const credentials = session.credentials;
```

## Logging Pattern
Use Amplify's ConsoleLogger per component:
```tsx
import { ConsoleLogger } from 'aws-amplify/utils';
const logger = new ConsoleLogger('ComponentName');
logger.debug('message');
logger.error('error', error);
```

## GraphQL / AppSync
- Types are auto-generated via `make codegen` (uses `codegen.config.mjs`)
- Generated files live in `src/graphql/generated/` — NEVER edit manually
- Use `useGraphqlApi` hook for AppSync operations
- Real-time updates via AppSync GraphQL subscriptions

## Key Dependencies
| Package | Purpose |
|---------|---------|
| `@cloudscape-design/components` v3 | UI components |
| `@cloudscape-design/collection-hooks` | Table/collection utilities |
| `@cloudscape-design/chat-components` | Chat UI |
| `@monaco-editor/react` | Code editor |
| `chart.js` + `react-chartjs-2` | Charts |
| `recharts` | Alternative charts |
| `react-markdown` + `remark-gfm` | Markdown rendering |
| `@dnd-kit/core` + `@dnd-kit/sortable` | Drag and drop |
| `pdfjs-dist` | PDF rendering |
| `dompurify` | HTML sanitization |
| `immer` | Immutable state updates |

## ESLint / Prettier Config
- **Flat config** (`eslint.config.js`)
- **Prettier**: `printWidth: 140`, `singleQuote: true`, `trailingComma: 'all'`
- **Max line length**: 140 (ignoring URLs, templates, comments, strings)
- **Components**: Arrow functions enforced (`react/function-component-definition`)
- **Unused vars**: Warn (ignore `_` prefixed)
- **No explicit any**: Warn
- **react-hooks/exhaustive-deps**: OFF (intentionally disabled)
- **Linebreak**: Unix only

## Hook File Naming
- NEW hooks: kebab-case (`use-my-hook.ts`)
- Legacy hooks: camelCase (`useMyHook.ts`) — don't rename existing ones

## CSS
- CSS Modules with `camelCase` convention
- Import Cloudscape global styles: `import '@cloudscape-design/global-styles/index.css'`

## Commands
```bash
make ui-lint             # Lint + typecheck (checksum-cached, use FORCE=1 to re-run)
make ui-build            # Production build
make ui-start STACK_NAME=<name>   # Dev server on port 3000
make codegen             # Regenerate GraphQL types
make codegen-check       # Verify generated types are up to date
cd src/ui && npm run lint -- --fix   # Direct ESLint fix
cd src/ui && npm run typecheck       # Direct TypeScript check
```
