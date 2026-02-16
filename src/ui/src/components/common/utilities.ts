// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable import/prefer-default-export */

export const getTimestampStr = (): string => {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const hour = String(now.getHours()).padStart(2, '0');
  const minute = String(now.getMinutes()).padStart(2, '0');
  const second = String(now.getSeconds()).padStart(2, '0');
  const millisecond = String(now.getMilliseconds()).padStart(3, '0');
  const formattedDate = `${year}-${month}-${day}-${hour}:${minute}:${second}.${millisecond}`;
  return formattedDate;
};

export const getJsonValidationError = (error: { message?: string; toString: () => string }): string => {
  const message = error.message || error.toString();

  // Common JSON syntax errors with user-friendly messages
  if (message.includes('Unexpected token')) {
    const match = message.match(/Unexpected token (.+?) in JSON at position (\d+)/);
    if (match) {
      const [, token, position] = match;
      return `Invalid character '${token}' found at position ${position}. Check for missing quotes, commas, or brackets.`;
    }
    return 'Invalid JSON syntax. Check for missing quotes, commas, or brackets.';
  }

  if (message.includes('Unexpected end of JSON input')) {
    return 'Incomplete JSON file. The file appears to be cut off or missing closing brackets.';
  }

  if (message.includes('Expected property name or')) {
    return 'Invalid property name. Property names must be enclosed in double quotes.';
  }

  if (message.includes('Unexpected string in JSON')) {
    return 'Invalid string format. Check for unescaped quotes or missing commas between properties.';
  }

  // Return the original message if we can't provide a better one
  return message;
};
