/* eslint-disable react/prop-types */
import React, { useState } from 'react';
import { Box, Container, SpaceBetween, Table } from '@awsui/components-react';
import { Logger } from 'aws-amplify';
import useAppContext from '../../contexts/app';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';
import FileViewer from '../document-viewer/JSONViewer';

const logger = new Logger('PagesPanel');

// Cell renderer components
const IdCell = ({ item }) => <span>{item.Id}</span>;
const ClassCell = ({ item }) => <span>{item.Class || '-'}</span>;
const ThumbnailCell = ({ imageUrl }) => (
  <div style={{ width: '100px', height: '100px' }}>
    {imageUrl ? (
      <a href={imageUrl} target="_blank" rel="noopener noreferrer" style={{ cursor: 'pointer' }}>
        <img
          src={imageUrl}
          alt="Page thumbnail"
          style={{
            maxWidth: '100%',
            maxHeight: '100%',
            objectFit: 'contain',
            transition: 'transform 0.2s',
            ':hover': {
              transform: 'scale(1.05)',
            },
          }}
          title="Click to view full size image"
        />
      </a>
    ) : (
      <Box textAlign="center" color="inherit">
        No image
      </Box>
    )}
  </div>
);

const ActionsCell = ({ item }) =>
  item.TextUri ? (
    <FileViewer fileUri={item.TextUri} fileType="json" buttonText="View/Edit Data" />
  ) : (
    <Box color="text-status-inactive">No text available</Box>
  );

// Column definitions
const COLUMN_DEFINITIONS = [
  {
    id: 'id',
    header: 'Page ID',
    cell: (item) => <IdCell item={item} />,
    sortingField: 'Id',
    minWidth: 160,
    width: 160,
    isResizable: true,
  },
  {
    id: 'class',
    header: 'Class/Type',
    cell: (item) => <ClassCell item={item} />,
    sortingField: 'Class',
    minWidth: 200,
    width: 200,
    isResizable: true,
  },
  {
    id: 'thumbnail',
    header: 'Thumbnail',
    cell: (item, { thumbnailUrls }) => <ThumbnailCell imageUrl={thumbnailUrls[item.Id]} />,
    minWidth: 240,
    width: 240,
    isResizable: true,
  },
  {
    id: 'actions',
    header: 'Actions',
    cell: (item) => <ActionsCell item={item} />,
    minWidth: 400,
    width: 400,
    isResizable: true,
  },
];

const PagesPanel = ({ pages }) => {
  const [thumbnailUrls, setThumbnailUrls] = useState({});
  const { currentCredentials } = useAppContext();

  const loadThumbnails = async () => {
    if (!pages) return;

    const urls = {};
    await Promise.all(
      pages.map(async (page) => {
        if (page.ImageUri) {
          try {
            const url = await generateS3PresignedUrl(page.ImageUri, currentCredentials);
            urls[page.Id] = url;
          } catch (err) {
            logger.error('Error generating presigned URL for thumbnail:', err);
            urls[page.Id] = null;
          }
        }
      }),
    );
    setThumbnailUrls(urls);
  };

  React.useEffect(() => {
    loadThumbnails();
  }, [pages]);

  // Create column definitions with necessary context
  const columnDefinitions = COLUMN_DEFINITIONS.map((column) => ({
    ...column,
    cell: (item) =>
      column.cell(item, {
        thumbnailUrls,
      }),
  }));

  return (
    <SpaceBetween size="l">
      <Container header={<h2>Document Pages</h2>}>
        <Table
          columnDefinitions={columnDefinitions}
          items={pages || []}
          sortingDisabled
          variant="embedded"
          resizableColumns
          stickyHeader
          empty={
            <Box textAlign="center" color="inherit">
              <b>No pages</b>
              <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                This document has no pages.
              </Box>
            </Box>
          }
          wrapLines
        />
      </Container>
    </SpaceBetween>
  );
};

export default PagesPanel;
