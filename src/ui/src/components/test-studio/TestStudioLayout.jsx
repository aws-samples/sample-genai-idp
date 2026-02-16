// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { AppLayout, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import { useLocation } from 'react-router-dom';

import Navigation from '../genaiidp-layout/navigation';
import TestSets from './TestSets';
import TestExecutions from './TestExecutions';
import TestResults from './TestResults';
import TestComparison from './TestComparison';
import { appLayoutLabels } from '../common/labels';
import useAppContext from '../../contexts/app';

const TestStudioLayout = () => {
  const { navigationOpen, setNavigationOpen, activeTestRuns, addTestRun, removeTestRun } = useAppContext();
  const location = useLocation();
  const [activeTabId, setActiveTabId] = useState('sets');
  const [timePeriodHours, setTimePeriodHours] = useState(2);
  const [selectedTestItems, setSelectedTestItems] = useState([]);

  // Handle URL tab parameter
  useEffect(() => {
    const urlParams = new URLSearchParams(location.search);
    const tab = urlParams.get('tab');
    if (tab && ['sets', 'executions', 'results', 'comparison'].includes(tab)) {
      setActiveTabId(tab);
    }
  }, [location.search]);

  const handleTestStart = (testRunId, testSetName, context, filesCount, configVersion) => {
    addTestRun(testRunId, testSetName, context, filesCount, configVersion);
  };

  const handleTestComplete = (testRunId) => {
    removeTestRun(testRunId);
  };

  const renderContent = () => {
    switch (activeTabId) {
      case 'sets':
        return <TestSets />;
      case 'executions': {
        const urlParams = new URLSearchParams(location.search);
        const testRunId = urlParams.get('testRunId');
        return (
          <TestExecutions
            timePeriodHours={timePeriodHours}
            setTimePeriodHours={setTimePeriodHours}
            selectedItems={selectedTestItems}
            setSelectedItems={setSelectedTestItems}
            preSelectedTestRunId={testRunId}
            activeTestRuns={activeTestRuns}
            onTestStart={handleTestStart}
            onTestComplete={handleTestComplete}
          />
        );
      }
      case 'results': {
        const urlParams = new URLSearchParams(location.search);
        const testRunId = urlParams.get('testRunId');
        return <TestResults testRunId={testRunId} />;
      }
      case 'comparison': {
        const urlParams = new URLSearchParams(location.search);
        const testIds = urlParams.get('testIds');
        const testRunIds = testIds ? testIds.split(',') : [];
        return <TestComparison preSelectedTestRunIds={testRunIds} />;
      }
      default:
        return <TestSets />;
    }
  };

  return (
    <AppLayout
      ariaLabels={appLayoutLabels}
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="Run tests, view results, and compare test outcomes">
              Test Studio
            </Header>
          }
        >
          <SpaceBetween size="l">{renderContent()}</SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default TestStudioLayout;
