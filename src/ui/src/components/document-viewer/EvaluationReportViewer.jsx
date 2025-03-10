/* eslint-disable react/prop-types */
import React, { useState, useEffect } from 'react';
import { Box } from '@awsui/components-react';
import { API, Logger } from 'aws-amplify';
import ReactMarkdown from 'react-markdown';
import getFileContents from '../../graphql/queries/getFileContents';

const logger = new Logger('EvaluationReportViewer');

// Define markdown components outside of render
const H1 = ({ children }) => <h1 className="text-2xl font-bold mb-4">{children}</h1>;
const H2 = ({ children }) => <h2 className="text-xl font-bold mb-3">{children}</h2>;
const H3 = ({ children }) => <h3 className="text-lg font-bold mb-2">{children}</h3>;
const Paragraph = ({ children }) => <p className="mb-4">{children}</p>;
const UnorderedList = ({ children }) => <ul className="list-disc ml-4 mb-4">{children}</ul>;
const OrderedList = ({ children }) => <ol className="list-decimal ml-4 mb-4">{children}</ol>;
const CodeBlock = ({ inline, children }) => {
  if (inline) {
    return <code className="bg-gray-100 px-1 rounded">{children}</code>;
  }
  return <code className="block bg-gray-100 p-4 rounded mb-4">{children}</code>;
};

const MarkdownViewer = ({ content }) => (
  <Box className="markdown-viewer p-8 bg-white" style={{ maxHeight: '800px', overflowY: 'auto' }}>
    <ReactMarkdown
      className="prose prose-sm max-w-none"
      components={{
        h1: H1,
        h2: H2,
        h3: H3,
        p: Paragraph,
        ul: UnorderedList,
        ol: OrderedList,
        code: CodeBlock,
      }}
    >
      {content}
    </ReactMarkdown>
  </Box>
);

const EvaluationReportViewer = ({ evaluationReportUri }) => {
  const [reportContent, setReportContent] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchReport = async () => {
      if (!evaluationReportUri) return;

      setIsLoading(true);
      setError(null);
      try {
        logger.info('Fetching evaluation report:', evaluationReportUri);

        const response = await API.graphql({
          query: getFileContents,
          variables: { s3Uri: evaluationReportUri },
        });

        const content = response.data.getFileContents;
        logger.debug('Received report content:', `${content.substring(0, 100)}...`);

        setReportContent(content);
      } catch (err) {
        logger.error('Error fetching evaluation report:', err);
        setError('Failed to load evaluation report. Please try again.');
      } finally {
        setIsLoading(false);
      }
    };

    fetchReport();
  }, [evaluationReportUri]);

  if (!evaluationReportUri) {
    return (
      <Box color="text-status-inactive" padding={{ top: 's' }}>
        Evaluation report not available for this document
      </Box>
    );
  }

  if (error) {
    return (
      <Box color="text-status-error" padding="s">
        {error}
      </Box>
    );
  }

  if (isLoading) {
    return (
      <Box textAlign="center" padding="s">
        Loading evaluation report...
      </Box>
    );
  }

  return reportContent && <MarkdownViewer content={reportContent} />;
};

export default EvaluationReportViewer;
