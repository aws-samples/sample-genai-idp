// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useRef, useState } from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';

import useAppContext from '../contexts/app';
import { Notification } from '../types/common';

const logger = new ConsoleLogger('useNotifications');

const dismissedInitialNotificationsStorageKey = 'dismissedInitialNotifications';

const initialNotifications: Omit<Notification, 'onDismiss'>[] = [
  {
    type: 'info',
    content: 'Welcome to GenAI IDP (GenAIIDP)',
    dismissible: true,
    dismissLabel: 'Dismiss message',
    id: 'welcome-1',
  },
];

const useNotifications = (): Notification[] => {
  const { errorMessage, setErrorMessage, successMessage, setSuccessMessage } = useAppContext();

  const [notifications, setNotifications] = useState<Notification[]>([]);

  // Pending auto-dismiss timers, cleared only on unmount. They cannot live in an
  // effect cleanup: the success effect resets successMessage as it fires, so the
  // very next render re-runs it, and a cleanup would clear the timeout it just set
  // — which is why success toasts used to linger on screen indefinitely.
  const dismissTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(
    () => () => {
      dismissTimersRef.current.forEach(clearTimeout);
      dismissTimersRef.current = [];
    },
    [],
  );

  useEffect(() => {
    // sets initial notifications and persists state of dismissed notifications in local storage

    const getDissmissedNotificationIdsFromStorage = () => {
      let dismissedInitialNotificationIds: string[] = [];
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
    const initialNotificationsNotDismissed = initialNotifications.filter((n) => !dismissedInitialNotificationIds.includes(String(n.id)));

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
    if (sameErrorMessage.length > maxSameError) {
      return;
    }
    // limit the number of errors within a time range
    const sameErrorInMs = sameErrorMessage.filter((i) => id - (i.id as number) > maxSameErrorInMs);
    if (sameErrorInMs.length) {
      return;
    }

    logger.debug('setting error notification', errorMessage);

    const errorNotification: Notification = {
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

  useEffect(() => {
    // adds success messages to notifications; auto-dismisses after a few seconds
    // so transient confirmations (e.g. "Configuration saved") don't linger.
    if (!successMessage) {
      return undefined;
    }

    const id = performance.now();
    const successNotification: Notification = {
      type: 'success',
      content: successMessage,
      dismissible: true,
      dismissLabel: 'Dismiss message',
      id,
      onDismiss: () => {
        setNotifications((current) => current.filter((i) => i.id !== id));
      },
    };
    setNotifications((current) => [...current, successNotification]);
    setSuccessMessage('');

    dismissTimersRef.current.push(
      setTimeout(() => {
        setNotifications((current) => current.filter((i) => i.id !== id));
      }, 5000),
    );
    return undefined;
  }, [successMessage]);

  return notifications;
};

export default useNotifications;
