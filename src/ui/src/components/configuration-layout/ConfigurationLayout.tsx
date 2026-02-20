// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Button,
  Alert,
  Spinner,
  Form,
  SegmentedControl,
  Modal,
  FormField,
  Input,
  RadioGroup,
  ExpandableSection,
  Icon,
} from '@cloudscape-design/components';
import Editor from '@monaco-editor/react';
// eslint-disable-next-line import/no-extraneous-dependencies
import yaml from 'js-yaml';
import ReactMarkdown from 'react-markdown';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import useConfiguration from '../../hooks/use-configuration';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import useConfigurationLibrary from '../../hooks/use-configuration-library';
import useSettingsContext from '../../contexts/settings';
import ConfigBuilder from './ConfigBuilder';
import ConfigurationVersionsTable from './ConfigurationVersionsTable';
import ConfigurationComparison from './ConfigurationComparison';
import { deepMerge } from '../../utils/configUtils';
import syncBdaIdpMutation from '../../graphql/queries/syncBdaIdp';

const client = generateClient();
const logger = new ConsoleLogger('ConfigurationLayout');

// Utility function to normalize boolean values from strings (same as use-configuration.js)
interface SchemaProperty {
  type?: string;
  properties?: Record<string, SchemaProperty>;
  items?: SchemaProperty;
}

interface ConfigSchema {
  properties?: Record<string, SchemaProperty>;
  [key: string]: unknown;
}

interface LibraryConfigItem {
  name: string;
  description?: string;
  readme?: string;
  config?: Record<string, unknown>;
  hasReadme?: boolean;
  path?: string;
  configFileType?: string;
  [key: string]: unknown;
}

const normalizeBooleans = (
  obj: Record<string, unknown> | null | undefined,
  schema: ConfigSchema | null | undefined,
): Record<string, unknown> | null | undefined => {
  if (!obj || !schema) return obj;

  const normalizeValue = (value: unknown, propertySchema: SchemaProperty | undefined): unknown => {
    if (propertySchema?.type === 'boolean') {
      if (typeof value === 'string') {
        if (value.toLowerCase() === 'true') return true;
        if (value.toLowerCase() === 'false') return false;
      }
      return value;
    }

    if (value && typeof value === 'object' && !Array.isArray(value) && propertySchema?.properties) {
      const normalized = { ...value };
      Object.keys(normalized).forEach((key) => {
        if (propertySchema.properties[key]) {
          normalized[key] = normalizeValue(normalized[key], propertySchema.properties[key]);
        }
      });
      return normalized;
    }

    if (Array.isArray(value) && propertySchema?.items) {
      return value.map((item) => normalizeValue(item, propertySchema.items));
    }

    return value;
  };

  const normalized = { ...obj };
  if (schema.properties) {
    Object.keys(normalized).forEach((key) => {
      if (schema.properties[key]) {
        normalized[key] = normalizeValue(normalized[key], schema.properties[key]);
      }
    });
  }
  return normalized;
};

// Utility function to check if two values are numerically equivalent
// Handles cases where 5 and 5.0, or "5" and 5 should be considered equal
const areNumericValuesEqual = (val1: unknown, val2: unknown): boolean => {
  // If both are numbers, direct comparison
  if (typeof val1 === 'number' && typeof val2 === 'number') {
    return val1 === val2;
  }

  // Try to parse both as numbers
  const num1 = typeof val1 === 'number' ? val1 : parseFloat(String(val1));
  const num2 = typeof val2 === 'number' ? val2 : parseFloat(String(val2));

  // Both must be valid numbers for numeric comparison
  if (!Number.isNaN(num1) && !Number.isNaN(num2)) {
    return num1 === num2;
  }

  return false;
};

// Check if a value could be interpreted as a number
const isNumericValue = (val: unknown): boolean => {
  if (typeof val === 'number') return true;
  if (typeof val === 'string' && val.trim() !== '') {
    return !Number.isNaN(parseFloat(val)) && isFinite(Number(val));
  }
  return false;
};

