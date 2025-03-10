// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from 'react';

const useSplitPanel = (selectedItems) => {
  const [splitPanelSize, setSplitPanelSize] = useState(300);
  const [splitPanelOpen, setSplitPanelOpen] = useState(false);
  const [hasManuallyClosedOnce, setHasManuallyClosedOnce] = useState(false);

  const onSplitPanelResize = ({ detail: { size } }) => {
    setSplitPanelSize(size);
  };

  const onSplitPanelToggle = ({ detail: { open } }) => {
    setSplitPanelOpen(open);

    if (!open) {
      setHasManuallyClosedOnce(true);
    }
  };

  useEffect(() => {
    if (selectedItems.length && !hasManuallyClosedOnce) {
      setSplitPanelOpen(true);
    }
  }, [selectedItems.length, hasManuallyClosedOnce]);

  return {
    splitPanelOpen,
    onSplitPanelToggle,
    splitPanelSize,
    onSplitPanelResize,
  };
};

export default useSplitPanel;
