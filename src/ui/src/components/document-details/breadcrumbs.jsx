// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';

import { BreadcrumbGroup } from '@awsui/components-react';

import { DOCUMENTS_PATH, COMPANY_SELECT_PATH } from '../../routes/constants';

const Breadcrumbs = () => {
  const { objectKey } = useParams();
  const [companyContext, setCompanyContext] = useState(null);

  useEffect(() => {
    // Get active company from localStorage
    try {
      const stored = localStorage.getItem('active_company');
      if (stored) {
        setCompanyContext(JSON.parse(stored));
      }
    } catch (err) {
      console.error('Failed to load company context:', err);
    }
  }, []);

  const decodedDocumentId = decodeURIComponent(objectKey);
  // Always ensure the objectKey in the URL is properly encoded to handle slashes correctly
  const encodedObjectKey = encodeURIComponent(decodedDocumentId);
  
  const items = [
    { text: 'Company Selection', href: `#${COMPANY_SELECT_PATH}` },
  ];

  if (companyContext) {
    items.push({
      text: `${companyContext.company_name} (${companyContext.company_number})`,
      href: `#${DOCUMENTS_PATH}`,
    });
  } else {
    items.push({ text: 'Documents', href: `#${DOCUMENTS_PATH}` });
  }

  items.push({ text: decodedDocumentId, href: `#${DOCUMENTS_PATH}/${encodedObjectKey}` });

  return <BreadcrumbGroup ariaLabel="Breadcrumbs" items={items} />;
};

export default Breadcrumbs;
