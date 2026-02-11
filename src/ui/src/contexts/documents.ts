// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useContext, createContext } from 'react';

export interface DocumentsContextValue {
  [key: string]: unknown;
}

export const DocumentsContext = createContext<DocumentsContextValue | null>(null);

const useDocumentsContext = (): DocumentsContextValue | null => useContext(DocumentsContext);

export default useDocumentsContext;
