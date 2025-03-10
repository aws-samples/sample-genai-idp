// src/components/configuration-layout/breadcrumbs.jsx
import React from 'react';
import { BreadcrumbGroup } from '@awsui/components-react';
import { DOCUMENTS_PATH, CONFIGURATION_PATH, DEFAULT_PATH } from '../../routes/constants';

export const configurationBreadcrumbItems = [
  { text: 'Document Processing', href: `#${DEFAULT_PATH}` },
  { text: 'Documents', href: `#${DOCUMENTS_PATH}` },
  { text: 'Configuration', href: `#${CONFIGURATION_PATH}` },
];

const Breadcrumbs = () => <BreadcrumbGroup ariaLabel="Breadcrumbs" items={configurationBreadcrumbItems} />;

export default Breadcrumbs;
