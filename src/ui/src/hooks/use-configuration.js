import { useState, useEffect } from 'react';
import { API, graphqlOperation, Logger } from 'aws-amplify';
import getConfigurationQuery from '../graphql/queries/getConfiguration';
import updateConfigurationMutation from '../graphql/queries/updateConfiguration';

const logger = new Logger('useConfiguration');

// Deep merge function for combining default and custom configurations
const deepMerge = (target, source) => {
  const result = { ...target };

  if (!source) {
    return result;
  }

  Object.keys(source)
    .filter((key) => Object.hasOwn(source, key))
    .forEach((key) => {
      if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
        if (Object.hasOwn(target, key) && target[key] && typeof target[key] === 'object') {
          result[key] = deepMerge(target[key], source[key]);
        } else {
          result[key] = { ...source[key] };
        }
      } else {
        result[key] = source[key];
      }
    });

  return result;
};

const useConfiguration = () => {
  const [schema, setSchema] = useState(null);
  const [defaultConfig, setDefaultConfig] = useState(null);
  const [customConfig, setCustomConfig] = useState(null);
  const [mergedConfig, setMergedConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchConfiguration = async () => {
    setLoading(true);
    setError(null);
    try {
      logger.debug('Fetching configuration...');
      const result = await API.graphql(graphqlOperation(getConfigurationQuery));
      logger.debug('API response:', result);

      const { Schema, Default, Custom } = result.data.getConfiguration;

      // Log raw data types
      logger.debug('Raw data types:', {
        Schema: typeof Schema,
        Default: typeof Default,
        Custom: typeof Custom,
      });

      // Enhanced parsing logic - handle both string and object types
      let schemaObj = Schema;
      let defaultObj = Default;
      let customObj = Custom;

      // Parse schema if it's a string
      if (typeof Schema === 'string') {
        try {
          schemaObj = JSON.parse(Schema);
          logger.debug('Schema parsed from string successfully');
        } catch (e) {
          logger.error('Error parsing schema string:', e);
          throw new Error(`Failed to parse schema data: ${e.message}`);
        }
      }

      // Parse default config if it's a string
      if (typeof Default === 'string') {
        try {
          defaultObj = JSON.parse(Default);
          logger.debug('Default config parsed from string successfully');
        } catch (e) {
          logger.error('Error parsing default config string:', e);
          throw new Error(`Failed to parse default configuration: ${e.message}`);
        }
      }

      // Parse custom config if it's a string and not null/empty
      if (typeof Custom === 'string' && Custom) {
        try {
          customObj = JSON.parse(Custom);
          logger.debug('Custom config parsed from string successfully');
        } catch (e) {
          logger.error('Error parsing custom config string:', e);
          // Don't throw here, just log the error and use empty object
          customObj = {};
        }
      } else if (!Custom) {
        customObj = {};
      }

      // Debug the parsed objects
      logger.debug('Parsed schema:', schemaObj);
      logger.debug('Parsed default config:', defaultObj);
      logger.debug('Parsed custom config:', customObj);

      // Validate the parsed objects
      if (!schemaObj || typeof schemaObj !== 'object') {
        throw new Error(`Invalid schema data structure ${typeof schemaObj}`);
      }

      if (!defaultObj || typeof defaultObj !== 'object') {
        throw new Error('Invalid default configuration data structure');
      }

      setSchema(schemaObj);
      setDefaultConfig(defaultObj);
      setCustomConfig(customObj);

      // Merge default and custom configurations
      const merged = deepMerge(defaultObj, customObj);
      setMergedConfig(merged);
    } catch (err) {
      logger.error('Error fetching configuration', err);
      setError(`Failed to load configuration: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const updateConfiguration = async (newCustomConfig) => {
    setError(null);
    try {
      logger.debug('Updating config with:', newCustomConfig);

      // Ensure we're sending a JSON string
      const configString = typeof newCustomConfig === 'string' ? newCustomConfig : JSON.stringify(newCustomConfig);

      const result = await API.graphql(graphqlOperation(updateConfigurationMutation, { customConfig: configString }));

      if (result.data.updateConfiguration) {
        setCustomConfig(newCustomConfig);
        // Update merged config
        const merged = deepMerge(defaultConfig, newCustomConfig);
        setMergedConfig(merged);
        return true;
      }
      return false;
    } catch (err) {
      logger.error('Error updating configuration', err);
      setError(`Failed to update configuration: ${err.message}`);
      return false;
    }
  };

  // Reset a specific configuration path back to default
  const resetToDefault = async (path) => {
    if (!customConfig || !path) return false;

    // Create a copy of the custom config
    const newCustomConfig = { ...customConfig };

    // Split the path into segments
    const pathSegments = path.split('.');

    // Navigate to the parent object of the value to reset
    let current = newCustomConfig;
    let parent = null;
    let lastKey = null;

    pathSegments.forEach((segment, index) => {
      if (index === pathSegments.length - 1) {
        parent = current;
        lastKey = segment;
      } else if (current[segment] === undefined || current[segment] === null) {
        // Path doesn't exist in the custom config, nothing to reset
      } else {
        current = current[segment];
      }
    });

    // Remove the property from the custom config
    if (parent && lastKey) {
      delete parent[lastKey];

      // Clean up empty objects
      let cleanupPath = pathSegments.slice(0, -1);
      while (cleanupPath.length > 0) {
        const tempObj = cleanupPath.reduce(
          (acc, segment) => (acc && acc[segment] ? acc[segment] : undefined),
          newCustomConfig,
        );

        // If object is empty, remove it
        if (tempObj && Object.keys(tempObj).length === 0) {
          const parentPath = cleanupPath.slice(0, -1);
          const lastSegment = cleanupPath[cleanupPath.length - 1];

          const parentObj = parentPath.reduce(
            (acc, segment) => (acc && acc[segment] ? acc[segment] : undefined),
            newCustomConfig,
          );

          if (parentObj) {
            delete parentObj[lastSegment];
            cleanupPath = parentPath;
          } else {
            break;
          }
        } else {
          break;
        }
      }

      // Update the custom configuration
      return updateConfiguration(newCustomConfig);
    }

    return false;
  };

  // Check if a value is customized or default
  const isCustomized = (path) => {
    if (!customConfig || !path) return false;

    // Split the path into segments
    const pathSegments = path.split('.');

    // Navigate through the custom config to check if the path exists
    // Use reduce instead of for...of loop to comply with eslint
    return pathSegments.reduce((exists, segment, index, array) => {
      if (!exists || !Object.hasOwn(exists, segment)) return false;

      if (index === array.length - 1) {
        // At the last segment, check if it exists in the current object
        return exists[segment] !== undefined;
      }

      // Continue navigating if this segment exists and is an object
      return typeof exists[segment] === 'object' ? exists[segment] : false;
    }, customConfig);
  };

  useEffect(() => {
    fetchConfiguration();
  }, []);

  return {
    schema,
    defaultConfig,
    customConfig,
    mergedConfig,
    loading,
    error,
    fetchConfiguration,
    updateConfiguration,
    resetToDefault,
    isCustomized,
  };
};

export default useConfiguration;
