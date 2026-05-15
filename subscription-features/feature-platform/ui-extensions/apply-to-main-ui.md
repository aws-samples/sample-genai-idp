# Applying the UI extensions to `src/ui/`

This document describes the exact, minimal changes needed to integrate the
files in `subscription-features/feature-platform/ui-extensions/` into the real
`src/ui/src/`. **None** of these changes have been applied yet.

All additions are **purely additive** — they do not alter existing routes,
components, or hooks. Removing them later is a straight file-delete + small
revert of the navigation/App.tsx edits.

---

## 1. Copy files

```bash
SRC=subscription-features/feature-platform/ui-extensions
DST=src/ui/src

cp -r $SRC/components/feature-page              $DST/components/
# (includes feature-host-globals.ts — the host-side shim that exposes
# React/ReactDOM/Cloudscape/aws-amplify/react-router-dom as window globals
# so feature UMD bundles can resolve them at script-load time.)
cp    $SRC/hooks/use-installed-features.ts       $DST/hooks/
cp    $SRC/hooks/use-catalog-features.ts         $DST/hooks/
cp    $SRC/hooks/use-feature-entitlement.ts      $DST/hooks/
cp    $SRC/hooks/use-feature-launch-url.ts       $DST/hooks/
cp    $SRC/hooks/use-subscribe-feature.ts        $DST/hooks/
cp    $SRC/hooks/use-unsubscribe-feature.ts      $DST/hooks/
cp    $SRC/graphql/feature-platform.ts           $DST/graphql/
cp    $SRC/types/feature-platform.ts             $DST/types/
cp    $SRC/navigation/feature-platform-nav-items.ts \
      $DST/components/genaiidp-layout/
```

> The `routes/feature-platform-constants.ts` file is NOT copied as a separate
> file — its two exports are merged into the existing `src/ui/src/routes/constants.ts`
> (see step 2).

## 2. Patch `src/ui/src/routes/constants.ts`

Append these two exports:

```typescript
// --- Feature Platform ---
export const FEATURES_PATH_PREFIX = '/features';
/** Route pattern: /features/:featureId */
export const FEATURE_DETAIL_PATH = `${FEATURES_PATH_PREFIX}/:featureId`;

/** Hash-link helper: href to pass to nav items & internal links. */
export const featureDetailHref = (featureId: string): string => `#${FEATURES_PATH_PREFIX}/${featureId}`;
```

## 3. Add route to `src/ui/src/App.tsx`

Inside the `<Routes>` block, add a route for `FEATURE_DETAIL_PATH`. Example
patch — the exact placement depends on the existing structure, but the goal
is to wrap it in the same authenticated `<Layout>` as other authenticated routes:

```tsx
import { FeaturePage } from './components/feature-page';
import useUserRole from './hooks/use-user-role';
import { FEATURES_PATH_PREFIX, FEATURE_DETAIL_PATH } from './routes/constants';

// ... inside the routes array, next to the other authenticated pages:

<Route
  path={FEATURE_DETAIL_PATH}
  element={
    <Layout>
      <FeaturePageWrapper />
    </Layout>
  }
/>

// ... optionally, a bare /features landing page too:
<Route path={FEATURES_PATH_PREFIX} element={<Layout><FeaturesLanding /></Layout>} />
```

Where `FeaturePageWrapper` is a tiny wrapper that injects the current role and stack name:

```tsx
const FeaturePageWrapper: React.FC = () => {
  const { groups } = useUserRole();
  // MAIN_STACK_NAME is already baked into aws-exports.js / settings context;
  // use the existing useSettingsContext() if available, or pass via env.
  const { settings } = useSettingsContext();
  return (
    <FeaturePage
      groups={groups}
      mainStackName={settings?.mainStackName ?? ''}
      marketplaceUrls={{/* optional */}}
    />
  );
};
```

## 4. Patch `src/ui/src/components/genaiidp-layout/navigation.tsx`

Add **one line** to each of the four role nav arrays
(`adminNavItems`, `authorNavItems`, `viewerNavItems`, `reviewerNavItems`).
The dynamic section is appended (not static) because it re-renders when
`useInstalledFeatures` returns new data.

**Before** (each array):
```tsx
export const adminNavItems = [
  { type: 'link', text: 'Document List', ... },
  // ... existing items ...
  { type: 'section', text: 'Resources', items: [...] },
];
```

**After**:
```tsx
import useInstalledFeatures from '../../hooks/use-installed-features';
import useCatalogFeatures from '../../hooks/use-catalog-features';
import { buildFeaturesNavSection } from './feature-platform-nav-items';

