// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders app div element', () => {
  render(<App />);
  const divElement = screen.getByText(
    // eslint-disable-next-line prettier/prettier
    (content, element) => element.tagName.toLowerCase() === 'div' && element.className.includes('App'),
  );
  expect(divElement).toBeInTheDocument();
});
