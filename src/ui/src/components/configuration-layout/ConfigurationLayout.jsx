import React, { useState, useEffect, useRef } from 'react';
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
} from '@awsui/components-react';
import Editor from '@monaco-editor/react';
// eslint-disable-next-line import/no-extraneous-dependencies
import yaml from 'js-yaml';
import useConfiguration from '../../hooks/use-configuration';
import FormView from './FormView';

const ConfigurationLayout = () => {
  const {
    schema,
    mergedConfig,
    defaultConfig,
    loading,
    error,
    updateConfiguration,
    fetchConfiguration,
    isCustomized,
    resetToDefault,
  } = useConfiguration();

  const [formValues, setFormValues] = useState({});
  const [jsonContent, setJsonContent] = useState('');
  const [yamlContent, setYamlContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [validationErrors, setValidationErrors] = useState([]);
  const [viewMode, setViewMode] = useState('form'); // Form view as default

  const editorRef = useRef(null);

  // Initialize form values from merged config
  useEffect(() => {
    if (mergedConfig) {
      console.log('Setting form values from mergedConfig:', mergedConfig);

      // Make a deep copy to ensure we're not dealing with references
      const formData = JSON.parse(JSON.stringify(mergedConfig));
      setFormValues(formData);

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
  const processSchema = (inputSchema) => {
    try {
      const processedSchema = {
        type: 'object',
        properties: {},
        required: inputSchema.required || [],
      };

      // Process schema properties to handle custom types like 'list'
      if (inputSchema.properties) {
        Object.entries(inputSchema.properties).forEach(([key, prop]) => {
          // Convert 'list' type to proper JSON Schema array type (for backwards compatibility)
          if (prop.type === 'list' || prop.type === 'array') {
            processedSchema.properties[key] = {
              type: 'array',
              items: prop.items || {},
            };

            // Process nested items if they have custom types
            if (prop.items && prop.items.type === 'object' && prop.items.properties) {
              const itemProps = {};
              Object.entries(prop.items.properties).forEach(([itemKey, itemProp]) => {
                if (itemProp.type === 'list' || itemProp.type === 'array') {
                  itemProps[itemKey] = {
                    type: 'array',
                    items: itemProp.items || {},
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
              processedSchema.properties[key].items.required = prop.items.required || [];
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
  const validateYamlContent = (yamlString) => {
    if (!schema) return [];

    try {
      // Convert YAML to JSON object
      const parsedYaml = yaml.load(yamlString);
      if (!parsedYaml) return [{ message: 'Empty or invalid YAML content' }];

      // Perform schema validation manually
      const errors = [];

      // Check required fields
      if (schema.required) {
        schema.required.forEach((field) => {
          if (parsedYaml[field] === undefined) {
            errors.push({ message: `Required field '${field}' is missing` });
          }
        });
      }

      // Validate property types and constraints
      if (schema.properties && parsedYaml) {
        Object.entries(schema.properties).forEach(([key, prop]) => {
          const value = parsedYaml[key];

          // Skip validation if value is undefined (already handled by required check)
          if (value === undefined) return;

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
                if (prop.minimum !== undefined && numValue < prop.minimum) {
                  errors.push({ message: `Field '${key}' must be at least ${prop.minimum}` });
                }
                if (prop.maximum !== undefined && numValue > prop.maximum) {
                  errors.push({ message: `Field '${key}' must be at most ${prop.maximum}` });
                }
              }
            }
          } else if (prop.type === 'string') {
            if (typeof value !== 'string') {
              errors.push({ message: `Field '${key}' must be a string` });
            } else {
              // Check string constraints
              if (prop.minLength !== undefined && value.length < prop.minLength) {
                errors.push({ message: `Field '${key}' must be at least ${prop.minLength} characters` });
              }
              if (prop.maxLength !== undefined && value.length > prop.maxLength) {
                errors.push({ message: `Field '${key}' must be at most ${prop.maxLength} characters` });
              }
              if (prop.pattern && !new RegExp(prop.pattern).test(value)) {
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
              if (prop.minItems !== undefined && value.length < prop.minItems) {
                errors.push({ message: `Field '${key}' must have at least ${prop.minItems} items` });
              }
              if (prop.maxItems !== undefined && value.length > prop.maxItems) {
                errors.push({ message: `Field '${key}' must have at most ${prop.maxItems} items` });
              }

              // Validate array items if schema is provided
              if (prop.items && prop.items.type && value.length > 0) {
                value.forEach((item, index) => {
                  if (prop.items.type === 'object' && prop.items.properties) {
                    // Validate object properties in array items
                    Object.entries(prop.items.properties).forEach(([itemKey, itemProp]) => {
                      const itemValue = item[itemKey];

                      // Check if required
                      if (prop.items.required && prop.items.required.includes(itemKey) && itemValue === undefined) {
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
                                message: `Field '${itemKey}' in item ${index} of '${key}' must be at least ${itemProp.minimum}`,
                              });
                            }
                            if (isValidNumber && itemProp.maximum !== undefined && numValue > itemProp.maximum) {
                              errors.push({
                                message: `Field '${itemKey}' in item ${index} of '${key}' must be at most ${itemProp.maximum}`,
                              });
                            }
                          }
                        } else if (itemProp.type === 'boolean' && typeof itemValue !== 'boolean') {
                          errors.push({ message: `Field '${itemKey}' in item ${index} of '${key}' must be a boolean` });
                        }
                      }
                    });
                  } else if (prop.items.type === 'string' && typeof item !== 'string') {
                    errors.push({ message: `Item ${index} in '${key}' must be a string` });
                  } else if (prop.items.type === 'number' || prop.items.type === 'integer') {
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
                      if (isValidNumber && prop.items.minimum !== undefined && numValue < prop.items.minimum) {
                        errors.push({
                          message: `Item ${index} in '${key}' must be at least ${prop.items.minimum}`,
                        });
                      }
                      if (isValidNumber && prop.items.maximum !== undefined && numValue > prop.items.maximum) {
                        errors.push({
                          message: `Item ${index} in '${key}' must be at most ${prop.items.maximum}`,
                        });
                      }
                    }
                  } else if (prop.items.type === 'boolean' && typeof item !== 'boolean') {
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
                if (prop.required && prop.required.includes(nestedKey) && nestedValue === undefined) {
                  errors.push({ message: `Object '${key}' is missing required field '${nestedKey}'` });
                }
              });
            }
          }

          // Check enum values
          if (prop.enum && !prop.enum.includes(value)) {
            errors.push({ message: `Field '${key}' must be one of: ${prop.enum.join(', ')}` });
          }
        });
      }

      return errors;
    } catch (e) {
      return [{ message: `Invalid YAML: ${e.message}` }];
    }
  };

  const handleEditorDidMount = (editor, monaco) => {
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
  const handleJsonEditorChange = (value) => {
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
      setValidationErrors([{ message: `Invalid JSON: ${e.message}` }]);
    }
  };

  // Handle changes in the YAML editor
  const handleYamlEditorChange = (value) => {
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
      setValidationErrors([{ message: `Invalid YAML: ${e.message}` }]);
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
      return [{ message: `Invalid ${viewMode.toUpperCase()}: ${e.message}` }];
    }
  };

  const handleSave = async () => {
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
      // and only include differences in our custom config
      const customConfigToSave = {};

      // Helper function to compare values - returns a new object
      const compareWithDefault = (current, defaultObj, path = '') => {
        // Make a new result object each time to avoid mutation
        const newResult = {};

        // Skip comparison for null objects
        if (!current || !defaultObj) {
          // If current exists but default doesn't, this is a customization
          if (current && !defaultObj) {
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
          if (!Array.isArray(defaultObj) || current.length !== defaultObj.length) {
            return { [path]: current };
          }

          // Check each array element
          let isDifferent = false;
          for (let i = 0; i < current.length; i += 1) {
            // Use += 1 instead of ++
            // For objects in arrays, recursively compare
            if (
              typeof current[i] === 'object' &&
              current[i] !== null &&
              typeof defaultObj[i] === 'object' &&
              defaultObj[i] !== null
            ) {
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

            // If key exists in current but not in default
            if (!(key in defaultObj) && key in current) {
              allResults = { ...allResults, [newPath]: current[key] };
            }
            // If key exists in both, compare recursively
            else if (key in defaultObj && key in current) {
              const nestedResults = compareWithDefault(current[key], defaultObj[key], newPath);
              allResults = { ...allResults, ...nestedResults };
            }
          });

          return allResults;
        }

        // Handle primitive values
        if (current !== defaultObj) {
          return { [path]: current };
        }

        return newResult;
      };

      // Create our customized config by comparing with defaults
      const differences = compareWithDefault(formValues, defaultConfig);

      // Flatten path results into a proper object structure - revised to avoid ESLint errors
      const buildObjectFromPaths = (paths) => {
        // Create a fresh result object
        const newResult = {};

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
                current = current[parts[i]];
              }

              // Set the value at the final path
              current[parts[parts.length - 1]] = value;

              // Deep merge this into result
              const deepMerge = (target, source) => {
                const output = { ...target };

                Object.keys(source).forEach((key) => {
                  if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
                    if (target[key] && typeof target[key] === 'object') {
                      output[key] = deepMerge(target[key], source[key]);
                    } else {
                      output[key] = { ...source[key] };
                    }
                  } else {
                    output[key] = source[key];
                  }
                });

                return output;
              };

              // Merge into result without modifying original objects
              Object.assign(newResult, deepMerge(newResult, objectToMerge));
            }
          } else {
            // For top-level values, create a new object with the property
            Object.assign(newResult, { [path]: value });
          }
        });

        return newResult;
      };

      // Convert the difference paths to a proper nested structure
      Object.assign(customConfigToSave, buildObjectFromPaths(differences));

      console.log('Saving customized config:', customConfigToSave);

      // Make sure we send at least the Info field, even if no customizations
      const success = await updateConfiguration(customConfigToSave);

      if (success) {
        setSaveSuccess(true);
        // Force a refresh of the configuration to ensure UI is in sync with backend
        setTimeout(() => {
          fetchConfiguration();
        }, 1000);
      } else {
        setSaveError('Failed to save configuration. Please try again.');
      }
    } catch (err) {
      console.error('Save error:', err);
      setSaveError(`Error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleFormChange = (newValues) => {
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
      setValidationErrors([{ message: `Error converting form values to JSON: ${e.message}` }]);
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
          {error}
          <Button onClick={fetchConfiguration} variant="primary" style={{ marginTop: '1rem' }}>
            Retry
          </Button>
        </Alert>
      </Container>
    );
  }

  if (!schema || !mergedConfig) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Alert type="error" header="Configuration not available">
          Unable to load configuration schema or values.
          <Button onClick={fetchConfiguration} variant="primary" style={{ marginTop: '1rem' }}>
            Retry
          </Button>
        </Alert>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
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
                <Button onClick={formatJson} iconName="file-text">
                  Format JSON
                </Button>
              )}
              {viewMode === 'yaml' && (
                <Button onClick={formatYaml} iconName="file-text">
                  Format YAML
                </Button>
              )}
              <Button variant="primary" onClick={handleSave} loading={isSaving}>
                Save changes
              </Button>
            </SpaceBetween>
          }
        >
          Configuration
        </Header>
      }
    >
      <Form>
        {saveSuccess && (
          <Alert
            type="success"
            dismissible
            onDismiss={() => setSaveSuccess(false)}
            header="Configuration saved successfully"
          >
            Your configuration changes have been saved.
          </Alert>
        )}

        {saveError && (
          <Alert type="error" dismissible onDismiss={() => setSaveError(null)} header="Error saving configuration">
            {saveError}
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

        <Box padding="s">
          {viewMode === 'form' && (
            <FormView
              schema={schema}
              formValues={formValues}
              defaultConfig={defaultConfig}
              isCustomized={isCustomized}
              onResetToDefault={resetToDefault}
              onChange={handleFormChange}
            />
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
  );
};

export default ConfigurationLayout;
