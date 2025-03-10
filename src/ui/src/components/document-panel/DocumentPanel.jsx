/* eslint-disable react/prop-types */
import React from 'react';
import { Box, ColumnLayout, Container, SpaceBetween, Button, Header } from '@awsui/components-react';
import { Logger } from 'aws-amplify';
import './DocumentPanel.css';
import DocumentViewers from '../document-viewers/DocumentViewers';
import SectionsPanel from '../sections-panel';
import PagesPanel from '../pages-panel';

const logger = new Logger('DocumentPanel');

const DocumentAttributes = ({ item }) => {
  return (
    <Container>
      <ColumnLayout columns={6} variant="text-grid">
        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Document ID</strong>
            </Box>
            <div>{item.objectKey}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Status</strong>
            </Box>
            <div>{item.objectStatus}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Submitted</strong>
            </Box>
            <div>{item.initialEventTime}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Completed</strong>
            </Box>
            <div>{item.completionTime}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Duration</strong>
            </Box>
            <div>{item.duration}</div>
          </div>
        </SpaceBetween>
      </ColumnLayout>
    </Container>
  );
};

export const DocumentPanel = ({ item, setToolsOpen, getDocumentDetailsFromIds, onDelete }) => {
  logger.debug('DocumentPanel item', item);
  return (
    <SpaceBetween size="s">
      <Container
        header={
          <Header
            variant="h2"
            actions={
              onDelete && (
                <Button iconName="remove" variant="normal" onClick={onDelete}>
                  Delete
                </Button>
              )
            }
          >
            Document Details
          </Header>
        }
      >
        <DocumentAttributes
          item={item}
          setToolsOpen={setToolsOpen}
          getDocumentDetailsFromIds={getDocumentDetailsFromIds}
        />
      </Container>
      <DocumentViewers objectKey={item.objectKey} evaluationReportUri={item.evaluationReportUri} />
      <SectionsPanel sections={item.sections} />
      <PagesPanel pages={item.pages} />
    </SpaceBetween>
  );
};

export default DocumentPanel;
