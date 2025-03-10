// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { FiTrendingDown, FiTrendingUp } from 'react-icons/fi';
import { MdTrendingFlat } from 'react-icons/md';

const style = {
  verticalAlign: 'middle',
};

export const SentimentTrendIcon = ({ trend = 'FLAT', size = '1.5em' }) => {
  if (trend === 'UP') {
    return <FiTrendingUp style={style} color="green" size={size} title="up" />;
  }

  if (trend === 'DOWN') {
    return <FiTrendingDown style={style} color="red" size={size} title="down" />;
  }

  return <MdTrendingFlat style={style} color="grey" size={size} title="flat" />;
};
SentimentTrendIcon.defaultProps = {
  trend: 'FLAT',
  size: '1.5em',
};
SentimentTrendIcon.propTypes = {
  trend: PropTypes.oneOf(['UP', 'DOWN', 'FLAT']),
  size: PropTypes.string,
};

const getTrendColor = (trend) => {
  if (trend === 'UP') {
    return 'green';
  }
  if (trend === 'DOWN') {
    return 'red';
  }
  return 'gray';
};

export const SentimentTrendIndicator = ({ trend = 'FLAT' }) => (
  <div>
    <span>
      <SentimentTrendIcon size="1.25em" trend={trend} />
    </span>
    <span style={{ verticalAlign: 'middle', padding: '3px', color: getTrendColor(trend) }}>
      {` ${trend.charAt(0)}${trend.slice(1).toLowerCase()} `}
    </span>
  </div>
);
SentimentTrendIndicator.defaultProps = {
  trend: 'FLAT',
};
SentimentTrendIndicator.propTypes = {
  trend: PropTypes.oneOf(['UP', 'DOWN', 'FLAT']),
};
