/* eslint-disable max-len */
import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import { Box, Button, Spinner, Header, Grid, Container, SpaceBetween, Input, Link } from '@awsui/components-react';
import PropTypes from 'prop-types';
import { API, Logger } from 'aws-amplify';
import queryKnowledgeBase from '../../graphql/queries/queryKnowledgeBase';
import { DOCUMENTS_PATH } from '../../routes/constants';
import useSettingsContext from '../../contexts/settings';

const logger = new Logger('queryKnowledgeBase');

const ValueWithLabel = ({ label, index, children }) => (
  <>
    <Box variant="awsui-key-label">
      <span tabIndex={index}>
        <ReactMarkdown>{label ? `**Q: ${label}**` : ''}</ReactMarkdown>
      </span>
    </Box>
    {children}
  </>
);

ValueWithLabel.propTypes = {
  label: PropTypes.string.isRequired,
  index: PropTypes.number.isRequired,
  children: PropTypes.node.isRequired,
};

const CustomLink = ({ href, children }) => {
  const handleClick = (e) => {
    e.preventDefault();
    // Handle the link click here
    console.log('Link clicked:', href);
    // You can add your custom navigation logic here
  };

  return (
    <Link href={`#${DOCUMENTS_PATH}/${href}`} onClick={handleClick}>
      {children}
    </Link>
  );
};
CustomLink.propTypes = {
  href: PropTypes.string.isRequired,
  children: PropTypes.node.isRequired,
};

export const DocumentsQueryLayout = () => {
  const [inputQuery, setInputQuery] = useState('');
  const [meetingKbQueries, setMeetingKbQueries] = useState([]);
  const [meetingKbQueryStatus, setMeetingKbQueryStatus] = useState(false);
  const [kbSessionId, setKbSessionId] = useState('');
  const { settings } = useSettingsContext();

  const getElementByIdAsync = (id) =>
    // eslint-disable-next-line
    new Promise((resolve) => {
      const getElement = () => {
        const element = document.getElementById(id);
        if (element) {
          resolve(element);
        } else {
          requestAnimationFrame(getElement);
        }
      };
      getElement();
    });

  const scrollToBottomOfChat = async () => {
    const chatDiv = await getElementByIdAsync('chatDiv');
    chatDiv.scrollTop = chatDiv.scrollHeight + 200;
  };

  const getDocumentsQueryResponseFromKB = async (input, sessionId) => {
    const response = await API.graphql({
      query: queryKnowledgeBase,
      variables: { input, sessionId },
    });
    return response;
  };

  const submitQuery = (query) => {
    if (meetingKbQueryStatus === true) {
      return;
    }

    setMeetingKbQueryStatus(true);

    const responseData = {
      label: query,
      value: '...',
    };
    const currentQueries = meetingKbQueries.concat(responseData);
    setMeetingKbQueries(currentQueries);
    scrollToBottomOfChat();

    logger.debug('Submitting GraphQL query:', query);
    const queryResponse = getDocumentsQueryResponseFromKB(query, kbSessionId);

    queryResponse.then((r) => {
      const kbResponse = JSON.parse(r.data.queryKnowledgeBase);
      const kbanswer = kbResponse.markdown;
      setKbSessionId(kbResponse.sessionId);
      const queries = currentQueries.map((q) => {
        if (q.value !== '...') {
          return q;
        }
        return {
          label: q.label,
          value: kbanswer,
        };
      });
      setMeetingKbQueries(queries);
      scrollToBottomOfChat();
    });
    setMeetingKbQueryStatus(false);
  };

  const onSubmit = (e) => {
    submitQuery(inputQuery);
    setInputQuery('');
    e.preventDefault();
    return true;
  };

  // eslint-disable-next-line
  const placeholder =
    settings.ShouldUseDocumentKnowledgeBase === 'true'
      ? 'Enter a question to query your document knowledge base.'
      : 'Document Knowledge Base is set to DISABLED for this GenAIIDP deployment.';
  // eslint-disable-next-line
  const initialMsg =
    settings.ShouldUseDocumentKnowledgeBase === 'true'
      ? 'Ask a question below.'
      : 'Document Knowledge Base queries are not enabled. Document Knowledge Base is set to DISABLED for this GenAIIDP deployment.';
  return (
    <Container
      fitHeight={false}
      header={<Header variant="h2">Documents Knowledge Base Query Tool</Header>}
      /* For future use. :) */
      footer={
        <form onSubmit={onSubmit}>
          <Grid gridDefinition={[{ colspan: { default: 12, xxs: 9 } }, { default: 12, xxs: 3 }]}>
            <Input
              placeholder={`${placeholder}`}
              onChange={({ detail }) => setInputQuery(detail.value)}
              value={inputQuery}
            />
            <Button type="submit">Submit</Button>
          </Grid>
        </form>
      }
    >
      <div id="chatDiv" style={{ overflow: 'hidden', overflowY: 'auto', height: '30em' }}>
        <SpaceBetween size="m">
          {meetingKbQueries.length > 0 ? (
            meetingKbQueries.map((entry, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <ValueWithLabel key={i} index={i} label={entry.label}>
                {entry.value === '...' ? (
                  <div style={{ height: '30px' }}>
                    <Spinner />
                  </div>
                ) : (
                  <ReactMarkdown
                    rehypePlugins={[rehypeRaw]}
                    components={{
                      documentid: CustomLink,
                    }}
                  >
                    {entry.value}
                  </ReactMarkdown>
                )}
              </ValueWithLabel>
            ))
          ) : (
            <ValueWithLabel key="nosummary">{`${initialMsg}`}</ValueWithLabel>
          )}
        </SpaceBetween>
      </div>
    </Container>
  );
};

export default DocumentsQueryLayout;
