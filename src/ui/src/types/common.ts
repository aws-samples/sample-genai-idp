// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface Notification {
  type: 'info' | 'error' | 'warning' | 'success';
  content: string;
  dismissible?: boolean;
  dismissLabel?: string;
  id: string | number;
  onDismiss?: () => void;
}

export interface SchemaValidationError {
  path: string;
  message: string;
  keyword?: string;
}
