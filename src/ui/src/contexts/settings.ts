// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useContext, createContext } from 'react';

export interface SettingsContextValue {
  [key: string]: unknown;
}

export const SettingsContext = createContext<SettingsContextValue | null>(null);

const useSettingsContext = (): SettingsContextValue | null => useContext(SettingsContext);

export default useSettingsContext;
