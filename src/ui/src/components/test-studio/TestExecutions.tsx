// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { SpaceBetween } from '@cloudscape-design/components';
import TestRunner from './TestRunner';
import TestResultsList from './TestResultsList';

interface ActiveTestRun {
  testRunId: string;
  testSetName: string;
  startTime: Date;
  filesCount?: number;
  context?: string;
  configVersion?: string;
}

interface TestRunItem {
  testRunId: string;
  testSetName: string;
  status: string;
  isActive?: boolean;
  progress?: number;
  filesCount: number;
  createdAt: string;
  completedAt: string | null;
  context: string;
  configVersion?: string | null;
}

interface TestExecutionsProps {
  timePeriodHours: number;
  setTimePeriodHours: (hours: number) => void;
  selectedItems: TestRunItem[];
  setSelectedItems: (items: TestRunItem[]) => void;
  preSelectedTestRunId?: string | null;
  activeTestRuns: ActiveTestRun[];
  onTestStart: (testRunId: string, testSetName: string, context: string, filesCount: number, configVersion?: string) => void;
  onTestComplete: (testRunId: string) => void;
}

const TestExecutions = ({
  timePeriodHours,
  setTimePeriodHours,
  selectedItems,
  setSelectedItems,
  preSelectedTestRunId,
  activeTestRuns,
  onTestStart,
  onTestComplete,
}: TestExecutionsProps): React.JSX.Element => {
  return (
    <SpaceBetween size="l">
      <TestRunner onTestStart={onTestStart} onTestComplete={onTestComplete} activeTestRuns={activeTestRuns} />
      <TestResultsList
        timePeriodHours={timePeriodHours}
        setTimePeriodHours={setTimePeriodHours}
        selectedItems={selectedItems}
        setSelectedItems={setSelectedItems}
        preSelectedTestRunId={preSelectedTestRunId}
        activeTestRuns={activeTestRuns}
        onTestComplete={onTestComplete}
      />
    </SpaceBetween>
  );
};

export default TestExecutions;
