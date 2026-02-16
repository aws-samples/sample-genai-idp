// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Box, Container, Header, SpaceBetween, Alert } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';

import PlotDisplay from './PlotDisplay';
import TableDisplay from './TableDisplay';
import TextDisplay from './TextDisplay';

const logger = new ConsoleLogger('AgentResultDisplay');

interface AgentResultDisplayProps {
  result?: string | Record<string, unknown> | null;
  query?: string;
}

const AgentResultDisplay = ({ result = null, query = '' }: AgentResultDisplayProps): React.JSX.Element | null => {
  if (!result) {
    return null;
  }

  logger.debug('Raw result received:', result);
  logger.debug('Result type:', typeof result);

  // Helper function to safely parse JSON strings with multiple levels
  const safeJsonParse = (data: unknown, fallback: unknown = null): unknown => {
    if (data === null || data === undefined) {
      return fallback;
    }

    // If it's already an object, return as is
    if (typeof data === 'object') {
      return data;
    }

    // If it's a string, try to parse it
    if (typeof data === 'string') {
      try {
        const parsed = JSON.parse(data);
        // If the parsed result is still a string, try parsing again (double-encoded JSON)
        if (typeof parsed === 'string') {
          try {
            return JSON.parse(parsed);
          } catch (innerError) {
            logger.debug('Inner JSON parse failed, returning first parse result:', innerError);
            return parsed;
          }
        }
        return parsed;
      } catch (error) {
        logger.warn('Failed to parse JSON string:', error);
        logger.debug('Failed string was:', data);
        return fallback;
      }
    }

    return data;
  };

  // Parse the result with enhanced logic
  let parsedResult = safeJsonParse(result, result) as Record<string, unknown>;

  logger.debug('Parsed result:', parsedResult);

  // Handle case where result might be wrapped in a "result" property (from DynamoDB)
  if (parsedResult && typeof parsedResult === 'object' && parsedResult.result) {
    logger.debug('Found nested result property, extracting...');
    parsedResult = safeJsonParse(parsedResult.result, parsedResult.result) as Record<string, unknown>;
    logger.debug('Extracted nested result:', parsedResult);
  }

  logger.debug('Parsed result:', parsedResult);

  const renderResultContent = (): React.JSX.Element => {
    const { responseType } = parsedResult;

    logger.debug('Rendering result with responseType:', responseType);

    switch (responseType) {
      case 'plotData': {
        logger.debug('Rendering plot data:', parsedResult);
        // Extract the first plot data item from the array
        const plotDataArray = parsedResult.plotData as Array<Record<string, unknown>> | undefined;
        const plotData = plotDataArray && plotDataArray.length > 0 ? plotDataArray[0] : null;
        return plotData ? <PlotDisplay plotData={plotData} /> : <div>No plot data available</div>;
      }

      case 'table': {
        logger.debug('Rendering table data:', parsedResult);
        // Extract the nested tableData
        const tableData = (parsedResult.tableData || parsedResult) as Record<string, unknown>;
        return tableData ? <TableDisplay tableData={tableData} /> : <div>No table data available</div>;
      }

      case 'text': {
        logger.debug('Rendering text data:', parsedResult);
        // Extract the nested textData or use the whole object if it has content
        const textData = (parsedResult.textData || parsedResult) as Record<string, unknown>;
        return textData ? <TextDisplay textData={textData} /> : <div>No text data available</div>;
      }

      default:
        // Fallback for legacy format or unknown response types
        logger.warn('Unknown or missing responseType:', responseType);
        logger.debug('Full parsed result for fallback:', parsedResult);
        return (
          <Box padding="m">
            <Header variant="h3">Raw Response</Header>
            <Alert type="warning">Unknown response type: {(responseType as string) || 'undefined'}</Alert>
            <Box padding="s">
              <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Debug Information:</Header>
              <pre style={{ fontSize: '12px', maxHeight: '300px', overflow: 'auto' }}>{JSON.stringify(parsedResult, null, 2)}</pre>
            </Box>
          </Box>
        );
    }
  };

  return (
    <Container
      header={
        <Header variant="h2">
          Results for: <i>{query}</i>
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Alert type="info">
          Response type: <strong>{(parsedResult.responseType as string) || 'Unknown'}</strong>
        </Alert>

        {renderResultContent()}
      </SpaceBetween>
    </Container>
  );
};

export default AgentResultDisplay;
