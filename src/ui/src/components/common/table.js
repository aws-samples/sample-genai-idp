// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Box, Button, Header, SpaceBetween } from '@awsui/components-react';

import { InfoLink } from './info-link';

export const getFilterCounterText = (count) => `${count} ${count === 1 ? 'match' : 'matches'}`;
/* prettier-ignore */
const getHeaderCounterText = (items = [], selectedItems = []) => (
  selectedItems && selectedItems.length > 0
    ? `(${selectedItems.length}/${items.length})`
    : `(${items.length})`
);
const getCounter = (props) => {
  if (props.counter) {
    return props.counter;
  }
  if (!props.totalItems) {
    return null;
  }
  return getHeaderCounterText(props.totalItems, props.selectedItems);
};

/* eslint-disable react/prop-types, react/destructuring-assignment */
export const TableHeader = (props) => (
  <Header
    counter={getCounter(props)}
    info={props.updateTools && <InfoLink onFollow={props.updateTools} />}
    description={props.description}
    actions={props.actionButtons}
  >
    {props.title}
  </Header>
);

export const TableEmptyState = ({ resourceName }) => (
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

export const TableNoMatchState = (props) => (
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
