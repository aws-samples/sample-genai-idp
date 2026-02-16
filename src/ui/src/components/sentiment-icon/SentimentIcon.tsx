// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { FiSmile, FiMeh, FiFrown } from 'react-icons/fi';

const style = {
  verticalAlign: 'middle',
};

type Sentiment = 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL' | 'MIXED';

interface SentimentIconProps {
  sentiment?: Sentiment;
  size?: string;
}

export const SentimentIcon = ({ sentiment = 'NEUTRAL', size = '1.5em' }: SentimentIconProps): React.JSX.Element => {
  if (sentiment === 'POSITIVE') {
    return <FiSmile style={style} color="green" size={size} title="positive" />;
  }

  if (sentiment === 'NEGATIVE') {
    return <FiFrown style={style} color="red" size={size} title="negative" />;
  }

  return <FiMeh style={style} color="grey" size={size} title={sentiment.toLowerCase()} />;
};

const getSentimentColor = (sentiment: Sentiment): string => {
  if (sentiment === 'POSITIVE') {
    return 'green';
  }
  if (sentiment === 'NEGATIVE') {
    return 'red';
  }
  return 'gray';
};

interface SentimentIndicatorProps {
  sentiment?: Sentiment;
}

export const SentimentIndicator = ({ sentiment = 'NEUTRAL' }: SentimentIndicatorProps): React.JSX.Element => (
  <div>
    <span>
      <SentimentIcon size="1.25em" sentiment={sentiment} />
    </span>
    <span style={{ verticalAlign: 'middle', padding: '3px', color: getSentimentColor(sentiment) }}>
      {` ${sentiment.charAt(0)}${sentiment.slice(1).toLowerCase()} `}
    </span>
  </div>
);
