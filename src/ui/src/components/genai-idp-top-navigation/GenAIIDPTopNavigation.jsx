// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Box, Button, Modal, SpaceBetween, TopNavigation } from '@awsui/components-react';
import { Auth, Logger } from 'aws-amplify';

import useAppContext from '../../contexts/app';

const logger = new Logger('TopNavigation');

/* eslint-disable react/prop-types */
const SignOutModal = ({ visible, setVisible }) => {
  async function signOut() {
    try {
      await Auth.signOut();
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
            <Button variant="primary" onClick={() => signOut()}>
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

const GenAIIDPTopNavigation = () => {
  const { user, isAdmin, groups } = useAppContext();
  const userId = user?.attributes?.email || 'user';
  const userRole = isAdmin ? 'Admin' : 'User';
  const [isSignOutModalVisible, setIsSignOutModalVisiblesetVisible] = useState(false);

  logger.debug('User role:', userRole);
  logger.debug('User groups:', groups);

  return (
    <>
      <div id="top-navigation" style={{ position: 'sticky', top: 0, zIndex: 1002 }}>
        <TopNavigation
          identity={{ href: '#', title: 'GenAI IDP Console (preview)' }}
          i18nStrings={{ overflowMenuTriggerText: 'More' }}
          utilities={[
            {
              type: 'menu-dropdown',
              text: userId,
              description: `${userId} (${userRole})`,
              iconName: 'user-profile',
              items: [
                {
                  id: 'signout',
                  type: 'button',
                  text: (
                    <Button variant="primary" onClick={() => setIsSignOutModalVisiblesetVisible(true)}>
                      Sign out
                    </Button>
                  ),
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
