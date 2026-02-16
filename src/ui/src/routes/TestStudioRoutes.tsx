// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Routes, Route } from 'react-router-dom';

import TestStudioLayout from '../components/test-studio/TestStudioLayout';

const TestStudioRoutes = (): React.JSX.Element => {
  return (
    <Routes>
      <Route path="*" element={<TestStudioLayout />} />
    </Routes>
  );
};

export default TestStudioRoutes;