// Inside the Navigation component, replace the static role arrays with a
// useMemo that appends the dynamic section. The role arrays remain as base
// constants but are combined per-render:

const Navigation: React.FC = () => {
  const { isAdmin, isAuthor, isReviewer } = useUserRole();
  const { features: installedFeatures } = useInstalledFeatures();
  const { features: catalogFeatures } = useCatalogFeatures();

  const featuresSection = useMemo(
    () => buildFeaturesNavSection(installedFeatures, catalogFeatures),
    [installedFeatures, catalogFeatures],
  );

  const items = useMemo(() => {
    const base = isAdmin
      ? adminNavItems
      : isAuthor
        ? authorNavItems
        : isReviewer
          ? reviewerNavItems
          : viewerNavItems;
    // Insert the dynamic "Subscription Features" section just before Resources
    const resourcesIdx = base.findIndex(
      (i) => i.type === 'section' && i.text === 'Resources',
    );
    if (resourcesIdx < 0) return [...base, featuresSection];
    return [
      ...base.slice(0, resourcesIdx),
      featuresSection,
      ...base.slice(resourcesIdx),
    ];
  }, [isAdmin, isAuthor, isReviewer, featuresSection]);

  // ... existing <SideNavigation items={items} /> render ...
};
```

The "Subscription Features" section is **always visible** — when no features
are installed, it shows a single "No features installed" item instead of an
empty section.

## 5. (Optional) Populate `marketplaceUrls`

If you want clickable Marketplace links in the NONE and EXPIRED states, supply
a map to the `FeaturePage` wrapper. A convenient place is a new settings key:

```typescript
// In useSettingsContext or a new constants file:
export const MARKETPLACE_LISTING_URLS: Record<string, string> = {
  'docs-by-status': 'https://aws.amazon.com/marketplace/pp/prodview-XYZ',
};
```

Passing an empty map is fine; the Marketplace button simply won't render.

---

## Checklist to apply (once reviewed)

- [ ] Copy `components/feature-page/` directory (includes `feature-host-globals.ts`, which is **required** — feature UMD bundles crash on load without it)
- [ ] Copy six hooks (`use-installed-features`, `use-catalog-features`, `use-feature-entitlement`, `use-feature-launch-url`, `use-subscribe-feature`, `use-unsubscribe-feature`)
- [ ] Copy `graphql/feature-platform.ts`
- [ ] Copy `types/feature-platform.ts`
- [ ] Copy `feature-platform-nav-items.ts` into genaiidp-layout/
- [ ] Merge `FEATURES_PATH_PREFIX` / `FEATURE_DETAIL_PATH` / `featureDetailHref` into `routes/constants.ts`
- [ ] Add `FEATURE_DETAIL_PATH` route to `App.tsx`
- [ ] Wire `buildFeaturesNavSection` into `navigation.tsx`
- [ ] Run `npm run lint` in `src/ui/` and confirm no errors
- [ ] Run `npx vitest run` in `src/ui/` and confirm the new `FeaturePage.test.tsx` passes

## Rollback

To remove the feature platform from the UI later:

1. Delete `src/ui/src/components/feature-page/`
2. Delete the six `use-*feature*` / `use-installed-features.ts` / `use-catalog-features.ts`
   / `use-subscribe-feature.ts` / `use-unsubscribe-feature.ts` hook files
3. Delete `src/ui/src/graphql/feature-platform.ts`
4. Delete `src/ui/src/types/feature-platform.ts`
5. Delete `src/ui/src/components/genaiidp-layout/feature-platform-nav-items.ts`
6. Revert the 3 line additions in `routes/constants.ts`, `App.tsx`, and `navigation.tsx`

No other UI code references any of these — rollback is safe.
