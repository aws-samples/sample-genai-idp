// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { FlashbarProps } from '@cloudscape-design/components';
import { Notification } from '../../types/common';
import QuickStartGradientButton from '../agent-chat/QuickStartGradientButton';

export const mapNotificationsToFlashbar = (notifications: Notification[]): FlashbarProps.MessageDefinition[] =>
  notifications.map((n) => {
    const item: FlashbarProps.MessageDefinition = {
      type: n.type,
      content: n.content,
      dismissible: n.dismissible,
      dismissLabel: n.dismissLabel,
      id: String(n.id),
      onDismiss: n.onDismiss,
    };
    if (n.buttonText && n.onButtonClick) {
      item.action = <QuickStartGradientButton label={n.buttonText} onClick={n.onButtonClick} />;
    }
    return item;
  });

export default mapNotificationsToFlashbar;
