// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from 'react';
import { Logger } from 'aws-amplify';

import useAppContext from '../contexts/app';

const logger = new Logger('useNotifications');

const dismissedInitialNotificationsStorageKey = 'dismissedInitialNotifications';
const initialNotifications = [
  {
    type: 'info',
    content: 'Welcome to GenAI IDP (GenAIIDP)',
    dismissible: true,
    dismissLabel: 'Dismiss message',
    id: 'welcome-1',
  },
];

const useNotifications = () => {
  const { errorMessage, setErrorMessage } = useAppContext();

  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    // sets initial notifications and persists state of dismissed notifications in local storage

    const getDissmissedNotificationIdsFromStorage = () => {
      let dismissedInitialNotificationIds = [];
      try {
        const dismissedStored = JSON.parse(localStorage.getItem(dismissedInitialNotificationsStorageKey) || '[]');
        if (!Array.isArray(dismissedStored)) {
          logger.warn('invalid format of dismisssed notifications from local storage');
        } else {
          dismissedInitialNotificationIds = dismissedStored;
        }
      } catch {
        logger.warn('failed to parse dismisssed notifications from local storage');
        return [];
      }

      return dismissedInitialNotificationIds;
    };

    const dismissedInitialNotificationIds = getDissmissedNotificationIdsFromStorage();
    const initialNotificationsNotDismissed = initialNotifications.filter(
      (n) => !dismissedInitialNotificationIds.includes(n.id),
    );

    const notificationIds = notifications.map((n) => n.id);
    // prettier-ignore
    if (
      // all have been dismissed
      !initialNotificationsNotDismissed.length
      // all area already in the notifications state
      || initialNotificationsNotDismissed.every((n) => notificationIds.includes(n.id))
    ) {
      return;
    }

    // add dismiss handler to notifications
    const initialNotificationsToShow = initialNotificationsNotDismissed.map((n) => ({
      ...n,
      onDismiss: () => {
        setNotifications((current) => current.filter((i) => i.id !== n.id));
        const storedIds = getDissmissedNotificationIdsFromStorage();
        localStorage.setItem(dismissedInitialNotificationsStorageKey, JSON.stringify([...storedIds, n.id]));
      },
    }));

    setNotifications((current) => [...initialNotificationsToShow, ...current]);
  }, [notifications]);

  useEffect(() => {
    // adds error messages to notifications
    const id = performance.now();
    const maxSameError = 3;
    const maxSameErrorInMs = 2000;

    if (!errorMessage) {
      return;
    }

    // limit the number of same error
    const sameErrorMessage = notifications.filter((i) => i.content === errorMessage);
    if (sameErrorMessage.lenth > maxSameError) {
      return;
    }
    // limit the number of errors within a time range
    const sameErrorInMs = sameErrorMessage.filter((i) => id - i.id > maxSameErrorInMs);
    if (sameErrorInMs.length) {
      return;
    }

    logger.debug('setting error notification', errorMessage);

    const errorNotification = {
      type: 'error',
      content: errorMessage,
      dismissible: true,
      dismissLabel: 'Dismiss message',
      id,
      onDismiss: () => {
        setNotifications((current) => current.filter((i) => i.id !== id));
      },
    };
    setNotifications((current) => [...current, errorNotification]);
    setErrorMessage('');
  }, [errorMessage, notifications]);

  return notifications;
};

export default useNotifications;
