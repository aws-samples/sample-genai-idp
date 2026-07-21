// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Routes, Route } from 'react-router-dom';

import TestStudioLayout from '../components/test-studio/TestStudioLayout';
import TestSetDetail from '../components/test-studio/TestSetDetail';
import TestSetDocumentDetail from '../components/test-studio/TestSetDocumentDetail';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';

const TestStudioRoutes = (): React.JSX.Element => {
  return (
    <Routes>
      {/* objectKey may contain slashes (nested input names) — wildcard segment */}
      <Route
        path="sets/:testSetId/doc/*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <TestSetDocumentDetail />
          </div>
        }
      />
      <Route
        path="sets/:testSetId"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <TestSetDetail />
          </div>
        }
      />
      <Route
        path="*"
        element={
          <div>
            <GenAIIDPTopNavigation />
            <TestStudioLayout />
          </div>
        }
      />
    </Routes>
  );
};

export default TestStudioRoutes;
