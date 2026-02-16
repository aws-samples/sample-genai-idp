// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes } from 'react-router-dom';

import DocumentListSplitPanel from '../document-list/DocumentListSplitPanel';

const CallsSplitPanel = (): React.JSX.Element => {
  return (
    <Routes>
      <Route index element={<DocumentListSplitPanel />} />
    </Routes>
  );
};

export default CallsSplitPanel;
