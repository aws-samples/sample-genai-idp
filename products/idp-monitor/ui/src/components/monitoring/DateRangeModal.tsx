// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Custom Date Range Modal
 *
 * Modal dialog for selecting a custom start/end date+time range.
 * Modeled on the Accelerator's DateRangeModal in
 * src/ui/src/components/common/DateRangeModal.tsx
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import DatePicker from '@cloudscape-design/components/date-picker';
import FormField from '@cloudscape-design/components/form-field';
import Modal from '@cloudscape-design/components/modal';
import SpaceBetween from '@cloudscape-design/components/space-between';
import TimeInput from '@cloudscape-design/components/time-input';
import { useState } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface DateRange {
  startDateTime: string;
  endDateTime: string;
}

interface DateRangeModalProps {
  visible: boolean;
  onDismiss: () => void;
  onApply: (range: DateRange) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function DateRangeModal({ visible, onDismiss, onApply }: DateRangeModalProps): JSX.Element {
  // Default to last 7 days
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

  const [startDate, setStartDate] = useState(weekAgo.toISOString().split('T')[0]);
  const [startTime, setStartTime] = useState('00:00:00');
  const [endDate, setEndDate] = useState(now.toISOString().split('T')[0]);
  const [endTime, setEndTime] = useState('23:59:59');
  const [error, setError] = useState<string | null>(null);

  const handleApply = () => {
    setError(null);

    if (!startDate || !endDate) {
      setError('Both start and end dates are required.');
      return;
    }

    const startDateTime = `${startDate}T${startTime || '00:00:00'}.000Z`;
    const endDateTime = `${endDate}T${endTime || '23:59:59'}.000Z`;

    if (startDateTime >= endDateTime) {
      setError('Start date/time must be before end date/time.');
      return;
    }

    // Warn if range exceeds 365 days
    const startMs = new Date(startDateTime).getTime();
    const endMs = new Date(endDateTime).getTime();
    const daysDiff = (endMs - startMs) / (1000 * 60 * 60 * 24);
    if (daysDiff > 365) {
      setError('Date range cannot exceed 365 days. Please select a shorter range.');
      return;
    }

    onApply({ startDateTime, endDateTime });
  };

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header="Select custom date range"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleApply}>
              Apply
            </Button>
          </SpaceBetween>
        </Box>
      }
      size="medium"
    >
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}
        <SpaceBetween size="m" direction="horizontal">
          <FormField label="Start date" constraintText="YYYY/MM/DD">
            <DatePicker
              value={startDate}
              onChange={({ detail }) => setStartDate(detail.value)}
              placeholder="YYYY/MM/DD"
              openCalendarAriaLabel={(selectedDate) =>
                `Choose start date${selectedDate ? `, selected date is ${selectedDate}` : ''}`
              }
            />
          </FormField>
          <FormField label="Start time (UTC)" constraintText="HH:mm:ss">
            <TimeInput
              value={startTime}
              onChange={({ detail }) => setStartTime(detail.value)}
              format="hh:mm:ss"
              placeholder="00:00:00"
            />
          </FormField>
        </SpaceBetween>
        <SpaceBetween size="m" direction="horizontal">
          <FormField label="End date" constraintText="YYYY/MM/DD">
            <DatePicker
              value={endDate}
              onChange={({ detail }) => setEndDate(detail.value)}
              placeholder="YYYY/MM/DD"
              openCalendarAriaLabel={(selectedDate) =>
                `Choose end date${selectedDate ? `, selected date is ${selectedDate}` : ''}`
              }
            />
          </FormField>
          <FormField label="End time (UTC)" constraintText="HH:mm:ss">
            <TimeInput
              value={endTime}
              onChange={({ detail }) => setEndTime(detail.value)}
              format="hh:mm:ss"
              placeholder="23:59:59"
            />
          </FormField>
        </SpaceBetween>
        <Box variant="small" color="text-body-secondary">
          Monitoring data is queried for the selected date range. All times are in UTC.
        </Box>
      </SpaceBetween>
    </Modal>
  );
}
