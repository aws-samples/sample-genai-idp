// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import type { SideNavigationProps } from '@cloudscape-design/components';
import { SideNavigation } from '@cloudscape-design/components';
import useSettingsContext from '../../contexts/settings';
import useUserRole from '../../hooks/use-user-role';

import {
  DOCUMENTS_PATH,
  DOCUMENTS_KB_QUERY_PATH,
  TEST_STUDIO_PATH,
  DEFAULT_PATH,
  UPLOAD_DOCUMENT_PATH,
  CONFIGURATION_PATH,
  PRICING_PATH,
  DISCOVERY_PATH,
  USER_MANAGEMENT_PATH,
  AGENT_CHAT_PATH,
  CAPACITY_PLANNING_PATH,
} from '../../routes/constants';

export const documentsNavHeader = { text: 'Tools', href: `#${DEFAULT_PATH}` };

// Full navigation items for Admin users
export const adminNavItems = [
  { type: 'link', text: 'Document List', href: `#${DOCUMENTS_PATH}` },
  { type: 'link', text: 'Document KB', href: `#${DOCUMENTS_KB_QUERY_PATH}` },
  { type: 'link', text: 'Upload Document(s)', href: `#${UPLOAD_DOCUMENT_PATH}` },
  { type: 'link', text: 'Agent Companion Chat', href: `#${AGENT_CHAT_PATH}` },
  {
    type: 'section',
    text: 'Configuration',
    items: [
      { type: 'link', text: 'Discovery', href: `#${DISCOVERY_PATH}` },
      { type: 'link', text: 'Capacity Planning', href: `#${CAPACITY_PLANNING_PATH}` },
      { type: 'link', text: 'View/Edit Configuration', href: `#${CONFIGURATION_PATH}` },
      { type: 'link', text: 'View/Edit Pricing', href: `#${PRICING_PATH}` },
      { type: 'link', text: 'User Management', href: `#${USER_MANAGEMENT_PATH}` },
    ],
  },
  {
    type: 'section',
    text: 'Test Studio',
    items: [
      { type: 'link', text: 'Test Sets', href: `#${TEST_STUDIO_PATH}?tab=sets` },
      { type: 'link', text: 'Test Executions', href: `#${TEST_STUDIO_PATH}?tab=executions` },
    ],
  },
  {
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
  },
];

// Limited navigation items for Reviewer users
export const reviewerNavItems = [{ type: 'link', text: 'Document List', href: `#${DOCUMENTS_PATH}` }];

// Keep for backward compatibility
export const documentsNavItems = adminNavItems;

const defaultOnFollowHandler = (ev: CustomEvent<SideNavigationProps.FollowDetail>): void => {
  if (ev.detail.href === '#deployment-info') {
    ev.preventDefault();
    return;
  }
  console.log(ev);
};

interface NavigationProps {
  header?: { text: string; href: string };
  items?: SideNavigationProps.Item[];
  onFollowHandler?: (ev: CustomEvent<SideNavigationProps.FollowDetail>) => void;
}

