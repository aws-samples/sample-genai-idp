// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';

// Import the component directly from the file instead of the directory
import DocumentsAgentsLayout from '../components/document-agents-layout/DocumentsAgentsLayout';
import GenAIIDPLayout from '../components/genaiidp-layout';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';

const logger = new ConsoleLogger('DocumentsAnalyticsRoutes');

const DocumentsAnalyticsRoutes = (): React.JSX.Element => {
  logger.info('DocumentsAnalyticsRoutes');

  return (
    <Routes>
      <Route
        path="*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <GenAIIDPLayout>
              <DocumentsAgentsLayout />
            </GenAIIDPLayout>
          </div>
        }
      />
    </Routes>
  );
};

export default DocumentsAnalyticsRoutes;
