// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import type { AnalyticsState, AnalyticsContextValue } from '../types/analytics';

const AnalyticsContext = createContext<AnalyticsContextValue | null>(null);

interface AnalyticsProviderProps {
  children: React.ReactNode;
}

export const AnalyticsProvider = ({ children }: AnalyticsProviderProps): React.JSX.Element => {
  // State for the analytics page
  const [analyticsState, setAnalyticsState] = useState<AnalyticsState>({
    queryText: '', // The submitted/executed query
    currentInputText: '', // The current text in the input box
    jobId: null,
    jobStatus: null,
    jobResult: null,
    agentMessages: null,
    error: null,
    isSubmitting: false,
    subscription: null,
  });

  // Function to update analytics state
  const updateAnalyticsState = useCallback((updates: Partial<AnalyticsState>) => {
    setAnalyticsState((prevState) => ({
      ...prevState,
      ...updates,
    }));
  }, []);

  // Function to reset analytics state
  const resetAnalyticsState = useCallback(() => {
    setAnalyticsState({
      queryText: '',
      currentInputText: '',
      jobId: null,
      jobStatus: null,
      jobResult: null,
      agentMessages: null,
      error: null,
      isSubmitting: false,
      subscription: null,
    });
  }, []);

  // Function to clear only results but keep query
  const clearAnalyticsResults = useCallback(() => {
    setAnalyticsState((prevState) => ({
      ...prevState,
      jobId: null,
      jobStatus: null,
      jobResult: null,
      agentMessages: null,
      error: null,
      isSubmitting: false,
      subscription: null,
    }));
  }, []);

  const contextValue = useMemo(
    () => ({
      analyticsState,
      updateAnalyticsState,
      resetAnalyticsState,
      clearAnalyticsResults,
    }),
    [analyticsState, updateAnalyticsState, resetAnalyticsState, clearAnalyticsResults],
  );

  return <AnalyticsContext.Provider value={contextValue}>{children}</AnalyticsContext.Provider>;
};

export const useAnalyticsContext = (): AnalyticsContextValue => {
  const context = useContext(AnalyticsContext);
  if (!context) {
    throw new Error('useAnalyticsContext must be used within an AnalyticsProvider');
  }
  return context;
};

export default AnalyticsContext;
