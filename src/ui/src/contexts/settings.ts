// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useContext, createContext } from 'react';

export interface SettingsContextValue {
  settings: Record<string, unknown>;
}

export const SettingsContext = createContext<SettingsContextValue | null>(null);

const useSettingsContext = (): SettingsContextValue => {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettingsContext must be used within SettingsContext.Provider');
  return ctx;
};

export default useSettingsContext;
