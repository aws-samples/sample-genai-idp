// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useContext, createContext } from 'react';

export interface AppContextValue {
  errorMessage: string | undefined;
  setErrorMessage: (message: string) => void;
  [key: string]: unknown;
}

export const AppContext = createContext<AppContextValue | null>(null);

const useAppContext = (): AppContextValue | null => useContext(AppContext);

export default useAppContext;
