// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import getConfigVersionsQuery from '../graphql/queries/getConfigVersions';
import getConfigVersionQuery from '../graphql/queries/getConfigVersion';
import useConfiguration from './use-configuration';
import setActiveVersionMutation from '../graphql/queries/setActiveVersion';
import deleteConfigVersionMutation from '../graphql/queries/deleteConfigVersion';
import type { ConfigVersion } from '../components/test-studio/utils/configVersionUtils';

const client = generateClient();
const logger = new ConsoleLogger('useConfigurationVersions');

interface VersionOption {
  label: string;
  value: string;
}

interface UseConfigurationVersionsReturn {
  versions: ConfigVersion[];
  loading: boolean;
  error: string | null;
  fetchVersions: () => Promise<void>;
  fetchVersion: (versionName: string) => Promise<{ schema: unknown; default: unknown; custom: unknown }>;
  setActiveVersion: (versionName: string) => Promise<Record<string, unknown>>;
  saveAsNewVersion: (
    configuration: Record<string, unknown>,
    versionName: string,
    description: string,
  ) => Promise<{ success: boolean; error?: string }>;
  getVersionOptions: () => VersionOption[];
  deleteVersion: (versionName: string, skipRefresh?: boolean) => Promise<Record<string, unknown>>;
}

const useConfigurationVersions = (): UseConfigurationVersionsReturn => {
  const [versions, setVersions] = useState<ConfigVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Get updateConfiguration from useConfiguration hook
  const { updateConfiguration } = useConfiguration();

  const fetchVersions = async (): Promise<void> => {
    setLoading(true);
    setError(null);

    try {
      const result = await client.graphql({ query: getConfigVersionsQuery as unknown as string });
      const response = (result as { data: Record<string, unknown> }).data.getConfigVersions as Record<string, unknown> & {
        success: boolean;
        error?: { message: string };
        versions?: ConfigVersion[];
      };

      // Handle null response
      if (!response) {
        throw new Error('No response received from fetch versions operation');
      }

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to fetch versions');
      }

      const fetchedVersions = response.versions || [];
      logger.info(
        'Fetched versions:',
        fetchedVersions.map((v) => ({ name: v.versionName, description: v.description, created: v.created, isActive: v.isActive })),
      );
      setVersions(fetchedVersions);
    } catch (err: unknown) {
      logger.error('Error fetching configuration versions:', err);
      console.error('Full error object:', err);
      const graphqlErr = err as { errors?: { message: string }[]; message?: string };
      if (graphqlErr.errors) {
        console.error('GraphQL errors:', graphqlErr.errors);
        graphqlErr.errors.forEach((gqlError, index) => {
          console.error(`Error ${index + 1}:`, gqlError.message);
        });
      }
      setError(graphqlErr.message || 'Failed to fetch versions');
    } finally {
      setLoading(false);
    }
  };

  const fetchVersion = async (versionName: string): Promise<{ schema: unknown; default: unknown; custom: unknown }> => {
    try {
      const result = await client.graphql({
        query: getConfigVersionQuery as unknown as string,
        variables: { versionName },
      });
      const response = (result as { data: Record<string, unknown> }).data.getConfigVersion as Record<string, unknown> & {
        success: boolean;
        error?: { message: string };
        Schema?: unknown;
        Default?: unknown;
        Custom?: unknown;
      };

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to fetch version');
      }

      return {
        schema: response.Schema,
        default: response.Default,
        custom: response.Custom,
      };
    } catch (err) {
      logger.error('Error fetching configuration version:', err);
      throw err;
    }
  };

  const setActiveVersion = async (versionName: string): Promise<Record<string, unknown>> => {
    try {
      const result = await client.graphql({
        query: setActiveVersionMutation as unknown as string,
        variables: { versionName },
      });
      const response = (result as { data: Record<string, unknown> }).data.setActiveVersion as Record<string, unknown> & {
        success: boolean;
        error?: { message: string };
      };

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to set active version');
      }

      // Refresh versions list after setting active
      await fetchVersions();

      return response;
    } catch (err) {
      logger.error('Error setting active version:', err);
      throw err;
    }
  };

  const saveAsNewVersion = async (
    configuration: Record<string, unknown>,
    versionName: string,
    description: string,
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      // Check if version name is "default"
      if (versionName === 'default') {
        return {
          success: false,
          error: 'Cannot create version "default" - this name is reserved. Please use a different name.',
        };
      }

      // Check if version name conflicts with active version
      const activeVersion = versions.find((v) => v.isActive);
      if (activeVersion && versionName === activeVersion.versionName) {
        return {
          success: false,
          error: `Cannot create version "${versionName}" - this name is already used by the active version. Please change the active version first or use a different name.`,
        };
      }

      // Add saveAsVersion flag to the configuration
      const configWithFlag = {
        ...configuration,
        saveAsVersion: true,
      };

      // Use the same format as regular updateConfiguration calls with saveAsVersion flag
      const success = await updateConfiguration(versionName, configWithFlag, description);

      if (!success) {
        throw new Error('Failed to save as new version');
      }

      // Refresh versions list after saving new version
      await fetchVersions();

      return { success: true };
    } catch (err) {
      logger.error('Error saving as new version for', versionName, ':', err);
      throw err;
    }
  };

  const deleteVersion = async (versionName: string, skipRefresh: boolean = false): Promise<Record<string, unknown>> => {
    try {
      const result = await client.graphql({
        query: deleteConfigVersionMutation as unknown as string,
        variables: { versionName },
      });
      const response = (result as { data: Record<string, unknown> }).data?.deleteConfigVersion as
        | (Record<string, unknown> & { success: boolean; error?: { message: string } })
        | undefined;

      if (!response) {
        throw new Error('No response received from delete operation');
      }

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to delete version');
      }

      // Only refresh if not skipping
      if (!skipRefresh) {
        await fetchVersions();
      }

      return response;
    } catch (err) {
      logger.error('Error deleting version:', err);
      throw err;
    }
  };

  useEffect(() => {
    fetchVersions();
  }, []);

  // Utility function to generate version options for Select components
  const getVersionOptions = (): VersionOption[] => {
    return versions.map((version) => {
      const truncatedDescription =
        version.description && version.description.length > 50 ? `${version.description.substring(0, 50)}...` : version.description;

      return {
        label: version.isActive
          ? `${version.versionName} (Active)${truncatedDescription ? ` - ${truncatedDescription}` : ''}`
          : `${version.versionName}${truncatedDescription ? ` - ${truncatedDescription}` : ''}`,
        value: version.versionName,
      };
    });
  };

  return {
    versions,
    loading,
    error,
    fetchVersions,
    fetchVersion,
    setActiveVersion,
    saveAsNewVersion,
    getVersionOptions,
    deleteVersion,
  };
};

export default useConfigurationVersions;
