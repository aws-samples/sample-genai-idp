// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useContext, createContext } from 'react';

export const UseCaseContext = createContext(null);

const useUseCaseContext = () => {
  const context = useContext(UseCaseContext);
  if (context === null) {
    throw new Error('useUseCaseContext must be used within a UseCaseContext.Provider');
  }
  return context;
};

export default useUseCaseContext;
