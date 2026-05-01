// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Discovery Page — Tabbed container for single-doc and multi-doc discovery.
 */

import React, { useState } from 'react';
import { Tabs } from '@cloudscape-design/components';
import DiscoveryPanel from './DiscoveryPanel';
import MultiDocDiscoveryPanel from './MultiDocDiscoveryPanel';

const DiscoveryPage = () => {
  const [activeTab, setActiveTab] = useState('single-doc');

  return (
    <Tabs
      activeTabId={activeTab}
      onChange={({ detail }) => setActiveTab(detail.activeTabId)}
      tabs={[
        {
          id: 'single-doc',
          label: 'Single Document',
          content: <DiscoveryPanel discoveryType="classes" />,
        },
        {
          id: 'multi-doc',
          label: 'Multiple Documents',
          content: <MultiDocDiscoveryPanel />,
        },
        {
          id: 'rules',
          label: 'Policy Discovery',
          content: <DiscoveryPanel discoveryType="rules" />,
        },
      ]}
    />
  );
};

export default DiscoveryPage;
