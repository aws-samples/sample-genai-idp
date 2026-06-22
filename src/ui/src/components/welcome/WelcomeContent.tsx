// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Container, Header, SpaceBetween, Link } from '@cloudscape-design/components';
import { DOCUMENTS_PATH, CONFIGURATION_PATH, UPLOAD_DOCUMENT_PATH, WELCOME_DISMISSED_KEY } from '../../routes/constants';

interface WelcomeContentProps {
  // When true, shows the "Don't show this again" dismissal (landing-page variant).
  showDismiss?: boolean;
  onDismiss?: () => void;
}

const WelcomeContent = ({ showDismiss = false, onDismiss }: WelcomeContentProps): React.JSX.Element => {
  const navigate = useNavigate();

  const openQuickStart = useCallback(() => {
    navigate(DOCUMENTS_PATH);
    window.dispatchEvent(new CustomEvent('openQuickStart'));
  }, [navigate]);

  const startTour = useCallback(() => {
    window.dispatchEvent(new CustomEvent('startTutorial'));
  }, []);

  const enterConsole = useCallback(() => {
    navigate(DOCUMENTS_PATH);
  }, [navigate]);

  return (
    <Container
      header={
        <Header variant="h1" description="Get a working configuration and test set in minutes — or jump straight into the console.">
          Welcome to GenAI IDP
        </Header>
      }
    >
      <SpaceBetween size="l">
        <SpaceBetween direction="horizontal" size="s">
          <Button variant="primary" iconName="gen-ai" onClick={openQuickStart}>
            Quick Start
          </Button>
          <Button iconName="status-info" onClick={startTour}>
            Take the tour
          </Button>
          <Button onClick={enterConsole}>Enter IDP Console</Button>
        </SpaceBetween>

        <Box>
          <Box variant="h3">Not sure where to begin?</Box>
          <SpaceBetween size="xs">
            <Box variant="p">
              <b>No configuration yet?</b> Use <Link onFollow={openQuickStart}>Quick Start</Link> to describe your document type (or upload
              an example) and we&apos;ll build a config and synthetic test set for you.
            </Box>
            <Box variant="p">
              <b>Already have a config?</b> Go to{' '}
              <Link onFollow={() => navigate(CONFIGURATION_PATH)}>Configuration &gt; View/Edit Configuration</Link> to review or update it.
            </Box>
            <Box variant="p">
              <b>Want to test a document?</b> Head to <Link onFollow={() => navigate(UPLOAD_DOCUMENT_PATH)}>Upload Document</Link> to run
              one through your active configuration.
            </Box>
          </SpaceBetween>
        </Box>

        {showDismiss && (
          <Box>
            <Link
              onFollow={() => {
                try {
                  localStorage.setItem(WELCOME_DISMISSED_KEY, 'true');
                } catch {
                  /* ignore */
                }
                onDismiss?.();
                navigate(DOCUMENTS_PATH);
              }}
            >
              Don&apos;t show this again
            </Link>
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default WelcomeContent;
