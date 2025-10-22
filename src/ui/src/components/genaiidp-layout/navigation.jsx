// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { React } from 'react';
import { Route, Switch, useLocation } from 'react-router-dom';
import { SideNavigation } from '@awsui/components-react';
import useSettingsContext from '../../contexts/settings';
import useAppContext from '../../contexts/app';

import {
  DOCUMENTS_PATH,
  DOCUMENTS_KB_QUERY_PATH,
  DOCUMENTS_ANALYTICS_PATH,
  DEFAULT_PATH,
  UPLOAD_DOCUMENT_PATH,
  CONFIGURATION_PATH,
  DISCOVERY_PATH,
} from '../../routes/constants';

export const documentsNavHeader = { text: 'Tools', href: `#${DEFAULT_PATH}` };

// Function to generate navigation items based on user role
export const getDocumentsNavItems = (isAdmin = false) => {
  const baseItems = [
    { type: 'link', text: 'Document List', href: `#${DOCUMENTS_PATH}` },
    { type: 'link', text: 'Upload Document(s)', href: `#${UPLOAD_DOCUMENT_PATH}` },
  ];

  // Items available to all users (including regular users)
  const sharedItems = [
    { type: 'link', text: 'Document KB', href: `#${DOCUMENTS_KB_QUERY_PATH}` },
    { type: 'link', text: 'Agent Analysis', href: `#${DOCUMENTS_ANALYTICS_PATH}` },
  ];

  // Admin-only items
  const adminItems = [
    { type: 'link', text: 'Discovery', href: `#${DISCOVERY_PATH}` },
    { type: 'link', text: 'View/Edit Configuration', href: `#${CONFIGURATION_PATH}` },
  ];

  // Combine items based on role
  const items = [...baseItems, ...sharedItems];
  if (isAdmin) {
    items.push(...adminItems);
  }

  // Add resources section (available to all)
  items.push({
    type: 'section',
    text: 'Resources',
    items: [
      {
        type: 'link',
        text: 'README',
        href: 'https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/blob/main/README.md',
        external: true,
      },
      {
        type: 'link',
        text: 'Source Code',
        href: 'https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws',
        external: true,
      },
    ],
  });

  return items;
};

// Default items (for backwards compatibility)
export const documentsNavItems = getDocumentsNavItems(true);

const defaultOnFollowHandler = (ev) => {
  // Prevent navigation for deployment info items (make them non-clickable)
  if (ev.detail.href === '#deployment-info') {
    ev.preventDefault();
    return;
  }
  // XXX keep the locked href for our demo pages
  // ev.preventDefault();
  console.log(ev);
};

/* eslint-disable react/prop-types */
const Navigation = ({ header = documentsNavHeader, items = null, onFollowHandler = defaultOnFollowHandler }) => {
  const location = useLocation();
  const path = location.pathname;
  const { isAdmin } = useAppContext();
  const { settings } = useSettingsContext() || {};

  let activeHref = `#${DEFAULT_PATH}`;

  // Determine active link based on current path, most specific routes first
  if (path.includes(CONFIGURATION_PATH)) {
    activeHref = `#${CONFIGURATION_PATH}`;
  } else if (path.includes(DOCUMENTS_KB_QUERY_PATH)) {
    activeHref = `#${DOCUMENTS_KB_QUERY_PATH}`;
  } else if (path.includes(DOCUMENTS_ANALYTICS_PATH)) {
    activeHref = `#${DOCUMENTS_ANALYTICS_PATH}`;
  } else if (path.includes(UPLOAD_DOCUMENT_PATH)) {
    activeHref = `#${UPLOAD_DOCUMENT_PATH}`;
  } else if (path.includes(DISCOVERY_PATH)) {
    activeHref = `#${DISCOVERY_PATH}`;
  } else if (path.includes(DOCUMENTS_PATH)) {
    activeHref = `#${DOCUMENTS_PATH}`;
  }

  // Get navigation items based on role (or use provided items)
  const navigationItems = [...(items || getDocumentsNavItems(isAdmin))];

  // Add deployment info section if version, stack name, or build datetime is available
  if (settings?.Version || settings?.StackName || settings?.BuildDateTime || settings?.IDPPattern) {
    const deploymentInfoItems = [];

    if (settings?.StackName) {
      deploymentInfoItems.push({
        type: 'link',
        text: `Stack Name: ${settings.StackName}`,
        href: '#stackname',
      });
    }

    if (settings?.Version) {
      deploymentInfoItems.push({
        type: 'link',
        text: `Version: ${settings.Version}`,
        href: '#version',
      });
    }

    if (settings?.BuildDateTime) {
      deploymentInfoItems.push({
        type: 'link',
        text: `Build: ${settings.BuildDateTime}`,
        href: '#builddatetime',
      });
    }

    if (settings?.IDPPattern) {
      const pattern = settings.IDPPattern.split(' ')[0];
      deploymentInfoItems.push({
        type: 'link',
        text: `Pattern: ${pattern}`,
        href: '#idppattern',
      });
    }

    navigationItems.push({
      type: 'section',
      text: 'Deployment Info',
      items: deploymentInfoItems,
    });
  }

  return (
    <Switch>
      <Route path={DOCUMENTS_PATH}>
        <SideNavigation
          items={navigationItems}
          header={header || documentsNavHeader}
          activeHref={activeHref}
          onFollow={onFollowHandler}
        />
      </Route>
    </Switch>
  );
};

export default Navigation;
