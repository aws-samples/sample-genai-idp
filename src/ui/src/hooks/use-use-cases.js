// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, useEffect, useCallback, useRef } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import listUseCasesQuery from '../graphql/queries/listUseCases';
import createUseCaseMutation from '../graphql/mutations/createUseCase';

const client = generateClient();
const logger = new ConsoleLogger('useUseCases');

const USE_CASE_STORAGE_KEY = 'selectedUseCase';
export const ALL_USE_CASES_ID = '_all';
const ALL_USE_CASES = { businessUnitId: ALL_USE_CASES_ID, useCaseId: ALL_USE_CASES_ID, name: 'All Use Cases', description: '' };

const useUseCases = ({ isAdmin = true, authLoading = false } = {}) => {
  const [useCases, setUseCases] = useState([]);
  const [selectedUseCase, setSelectedUseCaseState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const hasRestoredSelection = useRef(false);

  // Persist selection to localStorage
  const setSelectedUseCase = useCallback((useCase) => {
    setSelectedUseCaseState(useCase);
    try {
      if (useCase) {
        localStorage.setItem(USE_CASE_STORAGE_KEY, JSON.stringify(useCase));
      } else {
        localStorage.removeItem(USE_CASE_STORAGE_KEY);
      }
    } catch (err) {
      logger.warn('Failed to persist use case selection', err);
    }
  }, []);

  const fetchUseCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await client.graphql({ query: listUseCasesQuery });
      if (result.errors && result.errors.length > 0) {
        throw new Error(result.errors[0].message || 'GraphQL Error');
      }
      const fetchedUseCases = result.data.listUseCases?.useCases || [];
      logger.debug('Fetched use cases:', fetchedUseCases);
      setUseCases(fetchedUseCases);
    } catch (err) {
      logger.error('Error fetching use cases:', err);
      setError('Failed to load use cases');
    } finally {
      setLoading(false);
    }
  }, []);

  const createUseCase = useCallback(async (businessUnitId, useCaseId, name, description = '', sourceConfig = null) => {
    try {
      const variables = { businessUnitId, useCaseId, name, description };
      if (sourceConfig) {
        variables.sourceConfig = sourceConfig;
      }
      const result = await client.graphql({
        query: createUseCaseMutation,
        variables,
      });
      if (result.errors && result.errors.length > 0) {
        throw new Error(result.errors[0].message || 'GraphQL Error');
      }
      const newUseCase = result.data?.createUseCase;
      if (!newUseCase) {
        throw new Error('createUseCase returned null — the use case may not have been created');
      }
      setUseCases((prev) => {
        const existingIdx = prev.findIndex((u) => u.businessUnitId === newUseCase.businessUnitId && u.useCaseId === newUseCase.useCaseId);
        if (existingIdx >= 0) {
          const updated = [...prev];
          updated[existingIdx] = newUseCase;
          return updated;
        }
        return [...prev, newUseCase];
      });
      return newUseCase;
    } catch (err) {
      logger.error('Error creating use case:', err);
      throw err;
    }
  }, []);

  // Wait for auth to be ready before fetching use cases.
  // This prevents a race condition where the GraphQL call fires before
  // the Cognito session/token is available, causing it to fail silently.
  useEffect(() => {
    if (authLoading) {
      logger.debug('Auth still loading, deferring use case fetch');
      return;
    }
    logger.debug('Auth ready, fetching use cases');
    fetchUseCases();
  }, [fetchUseCases, authLoading]);

  // Restore selection from localStorage or auto-select for non-admin users.
  // This is separated from fetchUseCases so that it correctly runs whenever
  // useCases changes (e.g. after a retry) without being blocked by hasRestoredSelection.
  useEffect(() => {
    if (useCases.length === 0 || authLoading) return;
    if (hasRestoredSelection.current) return;

    hasRestoredSelection.current = true;
    let selectionRestored = false;
    try {
      const stored = localStorage.getItem(USE_CASE_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // Validate stored selection still exists and refresh if metadata changed
        if (parsed.useCaseId === ALL_USE_CASES_ID && isAdmin) {
          setSelectedUseCaseState(ALL_USE_CASES);
          selectionRestored = true;
        } else if (parsed.useCaseId !== ALL_USE_CASES_ID) {
          const match = useCases.find((uc) => uc.businessUnitId === parsed.businessUnitId && uc.useCaseId === parsed.useCaseId);
          if (match) {
            setSelectedUseCaseState(match);
            selectionRestored = true;
          } else {
            logger.warn('Previously selected use case no longer exists, clearing selection');
            localStorage.removeItem(USE_CASE_STORAGE_KEY);
          }
        } else {
          // Non-admin had "All Use Cases" stored; clear it
          logger.warn('Non-admin user had "All Use Cases" stored, clearing');
          localStorage.removeItem(USE_CASE_STORAGE_KEY);
        }
      }
    } catch (err) {
      logger.warn('Failed to restore use case selection from localStorage', err);
      localStorage.removeItem(USE_CASE_STORAGE_KEY);
    }

    // Auto-select for non-admin users who don't have a valid stored selection:
    // pick their first (or only) allowed use case so they see documents immediately
    if (!selectionRestored && !isAdmin && useCases.length > 0) {
      logger.debug('Auto-selecting first allowed use case for non-admin user');
      setSelectedUseCaseState(useCases[0]);
      try {
        localStorage.setItem(USE_CASE_STORAGE_KEY, JSON.stringify(useCases[0]));
      } catch (_) {
        // best-effort persistence
      }
    }
  }, [useCases, isAdmin, authLoading]);

  // Handle admin->non-admin role transitions: if the user loses admin rights
  // while "All Use Cases" is selected, clear the stale selection and reset
  // so the normal non-admin auto-select path can run.
  useEffect(() => {
    if (authLoading || !hasRestoredSelection.current) return;
    if (!isAdmin && selectedUseCase?.useCaseId === ALL_USE_CASES_ID) {
      logger.warn('Admin->non-admin transition detected with "All Use Cases" still selected, resetting');
      localStorage.removeItem(USE_CASE_STORAGE_KEY);
      if (useCases.length > 0) {
        setSelectedUseCaseState(useCases[0]);
        try {
          localStorage.setItem(USE_CASE_STORAGE_KEY, JSON.stringify(useCases[0]));
        } catch (_) {
          // best-effort persistence
        }
      } else {
        setSelectedUseCaseState(null);
      }
    }
  }, [isAdmin, authLoading, selectedUseCase, useCases]);

  // Revalidate selectedUseCase whenever useCases list changes
  // If the previously selected use case was removed, clear the selection
  // If it still exists but metadata changed, refresh the selection
  useEffect(() => {
    if (!selectedUseCase || selectedUseCase.useCaseId === ALL_USE_CASES_ID) return;
    const match = useCases.find((uc) => uc.businessUnitId === selectedUseCase.businessUnitId && uc.useCaseId === selectedUseCase.useCaseId);
    if (!match) {
      logger.warn('Previously selected use case no longer exists, clearing selection');
      setSelectedUseCase(null);
    } else if (match.name !== selectedUseCase.name || match.description !== selectedUseCase.description) {
      setSelectedUseCase(match);
    }
  }, [useCases, selectedUseCase, setSelectedUseCase]);

  // Whether multi-use-case mode is active (at least one use case registered)
  const isMultiUseCaseEnabled = useCases.length > 0;

  // The effective use case for API calls (null means global/default)
  const effectiveUseCase = selectedUseCase?.useCaseId === ALL_USE_CASES_ID ? null : selectedUseCase;

  return {
    useCases,
    selectedUseCase,
    setSelectedUseCase,
    effectiveUseCase,
    isMultiUseCaseEnabled,
    loading,
    error,
    fetchUseCases,
    createUseCase,
    ALL_USE_CASES,
  };
};

export default useUseCases;
