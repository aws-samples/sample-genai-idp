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
      console.log('Merged configuration result:', merged);
      // Double check the classification and extraction sections
      if (merged.classification) {
        console.log('Final classification data:', merged.classification);
      }
      if (merged.extraction) {
        console.log('Final extraction data:', merged.extraction);
      }
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

      // Make sure we have a valid object to update with
      const configToUpdate =
        !newCustomConfig || (typeof newCustomConfig === 'object' && Object.keys(newCustomConfig).length === 0)
          ? {} // Use empty object fallback
          : newCustomConfig;

      if (configToUpdate !== newCustomConfig) {
        logger.warn('Attempting to update with empty configuration, using {} as fallback');
      }

      // Ensure we're sending a JSON string
      const configString = typeof configToUpdate === 'string' ? configToUpdate : JSON.stringify(configToUpdate);

      logger.debug('Sending customConfig string:', configString);

      const result = await API.graphql(graphqlOperation(updateConfigurationMutation, { customConfig: configString }));

      if (result.data.updateConfiguration) {
        setCustomConfig(configToUpdate);
        // Update merged config
        const merged = deepMerge(defaultConfig, configToUpdate);
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

    // Handle both dot notation and bracket notation
    // First, normalize the path to handle array indices properly
    const normalizedPath = path.replace(/\[(\d+)\]/g, '.$1');

    // Split the path into segments and handle array indices
    let pathSegments;

    // Check if the path already contains bracket notation for arrays
    if (path.includes('[')) {
      // Use regex to split properly on both dots and brackets
      pathSegments = normalizedPath.split('.');
    } else {
      // Regular dot notation
      pathSegments = path.split('.');
    }

    // Look for any numeric segments which indicate array indices
    const arrayIndices = [];
    pathSegments.forEach((segment, index) => {
      if (/^\d+$/.test(segment)) {
        arrayIndices.push(index);
      }
    });

    // Special handling for list items using name property as a key
    if (arrayIndices.length > 0) {
      // For nested arrays, we need to handle the deepest array first
      // Get the index of the last array in the path
      const lastArrayIndex = arrayIndices[arrayIndices.length - 1];

      // Build the path to the parent array of the item we want to reset
      const arrayPath = pathSegments.slice(0, lastArrayIndex).join('.');

      // Get the array item index
      const itemIndex = parseInt(pathSegments[lastArrayIndex], 10);

      // Check if this is a property of an array item
      const isItemProperty = pathSegments.length > lastArrayIndex + 1;

      // Get the property name if this is an item property
      const propertyName = isItemProperty ? pathSegments[lastArrayIndex + 1] : null;

      // For debugging
      logger.debug(`Handling nested array. Full path: ${path}`);
      logger.debug(`Array path: ${arrayPath}, item index: ${itemIndex}, property: ${propertyName || 'none'}`);
      logger.debug(`Array indices in path: ${arrayIndices.join(', ')}`);
      logger.debug(`Last array index position: ${lastArrayIndex}`);

      logger.debug(`Detected array path: ${arrayPath}, index: ${itemIndex}, property: ${propertyName || 'none'}`);

      // Helper function to get value at a path
      const getValueAtPath = (obj, pathStr) => {
        if (!pathStr) return obj;
        return pathStr.split('.').reduce((acc, part) => {
          if (acc === undefined || acc === null) return undefined;
          return acc[part];
        }, obj);
      };

      // Helper function to set value at a path
      const setValueAtPath = (obj, pathStr, value) => {
        if (!pathStr) return false;

        const parts = pathStr.split('.');
        let current = obj;

        // Navigate to the parent object
        for (let i = 0; i < parts.length - 1; i += 1) {
          const part = parts[i];
          if (current[part] === undefined) {
            current[part] = {};
          }
          current = current[part];
        }

        // Set the value
        current[parts[parts.length - 1]] = value;
        return true;
      };

      const customArray = getValueAtPath(customConfig, arrayPath);
      const defaultArray = getValueAtPath(defaultConfig, arrayPath);

      // Check if both arrays exist
      if (Array.isArray(customArray) && Array.isArray(defaultArray)) {
        // Get current array in our modified copy
        let customArrayInNew = getValueAtPath(newCustomConfig, arrayPath);

        // If the array doesn't exist in our copy or is no longer an array, recreate it
        if (!Array.isArray(customArrayInNew)) {
          logger.debug(`Array at ${arrayPath} doesn't exist in the copy. Creating it.`);
          setValueAtPath(newCustomConfig, arrayPath, [...customArray]);
          customArrayInNew = getValueAtPath(newCustomConfig, arrayPath);
        }

        // If the property being reset is 'name', handle differently
        if (propertyName === 'name') {
          // Case 1: Name was modified - consider it a new item
          // Get the current item's name (before reset)
          const currentItemName = customArray[itemIndex]?.name;
          const defaultValue = customArray[itemIndex]
            ? defaultArray.find((item) => JSON.stringify(item) === JSON.stringify(customArray[itemIndex]))?.name
            : null;

          logger.debug(`Resetting name property. Current: ${currentItemName}, Default: ${defaultValue}`);

          if (currentItemName) {
            if (defaultValue) {
              // This was a renamed existing item - restore original name
              logger.debug(`Restoring original name: ${defaultValue}`);
              customArrayInNew[itemIndex].name = defaultValue;
            } else {
              // This is a new item that doesn't exist in defaults - remove it
              logger.debug(`Removing new item with name: ${currentItemName}`);
              customArrayInNew.splice(itemIndex, 1);
            }
          }
        } else if (propertyName) {
          // Case 2: Regular property modification of an array item

          // Find the item by looking at its name
          const currentItemName = customArray[itemIndex]?.name;

          if (currentItemName) {
            // Find matching default item by name
            const matchingDefaultItem = defaultArray.find((item) => item.name === currentItemName);

            if (matchingDefaultItem) {
              // Reset only the specified property to its default value
              logger.debug(`Resetting property ${propertyName} for item with name: ${currentItemName}`);

              if (matchingDefaultItem[propertyName] !== undefined) {
                // Set to default value
                customArrayInNew[itemIndex][propertyName] = matchingDefaultItem[propertyName];
              } else {
                // Property doesn't exist in default - remove it
                delete customArrayInNew[itemIndex][propertyName];
              }
            } else {
              // No matching default - this is a completely new item
              // For new items, just delete the property if it's not 'name'
              logger.debug(`No matching default found. Removing property: ${propertyName}`);
              delete customArrayInNew[itemIndex][propertyName];
            }
          }
        } else {
          // Case 3: Resetting an entire array item (not a specific property)
          const currentItemName = customArray[itemIndex]?.name;

          if (currentItemName) {
            // Find the matching default item by name
            const matchingDefaultItem = defaultArray.find((item) => item.name === currentItemName);

            if (matchingDefaultItem) {
              // Replace with default values
              logger.debug(`Resetting entire item with name: ${currentItemName}`);
              customArrayInNew[itemIndex] = { ...matchingDefaultItem };
            } else {
              // No matching default - this is a new item, remove it
              logger.debug(`No matching default found. Removing item: ${currentItemName}`);
              customArrayInNew.splice(itemIndex, 1);
            }
          }
        }

        // Check if this is a nested array (within another array)
        const isNestedArray = arrayPath.includes('.') && /\d+/.test(arrayPath);

        // For nested arrays, ONLY reset the specific property requested - NEVER remove the item
        if (isNestedArray) {
          logger.debug(`This is a nested array. Using minimal targeted reset.`);

          // If we have a property name and the item exists in our array
          if (propertyName && customArrayInNew[itemIndex]) {
            const currentItemName = customArrayInNew[itemIndex].name;
            const matchingDefaultItem = defaultArray.find((item) => item.name === currentItemName);

            if (matchingDefaultItem && matchingDefaultItem[propertyName] !== undefined) {
              logger.debug(`Resetting property '${propertyName}' to default value for item '${currentItemName}'`);

              // Simply restore the default value for this property - don't delete anything
              customArrayInNew[itemIndex][propertyName] = JSON.parse(JSON.stringify(matchingDefaultItem[propertyName]));

              logger.debug(
                `Property has been reset, but item is preserved: ${JSON.stringify(customArrayInNew[itemIndex])}`,
              );
            } else {
              logger.debug(
                `No matching default found for property '${propertyName}' in item '${currentItemName}'. Keeping current value.`,
              );
              // Do nothing - we want to keep the current value
            }
          } else {
            logger.debug(`No property name or item not found. Skipping reset for nested array item.`);
          }
        }
        // For top-level arrays, we can be more aggressive with cleanup
        else if (JSON.stringify(getValueAtPath(newCustomConfig, arrayPath)) === JSON.stringify(defaultArray)) {
          logger.debug(`Array at ${arrayPath} now matches default. Removing customization.`);

          // Navigate to the parent of array and remove the array
          const arrayPathSegments = arrayPath.split('.');
          let current = newCustomConfig;
          let arrayParent = null;
          let arrayKey = null;

          arrayPathSegments.forEach((segment, index) => {
            if (index === arrayPathSegments.length - 1) {
              arrayParent = current;
              arrayKey = segment;
            } else if (current[segment] !== undefined) {
              current = current[segment];
            }
          });

          if (arrayParent && arrayKey) {
            delete arrayParent[arrayKey];
          }
        }

        // Update configuration
        logger.debug('Custom config after reset:', JSON.stringify(newCustomConfig));
        return updateConfiguration(newCustomConfig);
      }

      // Fallback to original behavior if special handling doesn't apply
      logger.debug(`Fallback: Resetting array at path: ${arrayPath}`);
      if (arrayPath) {
        // Only reset entire array if we can't handle it more granularly
        return resetToDefault(arrayPath);
      }
    }

    // Handle non-array paths normally
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
      logger.debug(`Removing customization at path: ${path}, key: ${lastKey}`);
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

      // For debugging
      logger.debug('Custom config after reset:', JSON.stringify(newCustomConfig));

      // Update the custom configuration
      return updateConfiguration(newCustomConfig);
    }

    return false;
  };

  // Check if a value is customized or default
  const isCustomized = (path) => {
    if (!customConfig || !path) {
      return false;
    }

    try {
      // Split the path into segments, handling array indices properly
      const pathSegments = path.split(/[.[\]]+/).filter(Boolean);

      // Helper function to get value at path for comparison
      const getValueAtPath = (obj, segments) => {
        return segments.reduce((acc, segment) => {
          if (acc === null || acc === undefined || !Object.hasOwn(acc, segment)) {
            return undefined;
          }
          return acc[segment];
        }, obj);
      };

      // Get values from both custom and default configs
      const customValue = getValueAtPath(customConfig, pathSegments);
      const defaultValue = getValueAtPath(defaultConfig, pathSegments);

      // First check if the custom value exists
      const customValueExists = customValue !== undefined;

      // Special case for empty objects - they should count as not customized
      if (
        customValueExists &&
        typeof customValue === 'object' &&
        customValue !== null &&
        !Array.isArray(customValue) &&
        Object.keys(customValue).length === 0
      ) {
        return false;
      }

      // Special case for arrays
      if (customValueExists && Array.isArray(customValue)) {
        if (customValue.length === 0) return false; // Empty arrays aren't considered customized

        // Compare arrays for deep equality
        if (Array.isArray(defaultValue)) {
          // Different lengths means customized
          if (customValue.length !== defaultValue.length) return true;

          // Deep compare each element
          for (let i = 0; i < customValue.length; i += 1) {
            if (JSON.stringify(customValue[i]) !== JSON.stringify(defaultValue[i])) {
              return true;
            }
          }
          return false; // Arrays are identical
        }
        return true; // Custom is array, default isn't or is undefined
      }

      // Deep compare objects
      if (
        customValueExists &&
        typeof customValue === 'object' &&
        customValue !== null &&
        typeof defaultValue === 'object' &&
        defaultValue !== null
      ) {
        return JSON.stringify(customValue) !== JSON.stringify(defaultValue);
      }

      // Simple value comparison
      return customValueExists && customValue !== defaultValue;
    } catch (err) {
      logger.error(`Error in isCustomized for path: ${path}`, err);
      return false;
    }
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
