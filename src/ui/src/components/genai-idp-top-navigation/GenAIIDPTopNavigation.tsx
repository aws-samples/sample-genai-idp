// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Box, Button, Modal, SpaceBetween, TopNavigation, Badge } from '@cloudscape-design/components';
import { signOut } from 'aws-amplify/auth';
import { ConsoleLogger } from 'aws-amplify/utils';

import useAppContext from '../../contexts/app';
import useUserRole from '../../hooks/use-user-role';

const logger = new ConsoleLogger('TopNavigation');

interface SignOutModalProps {
  visible: boolean;
  setVisible: (visible: boolean) => void;
}

const SignOutModal = ({ visible, setVisible }: SignOutModalProps): React.JSX.Element => {
  async function handleSignOut() {
    try {
      // Set flag to prevent auto-login from immediately signing back in via SSO
      sessionStorage.setItem('idp_signed_out', 'true');

      // Amplify's signOut() handles both federated and non-federated flows:
      // - Clears local tokens from localStorage
      // - When OAuth is configured, redirects through Cognito's /logout endpoint
      //   using the redirectSignOut URL from aws-exports.js
      await signOut();
      logger.debug('signed out');
      window.location.reload();
    } catch (error) {
      logger.error('error signing out: ', error);
    }
  }
  return (
    <Modal
      onDismiss={() => setVisible(false)}
      visible={visible}
      closeAriaLabel="Close modal"
      size="medium"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setVisible(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => handleSignOut()}>
              Sign Out
            </Button>
          </SpaceBetween>
        </Box>
      }
      header="Sign Out"
    >
      Sign out of the application?
    </Modal>
  );
};

const GenAIIDPTopNavigation = (): React.JSX.Element => {
  const { user } = useAppContext();
  const { isAdmin, isAuthor, isReviewer, isViewer, loading: roleLoading } = useUserRole();
  const userId = user?.username || 'user';
  const [isSignOutModalVisible, setIsSignOutModalVisiblesetVisible] = useState(false);

  // Determine role display
  const getRoleDisplay = (): string => {
    if (roleLoading) return '';
    if (isAdmin) return 'Admin';
    if (isAuthor) return 'Author';
    if (isReviewer) return 'Reviewer';
    if (isViewer) return 'Viewer';
    return '';
  };

  const roleDisplay = getRoleDisplay();
  const userDisplayText = roleDisplay ? `${userId} (${roleDisplay})` : userId;

  return (
    <>
      <div id="top-navigation" style={{ position: 'sticky', top: 0, zIndex: 1002 }}>
        <TopNavigation
          identity={{ href: '#', title: 'IDP Accelerator Console' }}
          i18nStrings={{ overflowMenuTriggerText: 'More' }}
          utilities={[
            {
              type: 'menu-dropdown',
              text: userDisplayText,
              ...({
                description: roleDisplay ? (
                  <SpaceBetween direction="horizontal" size="xs">
                    <span>{userId}</span>
                    <Badge color={isAdmin ? 'blue' : isAuthor ? 'green' : 'grey'}>{roleDisplay}</Badge>
                  </SpaceBetween>
                ) : (
                  userId
                ),
              } as Record<string, unknown>),
              iconName: 'user-profile',
              items: [
                {
                  id: 'signout',
                  text: 'Sign out',
                  ...({ type: 'button' } as Record<string, unknown>),
                  ...({
                    text: (
                      <Button variant="primary" onClick={() => setIsSignOutModalVisiblesetVisible(true)}>
                        Sign out
                      </Button>
                    ),
                  } as Record<string, unknown>),
                },
                {
                  id: 'support-group',
                  text: 'Resources',
                  items: [
                    {
                      id: 'documentation',
                      text: 'Blog Post',
                      href: 'https://www.amazon.com/genaiidp',
                      external: true,
                      externalIconAriaLabel: ' (opens in new tab)',
                    },
                    {
                      id: 'source',
                      text: 'Source Code',
                      href: 'https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws',
                      external: true,
                      externalIconAriaLabel: ' (opens in new tab)',
                    },
                  ],
                },
              ],
            },
          ]}
        />
      </div>
      <SignOutModal visible={isSignOutModalVisible} setVisible={setIsSignOutModalVisiblesetVisible} />
    </>
  );
};

export default GenAIIDPTopNavigation;
