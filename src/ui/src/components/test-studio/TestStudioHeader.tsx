// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Header, SpaceBetween, Button } from '@cloudscape-design/components';
import type { IconProps } from '@cloudscape-design/components';
import handlePrint from './PrintUtils';

interface TestStudioHeaderProps {
  title: string;
  description?: React.ReactNode;
  showBackButton?: boolean;
  showPrintButton?: boolean;
  additionalActions?: React.ReactNode[];
  onBackClick?: () => void;
  preferences?: React.ReactNode;
}

const TestStudioHeader = ({
  title,
  description,
  showBackButton = true,
  showPrintButton = false,
  additionalActions = [],
  onBackClick,
  preferences: _preferences,
}: TestStudioHeaderProps): React.JSX.Element => {
  const actions = [];

  if (showBackButton) {
    const handleBackClick = onBackClick || (() => window.location.replace('#/test-studio?tab=executions'));

    actions.push(
      <Button key="back" onClick={handleBackClick} iconName="arrow-left">
        Back to Test Results
      </Button>,
    );
  }

  actions.push(...additionalActions);

  if (showPrintButton) {
    actions.push(
      <Button key="print" onClick={handlePrint} iconName={'print' as unknown as IconProps.Name}>
        Print
      </Button>,
    );
  }

  return (
    <Header
      variant="h2"
      actions={
        actions.length > 0 ? (
          <SpaceBetween direction="horizontal" size="xs">
            {actions}
          </SpaceBetween>
        ) : undefined
      }
    >
      {title}
      {description}
    </Header>
  );
};

export default TestStudioHeader;
