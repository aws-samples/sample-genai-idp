// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Routes, Route } from 'react-router-dom';

import TestStudioLayout from '../components/test-studio/TestStudioLayout';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';

const TestStudioRoutes = (): React.JSX.Element => {
  return (
    <Routes>
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
