// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, useEffect } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';
import {
  getModelConfigLimits,
  updateModelConfigLimits as updateModelConfigLimitsOp,
  restoreDefaultModelConfigLimits as restoreDefaultModelConfigLimitsOp,
} from '../graphql/generated';
import { parseModelConfigLimitsData } from '../graphql/awsjson-parsers';
import type { ModelConfigLimitsData } from '../graphql/awsjson-types';

interface UseModelConfigLimitsReturn {
  modelConfigLimits: ModelConfigLimitsData | null;
  defaultModelConfigLimits: ModelConfigLimitsData | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  fetchModelConfigLimits: (silent?: boolean) => Promise<void>;
  updateModelConfigLimits: (newLimits: unknown) => Promise<boolean>;
  restoreDefaultModelConfigLimits: () => Promise<boolean>;
}

const client = generateClient();
const logger = new ConsoleLogger('useModelConfigLimits');

const useModelConfigLimits = (): UseModelConfigLimitsReturn => {
  const [modelConfigLimits, setModelConfigLimits] = useState<ModelConfigLimitsData | null>(null);
  const [defaultModelConfigLimits, setDefaultModelConfigLimits] = useState<ModelConfigLimitsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchModelConfigLimits = async (silent: boolean = false): Promise<void> => {
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      logger.debug('Fetching model config limits...');
      const result = await client.graphql({ query: getModelConfigLimits });
      logger.debug('API response:', result);

      const response = result.data.getModelConfigLimits;

      if (!response?.success) {
        const errorMsg = response?.error?.message || 'Failed to load model config limits';
        throw new Error(errorMsg);
      }

      // modelConfigLimits and defaultModelConfigLimits come as AWSJSON (JSON strings)
      const limitsData = parseModelConfigLimitsData(response.modelConfigLimits as string);
      const defaultLimitsData = parseModelConfigLimitsData(response.defaultModelConfigLimits as string);

      if (limitsData == null || defaultLimitsData == null) {
        throw new Error('Failed to parse model config limits from server response');
      }

      logger.debug('Parsed model config limits:', limitsData);
      logger.debug('Parsed default model config limits:', defaultLimitsData);
      setModelConfigLimits(limitsData);
      setDefaultModelConfigLimits(defaultLimitsData);
    } catch (err: unknown) {
      logger.error('Error fetching model config limits', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to load model config limits: ${message}`);
    } finally {
      if (silent) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  };

  const updateModelConfigLimits = async (newLimits: unknown): Promise<boolean> => {
    setError(null);
    try {
      logger.debug('Updating model config limits with:', newLimits);

      // Send the entire limits object as AWSJSON (stringify if not already a string)
      const limitsJson = typeof newLimits === 'string' ? newLimits : JSON.stringify(newLimits);

      const result = await client.graphql({
        query: updateModelConfigLimitsOp,
        variables: { modelConfigLimits: limitsJson },
      });

      const response = result.data.updateModelConfigLimits;

      if (!response?.success) {
        const errorMsg = response?.error?.message || 'Failed to update model config limits';
        throw new Error(errorMsg);
      }

      // Refetch silently to ensure backend and frontend are in sync
      await fetchModelConfigLimits(true);

      return true;
    } catch (err: unknown) {
      logger.error('Error updating model config limits', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to update model config limits: ${message}`);
      return false;
    }
  };

  const restoreDefaultModelConfigLimits = async (): Promise<boolean> => {
    setError(null);
    try {
      logger.debug('Restoring default model config limits...');

      const result = await client.graphql({
        query: restoreDefaultModelConfigLimitsOp,
      });

      const response = result.data.restoreDefaultModelConfigLimits;

      if (!response?.success) {
        const errorMsg = response?.error?.message || 'Failed to restore default model config limits';
        throw new Error(errorMsg);
      }

      // Refetch to get the restored defaults
      await fetchModelConfigLimits(true);

      return true;
    } catch (err: unknown) {
      logger.error('Error restoring default model config limits', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to restore default model config limits: ${message}`);
      return false;
    }
  };

  useEffect(() => {
    fetchModelConfigLimits();
  }, []);

  return {
    modelConfigLimits,
    defaultModelConfigLimits,
    loading,
    refreshing,
    error,
    fetchModelConfigLimits,
    updateModelConfigLimits,
    restoreDefaultModelConfigLimits,
  };
};

export default useModelConfigLimits;
