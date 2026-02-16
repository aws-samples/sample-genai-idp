// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { StatusIndicator } from '@cloudscape-design/components';

interface HitlItem {
  hitlTriggered?: boolean;
  hitlStatus?: string;
  hitlCompleted?: boolean;
}

export const renderHitlStatus = (item: HitlItem): React.JSX.Element => {
  if (!item.hitlTriggered) {
    return <StatusIndicator type="stopped">N/A</StatusIndicator>;
  }

  const status = item.hitlStatus?.toLowerCase().replace(/\s+/g, '') || '';

  // Check for failed status
  if (status === 'failed' || status === 'reviewfailed') {
    return <StatusIndicator type="error">Review Failed</StatusIndicator>;
  }

  // Check for skipped status
  if (status === 'skipped' || status === 'reviewskipped') {
    return <StatusIndicator type="stopped">Review Skipped</StatusIndicator>;
  }

  // Check for completed status
  if (item.hitlCompleted || status === 'completed' || status === 'reviewcompleted') {
    return <StatusIndicator type="success">Review Completed</StatusIndicator>;
  }

  // Check for in-progress status
  if (status === 'inprogress' || status === 'reviewinprogress') {
    return <StatusIndicator type="in-progress">Review In Progress</StatusIndicator>;
  }

  // HITL triggered but not completed - pending review
  return <StatusIndicator type="pending">Review Pending</StatusIndicator>;
};

export default renderHitlStatus;
