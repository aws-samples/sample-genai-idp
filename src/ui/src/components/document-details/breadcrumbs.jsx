// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { useParams } from 'react-router-dom';

import { BreadcrumbGroup } from '@awsui/components-react';

import { DOCUMENTS_PATH } from '../../routes/constants';
import { documentListBreadcrumbItems } from '../document-list/breadcrumbs';

const Breadcrumbs = () => {
  const { objectKey } = useParams();
  const decodedDocumentId = decodeURIComponent(objectKey);
  // Always ensure the objectKey in the URL is properly encoded to handle slashes correctly
  const encodedObjectKey = encodeURIComponent(decodedDocumentId);
  const documentDetailsBreadcrumbItems = [
    ...documentListBreadcrumbItems,
    { text: decodedDocumentId, href: `#${DOCUMENTS_PATH}/${encodedObjectKey}` },
  ];

  return <BreadcrumbGroup ariaLabel="Breadcrumbs" items={documentDetailsBreadcrumbItems} />;
};

export default Breadcrumbs;
