// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';

import GenAIIDPLayout from '../components/genaiidp-layout';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';

const logger = new ConsoleLogger('DocumentsRoutes');

const DocumentsRoutes = (): React.JSX.Element => {
  logger.info('DocumentsRoutes');

  return (
    <Routes>
      <Route
        path="*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <GenAIIDPLayout />
          </div>
        }
      />
    </Routes>
  );
};

export default DocumentsRoutes;
