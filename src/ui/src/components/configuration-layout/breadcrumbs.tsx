// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// src/components/configuration-layout/breadcrumbs.jsx
import React from 'react';
import { BreadcrumbGroup } from '@cloudscape-design/components';
import { DOCUMENTS_PATH, CONFIGURATION_PATH, DEFAULT_PATH } from '../../routes/constants';

export const configurationBreadcrumbItems = [
  { text: 'Document Processing', href: `#${DEFAULT_PATH}` },
  { text: 'Documents', href: `#${DOCUMENTS_PATH}` },
  { text: 'Configuration', href: `#${CONFIGURATION_PATH}` },
];

const Breadcrumbs = (): React.JSX.Element => <BreadcrumbGroup ariaLabel="Breadcrumbs" items={configurationBreadcrumbItems} />;

export default Breadcrumbs;
