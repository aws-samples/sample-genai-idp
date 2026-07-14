// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { ContentLayout } from '@cloudscape-design/components';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';
import WelcomeContent from '../components/welcome/WelcomeContent';

const WelcomePage = (): React.JSX.Element => (
  <div>
    <GenAIIDPTopNavigation />
    <div style={{ maxWidth: 900, margin: '48px auto', padding: '0 24px' }}>
      <ContentLayout>
        <WelcomeContent showDismiss />
      </ContentLayout>
    </div>
  </div>
);

export default WelcomePage;
