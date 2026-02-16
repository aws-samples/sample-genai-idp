// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import type { LinkProps } from '@cloudscape-design/components';
import { Box, Button, Header, SpaceBetween } from '@cloudscape-design/components';

import { InfoLink } from './info-link';

export const getFilterCounterText = (count: number): string => `${count} ${count === 1 ? 'match' : 'matches'}`;
/* prettier-ignore */
const getHeaderCounterText = (items: unknown[] = [], selectedItems: unknown[] = []): string => (
  selectedItems && selectedItems.length > 0
    ? `(${selectedItems.length}/${items.length})`
    : `(${items.length})`
);

interface TableHeaderProps {
  counter?: string;
  totalItems?: unknown[];
  selectedItems?: unknown[];
  updateTools?: LinkProps['onFollow'];
  description?: string;
  actionButtons?: React.ReactNode;
  title?: React.ReactNode;
}

const getCounter = (props: TableHeaderProps): string | null => {
  if (props.counter) {
    return props.counter;
  }
  if (!props.totalItems) {
    return null;
  }
  return getHeaderCounterText(props.totalItems, props.selectedItems);
};

export const TableHeader = (props: TableHeaderProps): React.JSX.Element => (
  <Header
    counter={getCounter(props)}
    info={props.updateTools && <InfoLink onFollow={props.updateTools} />}
    description={props.description}
    actions={props.actionButtons}
  >
    {props.title}
  </Header>
);

interface TableEmptyStateProps {
  resourceName: string;
}

export const TableEmptyState = ({ resourceName }: TableEmptyStateProps): React.JSX.Element => (
  <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
    <SpaceBetween size="xxs">
      <div>
        <b>{` No ${resourceName.toLowerCase()}s`}</b>
        <Box variant="p" color="inherit">
          {`No ${resourceName.toLowerCase()}s found.`}
        </Box>
      </div>
    </SpaceBetween>
  </Box>
);

interface TableNoMatchStateProps {
  onClearFilter?: () => void;
}

export const TableNoMatchState = (props: TableNoMatchStateProps): React.JSX.Element => (
  <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
    <SpaceBetween size="xxs">
      <div>
        <b>No matches</b>
        <Box variant="p" color="inherit">
          We can&apos;t find a match.
        </Box>
      </div>
      <Button onClick={props.onClearFilter}>Clear filter</Button>
    </SpaceBetween>
  </Box>
);
