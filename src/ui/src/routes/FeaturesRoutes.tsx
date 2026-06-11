// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes, useParams } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';

import GenAIIDPLayout from '../components/genaiidp-layout';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';
import { FeaturePage } from '../components/feature-page';
import FeaturesToolsPanel from '../components/feature-page/FeaturesToolsPanel';
import useUserRole from '../hooks/use-user-role';
import useSettingsContext from '../contexts/settings';

const logger = new ConsoleLogger('FeaturesRoutes');

/**
 * Wrapper that pulls the current user role and stack name from context
 * and passes them to the `<FeaturePage />` renderer.
 *
 * This keeps `FeaturePage` itself free of app-specific hook imports so it
 * can live in the prototype library / be unit-tested in isolation.
 */
const FeaturePageWrapper: React.FC = () => {
  const { featureId } = useParams<{ featureId?: string }>();
  const { groups } = useUserRole();
  const { settings } = useSettingsContext();
  const mainStackName = (settings?.StackName as string | undefined) ?? '';
  logger.debug('FeaturePageWrapper', { featureId, mainStackName, groups });
  return <FeaturePage groups={groups} mainStackName={mainStackName} />;
};

const FeaturesRoutes = (): React.JSX.Element => {
  logger.info('FeaturesRoutes');
  return (
    <Routes>
      <Route
        // The `/*` suffix lets a feature's UMD declare its own nested
        // <Routes>; react-router passes `*` through to FeaturePage's
        // outlet so e.g. /features/claims-pack/queue resolves there.
        path=":featureId/*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <GenAIIDPLayout tools={<FeaturesToolsPanel />}>
              <FeaturePageWrapper />
            </GenAIIDPLayout>
          </div>
        }
      />
      <Route
        path="*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <GenAIIDPLayout tools={<FeaturesToolsPanel />}>
              <FeaturePageWrapper />
            </GenAIIDPLayout>
          </div>
        }
      />
    </Routes>
  );
};

export default FeaturesRoutes;