const Navigation = ({
  header = documentsNavHeader,
  items,
  onFollowHandler = defaultOnFollowHandler,
}: NavigationProps): React.JSX.Element => {
  const location = useLocation();
  const path = location.pathname;
  let activeHref = `#${DEFAULT_PATH}`;
  const { settings: rawSettings } = useSettingsContext() || {};
  const settings = rawSettings as Record<string, unknown> | undefined;
  const { isReviewer, isAdmin } = useUserRole();

  // Select navigation items based on user role
  const baseItems = useMemo(() => {
    if (items) return items;
    return isReviewer && !isAdmin ? reviewerNavItems : adminNavItems;
  }, [items, isReviewer, isAdmin]);

  // Filter out Capacity Planning link if pattern is not Pattern-2
  const filteredItems = useMemo(() => {
    const pattern = (settings?.IDPPattern as string | undefined)?.toLowerCase();

    // Check for Pattern-2 in various formats: "Pattern-2", "Pattern 2", "PATTERN_2", "Pattern2"
    const isPattern2 =
      !pattern || // Show if pattern not loaded yet (fail-safe)
      pattern.includes('pattern-2') ||
      pattern.includes('pattern 2') ||
      pattern.includes('pattern_2') ||
      pattern.includes('pattern2') ||
      /pattern[\s\-_]?2/.test(pattern); // Regex: "pattern" followed by optional separator, then "2"

    // Debug logging (remove after testing)
    if (pattern) {
      console.log('[Navigation] IDPPattern detected:', settings.IDPPattern, '| Is Pattern-2:', isPattern2);
    }

    if (isPattern2) {
      // Show Capacity Planning for Pattern-2 or if pattern is unknown
      return baseItems;
    }

    // Filter out Capacity Planning for Pattern 1 and Pattern 3
    return baseItems
      .map((item) => {
        if (item.type === 'section' && item.text === 'Configuration') {
          return {
            ...item,
            items: item.items.filter((subItem) => subItem.text !== 'Capacity Planning'),
          };
        }
        return item;
      })
      .filter((item) => item.text !== 'Capacity Planning'); // Also filter top-level if it exists
  }, [baseItems, settings?.IDPPattern]);

  // Determine active link based on current path
  if (path.includes(PRICING_PATH)) {
    activeHref = `#${PRICING_PATH}`;
  } else if (path.includes(CONFIGURATION_PATH)) {
    activeHref = `#${CONFIGURATION_PATH}`;
  } else if (path.includes(DOCUMENTS_KB_QUERY_PATH)) {
    activeHref = `#${DOCUMENTS_KB_QUERY_PATH}`;
  } else if (path.includes(TEST_STUDIO_PATH)) {
    const urlParams = new URLSearchParams(location.search);
    const tab = urlParams.get('tab');
    activeHref = tab ? `#${TEST_STUDIO_PATH}?tab=${tab}` : `#${TEST_STUDIO_PATH}?tab=sets`;
  } else if (path.includes(UPLOAD_DOCUMENT_PATH)) {
    activeHref = `#${UPLOAD_DOCUMENT_PATH}`;
  } else if (path.includes(DISCOVERY_PATH)) {
    activeHref = `#${DISCOVERY_PATH}`;
  } else if (path.includes(USER_MANAGEMENT_PATH)) {
    activeHref = `#${USER_MANAGEMENT_PATH}`;
  } else if (path.includes(CAPACITY_PLANNING_PATH)) {
    activeHref = `#${CAPACITY_PLANNING_PATH}`;
  } else if (path.includes(DOCUMENTS_PATH)) {
    activeHref = `#${DOCUMENTS_PATH}`;
  } else if (path === AGENT_CHAT_PATH) {
    activeHref = `#${AGENT_CHAT_PATH}`;
  }

  // Create navigation items with deployment info
  const navigationItems: SideNavigationProps.Item[] = [...filteredItems] as SideNavigationProps.Item[];

  if (settings?.Version || settings?.StackName || settings?.BuildDateTime || settings?.IDPPattern) {
    const deploymentInfoItems: SideNavigationProps.Item[] = [];

    if (settings?.StackName) {
      deploymentInfoItems.push({ type: 'link', text: `Stack Name: ${settings.StackName}`, href: '#stackname' });
    }
    if (settings?.Version) {
      deploymentInfoItems.push({ type: 'link', text: `Version: ${settings.Version}`, href: '#version' });
    }
    if (settings?.BuildDateTime) {
      deploymentInfoItems.push({ type: 'link', text: `Build: ${settings.BuildDateTime}`, href: '#builddatetime' });
    }
    if (settings?.IDPPattern) {
      const pattern = (settings.IDPPattern as string).split(' ')[0];
      deploymentInfoItems.push({ type: 'link', text: `Pattern: ${pattern}`, href: '#idppattern' });
    }

    navigationItems.push({
      type: 'section',
      text: 'Deployment Info',
      items: deploymentInfoItems,
    } as SideNavigationProps.Item);
  }

  return (
    <SideNavigation items={navigationItems} header={header || documentsNavHeader} activeHref={activeHref} onFollow={onFollowHandler} />
  );
};

export default Navigation;
