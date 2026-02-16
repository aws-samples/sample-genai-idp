// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { FiTrendingDown, FiTrendingUp } from 'react-icons/fi';
import { MdTrendingFlat } from 'react-icons/md';

const style = {
  verticalAlign: 'middle',
};

type Trend = 'UP' | 'DOWN' | 'FLAT';

interface SentimentTrendIconProps {
  trend?: Trend;
  size?: string;
}

export const SentimentTrendIcon = ({ trend = 'FLAT', size = '1.5em' }: SentimentTrendIconProps): React.JSX.Element => {
  if (trend === 'UP') {
    return <FiTrendingUp style={style} color="green" size={size} title="up" />;
  }

  if (trend === 'DOWN') {
    return <FiTrendingDown style={style} color="red" size={size} title="down" />;
  }

  return <MdTrendingFlat style={style} color="grey" size={size} title="flat" />;
};

const getTrendColor = (trend: Trend): string => {
  if (trend === 'UP') {
    return 'green';
  }
  if (trend === 'DOWN') {
    return 'red';
  }
  return 'gray';
};

interface SentimentTrendIndicatorProps {
  trend?: Trend;
}

export const SentimentTrendIndicator = ({ trend = 'FLAT' }: SentimentTrendIndicatorProps): React.JSX.Element => (
  <div>
    <span>
      <SentimentTrendIcon size="1.25em" trend={trend} />
    </span>
    <span style={{ verticalAlign: 'middle', padding: '3px', color: getTrendColor(trend) }}>
      {` ${trend.charAt(0)}${trend.slice(1).toLowerCase()} `}
    </span>
  </div>
);
