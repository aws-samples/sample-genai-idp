// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useContext, createContext } from 'react';

export const DocumentsContext = createContext(null);

const useDocumentsContext = () => useContext(DocumentsContext);

export default useDocumentsContext;
