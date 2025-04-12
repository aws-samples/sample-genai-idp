/* eslint-disable react/prop-types */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import { Box } from '@awsui/components-react';

const MARKDOWN_DEFAULT_HEIGHT = '600px';

const MarkdownView = ({ content }) => {
  return (
    <Box
      style={{
        height: MARKDOWN_DEFAULT_HEIGHT,
        position: 'relative',
        overflow: 'auto',
        padding: '16px',
        backgroundColor: '#ffffff',
        border: '2px solid #e9ebed',
        borderRadius: '4px',
        width: '100%',
        minWidth: '600px',
      }}
    >
      {content ? (
        <ReactMarkdown rehypePlugins={[rehypeRaw]}>{content}</ReactMarkdown>
      ) : (
        <Box textAlign="center" padding="l">
          No content to display
        </Box>
      )}
    </Box>
  );
};

export default MarkdownView;
