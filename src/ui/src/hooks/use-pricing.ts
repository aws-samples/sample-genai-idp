// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import getPricingQuery from '../graphql/queries/getPricing';
import updatePricingMutation from '../graphql/queries/updatePricing';
import restoreDefaultPricingMutation from '../graphql/queries/restoreDefaultPricing';

interface PricingResponse {
  success: boolean;
  error?: { message: string };
  pricing: unknown;
  defaultPricing: unknown;
}

interface GetPricingResult {
  data: { getPricing: PricingResponse };
}

interface MutationResponse {
  success: boolean;
  error?: { message: string };
}

interface UsePricingReturn {
  pricing: unknown;
  defaultPricing: unknown;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  fetchPricing: (silent?: boolean) => Promise<void>;
  updatePricing: (newPricing: unknown) => Promise<boolean>;
  restoreDefaultPricing: () => Promise<boolean>;
}

const client = generateClient();
const logger = new ConsoleLogger('usePricing');

const usePricing = (): UsePricingReturn => {
  const [pricing, setPricing] = useState<unknown>(null);
  const [defaultPricing, setDefaultPricing] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPricing = async (silent: boolean = false): Promise<void> => {
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      logger.debug('Fetching pricing...');
      const result = await client.graphql({ query: getPricingQuery as unknown as string });
      logger.debug('API response:', result);

      const response = (result as GetPricingResult).data.getPricing;

      if (!response.success) {
        const errorMsg = response.error?.message || 'Failed to load pricing';
        throw new Error(errorMsg);
      }

      // pricing comes as AWSJSON (a JSON string) - parse it
      let pricingData = response.pricing;
      if (typeof pricingData === 'string') {
        pricingData = JSON.parse(pricingData);
      }

      // defaultPricing also comes as AWSJSON - parse it
      let defaultPricingData = response.defaultPricing;
      if (typeof defaultPricingData === 'string') {
        defaultPricingData = JSON.parse(defaultPricingData);
      }

      // The new pricing data structure is { pricing: [{ name: "service/api", units: [{ name, price }] }] }
      // Just pass through the data directly - no restructuring needed
      logger.debug('Parsed pricing:', pricingData);
      logger.debug('Parsed default pricing:', defaultPricingData);
      setPricing(pricingData);
      setDefaultPricing(defaultPricingData);
    } catch (err: unknown) {
      logger.error('Error fetching pricing', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to load pricing: ${message}`);
    } finally {
      if (silent) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  };

  const updatePricing = async (newPricing: unknown): Promise<boolean> => {
    setError(null);
    try {
      logger.debug('Updating pricing with:', newPricing);

      // Send the entire pricing object as AWSJSON (stringify if not already a string)
      const pricingConfig = typeof newPricing === 'string' ? newPricing : JSON.stringify(newPricing);

      logger.debug('Sending pricingConfig:', pricingConfig);

      const result = await client.graphql({
        query: updatePricingMutation as unknown as string,
        variables: { pricingConfig },
      });

      const response = (result as { data: { updatePricing: MutationResponse } }).data.updatePricing;

      if (!response.success) {
        const errorMsg = response.error?.message || 'Failed to update pricing';
        throw new Error(errorMsg);
      }

      // Refetch silently to ensure backend and frontend are in sync
      await fetchPricing(true);

      return true;
    } catch (err: unknown) {
      logger.error('Error updating pricing', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to update pricing: ${message}`);
      return false;
    }
  };

  const restoreDefaultPricing = async (): Promise<boolean> => {
    setError(null);
    try {
      logger.debug('Restoring default pricing...');

      const result = await client.graphql({
        query: restoreDefaultPricingMutation as unknown as string,
      });

      const response = (result as { data: { restoreDefaultPricing: MutationResponse } }).data.restoreDefaultPricing;

      if (!response.success) {
        const errorMsg = response.error?.message || 'Failed to restore default pricing';
        throw new Error(errorMsg);
      }

      // Refetch to get the restored defaults
      await fetchPricing(true);

      return true;
    } catch (err: unknown) {
      logger.error('Error restoring default pricing', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(`Failed to restore default pricing: ${message}`);
      return false;
    }
  };

  useEffect(() => {
    fetchPricing();
  }, []);

  return {
    pricing,
    defaultPricing,
    loading,
    refreshing,
    error,
    fetchPricing,
    updatePricing,
    restoreDefaultPricing,
  };
};

export default usePricing;