const ConfigurationLayout = (): React.JSX.Element => {
  // Version selection state - declare first
  const [selectedVersionsForCompare, setSelectedVersionsForCompare] = useState<string[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [versionsTableExpanded, setVersionsTableExpanded] = useState(false);

  // Import as new version state
  const [importedConfigForNewVersion, setImportedConfigForNewVersion] = useState<Record<string, unknown> | null>(null);
  const [newVersionName, setNewVersionName] = useState('');
  const [newVersionDescription, setNewVersionDescription] = useState('');
  const [importSource, setImportSource] = useState<string | null>(null); // Track import source: 'file', 'library', 'migration'

  // Configuration Library state
  const [showLibraryBrowserModal, setShowLibraryBrowserModal] = useState(false);
  const [showReadmeModal, setShowReadmeModal] = useState(false);
  const [libraryConfigs, setLibraryConfigs] = useState<LibraryConfigItem[]>([]);
  const [selectedLibraryConfig, setSelectedLibraryConfig] = useState<LibraryConfigItem | null>(null);
  const [readmeContent, setReadmeContent] = useState('');
  const [libraryLoading, setLibraryLoading] = useState(false);

  // Add versions hook for the table
  const {
    versions,
    loading: versionsLoading,
    fetchVersions,
    fetchVersion,
    setActiveVersion,
    deleteVersion,
    saveAsNewVersion,
  } = useConfigurationVersions();

  // Get active version name
  const activeVersionName = useMemo(() => {
    const activeVersion = versions.find((v) => v.isActive);
    return activeVersion?.versionName || 'default';
  }, [versions]);

  // Version description state
  const currentVersionName = selectedVersion || activeVersionName;
  const currentVersion = versions.find((v) => v.versionName === currentVersionName);
  const [versionDescription, setVersionDescription] = useState(currentVersion?.description || '');

  // Update description when version changes
  useEffect(() => {
    setVersionDescription(currentVersion?.description || '');
    setExportFileName(currentVersionName || 'configuration'); // Update export filename when version changes
  }, [currentVersion?.description, currentVersionName]);

  // Handle URL query parameter for version selection
  useEffect(() => {
    // For hash routing, get parameters from the hash part
    const hash = window.location.hash;
    const urlParams = new URLSearchParams(hash.split('?')[1] || '');
    const versionParam = urlParams.get('version');

    if (versionParam && versions.length > 0 && !selectedVersion) {
      const versionExists = versions.some((v) => v.versionName === versionParam);
      if (versionExists) {
        setSelectedVersion(versionParam);
      }
    }
  }, [versions, selectedVersion]);

  const {
    schema,
    mergedConfig,
    defaultConfig,
    customConfig,
    loading,
    refreshing,
    error,
    updateConfiguration,
    fetchConfiguration,
    isCustomized,
    resetToDefault,
  } = useConfiguration(selectedVersion || activeVersionName); // Pass version to hook

  // Handle version selection
  const handleVersionSelect = async (versionName: string): Promise<void> => {
    logger.info('Selecting version:', versionName);
    setSelectedVersion(versionName);
    await fetchConfiguration(versionName); // Load selected version data into form
  };

  // Handle version selection for comparison
  const handleVersionSelectForCompare = (versionName: string, selected: boolean): void => {
    if (selected) {
      setSelectedVersionsForCompare((prev) => [...prev, versionName]);
    } else {
      setSelectedVersionsForCompare((prev) => prev.filter((v) => v !== versionName));
    }
  };

  // Version comparison state
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [compareData, setCompareData] = useState<{ versions: string[]; configs: Record<string, Record<string, unknown>> } | null>(null);
  const [_comparingVersions, setComparingVersions] = useState(false);

  // Handle version comparison
  const handleCompareVersions = async () => {
    if (selectedVersionsForCompare.length < 2) return;

    setComparingVersions(true);
    try {
      // Fetch raw configurations and merge them using same logic as fetchConfiguration
      const configPromises = selectedVersionsForCompare.map(async (versionName) => {
        const rawConfig = await fetchVersion(versionName);

        // Parse the configs (same logic as fetchConfiguration)
        let schemaObj = rawConfig.schema;
        let defaultObj = rawConfig.default;
        let customObj = rawConfig.custom;

        // Parse schema if it's a string
        if (typeof rawConfig.schema === 'string') {
          schemaObj = JSON.parse(rawConfig.schema);
        }

        // Unwrap nested Schema object if present
        if (schemaObj && (schemaObj as Record<string, unknown>).Schema) {
          schemaObj = (schemaObj as Record<string, unknown>).Schema;
        }

        // Parse default config if it's a string
        if (typeof rawConfig.default === 'string') {
          defaultObj = JSON.parse(rawConfig.default);
        }

        // Parse custom config if it's a string
        if (typeof rawConfig.custom === 'string' && rawConfig.custom) {
          customObj = JSON.parse(rawConfig.custom);
        } else if (!rawConfig.custom) {
          customObj = {};
        }

        // Normalize boolean values (same as fetchConfiguration)
        const normalizedDefaultObj = normalizeBooleans(defaultObj as Record<string, unknown>, schemaObj as ConfigSchema);
        const normalizedCustomObj = normalizeBooleans(customObj as Record<string, unknown>, schemaObj as ConfigSchema);

        // Return merged config (same as fetchConfiguration)
        return deepMerge(normalizedDefaultObj, normalizedCustomObj);
      });

      const configs = await Promise.all(configPromises);

      // Create comparison data
      const comparisonData = {
        versions: selectedVersionsForCompare,
        configs: configs.reduce<Record<string, Record<string, unknown>>>((acc, config, index) => {
          acc[selectedVersionsForCompare[index]] = config as Record<string, unknown>;
          return acc;
        }, {}),
      };

      setCompareData(comparisonData);
      setShowCompareModal(true);
    } catch (err) {
      console.error('Failed to fetch configurations for comparison:', err);
    } finally {
      setComparingVersions(false);
    }
  };

  // Handle activate version
  const handleActivateVersion = async (versionName: string, skipSyncConfirmation = false): Promise<void> => {
    // Validate versionName
    if (!versionName) {
      console.error('Cannot activate version: versionName is null or undefined');
      return;
    }

    // Check if Pattern 1 and show confirmation for auto-sync to BDA (unless skipping)
    if (isPattern1 && !skipSyncConfirmation) {
      setShowActivateVersionConfirmModal(true);
      return;
    }

    // Direct activation for non-Pattern 1 or when skipping confirmation
    await performActivateVersion(versionName);
  };

  // Perform the actual activation
  const performActivateVersion = async (versionName: string): Promise<void> => {
    if (!versionName) {
      console.error('Cannot activate version: versionName is null or undefined');
      return;
    }

    try {
      await setActiveVersion(versionName);

      // Small delay to ensure backend consistency before fetching config
      await new Promise((resolve) => setTimeout(resolve, 500));

      setSelectedVersion(versionName); // Select the activated version (useEffect will fetch config)
    } catch (err) {
      console.error('Failed to activate version:', err);
    }
  };

  // Perform sync to BDA then activate version
  const performSyncThenActivate = async (versionName: string): Promise<void> => {
    if (!versionName) {
      console.error('Cannot sync and activate: versionName is null or undefined');
      return;
    }

    try {
      // First sync to BDA
      await handleSyncBdaIdp('idp_to_bda');
      logger.debug(`Synced to BDA before activating version ${versionName}`);

      // Then activate the version (but don't sync again since we just did)
      await setActiveVersion(versionName);
      await new Promise((resolve) => setTimeout(resolve, 500));
      setSelectedVersion(versionName);
    } catch (err) {
      console.error('Failed to sync and activate version:', err);
    }
  };

  // Handle import as new version
  const handleImportAsNewVersion = () => {
    setImportError(null); // Clear any previous errors
    setShowImportSourceModal(true);
  };

  // Handle creating new version from imported config
  const handleCreateVersionFromImport = async () => {
    if (!importedConfigForNewVersion) {
      return;
    }

    try {
      const versionName = newVersionName.trim() || 'New imported version';
      const description = newVersionDescription.trim();

      logger.info(`Creating version from ${importSource || 'unknown'}: ${versionName} with description: "${description}"`);
      logger.info('Version creation params:', { versionName, description, hasConfig: !!importedConfigForNewVersion });

      const result = await saveAsNewVersion(importedConfigForNewVersion, versionName, description);

      if (!result.success) {
        setImportError(result.error || 'Failed to create version from import');
        return;
      }

      // Small delay to ensure backend consistency before fetching
      await new Promise((resolve) => setTimeout(resolve, 500));

      setSelectedVersion(versionName); // Highlight the new version in table
      await fetchVersions();
      logger.info(`Version ${versionName} created successfully from ${importSource}`);

      // Force close modal after all operations complete
      setImportedConfigForNewVersion(null);
      setImportSource(null);
      setNewVersionName('');
      setNewVersionDescription('');
      setShowImportSourceModal(false); // Also close import source modal
    } catch (err) {
      logger.error('Create version error:', err);
      console.error('Create version error:', err);
    }
  };

  // Handle delete versions
  const handleDeleteVersions = async (versionNames: string[]): Promise<void> => {
    try {
      for (const versionName of versionNames) {
        await deleteVersion(versionName, true); // Skip individual refresh
      }
      await fetchVersions(); // Single refresh after all deletions
      setSelectedVersionsForCompare([]); // Clear selection

      // If currently selected version was deleted, clear selection
      if (selectedVersion && versionNames.includes(selectedVersion)) {
        setSelectedVersion(null);
      }
    } catch (err) {
      console.error('Failed to delete versions:', err);
    }
  };

  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [jsonContent, setJsonContent] = useState('');
  const [yamlContent, setYamlContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [importSuccess, setImportSuccess] = useState(false);
  const [validationErrors, setValidationErrors] = useState<{ message: string; path?: string }[]>([]);
  const [viewMode, setViewMode] = useState('form'); // Form view as default
  const [showResetModal, setShowResetModal] = useState(false);
  const [showSaveAsDefaultModal, setShowSaveAsDefaultModal] = useState(false);
  const [showSaveAsVersionModal, setShowSaveAsVersionModal] = useState(false);
  const [saveAsVersionName, setSaveAsVersionName] = useState('');
  const [saveAsVersionDescription, setSaveAsVersionDescription] = useState('');
  const [saveAsVersionError, setSaveAsVersionError] = useState<string | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportFormat, setExportFormat] = useState('json');
  const [exportFileName, setExportFileName] = useState(currentVersionName || 'configuration');
  const [importError, setImportError] = useState<string | null>(null);
  const [extractionSchema, setExtractionSchema] = useState<unknown[] | null>(null);
  const [ruleSchema, setRuleSchema] = useState<unknown[] | null>(null);
  const [showMigrationModal, setShowMigrationModal] = useState(false);
  const [pendingImportConfig, setPendingImportConfig] = useState<Record<string, unknown> | null>(null);
  const [pendingImportSource, setPendingImportSource] = useState<{ type: string; name: string } | null>(null); // Track import source for version naming

  // Configuration Library state
  const [showImportSourceModal, setShowImportSourceModal] = useState(false);

  // ConfigBuilder tab state - lifted up to preserve across refreshes
  const [configBuilderActiveTab, setConfigBuilderActiveTab] = useState('configuration');

  // BDA/IDP Sync state
  const [syncingDirection, setSyncingDirection] = useState<string | null>(null); // Track which sync is running
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [syncSuccessMessage, setSyncSuccessMessage] = useState('');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [showSyncToBdaConfirmModal, setShowSyncToBdaConfirmModal] = useState(false);
  const [showActivateVersionConfirmModal, setShowActivateVersionConfirmModal] = useState(false);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editorRef = useRef<any>(null);

  // Compute whether there are unsaved changes by comparing formValues with mergedConfig
  const hasUnsavedChanges = useMemo(() => {
    if (!mergedConfig || !formValues || Object.keys(formValues).length === 0) {
      return false;
    }
    // Check if form values changed
    const formChanged = JSON.stringify(formValues) !== JSON.stringify(mergedConfig);
    // Check if version description changed
    const descriptionChanged = versionDescription !== (currentVersion?.description || '');

    return formChanged || descriptionChanged;
  }, [formValues, mergedConfig, versionDescription, currentVersion?.description]);

  // Warn user before leaving page with unsaved changes
  // Both beforeunload (browser close/refresh) and hashchange (SPA navigation)
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent): void => {
      if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    const handleHashChange = (): void => {
      // For SPA hash-based routing, intercept navigation when there are unsaved changes
      if (hasUnsavedChanges) {
        // eslint-disable-next-line no-alert
        const confirmed = window.confirm('You have unsaved configuration changes. Are you sure you want to leave?');
        if (!confirmed) {
          // Restore the hash to the config page
          window.history.pushState(null, '', `${window.location.pathname}#/documents/config`);
        }
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('hashchange', handleHashChange);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('hashchange', handleHashChange);
    };
  }, [hasUnsavedChanges]);

  // Discard unsaved changes by re-loading the current config from server
  const handleDiscardChanges = useCallback(async () => {
    await fetchConfiguration(currentVersionName, false);
    setVersionDescription(currentVersion?.description || '');
  }, [currentVersionName, currentVersion?.description, fetchConfiguration]);

  // Hooks for configuration library
  const { listConfigurations, getFile } = useConfigurationLibrary();
  const settingsContext = useSettingsContext() as Record<string, unknown> | null;
  const settings = settingsContext?.settings as Record<string, unknown> | undefined;

  // Helper function to map IDPPattern to directory name
  const getPatternDirectory = (idpPattern: string | undefined): string | null => {
    if (!idpPattern) return null;

    // Extract pattern number from string like "Pattern1 - Description" or "Pattern2 - Description"
    const match = idpPattern.match(/Pattern(\d+)/i);
    if (match) {
      return `pattern-${match[1]}`;
    }

    return null;
  };

  // Helper function to detect legacy format
  const isLegacyFormat = (config: Record<string, unknown>): boolean => {
    if (!config || !config.classes || !Array.isArray(config.classes)) return false;
    if (config.classes.length === 0) return false;

    // Check if first class has legacy attributes format (array instead of object with properties)
    const firstClass = config.classes[0];
    return firstClass.attributes && Array.isArray(firstClass.attributes);
  };

  // Helper function to check if Pattern-1 is selected
  const isPattern1 = (settings?.IDPPattern as string | undefined)?.includes('Pattern1');

  // Helper function to check if Pattern-2 is selected (for Rule Schema feature)
  const isPattern2 = (settings?.IDPPattern as string | undefined)?.includes('Pattern2');

  // Initialize form values from merged config
  useEffect(() => {
    if (mergedConfig) {
      console.log('Setting form values from mergedConfig:', mergedConfig);

      // Make a deep copy to ensure we're not dealing with references
      // Clear schemas first to ensure clean state
      setExtractionSchema(null);
      setRuleSchema(null);

      // Switch to configuration tab when version changes to avoid stale schema display
      setConfigBuilderActiveTab('configuration');

      const formData = JSON.parse(JSON.stringify(mergedConfig));
      setFormValues(formData);

      // Initialize extraction schema from config (stored in classes field)
      if (mergedConfig.classes) {
        setExtractionSchema(mergedConfig.classes as unknown[]);
      }

      // Initialize rule schema from config (stored in rule_classes field)
      if (mergedConfig.rule_classes) {
        setRuleSchema(mergedConfig.rule_classes as unknown[]);
      }

      // Set both JSON and YAML content
      const jsonString = JSON.stringify(mergedConfig, null, 2);
      setJsonContent(jsonString);

      try {
        const yamlString = yaml.dump(mergedConfig);
        setYamlContent(yamlString);
      } catch (e) {
        console.error('Error converting to YAML:', e);
        setYamlContent('# Error converting to YAML');
      }
    }
  }, [mergedConfig]);

  // Process schema to convert custom types to standard JSON Schema format
  const processSchema = (inputSchema: Record<string, unknown>): Record<string, unknown> | null => {
    try {
      const processedSchema = {
        type: 'object',
        properties: {},
        required: inputSchema.required || [],
      };

      // Process schema properties to handle custom types like 'list'
      if (inputSchema.properties) {
        Object.entries(inputSchema.properties as Record<string, Record<string, unknown>>).forEach(([key, prop]) => {
          // Convert 'list' type to proper JSON Schema array type (for backwards compatibility)
          if (prop.type === 'list' || prop.type === 'array') {
            processedSchema.properties[key] = {
              type: 'array',
              items: (prop.items as Record<string, unknown>) || {},
            };

            // Process nested items if they have custom types
            const items = prop.items as Record<string, unknown> | undefined;
            if (items && items.type === 'object' && items.properties) {
              const itemProps: Record<string, Record<string, unknown>> = {};
              Object.entries(items.properties as Record<string, Record<string, unknown>>).forEach(([itemKey, itemProp]) => {
                if (itemProp.type === 'list' || itemProp.type === 'array') {
                  itemProps[itemKey] = {
                    type: 'array',
                    items: (itemProp.items as Record<string, unknown>) || {},
                  };
                } else if (itemProp.type === 'number' || itemProp.type === 'integer') {
                  // For number types, we'll use a more flexible approach
                  // Instead of using oneOf, we'll just use type: ["number", "string"]
                  // This is more widely supported in JSON Schema implementations
                  itemProps[itemKey] = {
                    type: ['number', 'string'],
                  };

                  // Copy over any constraints
                  if (itemProp.minimum !== undefined) {
                    itemProps[itemKey].minimum = itemProp.minimum;
                  }
                  if (itemProp.maximum !== undefined) {
                    itemProps[itemKey].maximum = itemProp.maximum;
                  }
                } else {
                  itemProps[itemKey] = itemProp;
                }
              });
              processedSchema.properties[key].items.properties = itemProps;
              processedSchema.properties[key].items.required = (items as Record<string, unknown>).required || [];
            }
          } else if (prop.type === 'number' || prop.type === 'integer') {
            // For number types, we'll use a more flexible approach
            // Instead of using oneOf, we'll just use type: ["number", "string"]
            // This is more widely supported in JSON Schema implementations
            processedSchema.properties[key] = {
              type: ['number', 'string'],
            };

            // Copy over any constraints
            if (prop.minimum !== undefined) {
              processedSchema.properties[key].minimum = prop.minimum;
            }
            if (prop.maximum !== undefined) {
              processedSchema.properties[key].maximum = prop.maximum;
            }
          } else {
            // For non-list types, keep the original schema
            processedSchema.properties[key] = prop;
          }
        });
      }

      return processedSchema;
    } catch (e) {
      console.error('Error processing schema:', e);
      return null;
    }
  };

  // Validate YAML content against the schema
  const validateYamlContent = (yamlString: string): { message: string }[] => {
    if (!schema) return [];

    try {
      // Convert YAML to JSON object
      const parsedYaml = yaml.load(yamlString);
      if (!parsedYaml) return [{ message: 'Empty or invalid YAML content' }];

      // Perform schema validation manually
      const errors = [];

      // Check required fields
      if (schema.required) {
        (schema.required as string[]).forEach((field) => {
          if ((parsedYaml as Record<string, unknown>)[field] === undefined) {
            errors.push({ message: `Required field '${field}' is missing` });
          }
        });
      }

      // Validate property types and constraints
      if (schema.properties && parsedYaml) {
        Object.entries(schema.properties as Record<string, Record<string, unknown>>).forEach(([key, prop]) => {
          const value = (parsedYaml as Record<string, unknown>)[key];

          // Skip validation if value is undefined (already handled by required check)
          if (value === undefined) return;

          // Skip deep validation for classes and rule_classes fields - they have their own complex JSON Schema structure
          // Just check they're arrays if present
          if (key === 'classes' || key === 'rule_classes') {
            if (!Array.isArray(value)) {
              errors.push({ message: `Field '${key}' must be an array` });
            }
            return;
          }

          // Type validation
          if (prop.type === 'number' || prop.type === 'integer') {
            // For YAML validation, we'll be more permissive
            // We'll accept any string or number, but we'll still validate constraints
            // if the value can be converted to a number
            if (typeof value !== 'number' && typeof value !== 'string') {
              errors.push({ message: `Field '${key}' must be a number or a string` });
            } else {
              // Try to convert to number for constraint validation
              let numValue;
              let isValidNumber = false;

              if (typeof value === 'number') {
                numValue = value;
                isValidNumber = true;
              } else if (typeof value === 'string') {
                // Try to parse the string as a number
                numValue = parseFloat(value);
                isValidNumber = !Number.isNaN(numValue) && /^-?\d*\.?\d*$/.test(value);
              }

              // Only check constraints if it's a valid number
              if (isValidNumber) {
                if (prop.minimum !== undefined && numValue < Number(prop.minimum)) {
                  errors.push({ message: `Field '${key}' must be at least ${prop.minimum}` });
                }
                if (prop.maximum !== undefined && numValue > Number(prop.maximum)) {
                  errors.push({ message: `Field '${key}' must be at most ${prop.maximum}` });
                }
              }
            }
          } else if (prop.type === 'string') {
            if (typeof value !== 'string') {
              errors.push({ message: `Field '${key}' must be a string` });
            } else {
              // Check string constraints
              if (prop.minLength !== undefined && value.length < Number(prop.minLength)) {
                errors.push({ message: `Field '${key}' must be at least ${prop.minLength} characters` });
              }
              if (prop.maxLength !== undefined && value.length > Number(prop.maxLength)) {
                errors.push({ message: `Field '${key}' must be at most ${prop.maxLength} characters` });
              }
              if (prop.pattern && !new RegExp(String(prop.pattern)).test(value)) {
                errors.push({ message: `Field '${key}' does not match required pattern` });
              }
            }
          } else if (prop.type === 'boolean') {
            if (typeof value !== 'boolean') {
              errors.push({ message: `Field '${key}' must be a boolean` });
            }
          } else if (prop.type === 'array' || prop.type === 'list') {
            if (!Array.isArray(value)) {
              errors.push({ message: `Field '${key}' must be an array` });
            } else {
              // Check array constraints
              if (prop.minItems !== undefined && value.length < Number(prop.minItems)) {
                errors.push({ message: `Field '${key}' must have at least ${prop.minItems} items` });
              }
              if (prop.maxItems !== undefined && value.length > Number(prop.maxItems)) {
                errors.push({ message: `Field '${key}' must have at most ${prop.maxItems} items` });
              }

              // Validate array items if schema is provided
              const propItems = prop.items as Record<string, unknown> | undefined;
              if (propItems && propItems.type && value.length > 0) {
                value.forEach((item, index) => {
                  if (propItems.type === 'object' && propItems.properties) {
                    // Validate object properties in array items
                    Object.entries(propItems.properties as Record<string, Record<string, unknown>>).forEach(([itemKey, itemProp]) => {
                      const itemValue = (item as Record<string, unknown>)[itemKey];

                      // Check if required
                      if (propItems.required && (propItems.required as string[]).includes(itemKey) && itemValue === undefined) {
                        errors.push({ message: `Item ${index} in '${key}' is missing required field '${itemKey}'` });
                      }

                      // Type validation for item properties
                      if (itemValue !== undefined) {
                        if (itemProp.type === 'string' && typeof itemValue !== 'string') {
                          errors.push({ message: `Field '${itemKey}' in item ${index} of '${key}' must be a string` });
                        } else if (itemProp.type === 'number' || itemProp.type === 'integer') {
                          // For YAML validation, we'll be more permissive
                          if (typeof itemValue !== 'number' && typeof itemValue !== 'string') {
                            errors.push({
                              message: `Field '${itemKey}' in item ${index} of '${key}' must be a number or a string`,
                            });
                          } else {
                            // Try to convert to number for constraint validation
                            let numValue;
                            let isValidNumber = false;

                            if (typeof itemValue === 'number') {
                              numValue = itemValue;
                              isValidNumber = true;
                            } else if (typeof itemValue === 'string') {
                              // Try to parse the string as a number
                              numValue = parseFloat(itemValue);
                              isValidNumber = !Number.isNaN(numValue) && /^-?\d*\.?\d*$/.test(itemValue);
                            }

                            // Only check constraints if it's a valid number
                            if (isValidNumber && itemProp.minimum !== undefined && numValue < itemProp.minimum) {
                              errors.push({
                                message: `Field '${itemKey}' in item ${index} of '${key}' must be ` + `at least ${itemProp.minimum}`,
                              });
                            }
                            if (isValidNumber && itemProp.maximum !== undefined && numValue > itemProp.maximum) {
                              errors.push({
                                message: `Field '${itemKey}' in item ${index} of '${key}' must be ` + `at most ${itemProp.maximum}`,
                              });
                            }
                          }
                        } else if (itemProp.type === 'boolean' && typeof itemValue !== 'boolean') {
                          errors.push({ message: `Field '${itemKey}' in item ${index} of '${key}' must be a boolean` });
                        }
                      }
                    });
                  } else if (propItems.type === 'string' && typeof item !== 'string') {
                    errors.push({ message: `Item ${index} in '${key}' must be a string` });
                  } else if (propItems.type === 'number' || propItems.type === 'integer') {
                    // For YAML validation, we'll be more permissive
                    if (typeof item !== 'number' && typeof item !== 'string') {
                      errors.push({
                        message: `Item ${index} in '${key}' must be a number or a string`,
                      });
                    } else {
                      // Try to convert to number for constraint validation
                      let numValue;
                      let isValidNumber = false;

                      if (typeof item === 'number') {
                        numValue = item;
                        isValidNumber = true;
                      } else if (typeof item === 'string') {
                        // Try to parse the string as a number
                        numValue = parseFloat(item);
                        isValidNumber = !Number.isNaN(numValue) && /^-?\d*\.?\d*$/.test(item);
                      }

                      // Only check constraints if it's a valid number
                      if (
                        isValidNumber &&
                        (propItems as Record<string, unknown>).minimum !== undefined &&
                        numValue < Number((propItems as Record<string, unknown>).minimum)
                      ) {
                        errors.push({
                          message: `Item ${index} in '${key}' must be at least ${(propItems as Record<string, unknown>).minimum}`,
                        });
                      }
                      if (
                        isValidNumber &&
                        (propItems as Record<string, unknown>).maximum !== undefined &&
                        numValue > Number((propItems as Record<string, unknown>).maximum)
                      ) {
                        errors.push({
                          message: `Item ${index} in '${key}' must be at most ${(propItems as Record<string, unknown>).maximum}`,
                        });
                      }
                    }
                  } else if (propItems?.type === 'boolean' && typeof item !== 'boolean') {
                    errors.push({ message: `Item ${index} in '${key}' must be a boolean` });
                  }
                });
              }
            }
          } else if (prop.type === 'object') {
            if (typeof value !== 'object' || value === null || Array.isArray(value)) {
              errors.push({ message: `Field '${key}' must be an object` });
            } else if (prop.properties) {
              // Validate nested object properties
              Object.entries(prop.properties).forEach(([nestedKey]) => {
                const nestedValue = value[nestedKey];

                // Check if required
                if (prop.required && (prop.required as string[]).includes(nestedKey) && nestedValue === undefined) {
                  errors.push({ message: `Object '${key}' is missing required field '${nestedKey}'` });
                }
              });
            }
          }

          // Check enum values
          if (prop.enum && !(prop.enum as unknown[]).includes(value)) {
            errors.push({ message: `Field '${key}' must be one of: ${(prop.enum as string[]).join(', ')}` });
          }
        });
      }

      return errors;
    } catch (e) {
      return [{ message: `Invalid YAML: ${(e as Error).message}` }];
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleEditorDidMount = (editor: any, monaco: any): void => {
    editorRef.current = editor;

    // Set up JSON schema validation if schema is available
    if (schema) {
      try {
        // Process the schema once
        const processedSchema = processSchema(schema);

        if (processedSchema) {
          // Create the JSON Schema configuration
          const jsonSchema = {
            uri: 'http://myserver/schema.json',
            fileMatch: ['*'],
            schema: processedSchema,
          };

          // Set the diagnostics options with the processed schema for JSON
          monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [jsonSchema],
            allowComments: false,
            trailingCommas: 'error',
          });

          console.log('Processed JSON Schema:', processedSchema);

          // For YAML, we'll use manual validation in the onChange handler
          // since Monaco doesn't have built-in YAML schema validation
          if (viewMode === 'yaml') {
            // Initial validation of YAML content
            const yamlErrors = validateYamlContent(yamlContent);
            if (yamlErrors.length > 0) {
              setValidationErrors(yamlErrors);
            }
          }
        }
      } catch (e) {
        console.error('Error setting up schema validation:', e);
      }
    }
  };

  // Handle changes in the JSON editor
  const handleJsonEditorChange = (value: string | undefined): void => {
    setJsonContent(value);
    try {
      const parsedValue = JSON.parse(value);
      setFormValues(parsedValue);

      // Update YAML when JSON changes
      try {
        const yamlString = yaml.dump(parsedValue);
        setYamlContent(yamlString);
      } catch (yamlErr) {
        console.error('Error converting to YAML:', yamlErr);
      }

      setValidationErrors([]);
    } catch (e) {
      setValidationErrors([{ message: `Invalid JSON: ${(e as Error).message}` }]);
    }
  };

  // Handle changes in the YAML editor
  const handleYamlEditorChange = (value: string | undefined): void => {
    setYamlContent(value);
    try {
      const parsedValue = yaml.load(value);
      setFormValues(parsedValue);

      // Update JSON when YAML changes
      try {
        const jsonString = JSON.stringify(parsedValue, null, 2);
        setJsonContent(jsonString);
      } catch (jsonErr) {
        console.error('Error converting to JSON:', jsonErr);
      }

      // Validate YAML against schema
      if (schema) {
        const schemaErrors = validateYamlContent(value);
        setValidationErrors(schemaErrors);
      } else {
        setValidationErrors([]);
      }
    } catch (e) {
      setValidationErrors([{ message: `Invalid YAML: ${(e as Error).message}` }]);
    }
  };

  // Validate the current content based on view mode
  const validateCurrentContent = () => {
    if (!schema) return [];

    try {
      if (viewMode === 'json') {
        // For JSON, we rely on Monaco's built-in validation
        // But we can do a basic parse check here
        JSON.parse(jsonContent);
        return [];
      }
      if (viewMode === 'yaml') {
        // For YAML, use our custom validation
        return validateYamlContent(yamlContent);
      }
      return [];
    } catch (e) {
      return [{ message: `Invalid ${viewMode.toUpperCase()}: ${(e as Error).message}` }];
    }
  };

  const handleSave = async (saveAsDefault = false): Promise<void> => {
    // Validate content before saving
    const currentErrors = validateCurrentContent();

    if (currentErrors.length > 0) {
      setValidationErrors(currentErrors);
      setSaveError('Cannot save: Configuration contains validation errors');
      return;
    }

    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);

    try {
      // Simpler approach: Just compare the current form values with default values
      // and only include differences in our version config
      const customConfigToSave = {};

      // Helper function to compare values - returns a new object
      const compareWithDefault = (current, defaultObj, path = '') => {
        // Add debugging for granular assessment
        if (path.includes('granular')) {
          console.log(`DEBUG: compareWithDefault called with path '${path}':`, {
            // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
            current,
            currentType: typeof current,
            defaultObj,
            defaultType: typeof defaultObj,
            currentIsNull: current === null,
            currentIsUndefined: current === undefined,
            defaultIsNull: defaultObj === null,
            defaultIsUndefined: defaultObj === undefined,
          });
        }

        // Make a new result object each time to avoid mutation
        const newResult = {};

        // Skip comparison for null/undefined objects (but not false values!)
        if (current === null || current === undefined || defaultObj === null || defaultObj === undefined) {
          // If current exists but default doesn't, this is a customization
          if (current !== null && current !== undefined && (defaultObj === null || defaultObj === undefined)) {
            return { [path]: current };
          }
          return {};
        }

        // Handle different types
        if (typeof current !== typeof defaultObj) {
          return { [path]: current };
        }

        // Handle arrays
        if (Array.isArray(current)) {
          if (!Array.isArray(defaultObj)) {
            return { [path]: current };
          }

          // Special case: if current array is empty but default is not empty,
          // we need to explicitly save the empty array to override the default
          if (current.length === 0 && defaultObj.length > 0) {
            return { [path]: current };
          }

          // If lengths are different, arrays are different
          if (current.length !== defaultObj.length) {
            return { [path]: current };
          }

          // Check each array element
          let isDifferent = false;
          for (let i = 0; i < current.length; i += 1) {
            // Use += 1 instead of ++
            // For objects in arrays, recursively compare
            if (typeof current[i] === 'object' && current[i] !== null && typeof defaultObj[i] === 'object' && defaultObj[i] !== null) {
              const nestedPath = path ? `${path}[${i}]` : `[${i}]`;
              const nestedDiff = compareWithDefault(current[i], defaultObj[i], nestedPath);

              if (Object.keys(nestedDiff).length > 0) {
                isDifferent = true;
                // No need to continue, we know the array is different
                break;
              }
            }
            // For primitive values, direct compare
            else if (JSON.stringify(current[i]) !== JSON.stringify(defaultObj[i])) {
              isDifferent = true;
              break;
            }
          }

          if (isDifferent) {
            return { [path]: current };
          }
          return {};
        }

        // Handle objects (non-arrays)
        if (typeof current === 'object') {
          const keys = new Set([...Object.keys(current), ...Object.keys(defaultObj)]);
          let allResults = {};

          keys.forEach((key) => {
            const newPath = path ? `${path}.${key}` : key;

            // Add debugging for granular assessment
            if (newPath.includes('granular')) {
              console.log(`DEBUG: Comparing object key '${key}' at path '${newPath}':`, {
                // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
                currentValue: current[key],
                defaultValue: defaultObj[key],
                keyInCurrent: key in current,
                keyInDefault: key in defaultObj,
              });
            }

            // If key exists in current but not in default
            if (!(key in defaultObj) && key in current) {
              allResults = { ...allResults, [newPath]: current[key] };
            }
            // If key exists in both, compare recursively
            else if (key in defaultObj && key in current) {
              const nestedResults = compareWithDefault(current[key], defaultObj[key], newPath);

              // Add debugging for granular assessment
              if (newPath.includes('granular')) {
                console.log(`DEBUG: Recursive call result for '${newPath}':`, {
                  // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
                  nestedResults,
                  nestedResultsKeys: Object.keys(nestedResults),
                  nestedResultsLength: Object.keys(nestedResults).length,
                });
              }

              allResults = { ...allResults, ...nestedResults };
            }
          });

          return allResults;
        }

        // Handle primitive values - use numeric equivalence for numbers
        // This prevents false positives when Pydantic converts int to float (5 vs 5.0)
        if (isNumericValue(current) && isNumericValue(defaultObj)) {
          // Use numeric comparison for values that can be interpreted as numbers
          if (!areNumericValuesEqual(current, defaultObj)) {
            console.log(`DEBUG: Numeric difference detected at path '${path}':`, {
              // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
              current,
              currentType: typeof current,
              defaultObj,
              defaultType: typeof defaultObj,
            });
            const result = { [path]: current };
            return result;
          }
          // Numerically equal, no difference
          return newResult;
        }

        // Non-numeric primitive comparison
        if (current !== defaultObj) {
          console.log(`DEBUG: Primitive difference detected at path '${path}':`, {
            // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Debug logging with controlled internal data
            current,
            currentType: typeof current,
            defaultObj,
            defaultType: typeof defaultObj,
            areEqual: current === defaultObj,
            areStrictEqual: current !== defaultObj,
          });
          const result = { [path]: current };
          console.log(`DEBUG: Returning primitive difference result:`, result);
          return result;
        }

        return newResult;
      };

      let configToSave;

      if (saveAsDefault) {
        // When saving as default, merge form changes with complete Custom config
        // This ensures we capture both:
        // 1. User's form edits (formValues)
        // 2. Fields not in form like notes, system_prompt, task_prompt (from customConfig)
        const mergedConfigToSave = deepMerge(customConfig || {}, formValues);
        configToSave = { ...mergedConfigToSave, saveAsDefault: true };
        console.log('Saving merged config as new Default:', configToSave);
      } else {
        // CRITICAL: Compare formValues against mergedConfig (what user SEES and EDITS from)
        // mergedConfig = Default + Custom (the complete config displayed to user)
        // This ensures we only send actual user changes as the diff
        // Backend will merge this diff into existing Custom, preserving all other fields
        console.log('DEBUG: About to compare formValues with mergedConfig:', {
          formValues,
          mergedConfig,
          granularInFormValues: (formValues?.assessment as Record<string, unknown> | undefined)?.granular,
          granularInMergedConfig: (mergedConfig?.assessment as Record<string, unknown> | undefined)?.granular,
        });
        const differences = compareWithDefault(formValues, mergedConfig);
        console.log('DEBUG: Differences found by compareWithDefault:', differences);

        // Flatten path results into a proper object structure - revised to avoid ESLint errors
        const buildObjectFromPaths = (paths: Record<string, unknown>): Record<string, unknown> => {
          // Create a fresh result object
          const newResult: Record<string, unknown> = {};

          Object.entries(paths).forEach(([path, value]) => {
            if (!path) return; // Skip empty paths

            // For paths with dots, build nested structure
            if (path.includes('.') || path.includes('[')) {
              // Handle array notation
              if (path.includes('[')) {
                // Arrays need special handling
                // This is simplified - we'll include the whole array when it's customized
                const arrayPath = path.split('[')[0];
                if (!Object.prototype.hasOwnProperty.call(newResult, arrayPath)) {
                  // Find the array in formValues
                  const arrayValue = path.split('.').reduce((acc, part) => {
                    if (!acc) return undefined;
                    return acc[part.replace(/\[\d+\]$/, '')];
                  }, formValues);

                  if (arrayValue) {
                    // Create a new object with this property
                    Object.assign(newResult, { [arrayPath]: arrayValue });
                  }
                }
              } else {
                // Regular object paths
                const parts = path.split('.');

                // Build an object to merge
                const objectToMerge = {};
                let current = objectToMerge;

                // Build nested structure without modifying existing objects
                for (let i = 0; i < parts.length - 1; i += 1) {
                  // Use += 1 instead of ++
                  current[parts[i]] = {};
                  current = current[parts[i]]; // nosemgrep: javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop - Index from controlled array iteration
                }

                // Set the value at the final path - IMPORTANT: preserve boolean false values!
                current[parts[parts.length - 1]] = value;

                // Deep merge this into result
                const deepMergeNested = (target, source) => {
                  const output = { ...target };

                  Object.keys(source).forEach((key) => {
                    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
                      if (target[key] && typeof target[key] === 'object') {
                        output[key] = deepMergeNested(target[key], source[key]);
                      } else {
                        output[key] = { ...source[key] };
                      }
                    } else {
                      // CRITICAL FIX: Always set the value, including boolean false
                      output[key] = source[key];
                    }
                  });

                  return output;
                };

                // Merge into result without modifying original objects
                Object.assign(newResult, deepMergeNested(newResult, objectToMerge));
              }
            } else {
              // For top-level values, create a new object with the property
              Object.assign(newResult, { [path]: value });
            }
          });

          return newResult;
        };

        // Convert the difference paths to a proper nested structure
        const builtObject = buildObjectFromPaths(differences);
        console.log('DEBUG: Built object from paths:', builtObject);

        // Include classes ONLY if they changed from mergedConfig (what user sees)
        // This prevents unnecessarily sending the entire classes array on every save
        if (formValues.classes && Array.isArray(formValues.classes)) {
          const classesChanged = JSON.stringify(formValues.classes) !== JSON.stringify(mergedConfig?.classes);
          if (classesChanged) {
            builtObject.classes = formValues.classes;
            console.log('DEBUG: Including modified document schema (classes) in save:', formValues.classes);
          } else {
            console.log('DEBUG: Classes unchanged, not including in save');
          }
        }

        // CRITICAL: Always include the current rule schema (rule_classes) if it exists OR is explicitly empty
        // This ensures empty arrays are saved (to wipe all rule classes) and prevents schema loss
        if (formValues.rule_classes && Array.isArray(formValues.rule_classes)) {
          builtObject.rule_classes = formValues.rule_classes;
          console.log('DEBUG: Including rule schema (rule_classes) in save:', formValues.rule_classes);
        }

        // CRITICAL: Always include the current rule schema (rule_classes) if it exists OR is explicitly empty
        // This ensures empty arrays are saved (to wipe all rule classes) and prevents schema loss
        if (formValues.rule_classes && Array.isArray(formValues.rule_classes)) {
          builtObject.rule_classes = formValues.rule_classes;
          console.log('DEBUG: Including rule schema (rule_classes) in save:', formValues.rule_classes);
        }

        // CRITICAL: If there are no differences AND no schema changes AND no description changes, don't send update to backend
        // This prevents unnecessary API calls and potential data issues
        const descriptionChanged = versionDescription !== (currentVersion?.description || '');
        if (Object.keys(builtObject).length === 0 && !descriptionChanged) {
          console.log('No changes detected, skipping save');
          setSaveSuccess(true);
          setTimeout(() => setSaveSuccess(false), 3000);
          return;
        }

        // If only description changed, ensure we still send an update
        if (Object.keys(builtObject).length === 0 && descriptionChanged) {
          console.log('Only description changed, proceeding with save');
        }

        Object.assign(customConfigToSave, builtObject);
        configToSave = customConfigToSave;
        console.log('Saving customized config:', configToSave);
      }

      console.log('Save parameters:', { currentVersionName, configToSave, versionDescription });
      const success = await updateConfiguration(currentVersionName, configToSave, versionDescription);

      if (success) {
        setSaveSuccess(true);
        if (saveAsDefault) {
          setShowSaveAsDefaultModal(false);
        }
        // Refresh versions list after successful save
        await fetchVersions();
      } else {
        setSaveError('Failed to save configuration. Please try again.');
      }
    } catch (err) {
      console.error('Save error:', err);
      setSaveError(`Error: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveAsVersion = async () => {
    // Validate content before saving
    const currentErrors = validateCurrentContent();

    if (currentErrors.length > 0) {
      setValidationErrors(currentErrors);
      setSaveError('Cannot save: Configuration contains validation errors');
      return;
    }

    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);

    try {
      // Send merged config like "Save as default" - ensures all fields are captured
      const builtObject = deepMerge(customConfig || {}, formValues);

      const result = await saveAsNewVersion(builtObject, saveAsVersionName, saveAsVersionDescription);

      if (result.success) {
        setSaveSuccess(true);
        setShowSaveAsVersionModal(false);
        setSaveAsVersionName('');
        setSaveAsVersionDescription('');

        // Select the new version and refresh
        setSelectedVersion(saveAsVersionName);
        await fetchVersions();
        await fetchConfiguration(saveAsVersionName);
      } else {
        setSaveAsVersionError(result.error || 'Failed to save as version. Please try again.');
      }
    } catch (err) {
      console.error('Save as version error:', err);
      setSaveError(`Error: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleFormChange = (newValues: Record<string, unknown>): void => {
    setFormValues(newValues);
    try {
      // Update both JSON and YAML content
      const jsonString = JSON.stringify(newValues, null, 2);
      setJsonContent(jsonString);

      try {
        const yamlString = yaml.dump(newValues);
        setYamlContent(yamlString);
      } catch (yamlErr) {
        console.error('Error converting to YAML:', yamlErr);
      }

      setValidationErrors([]);
    } catch (e) {
      setValidationErrors([{ message: `Error converting form values to JSON: ${(e as Error).message}` }]);
    }
  };

  const formatJson = () => {
    if (editorRef.current && viewMode === 'json') {
      editorRef.current.getAction('editor.action.formatDocument').run();
    }
  };

  const formatYaml = () => {
    if (editorRef.current && viewMode === 'yaml') {
      editorRef.current.getAction('editor.action.formatDocument').run();

      // Re-validate after formatting
      setTimeout(() => {
        const errors = validateYamlContent(yamlContent);
        setValidationErrors(errors);
      }, 100);
    }
  };

  const handleResetAllToDefault = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);

    try {
      // Reset custom configuration by sending a special reset flag
      // Backend will clear Custom, and on next read it will copy Default -> Custom
      const success = await updateConfiguration(currentVersionName, { resetToDefault: true });

      if (success) {
        setSaveSuccess(true);
        setShowResetModal(false);
        // Refresh to show the restored default configuration
        await fetchConfiguration(currentVersionName);
        // Reset description to current version's description
        setVersionDescription(currentVersion?.description || '');
      } else {
        setSaveError('Failed to reset configuration. Please try again.');
      }
    } catch (err) {
      console.error('Reset error:', err);
      setSaveError(`Error: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Handler for BDA/IDP sync
  // Handler for BDA/IDP sync with direction support
  const handleSyncBdaIdp = async (direction = 'bidirectional'): Promise<void> => {
    setSyncingDirection(direction);
    setSyncSuccess(false);
    setSyncSuccessMessage('');
    setSyncError(null);

    try {
      logger.debug(`Starting BDA/IDP sync with direction: ${direction}...`);

      const result = await client.graphql({
        query: syncBdaIdpMutation as unknown as string,
        variables: {
          versionName: currentVersionName,
          direction,
        },
      });

      logger.debug('Sync API response:', result);

      const resultData = (result as unknown as Record<string, Record<string, unknown>>).data;
      const response = (resultData.syncBdaIdp || {}) as Record<string, unknown>;

      if (response.success) {
        setSyncSuccess(true);
        const directionLabel =
          (
            {
              bda_to_idp: 'from BDA to IDP',
              idp_to_bda: 'from IDP to BDA',
              bidirectional: 'bidirectionally',
            } as Record<string, string>
          )[direction] || direction;
        setSyncSuccessMessage(String(response.message || `Document classes have been synchronized ${directionLabel}.`));

        // If there are partial failures, also show the error details
        const syncErr = response.error as Record<string, unknown> | undefined;
        if (syncErr && syncErr.type === 'PARTIAL_SYNC_ERROR') {
          // Show both success and error for partial failures
          setTimeout(() => {
            setSyncError(syncErr.message as string);
          }, 100); // Small delay to show success first
        }

        // Refresh configuration to show any new classes
        await fetchConfiguration(currentVersionName);

        // Only auto-dismiss if there are no warnings in the message
        // Warnings indicate BDA limitations that users should read
        const hasWarnings =
          (response.message as string | undefined)?.includes('WARNING') || (response.warnings as unknown[] | undefined)?.length > 0;
        if (!hasWarnings) {
          setTimeout(() => {
            setSyncSuccess(false);
            setSyncSuccessMessage('');
          }, 5000);
        }
        logger.debug('BDA/IDP sync completed successfully');

        // If this was sync to BDA, activate the version (skip confirmation to prevent circular call)
        if (direction === 'idp_to_bda') {
          try {
            await handleActivateVersion(currentVersionName, true); // Skip confirmation
            logger.debug(`Activated version ${currentVersionName} after sync to BDA`);
          } catch (activateErr) {
            logger.error('Failed to activate version after sync:', activateErr);
            // Don't fail the sync, just log the error
          }
        }
      } else {
        const errorMsg = String(
          (response.error as Record<string, unknown> | undefined)?.message || response.message || 'Sync operation failed',
        );
        setSyncError(errorMsg);
        logger.error('Sync failed:', errorMsg);
      }
    } catch (err) {
      logger.error('Sync error:', err);
      setSyncError(`Sync failed: ${(err as Error).message}`);
    } finally {
      setSyncingDirection(null);
    }
  };

  const handleExport = () => {
    try {
      let content;
      let mimeType;
      let fileExtension;

      if (exportFormat === 'yaml') {
        content = yaml.dump(mergedConfig);
        mimeType = 'text/yaml';
        fileExtension = 'yaml';
      } else {
        content = JSON.stringify(mergedConfig, null, 2);
        mimeType = 'application/json';
        fileExtension = 'json';
      }

      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${exportFileName}.${fileExtension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setShowExportModal(false);
    } catch (err) {
      setSaveError(`Export failed: ${(err as Error).message}`);
    }
  };

  const handleImport = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        setImportError(null);
        const content = e.target.result as string;

        const importedConfig = file.name.endsWith('.yaml') || file.name.endsWith('.yml') ? yaml.load(content) : JSON.parse(content);

        if (importedConfig && typeof importedConfig === 'object') {
          // Check if config is in legacy format
          if (isLegacyFormat(importedConfig)) {
            // Show migration modal and store config for later
            setPendingImportConfig(importedConfig);
            setPendingImportSource({ type: 'file', name: file.name });
            setShowMigrationModal(true);
          } else {
            // Set imported config for new version creation
            setImportedConfigForNewVersion(importedConfig);
            setImportSource('file');
            const baseName = file.name.replace(/\.(json|yaml|yml)$/, '');
            setNewVersionName(baseName);
            setNewVersionDescription('');
          }
        } else {
          setImportError('Invalid configuration file format');
        }
      } catch (err) {
        setImportError(`Import failed: ${(err as Error).message}`);
      }
    };
    reader.readAsText(file);
    // Clear the input value to allow re-importing the same file
    event.target.value = '';
  };

  const handleMigrationConfirm = async () => {
    if (!pendingImportConfig || !pendingImportSource) return;

    // Generate version name based on import source
    let baseName;
    if (pendingImportSource.type === 'file') {
      baseName = pendingImportSource.name.replace(/\.(json|yaml|yml)$/, '');
    } else {
      baseName = pendingImportSource.name.split('/').pop();
    }

    // Set up for new version creation with migration
    setImportedConfigForNewVersion(pendingImportConfig);
    setImportSource('migration');
    setNewVersionName(baseName);
    setNewVersionDescription('Migrated from legacy format');
    setShowMigrationModal(false);
    setPendingImportConfig(null);
    setPendingImportSource(null);
  };

  const handleMigrationCancel = () => {
    setShowMigrationModal(false);
    setPendingImportConfig(null);
    setPendingImportSource(null);
  };

  // Handler for Import button click - show source selection modal
  // NOTE: Original JS referenced out-of-scope variables; fixed during TS migration
  const _handleImportClick = () => {
    setShowImportSourceModal(true);
  };

  // Handler for local file import
  const handleLocalFileImport = () => {
    document.getElementById('import-file').click();
  };

  // Handler for library import
  const handleLibraryImport = async () => {
    setLibraryLoading(true);

    try {
      const patternDir = getPatternDirectory(settings?.IDPPattern as string | undefined);
      if (!patternDir) {
        setImportError('Pattern not configured in settings');
        setLibraryLoading(false);
        return;
      }

      const configs = await listConfigurations(patternDir);
      setLibraryConfigs(configs as LibraryConfigItem[]);
      setShowImportSourceModal(false);
      setShowLibraryBrowserModal(true);
    } catch (err) {
      setImportError(`Failed to load library: ${(err as Error).message}`);
    } finally {
      setLibraryLoading(false);
    }
  };

  // Handler for selecting a library config
  const handleSelectLibraryConfig = async (config: LibraryConfigItem): Promise<void> => {
    setSelectedLibraryConfig(config);

    if (config.hasReadme) {
      // Fetch and show README
      const patternDir = getPatternDirectory(settings?.IDPPattern as string | undefined);
      const file = await getFile(patternDir, config.name, 'README.md');

      if (file) {
        setReadmeContent(file.content);
        setShowLibraryBrowserModal(false);
        setShowReadmeModal(true);
      } else {
        // No README or error, import directly
        await importFromLibrary(config);
      }
    } else {
      // No README, import directly
      await importFromLibrary(config);
    }
  };

  // Handler to import configuration from library
  const importFromLibrary = async (config: LibraryConfigItem): Promise<void> => {
    setShowReadmeModal(false);
    setShowLibraryBrowserModal(false);

    try {
      const patternDir = getPatternDirectory(settings?.IDPPattern as string | undefined);

      // Use the detected file type from the config object
      const fileName = config.configFileType === 'json' ? 'config.json' : 'config.yaml';
      const file = await getFile(patternDir, config.name, fileName);

      if (!file) {
        setImportError('Failed to load configuration file');
        return;
      }

      // Parse based on file type
      const importedConfig = fileName.endsWith('.json') ? JSON.parse(file.content) : yaml.load(file.content);

      if (importedConfig && typeof importedConfig === 'object') {
        // Check if config is in legacy format
        if (isLegacyFormat(importedConfig)) {
          setPendingImportConfig(importedConfig);
          setPendingImportSource({ type: 'library', name: config.name });
          setShowMigrationModal(true);
        } else {
          // Set imported config for new version creation
          setImportedConfigForNewVersion(importedConfig);
          setImportSource('library');
          const baseName = config.name.split('/').pop();
          setNewVersionName(baseName);
          setNewVersionDescription('');
        }
      } else {
        setImportError('Invalid configuration format');
      }
    } catch (err) {
      setImportError(`Import failed: ${(err as Error).message}`);
    }
  };

  if (loading) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
          <Box padding="s">Loading configuration...</Box>
        </Box>
      </Container>
    );
  }

  if (error) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Alert type="error" header="Error loading configuration">
          <SpaceBetween size="s">
            <div>{error}</div>
            <Box>
              <Button {...({ onClick: fetchConfiguration } as Record<string, unknown>)} variant="primary">
                Retry
              </Button>
            </Box>
          </SpaceBetween>
        </Alert>
      </Container>
    );
  }

  if (!schema || !mergedConfig) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Alert type="error" header="Configuration not available">
          <SpaceBetween size="s">
            <div>Unable to load configuration schema or values.</div>
            <Box>
              <Button {...({ onClick: fetchConfiguration } as Record<string, unknown>)} variant="primary">
                Retry
              </Button>
            </Box>
          </SpaceBetween>
        </Alert>
      </Container>
    );
  }

  return (
    <SpaceBetween size="s">
      {/* Configuration Versions Table */}
      <ExpandableSection
        headerText="Configuration Versions"
        headingTagOverride="h1"
        expanded={versionsTableExpanded}
        onChange={({ detail }) => setVersionsTableExpanded(detail.expanded)}
      >
        <ConfigurationVersionsTable
          versions={versions}
          loading={versionsLoading}
          onVersionSelect={handleVersionSelect}
          selectedVersionsForCompare={selectedVersionsForCompare}
          currentlyOpenVersion={selectedVersion || activeVersionName}
          onVersionSelectForCompare={handleVersionSelectForCompare}
          onCompareVersions={handleCompareVersions}
          onActivateVersion={handleActivateVersion}
          onDeleteVersions={handleDeleteVersions}
          onImportAsNewVersion={handleImportAsNewVersion}
        />
      </ExpandableSection>

      <Modal
        visible={showResetModal}
        onDismiss={() => setShowResetModal(false)}
        header="Reset All to Default"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowResetModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleResetAllToDefault} loading={isSaving}>
                Reset
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="span">Are you sure you want to reset all configuration settings to default values? This action cannot be undone.</Box>
      </Modal>

      <Modal
        visible={showSaveAsDefaultModal}
        onDismiss={() => setShowSaveAsDefaultModal(false)}
        header="Save as New Default"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowSaveAsDefaultModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => handleSave(true)} loading={isSaving}>
                Save as Default
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="m">
          <Box variant="span">
            Are you sure you want to save the current configuration as the new default? This will replace the existing default configuration
            and cannot be undone.
          </Box>
          <Alert type="warning" header="Important: Version upgrade considerations">
            The default configuration may be overwritten when you update the solution to a new version. We recommend using the Export button
            to download and save your configuration so you can easily restore it after an upgrade if needed.
          </Alert>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showSaveAsVersionModal}
        onDismiss={() => setShowSaveAsVersionModal(false)}
        header="Save as New Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowSaveAsVersionModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleSaveAsVersion} loading={isSaving} disabled={!saveAsVersionName.trim()}>
                Save as Version
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {saveAsVersionError && (
            <Alert type="error" dismissible onDismiss={() => setSaveAsVersionError(null)} header="Error">
              {saveAsVersionError}
            </Alert>
          )}
          <FormField
            label="Version Name"
            description="Enter a unique name for this configuration version"
            errorText={
              saveAsVersionName && !/^[a-zA-Z0-9_-]+$/.test(saveAsVersionName)
                ? 'Version name can only contain letters, numbers, hyphens, and underscores'
                : ''
            }
          >
            <Input
              value={saveAsVersionName}
              onChange={({ detail }) => setSaveAsVersionName(detail.value)}
              placeholder="e.g., my-custom-config"
            />
          </FormField>
          <FormField
            label="Version Description (Optional)"
            description="Optional description for this version (max 200 characters)"
            errorText={saveAsVersionDescription && saveAsVersionDescription.length > 200 ? 'Description cannot exceed 200 characters' : ''}
          >
            <Input
              value={saveAsVersionDescription}
              onChange={({ detail }) => setSaveAsVersionDescription(detail.value)}
              placeholder="Enter a description for this version..."
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showExportModal}
        onDismiss={() => setShowExportModal(false)}
        header="Export Configuration"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowExportModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleExport}>
                Export
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="l">
          <FormField label="File format">
            <RadioGroup
              value={exportFormat}
              onChange={({ detail }) => setExportFormat(detail.value)}
              items={[
                { value: 'json', label: 'JSON' },
                { value: 'yaml', label: 'YAML' },
              ]}
            />
          </FormField>
          <FormField label="File name">
            <Input
              value={exportFileName}
              onChange={({ detail }) => setExportFileName(detail.value)}
              placeholder={currentVersionName || 'configuration'}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={showMigrationModal}
        onDismiss={handleMigrationCancel}
        header="Configuration Migration Required"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={handleMigrationCancel}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleMigrationConfirm} loading={isSaving}>
                Save and Migrate
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="m">
          <Box variant="span">
            The configuration file you are importing uses a legacy format that needs to be migrated to the current JSON Schema format.
          </Box>
          <Alert type="info" header="What will happen">
            <ul>
              <li>The configuration will be automatically converted to the new format</li>
              <li>All your settings and document classes will be preserved</li>
              <li>The migrated configuration will be saved to the database</li>
              <li>You can review the changes after migration</li>
            </ul>
          </Alert>
          <Box variant="span">
            Click &quot;Save and Migrate&quot; to proceed with the migration, or &quot;Cancel&quot; to abort the import.
          </Box>
        </SpaceBetween>
      </Modal>

      {/* Import Source Selection Modal */}
      <Modal
        visible={showImportSourceModal}
        onDismiss={() => {
          setImportError(null);
          setShowImportSourceModal(false);
        }}
        header="Import as New Version"
        footer={
          <Box float="right">
            <Button variant="link" onClick={() => setShowImportSourceModal(false)}>
              Cancel
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="l">
          <Button variant="primary" onClick={handleLocalFileImport} iconName="upload" fullWidth>
            Import from Local File
          </Button>
          <Button variant="normal" onClick={handleLibraryImport} iconName="folder" fullWidth loading={libraryLoading}>
            Import from Configuration Library
          </Button>
        </SpaceBetween>
      </Modal>

      {/* Configuration Library Browser Modal */}
      <Modal
        visible={showLibraryBrowserModal}
        onDismiss={() => setShowLibraryBrowserModal(false)}
        header={`Configuration Library - ${(settings?.IDPPattern as string) || 'Pattern'}`}
        size="large"
        footer={
          <Box float="right">
            <Button variant="link" onClick={() => setShowLibraryBrowserModal(false)}>
              Cancel
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {libraryConfigs.length === 0 && (
            <Alert type="info">No configurations found for {settings?.IDPPattern as string} in the Config Library</Alert>
          )}

          {libraryConfigs.map((config) => (
            <Container key={config.name}>
              <SpaceBetween size="xs">
                <Box fontSize="heading-m" fontWeight="bold">
                  {config.name}
                </Box>
                <SpaceBetween size="xs" direction="horizontal">
                  <Box fontSize="body-s" color="text-body-secondary">
                    Format: {config.configFileType?.toUpperCase() || 'YAML'}
                  </Box>
                  {config.hasReadme && (
                    <Box fontSize="body-s" color="text-status-info">
                      <Icon name="file" /> README available
                    </Box>
                  )}
                </SpaceBetween>
                <Box float="right">
                  <Button variant="primary" onClick={() => handleSelectLibraryConfig(config)}>
                    Select
                  </Button>
                </Box>
              </SpaceBetween>
            </Container>
          ))}
        </SpaceBetween>
      </Modal>

      {/* README Preview Modal */}
      <Modal
        visible={showReadmeModal}
        onDismiss={() => setShowReadmeModal(false)}
        header={`Configuration: ${selectedLibraryConfig?.name}`}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowReadmeModal(false);
                  setShowLibraryBrowserModal(true);
                }}
              >
                Go Back
              </Button>
              <Button variant="primary" onClick={() => importFromLibrary(selectedLibraryConfig)}>
                Import This Configuration
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box padding="l">
          <ReactMarkdown>{readmeContent}</ReactMarkdown>
        </Box>
      </Modal>

      <Container
        header={
          <Header
            variant="h3"
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <SegmentedControl
                  selectedId={viewMode}
                  onChange={({ detail }) => setViewMode(detail.selectedId)}
                  options={[
                    { id: 'form', text: 'Form View' },
                    { id: 'json', text: 'JSON View' },
                    { id: 'yaml', text: 'YAML View' },
                  ]}
                />
                {viewMode === 'json' && (
                  <Button onClick={formatJson} iconName="file">
                    Format JSON
                  </Button>
                )}
                {viewMode === 'yaml' && (
                  <Button onClick={formatYaml} iconName="file">
                    Format YAML
                  </Button>
                )}
                <Button variant="normal" onClick={() => setShowExportModal(true)}>
                  Export
                </Button>
                <input id="import-file" type="file" accept=".json,.yaml,.yml" style={{ display: 'none' }} onChange={handleImport} />
                <Button variant="normal" onClick={() => fetchConfiguration(currentVersionName)} loading={refreshing} iconName="refresh">
                  Refresh
                </Button>
                {isPattern1 && (
                  <>
                    <Button variant="normal" onClick={() => handleSyncBdaIdp('bda_to_idp')} loading={syncingDirection === 'bda_to_idp'}>
                      Sync from BDA
                    </Button>
                    <Button variant="normal" onClick={() => setShowSyncToBdaConfirmModal(true)} loading={syncingDirection === 'idp_to_bda'}>
                      Sync to BDA
                    </Button>
                  </>
                )}
                <Button variant="normal" onClick={() => setShowResetModal(true)} disabled={currentVersionName === 'default'}>
                  Restore default (All)
                </Button>
                {/* Disable Save as default when already on default version */}
                <Button variant="normal" onClick={() => setShowSaveAsDefaultModal(true)} disabled={currentVersionName === 'default'}>
                  Save as default
                </Button>
                <Button variant="normal" onClick={() => setShowSaveAsVersionModal(true)} disabled={validationErrors.length > 0}>
                  Save as Version
                </Button>
                {/* Disable Save changes when on default version */}
                <Button
                  variant="primary"
                  onClick={() => handleSave(false)}
                  loading={isSaving}
                  disabled={!hasUnsavedChanges || validationErrors.length > 0 || currentVersionName === 'default'}
                >
                  Save changes
                </Button>
              </SpaceBetween>
            }
          >
            Configuration:{' '}
            {selectedVersion || (activeVersionName && currentVersion?.isActive ? `${activeVersionName} (Active)` : activeVersionName)}
            {currentVersion?.description ? ` - ${currentVersion.description}` : ''}
          </Header>
        }
      >
        <Form>
          {refreshing && (
            <Alert type="info" header="Syncing configuration...">
              <Box {...({ display: 'flex', alignItems: 'center' } as Record<string, unknown>)}>
                <Spinner size="normal" />
                <Box margin={{ left: 's' }}>Refreshing data from server</Box>
              </Box>
            </Alert>
          )}

          {saveSuccess && (
            <Alert type="success" dismissible onDismiss={() => setSaveSuccess(false)} header="Configuration saved successfully">
              Your configuration changes have been saved.
            </Alert>
          )}

          {importSuccess && (
            <Alert type="success" dismissible onDismiss={() => setImportSuccess(false)} header="Configuration imported successfully">
              The configuration has been imported from the library and loaded into the editor.
            </Alert>
          )}

          {saveError && (
            <Alert type="error" dismissible onDismiss={() => setSaveError(null)} header="Error saving configuration">
              {saveError}
            </Alert>
          )}

          {syncSuccess && (
            <Alert
              type="success"
              dismissible
              onDismiss={() => {
                setSyncSuccess(false);
                setSyncSuccessMessage('');
              }}
              header="BDA/IDP sync completed successfully"
            >
              {syncSuccessMessage}
            </Alert>
          )}

          {syncError && (
            <Alert type="error" dismissible onDismiss={() => setSyncError(null)} header="BDA/IDP sync error">
              <SpaceBetween size="s">
                {syncError.includes('Failed to sync classes:') ? (
                  <div>
                    <div>The following document classes failed to synchronize:</div>
                    <ul style={{ marginTop: '8px', paddingLeft: '20px' }}>
                      {syncError
                        .replace('Failed to sync classes: ', '')
                        .split(', ')
                        .map((classError) => (
                          <li key={`sync-error-${classError.replace(/[^a-zA-Z0-9]/g, '-')}`} style={{ marginBottom: '4px' }}>
                            {classError}
                          </li>
                        ))}
                    </ul>
                  </div>
                ) : (
                  <div>{syncError}</div>
                )}
              </SpaceBetween>
            </Alert>
          )}

          {validationErrors.length > 0 && (
            <Alert type="warning" header="Validation errors">
              <ul>
                {validationErrors.map((e, index) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <li key={index}>{e.message}</li>
                ))}
              </ul>
            </Alert>
          )}

          {hasUnsavedChanges && currentVersionName !== 'default' && (
            <Alert
              type="info"
              action={
                <Button variant="normal" onClick={handleDiscardChanges} loading={refreshing}>
                  Discard changes
                </Button>
              }
            >
              You have unsaved changes. Click <strong>Save changes</strong> to persist, or <strong>Discard changes</strong> to revert.
            </Alert>
          )}

          <Box padding="s">
            {viewMode === 'form' && (
              <SpaceBetween size="l">
                <ConfigBuilder
                  schema={{
                    ...schema,
                    properties: Object.fromEntries(Object.entries(schema?.properties || {}).filter(([key]) => key !== 'classes')),
                  }}
                  formValues={formValues}
                  defaultConfig={defaultConfig}
                  mergedConfig={mergedConfig}
                  isCustomized={isCustomized}
                  onResetToDefault={currentVersionName === 'default' ? null : resetToDefault}
                  onChange={handleFormChange}
                  extractionSchema={extractionSchema}
                  currentVersionName={currentVersionName}
                  activeTabId={configBuilderActiveTab}
                  onTabChange={setConfigBuilderActiveTab}
                  showRuleSchema={isPattern2}
                  versionDescription={versionDescription}
                  onDescriptionChange={setVersionDescription}
                  onSchemaChange={(schemaData: unknown, isDirty: boolean) => {
                    setExtractionSchema(schemaData as unknown[] | null);
                    if (isDirty) {
                      const updatedConfig = { ...formValues };
                      // CRITICAL: Always set classes, even if empty array (to support wipe all functionality)
                      // Handle null (no classes) by setting empty array
                      if (schemaData === null) {
                        updatedConfig.classes = [];
                      } else if (Array.isArray(schemaData)) {
                        // Store as 'classes' field with JSON Schema content
                        updatedConfig.classes = schemaData;
                      }
                      setFormValues(updatedConfig);
                      setJsonContent(JSON.stringify(updatedConfig, null, 2));
                      try {
                        setYamlContent(yaml.dump(updatedConfig));
                      } catch (e) {
                        console.error('Error converting to YAML:', e);
                      }
                    }
                  }}
                  onSchemaValidate={(valid: boolean, errors: unknown[]) => {
                    if (!valid) {
                      setValidationErrors(
                        errors.map((e) => ({
                          message: `Document Schema: ${(e as Record<string, string>).path} - ${(e as Record<string, string>).message}`,
                        })),
                      );
                    } else {
                      setValidationErrors([]);
                    }
                  }}
                  ruleSchema={ruleSchema}
                  onRuleSchemaChange={(schemaData: unknown, isDirty: boolean) => {
                    setRuleSchema(schemaData as unknown[] | null);
                    if (isDirty) {
                      const updatedConfig = { ...formValues };
                      // CRITICAL: Always set rule_classes, even if empty array
                      if (schemaData === null) {
                        updatedConfig.rule_classes = [];
                      } else if (Array.isArray(schemaData)) {
                        // Store as 'rule_classes' field with JSON Schema content
                        updatedConfig.rule_classes = schemaData;
                      }
                      setFormValues(updatedConfig);
                      setJsonContent(JSON.stringify(updatedConfig, null, 2));
                      try {
                        setYamlContent(yaml.dump(updatedConfig));
                      } catch (e) {
                        console.error('Error converting to YAML:', e);
                      }
                    }
                  }}
                  onRuleSchemaValidate={(valid: boolean, errors: unknown[]) => {
                    if (!valid) {
                      setValidationErrors(
                        errors.map((e) => ({
                          message: `Rule Schema: ${(e as Record<string, string>).path} - ${(e as Record<string, string>).message}`,
                        })),
                      );
                    } else {
                      setValidationErrors([]);
                    }
                  }}
                />
              </SpaceBetween>
            )}

            {viewMode === 'json' && (
              <Editor
                height="70vh"
                defaultLanguage="json"
                value={jsonContent}
                onChange={handleJsonEditorChange}
                onMount={handleEditorDidMount}
                options={{
                  minimap: { enabled: false },
                  formatOnPaste: true,
                  formatOnType: true,
                  automaticLayout: true,
                  scrollBeyondLastLine: false,
                  folding: true,
                  lineNumbers: 'on',
                  renderLineHighlight: 'all',
                  tabSize: 2,
                }}
              />
            )}

            {viewMode === 'yaml' && (
              <Box>
                <Editor
                  height="70vh"
                  defaultLanguage="yaml"
                  value={yamlContent}
                  onChange={handleYamlEditorChange}
                  onMount={handleEditorDidMount}
                  options={{
                    minimap: { enabled: false },
                    formatOnPaste: true,
                    formatOnType: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    folding: true,
                    lineNumbers: 'on',
                    renderLineHighlight: 'all',
                    tabSize: 2,
                  }}
                />
              </Box>
            )}
          </Box>
        </Form>
      </Container>

      {/* Version Form Modal */}
      <Modal
        visible={!!importedConfigForNewVersion}
        onDismiss={() => {
          setImportedConfigForNewVersion(null);
          setImportSource(null);
          setNewVersionName('');
          setNewVersionDescription('');
        }}
        header="Create New Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setImportedConfigForNewVersion(null);
                  setImportSource(null);
                  setNewVersionName('');
                  setNewVersionDescription('');
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleCreateVersionFromImport}
                disabled={
                  !newVersionName.trim() ||
                  newVersionName.length > 50 ||
                  !/^[a-zA-Z0-9_-]+$/.test(newVersionName) ||
                  (newVersionDescription && newVersionDescription.length > 200)
                }
              >
                Create Version
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {importError && (
            <Alert type="error" dismissible onDismiss={() => setImportError(null)} header="Import Error">
              {importError}
            </Alert>
          )}
          <Alert type="success" header="Configuration Loaded">
            Configuration successfully loaded and ready to be saved as a new version.
          </Alert>

          <FormField
            label="Version Name"
            errorText={
              newVersionName &&
              (newVersionName.length > 50
                ? 'Version name cannot exceed 50 characters'
                : !/^[a-zA-Z0-9_-]+$/.test(newVersionName)
                ? 'Version name can only contain letters, numbers, hyphens, and underscores'
                : '')
            }
          >
            <Input
              value={newVersionName}
              onChange={({ detail }) => setNewVersionName(detail.value)}
              placeholder="Version name"
              invalid={newVersionName && (newVersionName.length > 50 || !/^[a-zA-Z0-9_-]+$/.test(newVersionName))}
            />
          </FormField>
          <FormField
            label="Description (Optional)"
            errorText={newVersionDescription && newVersionDescription.length > 200 ? 'Description cannot exceed 200 characters' : ''}
          >
            <Input
              value={newVersionDescription}
              onChange={({ detail }) => setNewVersionDescription(detail.value)}
              placeholder="Optional description"
              invalid={newVersionDescription && newVersionDescription.length > 200}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Configuration Comparison Modal */}
      <Modal
        visible={showCompareModal}
        onDismiss={() => setShowCompareModal(false)}
        header="Configuration Comparison"
        size="max"
        footer={
          <Box float="right">
            <Button onClick={() => setShowCompareModal(false)}>Close</Button>
          </Box>
        }
      >
        {showCompareModal && compareData && <ConfigurationComparison versions={compareData.versions} configs={compareData.configs} />}
      </Modal>

      {/* Sync to BDA Confirmation Modal */}
      <Modal
        visible={showSyncToBdaConfirmModal}
        onDismiss={() => setShowSyncToBdaConfirmModal(false)}
        header="Confirm Sync to BDA"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowSyncToBdaConfirmModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  setShowSyncToBdaConfirmModal(false);
                  handleSyncBdaIdp('idp_to_bda');
                }}
                loading={syncingDirection === 'idp_to_bda'}
              >
                Confirm Sync
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Alert type="warning">
            This will sync your IDP document classes to BDA blueprints and set <strong>{currentVersionName}</strong> as the active
            configuration version.
          </Alert>
        </SpaceBetween>
      </Modal>

      {/* Activate Version Confirmation Modal */}
      <Modal
        visible={showActivateVersionConfirmModal}
        onDismiss={() => setShowActivateVersionConfirmModal(false)}
        header="Confirm Activate Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowActivateVersionConfirmModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  setShowActivateVersionConfirmModal(false);
                  if (selectedVersionsForCompare[0]) {
                    performSyncThenActivate(selectedVersionsForCompare[0]);
                  }
                }}
                loading={syncingDirection === 'idp_to_bda'}
                disabled={!selectedVersionsForCompare[0]}
              >
                Confirm Activate
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Alert type="warning">
            {selectedVersionsForCompare[0] ? (
              <>
                Activating version <strong>{selectedVersionsForCompare[0]}</strong> will first sync your IDP document classes to BDA
                blueprints, then set it as the active configuration version.
              </>
            ) : (
              <>No version selected. Please select a version to activate.</>
            )}
          </Alert>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default ConfigurationLayout;
