// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import PropTypes from 'prop-types';
import { FiSmile, FiMeh, FiFrown } from 'react-icons/fi';

const style = {
  verticalAlign: 'middle',
};

export const SentimentIcon = ({ sentiment = 'NEUTRAL', size = '1.5em' }) => {
  if (sentiment === 'POSITIVE') {
    return <FiSmile style={style} color="green" size={size} title="positive" />;
  }

  if (sentiment === 'NEGATIVE') {
    return <FiFrown style={style} color="red" size={size} title="negative" />;
  }

  return <FiMeh style={style} color="grey" size={size} tille={sentiment.toLowerCase()} />;
};
SentimentIcon.defaultProps = {
  sentiment: 'NEUTRAL',
  size: '1.5em',
};
SentimentIcon.propTypes = {
  sentiment: PropTypes.oneOf(['POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED']),
  size: PropTypes.string,
};

const getSentimentColor = (sentiment) => {
  if (sentiment === 'POSITIVE') {
    return 'green';
  }
  if (sentiment === 'NEGATIVE') {
    return 'red';
  }
  return 'gray';
};

export const SentimentIndicator = ({ sentiment = 'NEUTRAL' }) => (
  <div>
    <span>
      <SentimentIcon size="1.25em" sentiment={sentiment} />
    </span>
    <span style={{ verticalAlign: 'middle', padding: '3px', color: getSentimentColor(sentiment) }}>
      {` ${sentiment.charAt(0)}${sentiment.slice(1).toLowerCase()} `}
    </span>
  </div>
);
SentimentIndicator.defaultProps = {
  sentiment: 'NEUTRAL',
};
SentimentIndicator.propTypes = {
  sentiment: PropTypes.oneOf(['POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED']),
};
