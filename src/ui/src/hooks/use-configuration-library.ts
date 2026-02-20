// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

interface ConfigLibraryItem {
  name: string;
  hasReadme: boolean;
  path: string;
  configFileType: string;
}

interface ListConfigurationLibraryResponse {
  success: boolean;
  items: ConfigLibraryItem[];
  error?: string;
}

interface GetConfigurationLibraryFileResponse {
  success: boolean;
  content: string;
  contentType: string;
  error?: string;
}

interface UseConfigurationLibraryReturn {
  loading: boolean;
  error: string | null;
  listConfigurations: (pattern: string) => Promise<ConfigLibraryItem[]>;
  getFile: (pattern: string, configName: string, fileName: string) => Promise<{ content: string; contentType: string } | null>;
}

const client = generateClient();
const logger = new ConsoleLogger('useConfigurationLibrary');

const LIST_CONFIG_LIBRARY = `
  query ListConfigurationLibrary($pattern: String!) {
    listConfigurationLibrary(pattern: $pattern) {
      success
      items {
        name
        hasReadme
        path
        configFileType
      }
      error
    }
  }
`;

const GET_CONFIG_LIBRARY_FILE = `
  query GetConfigurationLibraryFile(
    $pattern: String!
    $configName: String!
    $fileName: String!
  ) {
    getConfigurationLibraryFile(
      pattern: $pattern
      configName: $configName
      fileName: $fileName
    ) {
      success
      content
      contentType
      error
    }
  }
`;

const useConfigurationLibrary = (): UseConfigurationLibraryReturn => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listConfigurations = async (pattern: string): Promise<ConfigLibraryItem[]> => {
    setLoading(true);
    setError(null);

    try {
      logger.debug('Listing configurations for pattern:', pattern);
      const result = await client.graphql({
        query: LIST_CONFIG_LIBRARY,
        variables: { pattern },
      });

      const response = (result as { data: { listConfigurationLibrary: ListConfigurationLibraryResponse } }).data.listConfigurationLibrary;

      if (!response.success) {
        throw new Error(response.error || 'Failed to list configurations');
      }

      logger.debug('Configurations listed successfully:', response.items);
      return response.items || [];
    } catch (err: unknown) {
      logger.error('Error listing configurations:', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return [];
    } finally {
      setLoading(false);
    }
  };

  const getFile = async (
    pattern: string,
    configName: string,
    fileName: string,
  ): Promise<{ content: string; contentType: string } | null> => {
    setLoading(true);
    setError(null);

    try {
      logger.debug('Getting file:', { pattern, configName, fileName });
      const result = await client.graphql({
        query: GET_CONFIG_LIBRARY_FILE,
        variables: { pattern, configName, fileName },
      });

      const response = (result as { data: { getConfigurationLibraryFile: GetConfigurationLibraryFileResponse } }).data
        .getConfigurationLibraryFile;

      if (!response.success) {
        throw new Error(response.error || 'Failed to get file');
      }

      logger.debug('File retrieved successfully');
      return {
        content: response.content,
        contentType: response.contentType,
      };
    } catch (err: unknown) {
      logger.error('Error getting file:', err);
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  return {
    loading,
    error,
    listConfigurations,
    getFile,
  };
};

export default useConfigurationLibrary;
