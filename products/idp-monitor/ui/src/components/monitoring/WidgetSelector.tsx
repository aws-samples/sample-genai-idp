// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Widget Selector Modal
 *
 * Allows users to show/hide individual dashboard widgets.
 * Preferences are persisted in localStorage.
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Checkbox from '@cloudscape-design/components/checkbox';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Header from '@cloudscape-design/components/header';
import Modal from '@cloudscape-design/components/modal';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useEffect, useState } from 'react';

import {
  WIDGET_DEFINITIONS,
  saveWidgetVisibility,
} from '../../types/widgets';
import type { WidgetId, WidgetVisibilityMap } from '../../types/widgets';

interface WidgetSelectorProps {
  visible: boolean;
  currentVisibility: WidgetVisibilityMap;
  onConfirm: (visibility: WidgetVisibilityMap) => void;
  onDismiss: () => void;
}

export function WidgetSelector({
  visible,
  currentVisibility,
  onConfirm,
  onDismiss,
}: WidgetSelectorProps): JSX.Element {
  const [localVisibility, setLocalVisibility] = useState<WidgetVisibilityMap>(currentVisibility);

  // Sync local state whenever the modal opens
  useEffect(() => {
    if (visible) setLocalVisibility(currentVisibility);
  }, [visible, currentVisibility]);

  const handleToggle = (id: WidgetId, checked: boolean) => {
    setLocalVisibility((prev) => ({ ...prev, [id]: checked }));
  };

  const handleSave = () => {
    saveWidgetVisibility(localVisibility);
    onConfirm(localVisibility);
  };

  const handleReset = () => {
    const defaults: WidgetVisibilityMap = Object.fromEntries(
      WIDGET_DEFINITIONS.map((w) => [w.id, w.defaultVisible]),
    ) as WidgetVisibilityMap;
    setLocalVisibility(defaults);
  };

  const enabledCount = Object.values(localVisibility).filter(Boolean).length;

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={
        <Header
          variant="h2"
          description={`${enabledCount} of ${WIDGET_DEFINITIONS.length} widgets visible`}
        >
          Customize Dashboard
        </Header>
      }
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleReset}>
              Reset to Defaults
            </Button>
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={enabledCount === 0}
            >
              Save
            </Button>
          </SpaceBetween>
        </Box>
      }
      size="medium"
    >
      <SpaceBetween size="m">
        <Box color="text-body-secondary" fontSize="body-s">
          Select the widgets you want to display on the monitoring dashboard.
          Your preferences are saved in your browser.
        </Box>
        <ColumnLayout columns={1} borders="horizontal">
          {WIDGET_DEFINITIONS.map((widget) => (
            <div
              key={widget.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 12,
                padding: '4px 0',
              }}
            >
              <Checkbox
                checked={localVisibility[widget.id]}
                onChange={({ detail }) => handleToggle(widget.id, detail.checked)}
              >
                <div>
                  <Box fontWeight="bold">{widget.label}</Box>
                  <Box color="text-body-secondary" fontSize="body-s">
                    {widget.description}
                  </Box>
                </div>
              </Checkbox>
            </div>
          ))}
        </ColumnLayout>
      </SpaceBetween>
    </Modal>
  );
}
