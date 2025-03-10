// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';

import { BreadcrumbGroup } from '@awsui/components-react';

import { DOCUMENTS_PATH, DEFAULT_PATH } from '../../routes/constants';

export const documentListBreadcrumbItems = [
  { text: 'Document Processing', href: `#${DEFAULT_PATH}` },
  { text: 'Documents', href: `#${DOCUMENTS_PATH}` },
];

const Breadcrumbs = () => <BreadcrumbGroup ariaLabel="Breadcrumbs" items={documentListBreadcrumbItems} />;

export default Breadcrumbs;
