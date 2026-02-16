// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { BreadcrumbGroup } from '@cloudscape-design/components';
import { DOCUMENTS_PATH, UPLOAD_DOCUMENT_PATH, DEFAULT_PATH } from '../../routes/constants';

export const uploadDocumentBreadcrumbItems = [
  { text: 'Document Processing', href: `#${DEFAULT_PATH}` },
  { text: 'Documents', href: `#${DOCUMENTS_PATH}` },
  { text: 'Upload Documents', href: `#${UPLOAD_DOCUMENT_PATH}` },
];

const Breadcrumbs = (): React.JSX.Element => <BreadcrumbGroup ariaLabel="Breadcrumbs" items={uploadDocumentBreadcrumbItems} />;

export default Breadcrumbs;
