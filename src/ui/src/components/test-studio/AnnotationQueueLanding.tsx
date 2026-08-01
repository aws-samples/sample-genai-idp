// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * AnnotationQueueLanding — where an annotator assigned to more than one test set
 * chooses which queue to work. Route: /test-studio/annotate
 *
 * A single-set annotator never sees this: the navigation links them straight into
 * their queue ("one link, one queue"). It also handles the two states that would
 * otherwise dead-end an annotator with no explanation — scope not yet resolved,
 * and no sets assigned at all.
 */

import React from 'react';
import { Alert, AppLayout, Box, Cards, ContentLayout, Header, Link, SpaceBetween, Spinner } from '@cloudscape-design/components';
import useAppContext from '../../contexts/app';
import useUserRole from '../../hooks/use-user-role';
import Navigation from '../genaiidp-layout/navigation';
import { appLayoutLabels } from '../common/labels';
import { testSetAnnotateHref } from '../../routes/constants';

const AnnotationQueueLanding = (): React.JSX.Element => {
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const { allowedTestSets, canAnnotate, loading } = useUserRole();

  const sets = allowedTestSets ?? [];

  return (
    <AppLayout
      headerSelector="#top-navigation"
      ariaLabels={appLayoutLabels}
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      toolsHide
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="The test sets you have been assigned to annotate">
              My annotation queues
            </Header>
          }
        >
          <SpaceBetween size="l">
            {loading && (
              <Box textAlign="center" padding="xl">
                <Spinner /> Loading your assignments…
              </Box>
            )}

            {!loading && !canAnnotate && (
              <Alert type="error" header="Not available for your account">
                Ground-truth annotation requires an Annotator, Author or Admin role.
              </Alert>
            )}

            {/* An annotator with no assigned set is denied every set server-side,
                so say who can fix it rather than showing an empty list. */}
            {!loading && canAnnotate && sets.length === 0 && (
              <Alert type="info" header="No test sets assigned yet">
                Your account has no test sets assigned, so there is nothing to annotate. Ask an administrator to assign you a test set —
                they can do this from User Management.
              </Alert>
            )}

            {!loading && sets.length > 0 && (
              <Cards
                items={sets.map((id) => ({ id }))}
                trackBy="id"
                cardDefinition={{
                  header: (item) => <Link href={testSetAnnotateHref(item.id)}>{item.id}</Link>,
                  sections: [
                    {
                      id: 'action',
                      content: (item) => <Link href={testSetAnnotateHref(item.id)}>Open queue — review lowest-confidence first</Link>,
                    },
                  ],
                }}
                cardsPerRow={[{ cards: 1 }, { minWidth: 600, cards: 2 }]}
              />
            )}
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
};

export default AnnotationQueueLanding;
