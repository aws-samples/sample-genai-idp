// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import type { LinkProps } from '@cloudscape-design/components';
import { Link } from '@cloudscape-design/components';

interface InfoLinkProps {
  id?: string;
  onFollow?: LinkProps['onFollow'];
}

/* eslint-disable jsx-a11y/anchor-is-valid */
export const InfoLink = ({ id, onFollow }: InfoLinkProps): React.JSX.Element => (
  <Link variant="info" id={id} onFollow={onFollow}>
    Info
  </Link>
);

export default InfoLink;
