/* eslint-disable react/prop-types */
import React, { useState } from 'react';
import { SpaceBetween, Box, Button, StatusIndicator } from '@awsui/components-react';
import { API, graphqlOperation, Logger } from 'aws-amplify';
import copyToBaselineMutation from '../../graphql/queries/copyToBaseline';
import FileViewer from '../document-viewer/FileViewer';
import EvaluationReportViewer from '../document-viewer/EvaluationReportViewer';

const logger = new Logger('DocumentViewers');

const ViewerControls = ({
  onViewSource,
  onViewReport,
  onSetAsBaseline,
  isSourceVisible,
  isReportVisible,
  evaluationReportUri,
  copyStatus,
}) => (
  <SpaceBetween direction="horizontal" size="xs">
    <Button onClick={onViewSource} variant={isSourceVisible ? 'primary' : 'normal'}>
      {isSourceVisible ? 'Close Source Document' : 'View Source Document'}
    </Button>
    {evaluationReportUri && (
      <Button onClick={onViewReport} variant={isReportVisible ? 'primary' : 'normal'}>
        {isReportVisible ? 'Close Evaluation Report' : 'View Evaluation Report'}
      </Button>
    )}
    <Button onClick={onSetAsBaseline} disabled={copyStatus === 'in-progress'}>
      Use as Evaluation Baseline
    </Button>
    {copyStatus === 'in-progress' && <StatusIndicator type="in-progress">Copying...</StatusIndicator>}
    {copyStatus === 'success' && <StatusIndicator type="success">Copy successful</StatusIndicator>}
    {copyStatus === 'error' && <StatusIndicator type="error">Copy failed</StatusIndicator>}
  </SpaceBetween>
);

const ViewerContent = ({ isSourceVisible, isReportVisible, objectKey, evaluationReportUri }) => {
  if (!isSourceVisible && !isReportVisible) {
    return null;
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 mt-4">
      {isSourceVisible && (
        <div className="flex-1 min-w-0">
          <FileViewer objectKey={objectKey} showControls={false} />
        </div>
      )}
      {isReportVisible && (
        <div className="flex-1 min-w-0">
          <EvaluationReportViewer
            objectKey={objectKey}
            evaluationReportUri={evaluationReportUri}
            showControls={false}
          />
        </div>
      )}
    </div>
  );
};

const DocumentViewers = ({ objectKey, evaluationReportUri }) => {
  const [isSourceVisible, setIsSourceVisible] = useState(false);
  const [isReportVisible, setIsReportVisible] = useState(false);
  const [copyStatus, setCopyStatus] = useState(null);

  const handleViewSource = () => {
    setIsSourceVisible(!isSourceVisible);
  };

  const handleViewReport = () => {
    setIsReportVisible(!isReportVisible);
  };

  const handleSetAsBaseline = async () => {
    setCopyStatus('in-progress');
    try {
      const result = await API.graphql(
        graphqlOperation(copyToBaselineMutation, {
          objectKey,
        }),
      );

      if (result.data.copyToBaseline.success) {
        setCopyStatus('success');
        setTimeout(() => setCopyStatus(null), 3000);
      } else {
        setCopyStatus('error');
        logger.error('Failed to copy:', result.data.copyToBaseline.message);
      }
    } catch (error) {
      setCopyStatus('error');
      logger.error('Error copying to evaluation baseline:', error);
    }
  };

  return (
    <Box>
      <SpaceBetween size="s">
        <ViewerControls
          onViewSource={handleViewSource}
          onViewReport={handleViewReport}
          onSetAsBaseline={handleSetAsBaseline}
          isSourceVisible={isSourceVisible}
          isReportVisible={isReportVisible}
          evaluationReportUri={evaluationReportUri}
          copyStatus={copyStatus}
        />
        <ViewerContent
          isSourceVisible={isSourceVisible}
          isReportVisible={isReportVisible}
          objectKey={objectKey}
          evaluationReportUri={evaluationReportUri}
        />
      </SpaceBetween>
    </Box>
  );
};

export default DocumentViewers;
