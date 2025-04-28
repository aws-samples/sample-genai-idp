// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useCallback } from 'react';

/**
 * Custom hook to manage modal visibility
 * @returns {Object} Modal state and handler functions
 */
const useModal = () => {
  const [visible, setVisible] = useState(false);

  const show = useCallback(() => {
    // Use setTimeout to ensure the state update is processed in the next tick
    // This helps with React's asynchronous state updates
    setTimeout(() => {
      setVisible(true);
    }, 0);
  }, []);

  const hide = useCallback(() => {
    setVisible(false);
  }, []);

  return {
    visible,
    show,
    hide,
  };
};

export default useModal;
