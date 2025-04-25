/* eslint-disable react/prop-types */
import React, { useState, useEffect } from 'react';
import { SpaceBetween, Box, Button, StatusIndicator } from '@awsui/components-react';
import { API, graphqlOperation, Logger } from 'aws-amplify';
import copyToBaselineMutation from '../../graphql/queries/copyToBaseline';
import FileViewer from '../document-viewer/FileViewer';
import { MarkdownReport } from '../document-viewer/MarkdownViewer';

const logger = new Logger('DocumentViewers');

const ViewerControls = ({
  onViewSource,
  onViewReport,
  onViewSummary,
  onSetAsBaseline,
  isSourceVisible,
  isReportVisible,
  isSummaryVisible,
  evaluationReportUri,
  summaryReportUri,
  copyStatus,
  evaluationStatus,
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
    {summaryReportUri && (
      <Button onClick={onViewSummary} variant={isSummaryVisible ? 'primary' : 'normal'}>
        {isSummaryVisible ? 'Close Document Summary' : 'View Document Summary'}
      </Button>
    )}
    <Button
      onClick={onSetAsBaseline}
      disabled={copyStatus === 'in-progress' || evaluationStatus === 'BASELINE_COPYING'}
    >
      Use as Evaluation Baseline
    </Button>
    {copyStatus === 'show-message' && (
      <StatusIndicator type="info">Copy started - see Evaluation status above</StatusIndicator>
    )}
    {evaluationStatus === 'BASELINE_COPYING' && (
      <StatusIndicator type="in-progress">Baseline copying in progress</StatusIndicator>
    )}
    {evaluationStatus === 'BASELINE_AVAILABLE' && !copyStatus && (
      <StatusIndicator type="success">Baseline available</StatusIndicator>
    )}
    {evaluationStatus === 'BASELINE_ERROR' && <StatusIndicator type="error">Baseline copy failed</StatusIndicator>}
  </SpaceBetween>
);

const ViewerContent = ({
  isSourceVisible,
  isReportVisible,
  isSummaryVisible,
  objectKey,
  evaluationReportUri,
  summaryReportUri,
}) => {
  if (!isSourceVisible && !isReportVisible && !isSummaryVisible) {
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
          <MarkdownReport
            reportUri={evaluationReportUri}
            documentId={objectKey}
            title="Evaluation Report"
            emptyMessage="Evaluation report not available for this document"
          />
        </div>
      )}
      {isSummaryVisible && (
        <div className="flex-1 min-w-0">
          <MarkdownReport
            reportUri={summaryReportUri}
            documentId={objectKey}
            title="Document Summary"
            emptyMessage="Summary report not available for this document"
          />
        </div>
      )}
    </div>
  );
};

const DocumentViewers = ({ objectKey, evaluationReportUri, summaryReportUri, evaluationStatus }) => {
  const [isSourceVisible, setIsSourceVisible] = useState(false);
  const [isReportVisible, setIsReportVisible] = useState(false);
  const [isSummaryVisible, setIsSummaryVisible] = useState(false);
  const [copyStatus, setCopyStatus] = useState(null);

  // Show temporary message when copy is initiated, then clear it
  useEffect(() => {
    let messageTimer;

    if (copyStatus === 'show-message') {
      // Clear the message after 5 seconds
      messageTimer = setTimeout(() => {
        setCopyStatus(null);
      }, 5000);
    }

    // Cleanup timer
    return () => {
      if (messageTimer) {
        clearTimeout(messageTimer);
      }
    };
  }, [copyStatus]);

  const handleViewSource = () => {
    setIsSourceVisible(!isSourceVisible);
  };

  const handleViewReport = () => {
    setIsReportVisible(!isReportVisible);
  };

  const handleViewSummary = () => {
    setIsSummaryVisible(!isSummaryVisible);
  };

  const handleSetAsBaseline = async () => {
    // Set in-progress status to disable button
    setCopyStatus('in-progress');

    try {
      const result = await API.graphql(
        graphqlOperation(copyToBaselineMutation, {
          objectKey,
        }),
      );

      // The Lambda returns immediately, so check the result
      if (result.data.copyToBaseline.success) {
        // Operation started successfully, show temporary message
        setCopyStatus('show-message');
        logger.info('Copy operation started:', result.data.copyToBaseline.message);
      } else {
        // Immediate failure (e.g., file not found)
        setCopyStatus('error');
        logger.error('Failed to start copy operation:', result.data.copyToBaseline.message);

        // Clear error status after 5 seconds
        setTimeout(() => setCopyStatus(null), 5000);
      }
    } catch (error) {
      setCopyStatus('error');
      logger.error('Error initiating copy to evaluation baseline:', error);

      // Clear error status after 5 seconds
      setTimeout(() => setCopyStatus(null), 5000);
    }
  };

  return (
    <Box>
      <SpaceBetween size="s">
        <ViewerControls
          onViewSource={handleViewSource}
          onViewReport={handleViewReport}
          onViewSummary={handleViewSummary}
          onSetAsBaseline={handleSetAsBaseline}
          isSourceVisible={isSourceVisible}
          isReportVisible={isReportVisible}
          isSummaryVisible={isSummaryVisible}
          evaluationReportUri={evaluationReportUri}
          summaryReportUri={summaryReportUri}
          copyStatus={copyStatus}
          evaluationStatus={evaluationStatus}
        />
        <ViewerContent
          isSourceVisible={isSourceVisible}
          isReportVisible={isReportVisible}
          isSummaryVisible={isSummaryVisible}
          objectKey={objectKey}
          evaluationReportUri={evaluationReportUri}
          summaryReportUri={summaryReportUri}
        />
      </SpaceBetween>
    </Box>
  );
};

export default DocumentViewers;
